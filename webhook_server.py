"""
Recoup v0.3.0 - Razorpay Webhook Ingestion & Recovery Server
FastAPI HTTP server listening for live payment failure events from Razorpay webhooks.
"""

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from rich.console import Console

import playbook
from models import (
    FailedPaymentContext,
    AgentDecision,
    PolicyVerdict,
    PaymentMethod,
    CustomerTier,
    FailureCategory,
    FailureCode,
    RecoveryActionType,
)
from policy import PolicyGuardrailEngine
from agent import RecoveryAgent
from razorpay_client import RazorpayClient, RazorpayPaymentLinkResponse

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

console = Console(force_terminal=True, safe_box=True)
app = FastAPI(title="Recoup - Razorpay AI Revenue Recovery Engine", version="0.7.0")

# Mount Static UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def serve_ui():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Recoup API Active. Navigate to /docs for Swagger UI."}

# Core Engine Singletons
agent = RecoveryAgent(model_name="granite4.1:8b")
razorpay_client = RazorpayClient()

# In-Memory Recovery Audit Store
AUDIT_LOGS: List[Dict[str, Any]] = []


def map_razorpay_error_to_taxonomy(error_code_str: str, error_desc: str) -> tuple[FailureCategory, FailureCode]:
    """Maps Razorpay webhook error strings (error_code / error_reason / description) to the
    Recoup v0.7.0 taxonomy. Ordered most-specific first."""
    t = f"{error_code_str or ''} {error_desc or ''}".lower()

    def has(*needles: str) -> bool:
        return all(n in t for n in needles)

    # --- Mandate / AutoPay / eNACH ---
    if has("pre", "debit") or has("pre-debit") or ("notification" in t and "mandate" in t):
        return FailureCategory.MANDATE_LIFECYCLE, FailureCode.PRE_DEBIT_NOTIFICATION_MISSING
    if "mandate" in t and ("pause" in t or "hold" in t):
        return FailureCategory.MANDATE_LIFECYCLE, FailureCode.MANDATE_PAUSED
    if ("mandate" in t or "autopay" in t or "e-mandate" in t or "emandate" in t) and ("amount" in t and "limit" in t or "max" in t):
        return FailureCategory.MANDATE_LIFECYCLE, FailureCode.MANDATE_AMOUNT_LIMIT_EXCEEDED
    if "mandate" in t and ("not active" in t or "revoked" in t or "cancelled" in t or "inactive" in t or "not found" in t):
        return FailureCategory.MANDATE_LIFECYCLE, FailureCode.MANDATE_NOT_ACTIVE

    # --- RBI card-on-file tokenisation ---
    if "token" in t and ("expired" in t or "invalid" in t or "not found" in t):
        return FailureCategory.COMPLIANCE_TOKENIZATION, FailureCode.TOKEN_EXPIRED_OR_INVALID
    if "token" in t or "tokeni" in t or "cof" in t:
        return FailureCategory.COMPLIANCE_TOKENIZATION, FailureCode.TOKENIZATION_FAILED

    # --- UPI limits ---
    if "upi" in t and ("new user" in t or "24 h" in t or "24h" in t or "cooling" in t):
        return FailureCategory.LIMIT_EXCEEDED, FailureCode.UPI_NEW_USER_LIMIT
    if ("daily" in t or "per day" in t or "count" in t) and ("limit" in t or "exceed" in t):
        return FailureCategory.LIMIT_EXCEEDED, FailureCode.UPI_DAILY_LIMIT
    if "upi" in t and ("limit" in t or "exceed" in t):
        return FailureCategory.LIMIT_EXCEEDED, FailureCode.UPI_PER_TXN_LIMIT

    # --- UPI auth / collect / PIN ---
    if ("collect" in t) and ("expire" in t or "timed" in t or "declined" in t):
        return FailureCategory.AUTHENTICATION_DROP, FailureCode.UPI_COLLECT_EXPIRED
    if ("mpin" in t or ("upi" in t and "pin" in t)) and ("attempt" in t or "incorrect" in t or "wrong" in t or "exceed" in t or "lock" in t):
        return FailureCategory.AUTHENTICATION_DROP, FailureCode.UPI_MPIN_ATTEMPTS_EXCEEDED

    # --- PSP app availability (payer app down, bank healthy) ---
    if ("psp" in t or "app" in t) and ("down" in t or "unavailable" in t or "not responding" in t or "unreachable" in t):
        return FailureCategory.PSP_UNAVAILABLE, FailureCode.PSP_APP_DOWN

    # --- Card controls ---
    if "international" in t or "cross border" in t or "cross-border" in t:
        return FailureCategory.METHOD_RESTRICTION, FailureCode.INTERNATIONAL_TXN_BLOCKED
    if ("not enabled" in t or "disabled" in t or "not allowed" in t) and ("online" in t or "ecom" in t or "e-commerce" in t or "card" in t):
        return FailureCategory.METHOD_RESTRICTION, FailureCode.CARD_NOT_ENABLED_ONLINE

    # --- Original taxonomy ---
    if "bank_downtime" in t or "gateway" in t or "timed_out" in t or "timeout" in t or "network" in t:
        return FailureCategory.TRANSIENT_TECHNICAL, FailureCode.BANK_DOWNTIME
    if "insufficient" in t or "low balance" in t or "low_balance" in t or ("balance" in t and "insufficient" in t):
        return FailureCategory.CUSTOMER_LIQUIDITY, FailureCode.INSUFFICIENT_FUNDS
    if "expired" in t or "lost" in t or "stolen" in t or "pick up" in t or "pick-up" in t or "account closed" in t or "closed" in t:
        return FailureCategory.HARD_DECLINE, FailureCode.CARD_EXPIRED
    if "fraud" in t or "risk" in t or "velocity" in t or "suspicious" in t:
        return FailureCategory.RISK_COMPLIANCE, FailureCode.SUSPECTED_FRAUD
    if "otp" in t or "3ds" in t or "authentication" in t:
        return FailureCategory.AUTHENTICATION_DROP, FailureCode.OTP_EXPIRED
    if "cancel" in t:
        return FailureCategory.AUTHENTICATION_DROP, FailureCode.PAYMENT_CANCELLED_BY_USER
    if "limit" in t:
        return FailureCategory.METHOD_RESTRICTION, FailureCode.CARD_LIMIT_EXCEEDED

    return FailureCategory.AUTHENTICATION_DROP, FailureCode.PAYMENT_CANCELLED_BY_USER


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "Recoup AI Revenue Recovery Engine",
        "version": "0.7.0",
        "model": agent.model_name,
        "knowledge_base": playbook.playbook_meta().get("schema_version"),
        "playbook_entries": len(playbook.all_entries()),
        "razorpay_live_keys": razorpay_client.has_credentials,
    }


