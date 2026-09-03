"""
Recoup v0.1.0 - Domain Data Models & Schemas
Defines structured schemas for failed payment events, AI decisions, and policy verdicts.
"""

from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class PaymentMethod(str, Enum):
    UPI_INTENT = "upi_intent"
    UPI_COLLECT = "upi_collect"
    UPI_AUTOPAY = "upi_autopay"
    CARD_CREDIT = "card_credit"
    CARD_DEBIT = "card_debit"
    NETBANKING = "netbanking"
    EMANDATE = "emandate"


class CustomerTier(str, Enum):
    ENTERPRISE = "enterprise"
    HIGH_VALUE = "high_value"
    STANDARD = "standard"
    NEW = "new"


class FailureCategory(str, Enum):
    TRANSIENT_TECHNICAL = "transient_technical"       # Gateway/NPCI/Bank downtime
    CUSTOMER_LIQUIDITY = "customer_liquidity"         # Low balance, insufficient funds
    AUTHENTICATION_DROP = "authentication_drop"       # OTP expired, incorrect PIN / MPIN
    METHOD_RESTRICTION = "method_restriction"         # Card usage disabled, international blocked
    HARD_DECLINE = "hard_decline"                     # Card expired, lost/stolen, account closed
    RISK_COMPLIANCE = "risk_compliance"               # Suspected fraud, velocity limit
    HIGH_VALUE_AMBIGUITY = "high_value_ambiguity"     # Transactions >= ₹50,000 requiring human attention
    # --- v0.7.0 expanded taxonomy (grounded in NPCI / RBI / Razorpay docs) ---
    MANDATE_LIFECYCLE = "mandate_lifecycle"              # eNACH / UPI AutoPay mandate not active, paused, non-compliant
    LIMIT_EXCEEDED = "limit_exceeded"                   # UPI per-txn / daily / new-user caps breached
    COMPLIANCE_TOKENIZATION = "compliance_tokenization"  # RBI card-on-file token missing / invalid
    PSP_UNAVAILABLE = "psp_unavailable"                 # Payer UPI app (GPay/PhonePe/Paytm) down, bank rails healthy


class FailureCode(str, Enum):
    GATEWAY_TECHNICAL_ERROR = "gateway_technical_error"
    BANK_DOWNTIME = "bank_downtime"
    PAYMENT_TIMED_OUT = "payment_timed_out"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    INVALID_OTP = "invalid_otp"
    OTP_EXPIRED = "otp_expired"
    PAYMENT_CANCELLED_BY_USER = "payment_cancelled_by_user"
    CARD_LIMIT_EXCEEDED = "card_limit_exceeded"
    CARD_EXPIRED = "card_expired"
    ACCOUNT_CLOSED = "account_closed"
    LOST_OR_STOLEN_CARD = "lost_or_stolen_card"
    SUSPECTED_FRAUD = "suspected_fraud"
    # --- v0.7.0 expanded taxonomy: UPI / NPCI ---
    UPI_COLLECT_EXPIRED = "upi_collect_expired"                 # Collect request not approved within TTL
    UPI_PER_TXN_LIMIT = "upi_per_txn_limit"                     # Amount exceeds per-transaction UPI cap
    UPI_DAILY_LIMIT = "upi_daily_limit"                         # Daily amount / count cap breached
    UPI_NEW_USER_LIMIT = "upi_new_user_limit"                   # New UPI user 24h / ₹5,000 cooling cap
    UPI_MPIN_ATTEMPTS_EXCEEDED = "upi_mpin_attempts_exceeded"   # Wrong UPI PIN 3x, temporary lock
    PSP_APP_DOWN = "psp_app_down"                               # Payer PSP app unavailable, bank healthy
    # --- Mandate / AutoPay / eNACH ---
    MANDATE_NOT_ACTIVE = "mandate_not_active"                   # Mandate revoked / never activated
    MANDATE_PAUSED = "mandate_paused"                           # Customer paused AutoPay
    PRE_DEBIT_NOTIFICATION_MISSING = "pre_debit_notification_missing"  # RBI 24h pre-debit notice not sent
    MANDATE_AMOUNT_LIMIT_EXCEEDED = "mandate_amount_limit_exceeded"    # Debit exceeds mandate max amount
    # --- Cards / RBI tokenization & card controls ---
    TOKENIZATION_FAILED = "tokenization_failed"                 # Network could not create CoF token
    TOKEN_EXPIRED_OR_INVALID = "token_expired_or_invalid"       # Saved token invalid, re-tokenization needed
    CARD_NOT_ENABLED_ONLINE = "card_not_enabled_online"         # Online/domestic use disabled (RBI controls)
    INTERNATIONAL_TXN_BLOCKED = "international_txn_blocked"      # Cross-border disabled on card


class RecoveryActionType(str, Enum):
    DYNAMIC_BACKOFF_RETRY = "dynamic_backoff_retry"           # Silent re-attempt on off-peak window
    ALTERNATIVE_PAYMENT_LINK = "alternative_payment_link"     # 1-click Razorpay payment link (WhatsApp / SMS)
    METHOD_SWITCH_NUDGE = "method_switch_nudge"               # Suggest switching from failed card to UPI/Netbanking
    SMART_DUNNING_SCHEDULE = "smart_dunning_schedule"         # Schedule mandate retry on salary / liquidity day
    ESCALATE_TO_HUMAN = "escalate_to_human"                   # Route to merchant ops / white-glove sales team
    IMMEDIATE_STOP = "immediate_stop"                         # Cease all automated action permanently


class FailedPaymentContext(BaseModel):
    """Rich context describing the failed payment event."""
    transaction_id: str
    order_id: str
    customer_id: str
    customer_name: str
    customer_tier: CustomerTier = CustomerTier.STANDARD
    cltv_inr: float = Field(default=0.0, description="Customer Lifetime Value in INR")
    preferred_channel: str = "whatsapp"  # "whatsapp", "sms", "email"
    opted_out: bool = False
    
    amount_inr: float
    payment_method: PaymentMethod
    failure_category: FailureCategory
    error_code: FailureCode
    error_message: str
    
    retry_count: int = 0
    created_at: datetime = Field(default_factory=datetime.now)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentDecision(BaseModel):
    """Structured decision output produced by the AI Agent."""
    transaction_id: str
    recommended_action: RecoveryActionType
    recovery_likelihood_pct: float = Field(ge=0.0, le=100.0, description="Estimated recovery chance (0-100%)")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Agent confidence (0.0 to 1.0)")
    backoff_seconds: int = Field(default=0, description="Suggested retry delay if applicable")
    channel: Optional[str] = "whatsapp"
    customer_message: Optional[str] = Field(default=None, description="Personalized customer communication draft")
    reasoning_summary: str = Field(description="Step-by-step rationale for why this action was chosen")
    requires_human_approval: bool = False
    decision_model: Optional[str] = Field(default=None, description="Engine/model that produced this decision")
    knowledge_grounded: bool = Field(default=False, description="True if a verified playbook entry informed this decision")
    playbook_entry_used: Optional[str] = Field(default=None, description="failure_code key of the playbook entry consulted, if any")


class PolicyVerdict(BaseModel):
    """Deterministic policy validation result ensuring financial safety."""
    is_permitted: bool
    violation_reasons: List[str] = Field(default_factory=list)
    enforced_action: RecoveryActionType
    applied_rule: str
    current_retry_count: int
    max_retries_allowed: int
