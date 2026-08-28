# Recoup — AI Revenue Recovery Engine

> **Razorpay AI Buildathon 2026**  
> **Track 03 — AI Revenue Recovery**

Recoup is an AI-powered revenue recovery system for Indian payment rails (UPI, Cards, Mandates, Netbanking). It intelligently diagnoses payment failures, assesses recoverability, personalizes customer recovery nudges, and validates every decision against strict deterministic financial guardrails.

---

## 📅 Versioning Strategy
We follow an iterative daily release cycle culminating in the final submission:
* **Day 1:** `v0.1.0` — Minimal AI Recovery Agent, Structured Decision Schema & Policy Guardrails
* **Day 2:** `v0.2.0` — Synthetic Dataset Generator, Competent Non-AI Baseline, Comparative Evaluation Benchmark
* **Day 3 (Current):** `v0.3.0` — Razorpay Test-Mode Connector, Live Webhook Receiver (`payment.failed`), 1-Click Payment Link Generator
* **Day 4–11:** `v0.4.0` $\rightarrow$ `v0.11.0` — Multi-channel execution, Interactive Web Checkout Simulator, Human Escalation Dashboard
* **Day 12:** `v1.0.0` — Complete Final Submission

---

## 🏛️ v0.3.0 Architecture

```text
[Razorpay Checkout Failure]
          ↓
[POST /webhook/razorpay (FastAPI)]  <-- Ingests `payment.failed` webhooks
          ↓
[Context Assembler & AI Agent]      <-- Granite 4.1 8B on RTX GPU
          ↓
[Deterministic Policy Engine]       <-- Financial Safety Guardrails
          ↓
[Razorpay API Client]               <-- Generates 1-click Payment Links (`/v1/payment_links`)
          ↓
[Live Audit Stream & Metrics API]   <-- Real-time recovery analytics
```

---

## 🚀 Quickstart (v0.3.0)

### 1. Requirements
* Python 3.10+
* Dependencies: `fastapi`, `uvicorn`, `pydantic`, `httpx`, `rich`
* Local GPU / Ollama model (`granite4.1:8b` or heuristic fallback)

### 2. Start the Live Webhook Server
```bash
python -m uvicorn webhook_server:app --port 8000
```

### 3. Run Live Webhook Ingestion Tests
```bash
python test_live_recovery.py
```

### 4. Run Comparative Benchmark
```bash
python benchmark.py
```

---

## 🛡️ Financial Guardrails Enforced in v0.1.0
1. **Hard Decline Zero-Retry Rule:** Expired, lost, or stolen cards immediately halt automated retries (`0 retries permitted`).
2. **Customer Opt-Out Rule:** If a customer has opted out, all recovery actions are instantly terminated.
3. **High-Value Escalation Gate:** Transactions $\ge \text{₹50,000}$ or enterprise accounts are automatically escalated to human sales/merchant ops.
4. **Max Retry Limits:** Category-specific retry caps prevent merchant fee burning and bank spam.
