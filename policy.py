"""
Recoup v0.1.0 - Deterministic Policy Guardrails
Enforces non-negotiable financial safety rules. The AI Agent proposes; Policy authorizes or overrides.
"""

from models import (
    FailedPaymentContext,
    AgentDecision,
    PolicyVerdict,
    FailureCategory,
    FailureCode,
    RecoveryActionType,
)

# Deterministic Safety Rules
MAX_RETRIES_BY_CATEGORY = {
    FailureCategory.TRANSIENT_TECHNICAL: 3,
    FailureCategory.CUSTOMER_LIQUIDITY: 2,
    FailureCategory.AUTHENTICATION_DROP: 1,
    FailureCategory.METHOD_RESTRICTION: 1,
    FailureCategory.HARD_DECLINE: 0,        # Strict 0 retries on invalid/stolen cards
    FailureCategory.RISK_COMPLIANCE: 0,      # Suspicious transactions require human review
    FailureCategory.HIGH_VALUE_AMBIGUITY: 1,
    FailureCategory.MANDATE_LIFECYCLE: 1,        # Dead/paused mandates need customer re-auth, not blind retry
    FailureCategory.LIMIT_EXCEEDED: 1,          # Same amount on same rail will always fail; switch method
    FailureCategory.COMPLIANCE_TOKENIZATION: 1,  # Broken token never recovers on retry; re-consent needed
    FailureCategory.PSP_UNAVAILABLE: 2,         # Transient — retry via alternate PSP / rail
}

HIGH_VALUE_THRESHOLD_INR = 50000.0  # Transactions >= ₹50,000 require human escalation


