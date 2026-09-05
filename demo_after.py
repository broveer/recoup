"""
Demo scene 4 - AFTER: same failure, knowledge-grounded, then the guardrail override.

    python demo_after.py

Deterministic (RECOUP_DISABLE_LLM=1) - no GPU, no network.
"""
import os

os.environ["RECOUP_DISABLE_LLM"] = "1"

from models import (
    FailedPaymentContext, PaymentMethod, FailureCategory, FailureCode, RecoveryActionType,
)
from agent import RecoveryAgent
from policy import PolicyGuardrailEngine

ctx = FailedPaymentContext(
    transaction_id="pay_DEMO_1", order_id="o1", customer_id="c1",
    customer_name="Ananya Iyer", amount_inr=649.0,
    payment_method=PaymentMethod.UPI_AUTOPAY,
    failure_category=FailureCategory.MANDATE_LIFECYCLE,
    error_code=FailureCode.PRE_DEBIT_NOTIFICATION_MISSING,
    error_message="Recurring debit attempted without the mandatory 24h pre-debit notification.",
)

decision = RecoveryAgent(use_playbook=True).decide(ctx)   # <-- with the curated playbook

print("\n" + "=" * 64)
print("  AFTER  -  agent + curated playbook (RAG)")
print("=" * 64)
print(f"  failure code   : {ctx.error_code.value}")
print("  " + "-" * 60)
print(f"  recommended    : {decision.recommended_action.value}")
print(f"  grounded on    : {decision.playbook_entry_used}")
print(f"  reasoning      : {decision.reasoning_summary}")

# The guardrail has teeth: force an unsafe silent retry and let policy override it.
bad = decision.model_copy(update={"recommended_action": RecoveryActionType.DYNAMIC_BACKOFF_RETRY})
verdict = PolicyGuardrailEngine.validate(ctx, bad)
print("  " + "-" * 60)
print("  if the model had instead said 'dynamic_backoff_retry':")
print(f"    permitted    : {verdict.is_permitted}")
print(f"    enforced     : {verdict.enforced_action.value}")
print(f"    rule applied : {verdict.applied_rule}")
print("=" * 64 + "\n")
