# Recoup — AI Revenue Recovery Engine

> **Razorpay AI Buildathon 2026**  
> **Track 03 — AI Revenue Recovery**

Recoup is an AI-powered revenue recovery system for Indian payment rails (UPI, Cards, Mandates, Netbanking). It intelligently diagnoses payment failures, assesses recoverability, personalizes customer recovery nudges, and validates every decision against strict deterministic financial guardrails.

---

## 📅 Versioning Strategy
We follow a 12-day iterative daily release cycle culminating in the final submission:
* **Day 1 (Current):** `v0.1.0` — Minimal AI Recovery Agent, Structured Decision Schema & Policy Guardrails
* **Day 2–11:** `v0.2.0` $\rightarrow$ `v0.11.0` — Synthetic evaluation cohort, Non-AI Baseline, Benchmark metrics, Razorpay Test-Mode integration, Multi-channel execution
* **Day 12:** `v1.0.0` — Complete Final Submission

---

## 🏛️ v0.1.0 Architecture

```text
[Failed Payment Event]
          ↓
[Context Model (models.py)]
          ↓
[AI Recovery Agent (agent.py)]  <-- Ollama / Local LLM Reasoning
          ↓
[Agent Decision JSON] (Action, Recovery Likelihood %, Customer Message, Rationale)
          ↓
[Policy Guardrail Engine (policy.py)] <-- Deterministic Financial Safety Rules
          ↓
[Enforced Safe Action] (Retry / Nudge / Escalate / Hard Stop)
```

---

## 🚀 Quickstart (v0.1.0)

### 1. Requirements
* Python 3.10+
* Dependencies: `pydantic`, `httpx`, `rich`
* (Optional) [Ollama](https://ollama.ai/) running locally with `llama3.2` or any preferred model.

### 2. Run the Demo
```bash
python run_agent.py
```

---

## 🛡️ Financial Guardrails Enforced in v0.1.0
1. **Hard Decline Zero-Retry Rule:** Expired, lost, or stolen cards immediately halt automated retries (`0 retries permitted`).
2. **Customer Opt-Out Rule:** If a customer has opted out, all recovery actions are instantly terminated.
3. **High-Value Escalation Gate:** Transactions $\ge \text{₹50,000}$ or enterprise accounts are automatically escalated to human sales/merchant ops.
4. **Max Retry Limits:** Category-specific retry caps prevent merchant fee burning and bank spam.
