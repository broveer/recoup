"""
Recoup v0.1.0 - AI Revenue Recovery Agent
Uses Ollama (local LLM) to analyze failed payment context, assess recovery likelihood,
and formulate personalized, safe intervention recommendations with structured JSON.
"""

import json
import httpx
from models import (
    FailedPaymentContext,
    AgentDecision,
    RecoveryActionType,
    FailureCategory,
    FailureCode,
)


import re

class RecoveryAgent:
    def __init__(self, model_name: str = "granite4.1:8b", host: str = "http://localhost:11434"):
        self.model_name = model_name
        self.host = host

    def _build_system_prompt(self) -> str:
        return (
            "You are Recoup, an expert AI Revenue Recovery Agent for Indian payment rails (UPI, Cards, Mandates, Netbanking).\n"
            "Your objective: Analyze failed payment events, determine why they failed, evaluate recoverability, and recommend the best intervention.\n"
            "Available Actions:\n"
            "- 'dynamic_backoff_retry': For transient gateway/bank timeouts. Silent background retry during bank off-peak hours.\n"
            "- 'alternative_payment_link': For OTP dropoffs, user cancellations, or payment friction. Send instant 1-click Razorpay payment link via WhatsApp/SMS.\n"
            "- 'method_switch_nudge': When card limits or bank netbanking fails. Suggest switching to UPI Intent / alternate card.\n"
            "- 'smart_dunning_schedule': For insufficient funds on subscriptions/mandates. Schedule retry on liquidity dates.\n"
            "- 'escalate_to_human': For high-value transactions (>= ₹50,000) or enterprise accounts requiring white-glove merchant outreach.\n"
            "- 'immediate_stop': For expired cards, stolen instruments, or closed accounts. Zero retries allowed.\n\n"
            "Return ONLY a valid JSON object strictly matching this schema:\n"
            "{\n"
            '  "recommended_action": "dynamic_backoff_retry" | "alternative_payment_link" | "method_switch_nudge" | "smart_dunning_schedule" | "escalate_to_human" | "immediate_stop",\n'
            '  "recovery_likelihood_pct": float (0 to 100),\n'
            '  "confidence_score": float (0.0 to 1.0),\n'
            '  "backoff_seconds": int,\n'
            '  "channel": "whatsapp" | "sms" | "email" | "silent_retry",\n'
            '  "customer_message": "Concise, empathetic draft message for customer or null if silent",\n'
            '  "reasoning_summary": "Clear, concise 2-sentence rationale for this decision",\n'
            '  "requires_human_approval": bool\n'
            "}"
        )

    def _build_user_prompt(self, context: FailedPaymentContext) -> str:
        return (
            f"Analyze this failed payment event:\n"
            f"- Transaction ID: {context.transaction_id}\n"
            f"- Customer Name: {context.customer_name} (Tier: {context.customer_tier.value}, CLTV: ₹{context.cltv_inr:,.2f})\n"
            f"- Amount: ₹{context.amount_inr:,.2f}\n"
            f"- Payment Method: {context.payment_method.value}\n"
            f"- Failure Category: {context.failure_category.value}\n"
            f"- Error Code: {context.error_code.value}\n"
            f"- Error Message: {context.error_message}\n"
            f"- Retry Count: {context.retry_count}\n"
            f"- Preferred Channel: {context.preferred_channel}\n"
            f"- Opted Out: {context.opted_out}\n\n"
            f"Provide your JSON decision now."
        )

    def decide(self, context: FailedPaymentContext) -> AgentDecision:
        """Analyzes context and produces structured AgentDecision via Ollama or heuristic fallback."""
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0, connect=3.0)) as client:
                payload = {
                    "model": self.model_name,
                    "system": self._build_system_prompt(),
                    "prompt": self._build_user_prompt(context),
                    "format": "json",
                    "stream": False,
                }
                response = client.post(f"{self.host}/api/generate", json=payload)
                if response.status_code == 200:
                    raw_text = response.json().get("response", "{}").strip()
                    # Strip possible markdown code blocks if returned
                    clean_json = re.sub(r"^```json\s*", "", raw_text, flags=re.MULTILINE)
                    clean_json = re.sub(r"^```\s*", "", clean_json, flags=re.MULTILINE).strip()
                    data = json.loads(clean_json)
                    return AgentDecision(
                        transaction_id=context.transaction_id,
                        recommended_action=RecoveryActionType(data.get("recommended_action", "alternative_payment_link")),
                        recovery_likelihood_pct=float(data.get("recovery_likelihood_pct", 50.0)),
                        confidence_score=float(data.get("confidence_score", 0.8)),
                        backoff_seconds=int(data.get("backoff_seconds", 0)),
                        channel=data.get("channel", context.preferred_channel),
                        customer_message=data.get("customer_message"),
                        reasoning_summary=data.get("reasoning_summary", "Live AI Agent analyzed payment context."),
                        requires_human_approval=bool(data.get("requires_human_approval", False)),
                    )
        except Exception:
            pass

        return self._heuristic_fallback(context)

    def _heuristic_fallback(self, context: FailedPaymentContext) -> AgentDecision:
        """Intelligent heuristic fallback if local LLM is temporarily unavailable."""
        if context.failure_category == FailureCategory.HARD_DECLINE:
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.IMMEDIATE_STOP,
                recovery_likelihood_pct=0.0,
                confidence_score=0.99,
                backoff_seconds=0,
                channel="whatsapp",
                customer_message=f"Hi {context.customer_name}, your payment card is expired or invalid. Please update your payment method to continue.",
                reasoning_summary="Hard decline detected. Instrument is permanently invalid; halting automated retries to prevent fees.",
                requires_human_approval=False,
            )
        elif context.amount_inr >= 50000.0 or context.customer_tier == "enterprise":
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.ESCALATE_TO_HUMAN,
                recovery_likelihood_pct=75.0,
                confidence_score=0.95,
                backoff_seconds=0,
                channel="email",
                customer_message=None,
                reasoning_summary=f"High-value transaction of ₹{context.amount_inr:,.2f} for {context.customer_name}. Route to sales/account exec for white-glove outreach.",
                requires_human_approval=True,
            )
        elif context.failure_category == FailureCategory.TRANSIENT_TECHNICAL:
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.DYNAMIC_BACKOFF_RETRY,
                recovery_likelihood_pct=85.0,
                confidence_score=0.90,
                backoff_seconds=1800,
                channel="silent_retry",
                customer_message=None,
                reasoning_summary="Transient bank or network gateway downtime detected. Scheduling silent off-peak retry in 30 minutes.",
                requires_human_approval=False,
            )
        elif context.failure_category == FailureCategory.CUSTOMER_LIQUIDITY:
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.SMART_DUNNING_SCHEDULE,
                recovery_likelihood_pct=55.0,
                confidence_score=0.85,
                backoff_seconds=86400,
                channel="whatsapp",
                customer_message=f"Hi {context.customer_name}, we couldn't process your payment of ₹{context.amount_inr:,.2f}. Here is a quick link to retry anytime: rzp.io/l/pay",
                reasoning_summary="Customer liquidity friction detected. Scheduled mandate retry and sent lightweight payment link.",
                requires_human_approval=False,
            )
        else:
            return AgentDecision(
                transaction_id=context.transaction_id,
                recommended_action=RecoveryActionType.ALTERNATIVE_PAYMENT_LINK,
                recovery_likelihood_pct=70.0,
                confidence_score=0.88,
                backoff_seconds=300,
                channel="whatsapp",
                customer_message=f"Hi {context.customer_name}, your payment was interrupted. Complete it in 1-click via UPI: rzp.io/l/quickpay",
                reasoning_summary="Authentication dropoff or user cancellation. Sending immediate 1-click payment link via WhatsApp.",
                requires_human_approval=False,
            )