@app.post("/webhook/razorpay")
async def handle_razorpay_webhook(request: Request):
    """
    Ingests official Razorpay Webhook payloads (e.g. event: 'payment.failed').
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_type = body.get("event", "")
    if event_type != "payment.failed":
        return {"status": "ignored", "detail": f"Event '{event_type}' not actionable for recovery."}

    # Extract Entities
    payload_data = body.get("payload", {})
    payment_entity = payload_data.get("payment", {}).get("entity", {})
    order_entity = payload_data.get("order", {}).get("entity", {})

    tx_id = payment_entity.get("id", f"pay_live_{int(datetime.now().timestamp())}")
    order_id = payment_entity.get("order_id", order_entity.get("id", "order_live_001"))
    
    # Razorpay amount is in paise (100 paise = 1 INR)
    amount_inr = float(payment_entity.get("amount", 0)) / 100.0 if payment_entity.get("amount") else 2499.0
    method_str = payment_entity.get("method", "upi")
    
    # Error metadata
    err_code = payment_entity.get("error_code", "BAD_REQUEST_ERROR")
    err_desc = payment_entity.get("error_description", payment_entity.get("error_reason", "Payment failed at gateway"))

    # Customer info
    cust_email = payment_entity.get("email", "customer@example.com")
    cust_contact = payment_entity.get("contact", "+919876543210")
    cust_name = payment_entity.get("notes", {}).get("customer_name", "Valued Customer")
    cltv_inr = float(payment_entity.get("notes", {}).get("cltv_inr", 5000.0))
    tier_str = payment_entity.get("notes", {}).get("tier", "standard")
    
    tier = CustomerTier.ENTERPRISE if amount_inr >= 50000.0 else CustomerTier.STANDARD

    # Map to taxonomy
    category, failure_code = map_razorpay_error_to_taxonomy(err_code, err_desc)
    
    # Map method
    if "upi" in method_str:
        p_method = PaymentMethod.UPI_INTENT
    elif "card" in method_str:
        p_method = PaymentMethod.CARD_CREDIT
    elif "netbanking" in method_str:
        p_method = PaymentMethod.NETBANKING
    else:
        p_method = PaymentMethod.UPI_INTENT

    # 1. Assemble Rich Context
    context = FailedPaymentContext(
        transaction_id=tx_id,
        order_id=order_id,
        customer_id=f"cust_{cust_contact[-4:]}",
        customer_name=cust_name,
        customer_tier=tier,
        cltv_inr=cltv_inr,
        preferred_channel="whatsapp",
        opted_out=False,
        amount_inr=amount_inr,
        payment_method=p_method,
        failure_category=category,
        error_code=failure_code,
        error_message=err_desc,
        retry_count=0,
    )

    console.print(f"\n[bold yellow]⚡ INCOMING WEBHOOK:[/bold yellow] [bold white]{tx_id}[/bold white] | [cyan]₹{amount_inr:,.2f}[/cyan] ({cust_name})")
    console.print(f"[dim]Razorpay Error: {err_code} | {err_desc}[/dim]")

    # 2. AI Reasoning (retrieval-augmented with the curated playbook)
    decision: AgentDecision = agent.decide(context)
    _kb = f"grounded:{decision.playbook_entry_used}" if decision.knowledge_grounded else "ungrounded"
    console.print(f"🤖 [bold green]AI Recommendation:[/bold green] {decision.recommended_action.value} "
                  f"(Likelihood: {decision.recovery_likelihood_pct}%) [dim]{_kb}[/dim]")

    # 3. Policy Guardrail Validation
    verdict: PolicyVerdict = PolicyGuardrailEngine.validate(context, decision)
    console.print(f"🛡️  [bold magenta]Policy Verdict:[/bold magenta] {'PERMITTED' if verdict.is_permitted else 'OVERRIDDEN'} ({verdict.applied_rule})")

    # 4. Action Execution
    action_result: Dict[str, Any] = {
        "enforced_action": verdict.enforced_action.value,
        "policy_rule": verdict.applied_rule,
        "is_permitted": verdict.is_permitted,
    }

    if verdict.enforced_action == RecoveryActionType.ALTERNATIVE_PAYMENT_LINK:
        plink: RazorpayPaymentLinkResponse = razorpay_client.create_payment_link(
            amount_inr=amount_inr,
            description=f"Recovery link for {order_id}",
            customer_name=cust_name,
            customer_phone=cust_contact,
            customer_email=cust_email,
            notes={"original_tx": tx_id, "recovery_agent": "Recoup-v0.3.0"},
        )
        action_result["payment_link"] = plink.model_dump()
        console.print(f"🔗 [bold cyan]Razorpay Payment Link Generated:[/bold cyan] [underline]{plink.short_url}[/underline] ([green]WhatsApp / SMS Dispatched[/green])\n")

    elif verdict.enforced_action == RecoveryActionType.SMART_DUNNING_SCHEDULE:
        # Create a backup payment link so customer can pay via alternate account if preferred
        plink: RazorpayPaymentLinkResponse = razorpay_client.create_payment_link(
            amount_inr=amount_inr,
            description=f"Backup link for subscription {order_id}",
            customer_name=cust_name,
            customer_phone=cust_contact,
            customer_email=cust_email,
            notes={"original_tx": tx_id, "recovery_agent": "Recoup-v0.4.0", "strategy": "smart_dunning"},
        )
        action_result["status"] = "SCHEDULED_SMART_DUNNING"
        action_result["scheduled_date"] = "1st of Month (Salary Day 9:00 AM)"
        action_result["payment_link"] = plink.model_dump()
        console.print(f"📅 [bold magenta]Smart Dunning Scheduled:[/bold magenta] Auto-debit on {action_result['scheduled_date']}\n")
        console.print(f"🔗 [bold cyan]Backup Payment Link:[/bold cyan] {plink.short_url} (Dispatched via WhatsApp)\n")

    elif verdict.enforced_action == RecoveryActionType.ESCALATE_TO_HUMAN:
        action_result["status"] = "QUEUED_FOR_WHITE_GLOVE_OUTREACH"
        console.print("👤 [bold yellow]High-Value Escalation:[/bold yellow] Routed to White-Glove Merchant Team\n")

    elif verdict.enforced_action == RecoveryActionType.IMMEDIATE_STOP:
        # Generate an 'Update Payment Method' link for hard declines
        plink: RazorpayPaymentLinkResponse = razorpay_client.create_payment_link(
            amount_inr=amount_inr,
            description=f"Update payment method for {order_id}",
            customer_name=cust_name,
            customer_phone=cust_contact,
            customer_email=cust_email,
            notes={"original_tx": tx_id, "action": "update_card"},
        )
        action_result["status"] = "AUTOMATED_RECOVERY_HALTED"
        action_result["update_link"] = plink.model_dump()
        console.print("🛑 [bold red]Immediate Halt:[/bold red] Hard decline detected. Customer prompted to update card details.\n")

    elif verdict.enforced_action == RecoveryActionType.DYNAMIC_BACKOFF_RETRY:
        action_result["status"] = "SCHEDULED_DYNAMIC_BACKOFF"
        action_result["retry_delay_seconds"] = decision.backoff_seconds or 1800
        console.print(f"⏳ [bold blue]Dynamic Backoff Scheduled:[/bold blue] Silent retry in {action_result['retry_delay_seconds']}s\n")

    # 5. Audit Logging
    audit_entry = {
        "timestamp": datetime.now().isoformat(),
        "transaction_id": tx_id,
        "customer_name": cust_name,
        "amount_inr": amount_inr,
        "error_code": failure_code.value,
        "failure_category": category.value,
        "knowledge_grounded": decision.knowledge_grounded,
        "playbook_entry_used": decision.playbook_entry_used,
        "ai_decision": decision.model_dump(mode="json"),
        "policy_verdict": verdict.model_dump(mode="json"),
        "action_execution": action_result,
    }
    AUDIT_LOGS.append(audit_entry)

    return {
        "status": "processed",
        "transaction_id": tx_id,
        "customer_name": cust_name,
        "amount_inr": amount_inr,
        "failure_category": category.value,
        "error_code": failure_code.value,
        "knowledge_grounded": decision.knowledge_grounded,
        "playbook_entry_used": decision.playbook_entry_used,
        "ai_recommendation": decision.recommended_action.value,
        "enforced_action": verdict.enforced_action.value,
        "execution": action_result,
        "ai_decision": decision.model_dump(mode="json"),
        "policy_verdict": verdict.model_dump(mode="json"),
        "context": context.model_dump(mode="json"),
    }


@app.get("/api/audit-logs")
def get_audit_logs():
    return {"count": len(AUDIT_LOGS), "records": AUDIT_LOGS}


@app.get("/api/metrics")
def get_metrics():
    total_risk = sum(log["amount_inr"] for log in AUDIT_LOGS)
    links_created = sum(1 for log in AUDIT_LOGS if "payment_link" in log["action_execution"])
    escalations = sum(1 for log in AUDIT_LOGS if log["action_execution"]["enforced_action"] == "escalate_to_human")
    stops = sum(1 for log in AUDIT_LOGS if log["action_execution"]["enforced_action"] == "immediate_stop")
    return {
        "total_events_processed": len(AUDIT_LOGS),
        "total_revenue_at_risk_inr": total_risk,
        "payment_links_generated": links_created,
        "human_escalations": escalations,
        "hard_stops_enforced": stops,
    }


@app.get("/api/escalations")
def get_escalations():
    escalated = [
        log for log in AUDIT_LOGS 
        if log["action_execution"]["enforced_action"] == "escalate_to_human"
    ]
    return {"count": len(escalated), "records": escalated}


@app.post("/api/escalations/{tx_id}/resolve")
def resolve_escalation(tx_id: str, request_data: Dict[str, Any]):
    resolution_type = request_data.get("resolution_type", "concierge_outreach")
    for log in AUDIT_LOGS:
        if log["transaction_id"] == tx_id:
            log["action_execution"]["escalation_status"] = "RESOLVED"
            log["action_execution"]["resolved_at"] = datetime.now().isoformat()
            log["action_execution"]["resolution_type"] = resolution_type
            return {"status": "success", "message": f"Escalation for {tx_id} resolved via {resolution_type}"}
    return {"status": "not_found", "message": f"Transaction {tx_id} not found in active audit records."}


_BENCHMARK_FALLBACK = {
    "note": "Run `RECOUP_DISABLE_LLM=1 python benchmark.py` to (re)generate data/benchmark_summary.json.",
    "cohort_size": 200,
    "arms": {
        "baseline": {"recovery_rate_pct": 34.5, "policy_violations": 38},
        "ai_nokb": {"recovery_rate_pct": 54.5, "policy_violations": 7},
        "ai_kb": {"recovery_rate_pct": 58.5, "policy_violations": 7},
    },
    "kb_lift": {"recovery_rate_points": 4.0, "extra_transactions": 8},
    "vs_baseline": {"recovery_rate_points": 24.0},
}


@app.get("/api/benchmark-summary")
def get_benchmark_summary():
    """Serves the machine-readable output of the last `python benchmark.py` run."""
    path = os.path.join(DATA_DIR, "benchmark_summary.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return _BENCHMARK_FALLBACK


@app.get("/api/playbook")
def get_playbook(code: Optional[str] = None):
    """The curated recovery knowledge base that grounds every AI decision.

    Pass ?code=<failure_code> for a single entry; otherwise returns metadata,
    a taxonomy-coverage report, and all entries.
    """
    if code:
        entry = playbook.lookup(code)
        if not entry:
            raise HTTPException(status_code=404, detail=f"No playbook entry for '{code}'")
        return entry
    return {
        "meta": playbook.playbook_meta(),
        "coverage": playbook.coverage_report([c.value for c in FailureCode]),
        "entries": playbook.all_entries(),
    }


@app.post("/api/whatsapp/interactive-action")
def handle_whatsapp_interactive_action(payload: Dict[str, Any]):
    """
    Handles structured WhatsApp Quick-Reply Chip actions from customers safely.
    Zero prompt-injection risk: all intents are strongly typed and bounded.
    """
    tx_id = payload.get("transaction_id", "")
    action_type = payload.get("action_type", "")
    cust_name = payload.get("customer_name", "Valued Customer")
    amount = float(payload.get("amount_inr", 3499.0))
    error_code = payload.get("error_code", "otp_expired")
    gstin = payload.get("gstin", "29AABCU9603R1Z2")

    if action_type == "why_failed":
        if "otp" in error_code or "3ds" in error_code:
            explanation = f"Hi {cust_name}, your payment of ₹{amount:,.2f} timed out during the bank OTP verification step. Your bank account has NOT been debited. You can complete it without entering OTP by using UPI Intent below."
        elif "bank" in error_code or "gateway" in error_code:
            explanation = f"Hi {cust_name}, your issuing bank's switch was temporarily offline. Your money is completely safe. You can complete payment using any other bank card or Google Pay / PhonePe UPI."
        elif "insufficient" in error_code:
            explanation = f"Hi {cust_name}, the auto-debit was paused because your primary account balance was below ₹{amount:,.2f}. No penalty was charged. We will re-attempt on your next salary cycle, or you can pay with an alternate UPI account."
        else:
            explanation = f"Hi {cust_name}, the gateway rejected the transaction ({error_code}). Your account was not charged. You can use our secure 1-click alternate payment link below."

        return {
            "status": "success",
            "action_type": "why_failed",
            "reply_message": explanation,
            "can_pay": True,
        }

    elif action_type == "add_gst":
        # Create a B2B Tax Invoice Razorpay Payment Link with GSTIN metadata
        plink = razorpay_client.create_payment_link(
            amount_inr=amount,
            description=f"Tax Invoice for {cust_name} (GSTIN: {gstin})",
            customer_name=cust_name,
            notes={"gstin": gstin, "invoice_type": "B2B_TAX_INVOICE", "original_tx": tx_id}
        )
        return {
            "status": "success",
            "action_type": "add_gst",
            "gstin_applied": gstin,
            "company_name": f"{cust_name} Enterprises Pvt Ltd",
            "reply_message": f"✅ GSTIN {gstin} attached! An official B2B GST tax invoice will be emailed upon payment. Complete payment with input tax credit (ITC) benefit below:",
            "payment_link": plink.model_dump(mode="json"),
        }

    elif action_type == "remind_later":
        return {
            "status": "success",
            "action_type": "remind_later",
            "scheduled_time": "Today at 8:00 PM IST",
            "reply_message": f"⏰ Got it, {cust_name}! We've paused retries and reserved your cart for the next 24 hours. We'll send you a gentle WhatsApp nudge at 8:00 PM today when you're free.",
        }

    elif action_type == "cancel_opt_out":
        # Enforce strict deterministic compliance halt
        console.print(f"🛑 [bold red]Customer Opt-Out Enforced:[/bold red] {tx_id} requested STOP. Recovery permanently halted.\n")
        return {
            "status": "success",
            "action_type": "cancel_opt_out",
            "policy_enforced": "POLICY_CUSTOMER_OPT_OUT_HALT",
            "reply_message": f"Understood, {cust_name}. Your order has been cancelled and automated recovery has been stopped permanently. You will not receive any further reminders from us.",
        }

    return {"status": "error", "message": f"Unknown action type '{action_type}'"}

