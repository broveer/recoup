"""
Payment Failure Taxonomy & Recovery Actions for Indian Payment Rails (UPI, Cards, Mandates, Netbanking).
"""

from enum import Enum


class PaymentMethod(str, Enum):
    UPI_COLLECT = "upi_collect"
    UPI_INTENT = "upi_intent"
    UPI_AUTOPAY = "upi_autopay"
    CARD_CREDIT = "card_credit"
    CARD_DEBIT = "card_debit"
    EMANDATE_NETBANKING = "emandate_netbanking"
    EMANDATE_DEBIT_CARD = "emandate_debit_card"
    NETBANKING = "netbanking"
    WALLET = "wallet"


class CustomerTier(str, Enum):
    ENTERPRISE = "enterprise"
    HIGH_VALUE = "high_value"
    STANDARD = "standard"
    NEW = "new"


class FailureCategory(str, Enum):
    TRANSIENT_TECHNICAL = "transient_technical"       # Gateway, NPCI, Bank switch timeouts
    CUSTOMER_LIQUIDITY = "customer_liquidity"         # Insufficient funds, low balance
    AUTHENTICATION_DROP = "authentication_drop"       # OTP expired, incorrect PIN, user closed window
    METHOD_RESTRICTION = "method_restriction"         # Limit exceeded, international not enabled
    HARD_DECLINE = "hard_decline"                     # Card expired, invalid CVV, card stolen, closed account
    RISK_COMPLIANCE = "risk_compliance"               # Suspected fraud, velocity block
    HIGH_VALUE_AMBIGUITY = "high_value_ambiguity"     # Transactions >= ₹50,000 requiring human intervention


class FailureCode(str, Enum):
    # Transient Technical
    GATEWAY_TECHNICAL_ERROR = "gateway_technical_error"
    BANK_DOWNTIME = "bank_downtime"
    PAYMENT_TIMED_OUT = "payment_timed_out"
    NPCI_NETWORK_ERROR = "npci_network_error"

    # Customer Liquidity
    INSUFFICIENT_FUNDS = "insufficient_funds"
    ACCOUNT_LOW_BALANCE = "account_low_balance"

    # Authentication Drop
    INVALID_OTP = "invalid_otp"
    OTP_EXPIRED = "otp_expired"
    PAYMENT_CANCELLED_BY_USER = "payment_cancelled_by_user"
    UPI_PIN_TIMEOUT = "upi_pin_timeout"

    # Method Restriction
    CARD_LIMIT_EXCEEDED = "card_limit_exceeded"
    BANK_NOT_ENABLED_FOR_NETBANKING = "bank_not_enabled_for_netbanking"
    INTERNATIONAL_NOT_ALLOWED = "international_not_allowed"

    # Hard Decline
    CARD_EXPIRED = "card_expired"
    INVALID_CARD_DETAILS = "invalid_card_details"
    ACCOUNT_CLOSED = "account_closed"
    LOST_OR_STOLEN_CARD = "lost_or_stolen_card"

    # Risk & Compliance
    SUSPECTED_FRAUD = "suspected_fraud"
    VELOCITY_LIMIT_EXCEEDED = "velocity_limit_exceeded"
    RISK_CHECK_FAILED = "risk_check_failed"


class RecoveryActionType(str, Enum):
    DYNAMIC_BACKOFF_RETRY = "dynamic_backoff_retry"           # Silent re-attempt on off-peak window
    ALTERNATIVE_PAYMENT_LINK = "alternative_payment_link"     # 1-click Razorpay payment link (UPI intent / SMS / WhatsApp)
    METHOD_SWITCH_NUDGE = "method_switch_nudge"               # Suggest switching from failed card to UPI/Netbanking
    SMART_DUNNING_SCHEDULE = "smart_dunning_schedule"         # Schedule mandate retry on salary / liquidity day
    ESCALATE_TO_HUMAN = "escalate_to_human"                   # Route to merchant ops / white-glove sales team
    IMMEDIATE_STOP = "immediate_stop"                         # Cease all automated action permanently


class RecoveryOutcomeStatus(str, Enum):
    RECOVERED = "recovered"
    FAILED_PERMANENT = "failed_permanent"
    FAILED_RETRYABLE = "failed_retryable"
    ESCALATED = "escalated"
    STOPPED = "stopped"
