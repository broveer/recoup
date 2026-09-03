"""
Recoup v0.7.0 - AI Revenue Recovery Agent (Retrieval-Augmented)
Analyzes failed payment context, retrieves the verified recovery playbook entry for the
failure code, and produces a structured, policy-checkable AgentDecision.

Runtime model : Granite 4.1 8B via Ollama on local GPU (heuristic fallback if unavailable).
Knowledge base: data/recovery_playbook.json (curated offline by the Gemma pipeline).

`use_playbook=False` reproduces pre-v0.7 behaviour (no knowledge grounding) and is used by
benchmark.py as the "before" arm of the A/B.
"""

import json
import os
import re
import httpx

import playbook
from models import (
    FailedPaymentContext,
    AgentDecision,
    RecoveryActionType,
    FailureCategory,
    FailureCode,
)


class RecoveryAgent:
    def __init__(
        self,
        model_name: str = "granite4.1:8b",
        host: str = "http://localhost:11434",
        use_playbook: bool = True,
    ):
        self.model_name = model_name
        self.host = host
        self.use_playbook = use_playbook

    # ----------------------------------------------------------------- prompts
    def _build_system_prompt(self) -> str:
        return (
            "You are Recoup, an expert AI Revenue Recovery Agent for Indian payment rails "
            "(UPI, Cards, eNACH / UPI AutoPay mandates, Netbanking).\n"
            "Objective: given a failed payment, determine why it failed, judge recoverability, "
            "and pick the single best intervention.\n\n"
            "Available Actions (choose exactly one):\n"
            "- 'dynamic_backoff_retry': transient gateway/bank/PSP errors. Silent background retry in an off-peak window.\n"
            "- 'alternative_payment_link': OTP/session drops, expired collect, dead/paused mandates, broken card tokens. Send a 1-click Razorpay link (WhatsApp/SMS).\n"
            "- 'method_switch_nudge': a limit is breached or a method is disabled (UPI cap, card not enabled online, international blocked). Nudge to a working rail.\n"
            "- 'smart_dunning_schedule': insufficient funds, or a recurring debit that needs an RBI 24h pre-debit notification first. Schedule on a liquidity/compliant date.\n"
            "- 'escalate_to_human': >= Rs 50,000, enterprise accounts, or suspected fraud / risk.\n"
            "- 'immediate_stop': expired / closed / lost / stolen instruments. Zero retries.\n\n"
            "Failure categories you may see: transient_technical, customer_liquidity, authentication_drop, "
            "method_restriction, hard_decline, risk_compliance, high_value_ambiguity, mandate_lifecycle, "
            "limit_exceeded, compliance_tokenization, psp_unavailable.\n\n"
            "KNOWLEDGE GROUNDING:\n"
            "- If a VERIFIED PLAYBOOK ENTRY is supplied below, its 'recommended action' and 'retryable' flag are "
            "authoritative. Follow them unless an obvious safety rule forbids it. Adapt (do not copy) its customer explanation.\n"
            "- If NO playbook entry is supplied, you are working from general knowledge only: be conservative, set "
            '"requires_human_approval": true, and keep "confidence_score" <= 0.5.\n\n'
            "Return ONLY a valid JSON object with this schema:\n"
            "{\n"
            '  "recommended_action": "dynamic_backoff_retry" | "alternative_payment_link" | "method_switch_nudge" | "smart_dunning_schedule" | "escalate_to_human" | "immediate_stop",\n'
            '  "recovery_likelihood_pct": float (0 to 100),\n'
            '  "confidence_score": float (0.0 to 1.0),\n'
            '  "backoff_seconds": int,\n'
            '  "channel": "whatsapp" | "sms" | "email" | "silent_retry",\n'
            '  "customer_message": "empathetic draft, or null if silent",\n'
            '  "reasoning_summary": "2 concise sentences",\n'
            '  "requires_human_approval": bool\n'
            "}"
        )

    def _build_user_prompt(self, context: FailedPaymentContext, entry) -> str:
        base = (
            f"Analyze this failed payment event:\n"
            f"- Transaction ID: {context.transaction_id}\n"
            f"- Customer: {context.customer_name} (Tier: {context.customer_tier.value}, CLTV: Rs {context.cltv_inr:,.2f})\n"
            f"- Amount: Rs {context.amount_inr:,.2f}\n"
            f"- Payment Method: {context.payment_method.value}\n"
            f"- Failure Category: {context.failure_category.value}\n"
            f"- Error Code: {context.error_code.value}\n"
            f"- Error Message: {context.error_message}\n"
            f"- Retry Count: {context.retry_count}\n"
            f"- Preferred Channel: {context.preferred_channel}\n"
            f"- Opted Out: {context.opted_out}\n\n"
        )
        if entry:
            return base + playbook.format_for_prompt(entry) + "\n\nProvide your JSON decision now."
        if self.use_playbook:
            return base + (
                "NO VERIFIED PLAYBOOK ENTRY exists for this failure code. Operate conservatively "
                "as instructed above. Provide your JSON decision now."
            )
        return base + "Provide your JSON decision now."

    # ------------------------------------------------------------------ decide
    def decide(self, context: FailedPaymentContext) -> AgentDecision:
        entry = playbook.lookup(context.error_code.value) if self.use_playbook else None
        grounded = entry is not None
        kb_key = context.error_code.value if grounded else None
        kb_tag = "+kb" if grounded else ""

        # RECOUP_DISABLE_LLM=1 -> skip Ollama entirely (fast, reproducible benchmarking / offline demo)
        if os.getenv("RECOUP_DISABLE_LLM") == "1":
            return self._heuristic_fallback(context, entry)

        try:
            mode = "hit" if grounded else ("miss" if self.use_playbook else "off")
            print(f"[agent] {context.transaction_id} -> {self.model_name} (playbook={mode})")
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=5.0)) as client:
                payload = {
                    "model": self.model_name,
                    "system": self._build_system_prompt(),
                    "prompt": self._build_user_prompt(context, entry),
                    "format": "json",
                    "stream": False,
                }
                response = client.post(f"{self.host}/api/generate", json=payload)
                if response.status_code == 200:
                    raw_text = response.json().get("response", "{}").strip()
                    clean_json = re.sub(r"^```json\s*", "", raw_text, flags=re.MULTILINE)
                    clean_json = re.sub(r"^```\s*", "", clean_json, flags=re.MULTILINE).strip()
                    data = json.loads(clean_json)
                    print(f"[agent] {self.model_name} -> {data.get('recommended_action')} (grounded={grounded})")
                    return AgentDecision(
                        transaction_id=context.transaction_id,
                        recommended_action=RecoveryActionType(data.get("recommended_action", "alternative_payment_link")),
                        recovery_likelihood_pct=float(data.get("recovery_likelihood_pct", 50.0)),
                        confidence_score=float(data.get("confidence_score", 0.8)),
                        backoff_seconds=int(data.get("backoff_seconds", 0)),
                        channel=data.get("channel", context.preferred_channel),
                        customer_message=data.get("customer_message"),
                        reasoning_summary=data.get("reasoning_summary", "Live AI Agent analysed payment context."),
                        requires_human_approval=bool(data.get("requires_human_approval", False)),
                        decision_model=f"ollama-{self.model_name}{kb_tag}",
                        knowledge_grounded=grounded,
                        playbook_entry_used=kb_key,
                    )
                print(f"WARN [agent] Ollama non-200: {response.status_code} - {response.text[:200]}")
        except Exception as e:
            print(f"WARN [agent] Ollama unavailable ({e}). Using heuristic fallback.")

        return self._heuristic_fallback(context, entry)

    # ---------------------------------------------------------------- fallback
    def _heuristic_fallback(self, context: FailedPaymentContext, entry=None) -> AgentDecision:
        """Deterministic fallback when the local LLM is unavailable.

        With a playbook entry it follows the curated recommended action; without one it
        reproduces the conservative pre-v0.7 heuristic and flags for human approval.
        """
        grounded = entry is not None
        kb_key = context.error_code.value if grounded else None
        model_tag = "heuristic+kb" if grounded else "heuristic"

        # Safety-first overrides (independent of the knowledge base)
        if context.amount_inr >= 50000.0 or context.customer_tier == "enterprise":
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.ESCALATE_TO_HUMAN,
                recovery_likelihood_pct=75.0,
                confidence_score=0.95,
                backoff_seconds=0,
                channel="email",
                customer_message=None,
                reasoning_summary=f"High-value transaction of Rs {context.amount_inr:,.2f} for {context.customer_name}. Route to white-glove outreach.",
                requires_human_approval=True,
                decision_model=model_tag,
                knowledge_grounded=grounded,
                playbook_entry_used=kb_key,
            )

        if context.failure_category == FailureCategory.HARD_DECLINE:
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.IMMEDIATE_STOP,
                recovery_likelihood_pct=0.0,
                confidence_score=0.99,
                backoff_seconds=0,
                channel="whatsapp",
                customer_message=f"Hi {context.customer_name}, your payment card is expired or invalid. Please update your payment method to continue.",
                reasoning_summary="Hard decline detected. Instrument permanently invalid; halting automated retries.",
                requires_human_approval=False,
                decision_model=model_tag,
                knowledge_grounded=grounded,
                playbook_entry_used=kb_key,
            )

        # Playbook-grounded fallback: follow the curated recommended action
        if grounded:
            action = RecoveryActionType(entry["recommended_action"])
            backoff = 1800 if action == RecoveryActionType.DYNAMIC_BACKOFF_RETRY else (
                86400 if action == RecoveryActionType.SMART_DUNNING_SCHEDULE else 0
            )
            # WhatsApp is the higher-converting channel for any customer-facing recovery in India;
            # only silent retries and human escalations bypass it.
            if action == RecoveryActionType.DYNAMIC_BACKOFF_RETRY:
                channel = "silent_retry"
            elif action == RecoveryActionType.ESCALATE_TO_HUMAN:
                channel = "email"
            else:
                channel = "whatsapp"
            msg = None if action in (RecoveryActionType.DYNAMIC_BACKOFF_RETRY, RecoveryActionType.ESCALATE_TO_HUMAN) else (
                f"Hi {context.customer_name}, {entry['customer_explanation']}"
            )
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=action,
                recovery_likelihood_pct=70.0 if entry.get("is_retryable") else 55.0,
                confidence_score=0.9,
                backoff_seconds=backoff,
                channel=channel,
                customer_message=msg,
                reasoning_summary=f"Playbook[{entry['failure_code']}]: {entry['root_cause'][:180]}",
                requires_human_approval=False,
                decision_model=model_tag,
                knowledge_grounded=True,
                playbook_entry_used=kb_key,
            )

        # Ungrounded heuristic (pre-v0.7 behaviour) - conservative, flag for review
        if context.failure_category == FailureCategory.TRANSIENT_TECHNICAL:
            action, backoff, channel = RecoveryActionType.DYNAMIC_BACKOFF_RETRY, 1800, "silent_retry"
            msg = None
            reason = "Transient downtime detected. Scheduling silent off-peak retry."
        elif context.failure_category == FailureCategory.CUSTOMER_LIQUIDITY:
            action, backoff, channel = RecoveryActionType.SMART_DUNNING_SCHEDULE, 86400, "whatsapp"
            msg = f"Hi {context.customer_name}, we could not process Rs {context.amount_inr:,.2f}. Retry anytime: rzp.io/l/pay"
            reason = "Liquidity friction. Scheduled retry and sent a lightweight payment link."
        else:
            action, backoff, channel = RecoveryActionType.ALTERNATIVE_PAYMENT_LINK, 300, "whatsapp"
            msg = f"Hi {context.customer_name}, your payment was interrupted. Complete it in 1-click: rzp.io/l/quickpay"
            reason = "Authentication dropoff or unclassified failure. Sent a 1-click payment link."

        return AgentDecision(
            transaction_id=context.transaction_id,
            recommended_action=action,
            recovery_likelihood_pct=65.0,
            confidence_score=0.5,
            backoff_seconds=backoff,
            channel=channel,
            customer_message=msg,
            reasoning_summary=reason + " (no knowledge-base entry - conservative default)",
            requires_human_approval=True,
            decision_model=model_tag,
            knowledge_grounded=False,
            playbook_entry_used=None,
        )
