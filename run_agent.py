import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from models import (
    FailedPaymentContext,
    PaymentMethod,
    CustomerTier,
    FailureCategory,
    FailureCode,
)
from agent import RecoveryAgent
from policy import PolicyGuardrailEngine

console = Console(force_terminal=True, safe_box=True)


def run_scenarios():
    console.print("\n[bold cyan]===========================================================[/bold cyan]")
    console.print("[bold yellow]        🚀 RECOUP v0.1.0 - AI REVENUE RECOVERY AGENT        [/bold yellow]")
    console.print("[bold cyan]===========================================================[/bold cyan]\n")

    agent = RecoveryAgent(model_name="llama3.2")
    
    # 4 Realistic Failure Scenarios
    scenarios = [
        FailedPaymentContext(
            transaction_id="pay_HDFC_90214",
            order_id="order_77102",
            customer_id="cust_aditi_sharma",
            customer_name="Aditi Sharma",
            customer_tier=CustomerTier.STANDARD,
            cltv_inr=14500.0,
            amount_inr=1899.0,
            payment_method=PaymentMethod.UPI_INTENT,
            failure_category=FailureCategory.TRANSIENT_TECHNICAL,
            error_code=FailureCode.BANK_DOWNTIME,
            error_message="NPCI Switch timed out during issuing bank communication.",
            retry_count=0,
            preferred_channel="whatsapp",
        ),
        FailedPaymentContext(
            transaction_id="pay_OTP_33109",
            order_id="order_88204",
            customer_id="cust_rahul_verma",
            customer_name="Rahul Verma",
            customer_tier=CustomerTier.STANDARD,
            cltv_inr=4200.0,
            amount_inr=3499.0,
            payment_method=PaymentMethod.CARD_CREDIT,
            failure_category=FailureCategory.AUTHENTICATION_DROP,
            error_code=FailureCode.OTP_EXPIRED,
            error_message="Customer 3DS session timed out after 300 seconds.",
            retry_count=0,
            preferred_channel="whatsapp",
        ),
        FailedPaymentContext(
            transaction_id="pay_HARD_44821",
            order_id="order_99103",
            customer_id="cust_vikram_singh",
            customer_name="Vikram Singh",
            customer_tier=CustomerTier.NEW,
            cltv_inr=999.0,
            amount_inr=999.0,
            payment_method=PaymentMethod.CARD_DEBIT,
            failure_category=FailureCategory.HARD_DECLINE,
            error_code=FailureCode.CARD_EXPIRED,
            error_message="Card validity date has passed (Expired 07/26).",
            retry_count=0,
            preferred_channel="sms",
        ),
        FailedPaymentContext(
            transaction_id="pay_ENT_55012",
            order_id="order_11204",
            customer_id="cust_zenith_technologies",
            customer_name="Zenith Technologies Ltd",
            customer_tier=CustomerTier.ENTERPRISE,
            cltv_inr=450000.0,
            amount_inr=125000.0,
            payment_method=PaymentMethod.NETBANKING,
            failure_category=FailureCategory.HIGH_VALUE_AMBIGUITY,
            error_code=FailureCode.CARD_LIMIT_EXCEEDED,
            error_message="Single transaction limit exceeded on corporate netbanking.",
            retry_count=0,
            preferred_channel="email",
        ),
    ]

    for idx, ctx in enumerate(scenarios, 1):
        console.print(f"[bold white on blue] SCENARIO {idx} [/bold white on blue] [bold]{ctx.transaction_id}[/bold] - [yellow]₹{ctx.amount_inr:,.2f}[/yellow] ({ctx.customer_name})")
        console.print(f"[dim]Error: {ctx.error_code.value} | Reason: {ctx.error_message}[/dim]\n")

        # 1. AI Decision
        decision = agent.decide(ctx)

        # 2. Policy Validation
        verdict = PolicyGuardrailEngine.validate(ctx, decision)

        # Render Rich Table
        table = Table(show_header=True, header_style="bold magenta", expand=True)
        table.add_column("Component", style="cyan", width=22)
        table.add_column("Details & Output", style="white")

        table.add_row("Payment Context", f"Method: [green]{ctx.payment_method.value}[/green] | Category: [yellow]{ctx.failure_category.value}[/yellow] | CLTV: ₹{ctx.cltv_inr:,.2f}")
        table.add_row("AI Recommendation", f"[bold yellow]{decision.recommended_action.value}[/bold yellow] (Likelihood: [bold green]{decision.recovery_likelihood_pct}%[/bold green], Conf: {decision.confidence_score})")
        table.add_row("AI Reasoning", f"[italic]{decision.reasoning_summary}[/italic]")
        
        if decision.customer_message:
            table.add_row("Draft Message", f"[dim]\"{decision.customer_message}\"[/dim] ([cyan]{decision.channel}[/cyan])")
            
        status_color = "bold green" if verdict.is_permitted else "bold red"
        table.add_row("Policy Verdict", f"[{status_color}]{'PERMITTED' if verdict.is_permitted else 'OVERRIDDEN'}[/{status_color}] (Rule: [dim]{verdict.applied_rule}[/dim])")
        
        if not verdict.is_permitted:
            table.add_row("Violations Prevented", "\n".join(f"[red]• {v}[/red]" for v in verdict.violation_reasons))
            
        table.add_row("Enforced Final Action", f"[bold green]{verdict.enforced_action.value.upper()}[/bold green]")

        console.print(table)
        console.print("-" * 75 + "\n")

    console.print("[bold green]✅ v0.1.0 Agent Execution Complete! All scenarios safely evaluated.[/bold green]\n")


if __name__ == "__main__":
    run_scenarios()
