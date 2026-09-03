"""
Recoup v0.2.0 - Synthetic Payment Failure Dataset Generator
Generates realistic payment failure cohorts based on Indian payment rails (UPI, Cards, Mandates, Netbanking).
"""

import json
import random
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any
from models import (
    FailedPaymentContext,
    PaymentMethod,
    CustomerTier,
    FailureCategory,
    FailureCode,
)

# Realistic Archetypes based on RBI & NPCI distributions
ARCHETYPES = [
    {
        "category": FailureCategory.TRANSIENT_TECHNICAL,
        "codes": [
            (FailureCode.BANK_DOWNTIME, "Issuing bank core switch timed out during transaction routing."),
            (FailureCode.GATEWAY_TECHNICAL_ERROR, "NPCI Switch network timeout on UPI processing."),
            (FailureCode.PAYMENT_TIMED_OUT, "Gateway upstream timeout communicating with payment aggregator."),
        ],
        "methods": [PaymentMethod.UPI_INTENT, PaymentMethod.UPI_COLLECT, PaymentMethod.NETBANKING],
        "weight": 22,
        "amount_range": (299.0, 8500.0),
    },
    {
        "category": FailureCategory.AUTHENTICATION_DROP,
        "codes": [
            (FailureCode.OTP_EXPIRED, "Customer 3DS / OTP session timed out after 300 seconds."),
            (FailureCode.INVALID_OTP, "Customer entered incorrect OTP 2 times and abandoned checkout."),
            (FailureCode.PAYMENT_CANCELLED_BY_USER, "User tapped cancel on bank 3DS / UPI PIN prompt."),
            (FailureCode.UPI_COLLECT_EXPIRED, "UPI collect request lapsed before the payer approved it."),
            (FailureCode.UPI_MPIN_ATTEMPTS_EXCEEDED, "Payer entered wrong UPI PIN 3 times; UPI temporarily locked."),
        ],
        "methods": [PaymentMethod.CARD_CREDIT, PaymentMethod.CARD_DEBIT, PaymentMethod.UPI_INTENT],
        "weight": 18,
        "amount_range": (499.0, 12000.0),
    },
    {
        "category": FailureCategory.CUSTOMER_LIQUIDITY,
        "codes": [
            (FailureCode.INSUFFICIENT_FUNDS, "Account balance insufficient for subscription debit on mandate."),
        ],
        "methods": [PaymentMethod.UPI_AUTOPAY, PaymentMethod.EMANDATE],
        "weight": 14,  # recurring subscriptions
        "amount_range": (199.0, 4999.0),
    },
    {
        "category": FailureCategory.HARD_DECLINE,
        "codes": [
            (FailureCode.CARD_EXPIRED, "Payment card expired (expiry date has passed)."),
            (FailureCode.ACCOUNT_CLOSED, "Customer bank account associated with instrument is closed."),
            (FailureCode.LOST_OR_STOLEN_CARD, "Bank returned pick-up card / stolen instrument flag."),
        ],
        "methods": [PaymentMethod.CARD_DEBIT, PaymentMethod.CARD_CREDIT],
        "weight": 11,
        "amount_range": (399.0, 9500.0),
    },
    {
        "category": FailureCategory.HIGH_VALUE_AMBIGUITY,
        "codes": [
            (FailureCode.CARD_LIMIT_EXCEEDED, "Single corporate netbanking transaction limit exceeded."),
        ],
        "methods": [PaymentMethod.NETBANKING, PaymentMethod.CARD_CREDIT],
        "weight": 7,  # high-ticket / B2B
        "amount_range": (55000.0, 250000.0),
    },
    # --- v0.7.0 expanded taxonomy: real-world Indian failure modes ---
    {
        "category": FailureCategory.MANDATE_LIFECYCLE,
        "codes": [
            (FailureCode.MANDATE_NOT_ACTIVE, "eNACH mandate revoked / not activated at sponsor bank."),
            (FailureCode.MANDATE_PAUSED, "Customer paused UPI AutoPay mandate in PSP app."),
            (FailureCode.PRE_DEBIT_NOTIFICATION_MISSING, "RBI-mandated 24h pre-debit notification was not delivered."),
            (FailureCode.MANDATE_AMOUNT_LIMIT_EXCEEDED, "Debit amount exceeds the per-transaction ceiling set on the mandate."),
        ],
        "methods": [PaymentMethod.UPI_AUTOPAY, PaymentMethod.EMANDATE],
        "weight": 9,
        "amount_range": (199.0, 4999.0),
        "consumer_only": True,
    },
    {
        "category": FailureCategory.LIMIT_EXCEEDED,
        "codes": [
            (FailureCode.UPI_DAILY_LIMIT, "Cumulative daily UPI limit reached on payer bank / app."),
            (FailureCode.UPI_NEW_USER_LIMIT, "New UPI user 24h cooling cap (₹5,000) breached."),
        ],
        "methods": [PaymentMethod.UPI_INTENT, PaymentMethod.UPI_COLLECT],
        "weight": 6,
        "amount_range": (2000.0, 9000.0),
        "consumer_only": True,
    },
    {
        "category": FailureCategory.LIMIT_EXCEEDED,
        "codes": [
            (FailureCode.UPI_PER_TXN_LIMIT, "Exceeds bank-set per-transaction UPI limit of ₹25,000."),
        ],
        "methods": [PaymentMethod.UPI_INTENT],
        "weight": 3,
        "amount_range": (26000.0, 49000.0),
        "consumer_only": True,
    },
    {
        "category": FailureCategory.COMPLIANCE_TOKENIZATION,
        "codes": [
            (FailureCode.TOKENIZATION_FAILED, "Network could not create a card-on-file token; AFA consent incomplete."),
            (FailureCode.TOKEN_EXPIRED_OR_INVALID, "Saved network token invalid after card reissue."),
        ],
        "methods": [PaymentMethod.CARD_CREDIT, PaymentMethod.CARD_DEBIT],
        "weight": 5,
        "amount_range": (499.0, 6000.0),
        "consumer_only": True,
    },
    {
        "category": FailureCategory.PSP_UNAVAILABLE,
        "codes": [
            (FailureCode.PSP_APP_DOWN, "Payer PSP app (PhonePe / GPay / Paytm) unreachable; bank rails healthy."),
        ],
        "methods": [PaymentMethod.UPI_INTENT, PaymentMethod.UPI_COLLECT],
        "weight": 3,
        "amount_range": (199.0, 5000.0),
        "consumer_only": True,
    },
    {
        "category": FailureCategory.METHOD_RESTRICTION,
        "codes": [
            (FailureCode.CARD_NOT_ENABLED_ONLINE, "Online / e-commerce usage switched off on card (RBI card controls)."),
            (FailureCode.INTERNATIONAL_TXN_BLOCKED, "International transactions disabled on card."),
        ],
        "methods": [PaymentMethod.CARD_DEBIT, PaymentMethod.CARD_CREDIT],
        "weight": 2,
        "amount_range": (499.0, 12000.0),
        "consumer_only": True,
    },
]

