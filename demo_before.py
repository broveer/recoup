"""
Demo scene 1 - BEFORE: the agent meets a failure it has no knowledge of.

    python demo_before.py

Deterministic (RECOUP_DISABLE_LLM=1) - no GPU, no network.
"""
import os

os.environ["RECOUP_DISABLE_LLM"] = "1"

from models import FailedPaymentContext, PaymentMethod, FailureCategory, FailureCode
from agent import RecoveryAgent

ctx = FailedPaymentContext(
    transaction_id="pay_DEMO_1", order_id="o1", customer_id="c1",
    customer_name="Ananya Iyer", amount_inr=649.0,
    payment_method=PaymentMethod.UPI_AUTOPAY,
    failure_category=FailureCategory.MANDATE_LIFECYCLE,
    error_code=FailureCode.PRE_DEBIT_NOTIFICATION_MISSING,
    error_message="Recurring debit attempted without the mandatory 24h pre-debit notification.",
)

decision = RecoveryAgent(use_playbook=False).decide(ctx)   # <-- no knowledge base

print("\n" + "=" * 64)
print("  BEFORE  -  agent with NO knowledge base")
print("=" * 64)
print(f"  scenario       : UPI AutoPay debit, RBI 24h pre-debit notice not sent")
print(f"  failure code   : {ctx.error_code.value}")
print("  " + "-" * 60)
print(f"  recommended    : {decision.recommended_action.value}")
print(f"  knowledge      : {'grounded' if decision.knowledge_grounded else 'NONE - operating on a guess'}")
print(f"  needs a human  : {decision.requires_human_approval}")
print(f"  reasoning      : {decision.reasoning_summary}")
print("=" * 64 + "\n")
