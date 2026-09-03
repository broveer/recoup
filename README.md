# Recoup — AI Revenue Recovery Engine

> **Razorpay AI Buildathon 2026**
> **Track 03 — AI Revenue Recovery**

Recoup is an AI-powered revenue recovery system for Indian payment rails (UPI, Cards, eNACH / UPI AutoPay mandates, Netbanking). It diagnoses payment failures, assesses recoverability, personalises customer recovery nudges, and validates **every** decision against strict deterministic financial guardrails.

As of **`v0.7.0`**, every AI decision is **knowledge-grounded**: the agent retrieves a human-reviewed playbook entry — curated from official NPCI / RBI / Razorpay documentation — for the specific failure code before it decides. When there is no entry, it stays conservative and flags for human review instead of guessing.

---

## 📅 Versioning Strategy
Iterative daily release cycle culminating in the final submission:
* **Day 1:** `v0.1.0` — Minimal AI Recovery Agent, Structured Decision Schema & Policy Guardrails
* **Day 2:** `v0.2.0` — Synthetic Dataset Generator, Competent Non-AI Baseline, Comparative Evaluation Benchmark
* **Day 3:** `v0.3.0` — Razorpay Test-Mode Connector, Live Webhook Receiver (`payment.failed`), 1-Click Payment Link Generator
* **Day 4:** `v0.4.0` / `v0.4.1` — Interactive Neo-Brutalist Web Simulator & Dedicated Action Cards
* **Day 5:** `v0.5.0` — VIP Human Escalation Desk, Live Comparative Benchmark Visualizer, Multi-Rail Lift Breakdown
* **Day 6:** `v0.6.0` — WhatsApp Interactive Quick-Reply Chips (WABA Standards), Zero-Jailbreak Multi-Turn Agentic Actions
* **Day 7 (Current):** `v0.7.0` — **Knowledge-Grounded Recovery**: 11-category / 26-code failure taxonomy, curated recovery playbook (RAG), offline Gemma curator pipeline, 3 new RBI/NPCI compliance guardrails, three-arm A/B/C benchmark
* **Day 8–11:** `v0.8.0` → `v0.11.0` — Automated Pytest Suite, Demo Video Recording Package
* **Day 12:** `v1.0.0` — Complete Final Submission

See **[ENGINEERING_JOURNAL.md](ENGINEERING_JOURNAL.md)** for the reasoning behind every non-obvious design decision.

---

## 🏛️ v0.7.0 Architecture

### Two model tiers — the strong model never touches live money

```text
OFFLINE  (scheduled, human-gated)                 RUNTIME  (on the webhook path)
─────────────────────────────────                ──────────────────────────────────
data/sources/*.md                                 POST /webhook/razorpay  (payment.failed)
  NPCI · RBI · Razorpay extracts                          ↓
        ↓                                          Context Assembler + taxonomy mapper
  ingest.py  →  Gemma 26B-A4B curator                     ↓
  (structured extraction, safe-action              playbook.lookup(error_code)  ← data/recovery_playbook.json
   constraints, cross-verification)                       ↓
        ↓                                          AI Agent  ·  Granite 4.1 8B (local GPU)
  data/playbook_proposed.json                       retrieval-augmented; conservative if no entry
        ↓   (diff: added / changed / unchanged)           ↓
  human review  →  ingest.py --merge --yes          Deterministic Policy Engine  ·  8 guardrail rules
        ↓                                                 ↓
  data/recovery_playbook.json  ──────────────────►  Razorpay API Client  →  1-click Payment Links
                                                          ↓
                                                   Metrics & Audit API
                                                   /api/metrics · /api/playbook · /api/benchmark-summary
                                                   /api/escalations · /api/whatsapp/interactive-action
```

### Failure taxonomy (`v0.7.0`)

**11 categories / 26 error codes**, grounded in NPCI / RBI / Razorpay docs. New in `v0.7.0`:

| Category | Covers |
| --- | --- |
| `mandate_lifecycle` | eNACH / UPI AutoPay: not active, paused, over-limit, **missing RBI 24h pre-debit notification** |
| `limit_exceeded` | UPI per-transaction cap, daily cap, new-user 24h ₹5,000 cooling limit |
| `compliance_tokenization` | RBI Card-on-File token failed / expired / invalid |
| `psp_unavailable` | Payer UPI app (GPay / PhonePe / Paytm) down while bank rails are healthy |

---

## 🚀 Quickstart

### 1. Requirements
* Python 3.10+
* `pip install -r requirements.txt`  (`fastapi`, `uvicorn`, `pydantic`, `httpx`, `rich`)
* Optional: local Ollama model `granite4.1:8b` on GPU — a deterministic heuristic fallback runs without it.

### 2. Launch the dashboard
```bash
python -m uvicorn webhook_server:app --port 8000
```
Open **`http://localhost:8000`**.

### 3. Run the three-arm benchmark (Rule Baseline vs AI no-KB vs AI + Playbook)
```bash
RECOUP_DISABLE_LLM=1 python benchmark.py      # deterministic, reproducible
python benchmark.py                            # with the live LLM in the loop
```
Writes `data/benchmark_summary.json` (served at `/api/benchmark-summary`).

### 4. Run the knowledge pipeline
```bash
python ingest.py --offline --merge             # no network: stub curator + review diff
```
For the live curator (Gemma on **Hyper by Charm**, an OpenAI-compatible endpoint), set
`HYPER_API_KEY` and `RECOUP_CURATOR_MODEL` (kept in a git-ignored `.env`), then:
```bash
pip install openai
python ingest.py --merge          # review the proposed diff
python ingest.py --merge --yes    # apply added/changed entries after review
```

### 5. Inspect the knowledge base
```bash
python playbook.py                             # coverage report
curl http://localhost:8000/api/playbook        # full KB + provenance
```

---

## 🛡️ Deterministic Financial Guardrails

The AI **proposes**; the policy engine **authorises or overrides**. Eight rules:

1. **Customer Opt-Out** — opted-out customer → all recovery halts immediately.
2. **Hard-Decline Zero-Retry** — expired / lost / stolen / closed → `0` retries.
3. **High-Value Escalation Gate** — ≥ ₹50,000 or enterprise → human outreach.
4. **Max Retry Limits** — per-category caps stop fee burning and bank spam.
5. **Risk / Fraud Hold** — suspected fraud → human risk team, never automated.
6. **Mandate Re-Auth Required** *(new)* — dead / paused / over-limit mandate cannot be silently retried.
7. **RBI Pre-Debit Notification Required** *(new)* — no immediate retry without the mandatory 24h notice.
8. **RBI Re-Tokenisation Required** *(new)* — an invalid card-on-file token is never retried; customer re-consents.

---

## 📊 Results (`v0.7.0`, 200-case held-out cohort, `RECOUP_DISABLE_LLM=1` — fully reproducible)

| Arm | Recovery rate | Policy violations |
| --- | --- | --- |
| Rule Baseline (static dunning) | 34.5% | 38 |
| AI, no knowledge base | 54.5% | 7 |
| **AI + Playbook** | **58.5%** | **7** |

Knowledge-base lift is **+4.0 points / +8 transactions** in deterministic mode (its floor) and
larger with the live LLM (an un-grounded model picks unsafe retries on codes it doesn't know).
Per-rail lift vs baseline: **UPI AutoPay +36 pts · UPI +35 · Netbanking +19 · Mandates (eNACH) +18 · Cards +11**.
Recovery *rate* is the headline metric; see [ENGINEERING_JOURNAL.md](ENGINEERING_JOURNAL.md) Problem 6 for why.