class PolicyGuardrailEngine:
    """Evaluates an AI Agent decision against strict deterministic financial rules."""

    @staticmethod
    def validate(context: FailedPaymentContext, decision: AgentDecision) -> PolicyVerdict:
        violations = []
        max_allowed_retries = MAX_RETRIES_BY_CATEGORY.get(context.failure_category, 1)

        # Rule 1: Explicit Customer Opt-Out
        if context.opted_out:
            return PolicyVerdict(
                is_permitted=False,
                violation_reasons=["Customer has explicitly opted out of communications and recovery attempts."],
                enforced_action=RecoveryActionType.IMMEDIATE_STOP,
                applied_rule="RULE_CUSTOMER_OPT_OUT",
                current_retry_count=context.retry_count,
                max_retries_allowed=0,
            )

        # Rule 2: Hard Decline Zero-Retry Rule
        if context.failure_category == FailureCategory.HARD_DECLINE:
            if decision.recommended_action in (RecoveryActionType.DYNAMIC_BACKOFF_RETRY, RecoveryActionType.SMART_DUNNING_SCHEDULE):
                violations.append(f"Hard decline detected ({context.error_code}). Automated retrying is strictly prohibited.")
                return PolicyVerdict(
                    is_permitted=False,
                    violation_reasons=violations,
                    enforced_action=RecoveryActionType.IMMEDIATE_STOP,
                    applied_rule="RULE_HARD_DECLINE_ZERO_RETRY",
                    current_retry_count=context.retry_count,
                    max_retries_allowed=0,
                )

        # Rule 3: High Value Transaction Gate (>= ₹50,000)
        if context.amount_inr >= HIGH_VALUE_THRESHOLD_INR:
            if decision.recommended_action != RecoveryActionType.ESCALATE_TO_HUMAN:
                violations.append(f"Transaction amount (₹{context.amount_inr:,.2f}) exceeds automated threshold (₹{HIGH_VALUE_THRESHOLD_INR:,.2f}).")
                return PolicyVerdict(
                    is_permitted=False,
                    violation_reasons=violations,
                    enforced_action=RecoveryActionType.ESCALATE_TO_HUMAN,
                    applied_rule="RULE_HIGH_VALUE_ESCALATION",
                    current_retry_count=context.retry_count,
                    max_retries_allowed=max_allowed_retries,
                )

        # Rule 4: Exceeded Max Retries (only triggers if attempting an active recovery action)
        if decision.recommended_action != RecoveryActionType.IMMEDIATE_STOP and context.retry_count >= max_allowed_retries:
            violations.append(f"Retry count ({context.retry_count}) has reached or exceeded max limit ({max_allowed_retries}).")
            return PolicyVerdict(
                is_permitted=False,
                violation_reasons=violations,
                enforced_action=RecoveryActionType.IMMEDIATE_STOP,
                applied_rule="RULE_MAX_RETRIES_EXCEEDED",
                current_retry_count=context.retry_count,
                max_retries_allowed=max_allowed_retries,
            )

        # Rule 5: Risk / Fraud Safeguard
        if context.failure_category == FailureCategory.RISK_COMPLIANCE:
            if decision.recommended_action != RecoveryActionType.ESCALATE_TO_HUMAN:
                violations.append("Suspected fraud / risk flagged. Must escalate to merchant risk team.")
                return PolicyVerdict(
                    is_permitted=False,
                    violation_reasons=violations,
                    enforced_action=RecoveryActionType.ESCALATE_TO_HUMAN,
                    applied_rule="RULE_RISK_COMPLIANCE_HOLD",
                    current_retry_count=context.retry_count,
                    max_retries_allowed=0,
                )

        # Rule 6: Mandate Lifecycle Integrity — a dead / paused / over-limit mandate cannot be silently retried
        if context.failure_category == FailureCategory.MANDATE_LIFECYCLE and context.error_code in (
            FailureCode.MANDATE_NOT_ACTIVE,
            FailureCode.MANDATE_PAUSED,
            FailureCode.MANDATE_AMOUNT_LIMIT_EXCEEDED,
        ):
            if decision.recommended_action in (RecoveryActionType.DYNAMIC_BACKOFF_RETRY, RecoveryActionType.SMART_DUNNING_SCHEDULE):
                violations.append(
                    f"Mandate is not debitable ({context.error_code.value}). Silent retry / auto-dunning burns bank hits and cannot succeed until the customer re-authorises."
                )
                return PolicyVerdict(
                    is_permitted=False,
                    violation_reasons=violations,
                    enforced_action=RecoveryActionType.ALTERNATIVE_PAYMENT_LINK,
                    applied_rule="RULE_MANDATE_REAUTH_REQUIRED",
                    current_retry_count=context.retry_count,
                    max_retries_allowed=max_allowed_retries,
                )

        # Rule 7: RBI e-Mandate Pre-Debit Notification — 24h notice is legally required before a recurring debit
        if context.error_code == FailureCode.PRE_DEBIT_NOTIFICATION_MISSING:
            if decision.recommended_action == RecoveryActionType.DYNAMIC_BACKOFF_RETRY:
                violations.append(
                    "RBI e-mandate rules require a pre-debit notification to the customer at least 24h before debit. Immediate retry is non-compliant."
                )
                return PolicyVerdict(
                    is_permitted=False,
                    violation_reasons=violations,
                    enforced_action=RecoveryActionType.SMART_DUNNING_SCHEDULE,
                    applied_rule="RULE_PRE_DEBIT_NOTIFICATION_REQUIRED",
                    current_retry_count=context.retry_count,
                    max_retries_allowed=max_allowed_retries,
                )

        # Rule 8: RBI Card-on-File Tokenisation Compliance — a missing / invalid token never recovers on retry
        if context.failure_category == FailureCategory.COMPLIANCE_TOKENIZATION:
            if decision.recommended_action in (RecoveryActionType.DYNAMIC_BACKOFF_RETRY, RecoveryActionType.SMART_DUNNING_SCHEDULE):
                violations.append(
                    f"Card-on-file token is missing or invalid ({context.error_code.value}). Retrying the stored token will always fail; customer must re-enter the card and re-consent to tokenisation."
                )
                return PolicyVerdict(
                    is_permitted=False,
                    violation_reasons=violations,
                    enforced_action=RecoveryActionType.ALTERNATIVE_PAYMENT_LINK,
                    applied_rule="RULE_RETOKENIZATION_REQUIRED",
                    current_retry_count=context.retry_count,
                    max_retries_allowed=max_allowed_retries,
                )

        # If all checks pass
        return PolicyVerdict(
            is_permitted=True,
            violation_reasons=[],
            enforced_action=decision.recommended_action,
            applied_rule="RULE_POLICY_APPROVED",
            current_retry_count=context.retry_count,
            max_retries_allowed=max_allowed_retries,
        )
