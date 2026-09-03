"""
Recoup v0.2.0 - Competent Non-AI Rule-Based Baseline Engine
Implements industry-standard static dunning and rule-table recovery logic to serve as a benchmark.
"""

from models import (
    FailedPaymentContext,
    AgentDecision,
    RecoveryActionType,
    FailureCategory,
    FailureCode,
)


class RuleBasedBaselineEngine:
    """
    A competent, deterministic rule-based recovery engine.
    Uses standard static error code lookup tables and fixed retry schedules.
    """

    @staticmethod
    def decide(context: FailedPaymentContext) -> AgentDecision:
        code = context.error_code

        # 1. Transient Gateway & Bank Downtimes
        if code in (FailureCode.BANK_DOWNTIME, FailureCode.GATEWAY_TECHNICAL_ERROR, FailureCode.PAYMENT_TIMED_OUT):
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.DYNAMIC_BACKOFF_RETRY,
                recovery_likelihood_pct=60.0,
                confidence_score=0.80,
                backoff_seconds=21600,  # Standard static 6-hour delay
                channel="silent_retry",
                customer_message=None,
                reasoning_summary="Rule table match: Gateway/bank error mapped to standard 6-hour static retry.",
                requires_human_approval=False,
                decision_model="rule-based-baseline",
            )

        # 2. Insufficient Funds / Liquidity
        elif code == FailureCode.INSUFFICIENT_FUNDS:
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.SMART_DUNNING_SCHEDULE,
                recovery_likelihood_pct=40.0,
                confidence_score=0.75,
                backoff_seconds=86400,  # Standard static 24-hour delay (ignores salary cycles)
                channel="email",        # Standard generic email dunning
                customer_message="Your payment failed due to insufficient balance. Please ensure funds are available for the next debit attempt in 24 hours.",
                reasoning_summary="Rule table match: Insufficient funds mapped to 24-hour email dunning.",
                requires_human_approval=False,
                decision_model="rule-based-baseline",
            )

        # 3. Authentication Drops (OTP / Cancellation)
        elif code in (FailureCode.OTP_EXPIRED, FailureCode.INVALID_OTP, FailureCode.PAYMENT_CANCELLED_BY_USER):
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.ALTERNATIVE_PAYMENT_LINK,
                recovery_likelihood_pct=35.0,
                confidence_score=0.70,
                backoff_seconds=0,
                channel="email",        # Standard slow email notification
                customer_message=f"Your payment of ₹{context.amount_inr:,.2f} could not be completed. Click here to try again: https://rzp.io/l/dunning",
                reasoning_summary="Rule table match: Authentication drop mapped to generic dunning email.",
                requires_human_approval=False,
                decision_model="rule-based-baseline",
            )

        # 3b. Mandate debit failures - static table blindly schedules a 24h retry (no lifecycle awareness)
        elif code in (
            FailureCode.MANDATE_NOT_ACTIVE,
            FailureCode.MANDATE_PAUSED,
            FailureCode.MANDATE_AMOUNT_LIMIT_EXCEEDED,
            FailureCode.PRE_DEBIT_NOTIFICATION_MISSING,
        ):
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.SMART_DUNNING_SCHEDULE,
                recovery_likelihood_pct=35.0,
                confidence_score=0.65,
                backoff_seconds=86400,
                channel="email",
                customer_message="Your scheduled payment failed. We will retry the auto-debit in 24 hours.",
                reasoning_summary="Rule table match: mandate debit failure mapped to standard 24-hour retry.",
                requires_human_approval=False,
                decision_model="rule-based-baseline",
            )

        # 3c. Card-on-file token failures - static table retries the stored token
        elif code in (FailureCode.TOKENIZATION_FAILED, FailureCode.TOKEN_EXPIRED_OR_INVALID):
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.DYNAMIC_BACKOFF_RETRY,
                recovery_likelihood_pct=30.0,
                confidence_score=0.55,
                backoff_seconds=21600,
                channel="silent_retry",
                customer_message=None,
                reasoning_summary="Rule table match: card token error mapped to standard 6-hour retry.",
                requires_human_approval=False,
                decision_model="rule-based-baseline",
            )

        # 3d. UPI limits, PSP outages, card controls - generic dunning email (no nuance)
        elif code in (
            FailureCode.UPI_PER_TXN_LIMIT,
            FailureCode.UPI_DAILY_LIMIT,
            FailureCode.UPI_NEW_USER_LIMIT,
            FailureCode.UPI_COLLECT_EXPIRED,
            FailureCode.UPI_MPIN_ATTEMPTS_EXCEEDED,
            FailureCode.PSP_APP_DOWN,
            FailureCode.CARD_NOT_ENABLED_ONLINE,
            FailureCode.INTERNATIONAL_TXN_BLOCKED,
        ):
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.ALTERNATIVE_PAYMENT_LINK,
                recovery_likelihood_pct=32.0,
                confidence_score=0.60,
                backoff_seconds=0,
                channel="email",
                customer_message=f"Your payment of ₹{context.amount_inr:,.2f} did not go through. Please try again: https://rzp.io/l/dunning",
                reasoning_summary="Rule table match: UPI/card restriction mapped to generic payment link email.",
                requires_human_approval=False,
                decision_model="rule-based-baseline",
            )

        # 4. Hard Declines (Expired / Closed / Stolen)
        elif code in (FailureCode.CARD_EXPIRED, FailureCode.ACCOUNT_CLOSED, FailureCode.LOST_OR_STOLEN_CARD):
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.IMMEDIATE_STOP,
                recovery_likelihood_pct=0.0,
                confidence_score=0.99,
                backoff_seconds=0,
                channel="email",
                customer_message="Your payment instrument is invalid or expired. Please update your billing details.",
                reasoning_summary="Rule table match: Hard decline code mapped to immediate stop.",
                requires_human_approval=False,
                decision_model="rule-based-baseline",
            )

        # 5. Method Restrictions & High-Value Ambiguity (Default Fallback)
        else:
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.ALTERNATIVE_PAYMENT_LINK,
                recovery_likelihood_pct=30.0,
                confidence_score=0.60,
                backoff_seconds=0,
                channel="email",
                customer_message=f"Payment of ₹{context.amount_inr:,.2f} failed. Please use an alternative payment method: https://rzp.io/l/dunning",
                reasoning_summary="Rule table match: Unclassified failure mapped to standard payment link email.",
                requires_human_approval=False,
                decision_model="rule-based-baseline",
            )
