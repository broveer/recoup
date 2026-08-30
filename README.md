# Recoup — AI Revenue Recovery Engine

> **Razorpay AI Buildathon 2026**  
> **Track 03 — AI Revenue Recovery**

Recoup is an AI-powered revenue recovery system for Indian payment rails (UPI, Cards, Mandates, Netbanking). It intelligently diagnoses payment failures, assesses recoverability, personalizes customer recovery nudges, and validates every decision against strict deterministic financial guardrails.

---

## 📅 Versioning Strategy
We follow an iterative daily release cycle culminating in the final submission:
* **Day 1:** `v0.1.0` — Minimal AI Recovery Agent, Structured Decision Schema & Policy Guardrails
* **Day 2:** `v0.2.0` — Synthetic Dataset Generator, Competent Non-AI Baseline, Comparative Evaluation Benchmark
* **Day 3:** `v0.3.0` — Razorpay Test-Mode Connector, Live Webhook Receiver (`payment.failed`), 1-Click Payment Link Generator
* **Day 4:** `v0.4.0` / `v0.4.1` — Interactive Neo-Brutalist Web Simulator & Dedicated Action Cards
* **Day 5 (Current):** `v0.5.0` — VIP Human Escalation Desk, Live Comparative Benchmark Visualizer, and Multi-Rail Lift Breakdown
* **Day 6–11:** `v0.6.0` $\rightarrow$ `v0.11.0` — Multi-channel execution, Test Suite, Demo Video Recording Package
* **Day 12:** `v1.0.0` — Complete Final Submission

---

## 🏛️ v0.5.0 Architecture

```text
[Interactive Neo-Brutalist Suite (http://localhost:8000)]
   ├── Tab 1: Live Checkout & Recovery Simulator (Razorpay 1-Click WhatsApp)
   ├── Tab 2: VIP Human Escalation Queue (High-Ticket / Enterprise Guardrail)
   └── Tab 3: Comparative Benchmark & Multi-Rail Visual Analytics (+34% Lift)
          ↓
[POST /webhook/razorpay (FastAPI)]  <-- Ingests `payment.failed` webhooks
          ↓
[Context Assembler & AI Agent]      <-- Granite 4.1 8B on RTX GPU
          ↓
[Deterministic Policy Engine]       <-- Financial Safety Guardrails
          ↓
[Razorpay API Client]               <-- Generates 1-click Payment Links (`/v1/payment_links`)
          ↓
[Live Metrics & Audit API]          <-- /api/metrics, /api/escalations, /api/benchmark-summary
```

---

## 🚀 Quickstart (v0.5.0)

### 1. Requirements
* Python 3.10+
* Dependencies: `fastapi`, `uvicorn`, `pydantic`, `httpx`, `rich`
* Local GPU / Ollama model (`granite4.1:8b` or heuristic fallback)

### 2. Launch the Complete Neo-Brutalist Dashboard
```bash
python -m uvicorn webhook_server:app --port 8000
```
Open your browser and navigate to: **`http://localhost:8000`**

### 3. Run Automated Comparative Benchmark
```bash
python benchmark.py
```

---

## 🛡️ Financial Guardrails Enforced in v0.1.0
1. **Hard Decline Zero-Retry Rule:** Expired, lost, or stolen cards immediately halt automated retries (`0 retries permitted`).
2. **Customer Opt-Out Rule:** If a customer has opted out, all recovery actions are instantly terminated.
3. **High-Value Escalation Gate:** Transactions $\ge \text{₹50,000}$ or enterprise accounts are automatically escalated to human sales/merchant ops.
4. **Max Retry Limits:** Category-specific retry caps prevent merchant fee burning and bank spam.