INDIAN_NAMES = [
    ("Aarav Mehta", "enterprise", 320000.0),
    ("Priya Sharma", "standard", 4500.0),
    ("Rohan Deshmukh", "high_value", 48000.0),
    ("Ananya Iyer", "standard", 6200.0),
    ("Vikram Singhania", "enterprise", 750000.0),
    ("Neha Kapoor", "new", 1200.0),
    ("Karan Patel", "standard", 8900.0),
    ("Pooja Nair", "high_value", 35000.0),
    ("Siddharth Rao", "standard", 5400.0),
    ("Tanvi Joshi", "new", 800.0),
    ("Rajesh Mittal & Sons", "enterprise", 920000.0),
    ("Deepak Verma", "standard", 3100.0),
    ("Sneha Kulkarni", "high_value", 28000.0),
    ("Amitabh Sen", "enterprise", 410000.0),
    ("Ishita Roy", "standard", 7200.0),
]


def generate_cohort(size: int = 100, seed: int = 42) -> List[FailedPaymentContext]:
    """Generates a statistically realistic cohort of failed payment events."""
    random.seed(seed)
    cohort: List[FailedPaymentContext] = []

    weights = [a["weight"] for a in ARCHETYPES]
    archetype_choices = random.choices(ARCHETYPES, weights=weights, k=size)

    base_time = datetime(2026, 8, 20, 10, 0, 0)

    for i, arch in enumerate(archetype_choices, 1):
        category = arch["category"]
        code_tuple = random.choice(arch["codes"])
        error_code, error_msg = code_tuple
        method = random.choice(arch["methods"])
        
        # Determine amount
        min_amt, max_amt = arch["amount_range"]
        amount = round(random.uniform(min_amt, max_amt), 2)
        
        # Pick customer profile
        if category == FailureCategory.HIGH_VALUE_AMBIGUITY or amount >= 50000.0:
            name, tier_str, cltv = random.choice([n for n in INDIAN_NAMES if n[1] == "enterprise"])
        elif arch.get("consumer_only"):
            name, tier_str, cltv = random.choice([n for n in INDIAN_NAMES if n[1] != "enterprise"])
        else:
            name, tier_str, cltv = random.choice(INDIAN_NAMES)
            
        tier = CustomerTier(tier_str)
        channel = "whatsapp" if tier != CustomerTier.ENTERPRISE else "email"
        
        # Realistic timestamp spread over 5 days
        tx_time = base_time + timedelta(
            days=random.randint(0, 5),
            hours=random.randint(8, 22),
            minutes=random.randint(0, 59),
        )
        
        ctx = FailedPaymentContext(
            transaction_id=f"pay_{method.value[:3].upper()}_{10000 + i}",
            order_id=f"order_{80000 + i}",
            customer_id=f"cust_{name.lower().replace(' ', '_').replace('&', '')}",
            customer_name=name,
            customer_tier=tier,
            cltv_inr=cltv,
            preferred_channel=channel,
            opted_out=(random.random() < 0.03),  # 3% explicit opt-out rate
            amount_inr=amount,
            payment_method=method,
            failure_category=category,
            error_code=error_code,
            error_message=error_msg,
            retry_count=0,
            created_at=tx_time,
        )
        cohort.append(ctx)

    return cohort


def save_dataset(cohort: List[FailedPaymentContext], filename: str):
    """Saves cohort to JSON file in data/ directory."""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    filepath = os.path.join(data_dir, filename)
    
    serialized = [ctx.model_dump(mode="json") for ctx in cohort]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(serialized, f, indent=2)
    return filepath


def load_dataset(filename: str) -> List[FailedPaymentContext]:
    """Loads a cohort JSON dataset into Pydantic models."""
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    filepath = os.path.join(data_dir, filename)
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Dataset {filepath} not found.")
        
    with open(filepath, "r", encoding="utf-8") as f:
        raw_list = json.load(f)
    return [FailedPaymentContext(**item) for item in raw_list]


if __name__ == "__main__":
    dev_cohort = generate_cohort(size=50, seed=101)
    dev_path = save_dataset(dev_cohort, "dev_cohort_50.json")
    print(f"Generated Dev Dataset (50 items): {dev_path}")

    eval_cohort = generate_cohort(size=200, seed=202)
    eval_path = save_dataset(eval_cohort, "eval_cohort_200.json")
    print(f"Generated Held-Out Eval Dataset (200 items): {eval_path}")
