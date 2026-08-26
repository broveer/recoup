# Recoup — AI Revenue Recovery Engine

> **Razorpay AI Buildathon 2026**  
> **Track 03 — AI Revenue Recovery**

Recoup is an AI-powered revenue recovery system for Indian payment rails (UPI, Cards, Mandates, Netbanking). It intelligently diagnoses payment failures, assesses recoverability, personalizes customer recovery nudges, and validates every decision against strict deterministic financial guardrails.

---

## 📅 Versioning Strategy
We follow an iterative daily release cycle culminating in the final submission:
* **Day 1:** `v0.1.0` — Minimal AI Recovery Agent, Structured Decision Schema & Policy Guardrails
* **Day 2 (Current):** `v0.2.0` — Synthetic Dataset Generator, Competent Non-AI Baseline, Comparative Evaluation Benchmark
* **Day 3–11:** `v0.3.0` $\rightarrow$ `v0.11.0` — Razorpay Test-Mode integration, Multi-channel execution, Interactive Web Checkout Simulator
* **Day 12:** `v1.0.0` — Complete Final Submission

---

## 🏛️ v0.2.0 Architecture

```text
[Synthetic Dataset (dataset.py)]
   ├── dev_cohort_50.json (50 cases)
   └── eval_cohort_100.json (100 held-out cases)
          ↓
[Dual Pipeline Evaluation (benchmark.py)]
   ├── Non-AI Rule Baseline (baseline.py)   <-- Standard static rule table
   └── Recoup AI Agent (agent.py)           <-- Granite 4.1 8B on RTX GPU
          ↓
[Policy Guardrail Engine (policy.py)]       <-- Deterministic Safety Validation
          ↓
[Outcome Simulator & Economic Metrics]
   ├── Net Revenue Recovered (₹)
   ├── Recovery Success Rate (%)
   └── Friction Costs & Policy Violations Prevented
```

---

## 🚀 Quickstart (v0.2.0)

### 1. Requirements
* Python 3.10+
* Dependencies: `pydantic`, `httpx`, `rich`
* Local GPU / Ollama model (`granite4.1:8b` or heuristic fallback)

### 2. Run the Comparative Benchmark
```bash
python benchmark.py
```

### 3. Run Individual Scenario Inspection
```bash
python run_agent.py
```

---

## 🛡️ Financial Guardrails Enforced in v0.1.0
1. **Hard Decline Zero-Retry Rule:** Expired, lost, or stolen cards immediately halt automated retries (`0 retries permitted`).
2. **Customer Opt-Out Rule:** If a customer has opted out, all recovery actions are instantly terminated.
3. **High-Value Escalation Gate:** Transactions $\ge \text{₹50,000}$ or enterprise accounts are automatically escalated to human sales/merchant ops.
4. **Max Retry Limits:** Category-specific retry caps prevent merchant fee burning and bank spam.
