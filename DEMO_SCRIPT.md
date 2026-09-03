# Demo Video Script — Recoup v0.7.0 (Knowledge-Grounded Recovery)

Target length **4–5 min**. Structure: **before → the problem → the approach → after → the number → roadmap.**
Every command below is copy-paste runnable. Record with `RECOUP_DISABLE_LLM=1` unset if the GPU
is free (more convincing), or set for a guaranteed-clean take.

---

## 0. Setup (before recording)

```bash
pip install -r requirements.txt
RECOUP_DISABLE_LLM=1 python benchmark.py        # generates data/benchmark_summary.json
python -m uvicorn webhook_server:app --port 8000
```

Have two terminals + the browser at `http://localhost:8000` ready.

---

## 1. BEFORE — the agent meets a failure it doesn't understand  (~45s)

> "Recoup recovers failed payments. Until v0.7 it knew 12 error codes. Real Indian checkout
> has many more. Here's a UPI AutoPay mandate that failed because the RBI-mandated 24-hour
> pre-debit notification was never sent."

```bash
python - <<'PY'
import os; os.environ["RECOUP_DISABLE_LLM"] = "1"
from models import *
from agent import RecoveryAgent
from policy import PolicyGuardrailEngine

ctx = FailedPaymentContext(
    transaction_id="pay_DEMO_1", order_id="o1", customer_id="c1", customer_name="Ananya Iyer",
    amount_inr=649.0, payment_method=PaymentMethod.UPI_AUTOPAY,
    failure_category=FailureCategory.MANDATE_LIFECYCLE,
    error_code=FailureCode.PRE_DEBIT_NOTIFICATION_MISSING,
    error_message="Recurring debit attempted without the mandatory 24h pre-debit notification.")

d = RecoveryAgent(use_playbook=False).decide(ctx)          # <-- no knowledge base
print("action        :", d.recommended_action.value)
print("grounded      :", d.knowledge_grounded)
print("human approval :", d.requires_human_approval)
print("reasoning     :", d.reasoning_summary)
PY
```

> "No knowledge base: it falls back to a generic payment link and flags for human review.
> It has no idea this is a compliance rule with a specific fix."

---

## 2. THE PROBLEM & APPROACH — architecture  (~60s)

Show the diagram in [README.md](README.md) (the two-tier ASCII block). Narrate:

- **Why not scrape forums live at decision time?** Injection risk on a zero-jailbreak system,
  non-reproducible decisions, and forum sarcasm poisoning the model. (→ ENGINEERING_JOURNAL Problem 2)
- **Instead:** an *offline* curator (Gemma 26B-A4B) distils official NPCI / RBI / Razorpay docs
  into a reviewed playbook. The strong model never touches a live payment.
- **The runtime agent (Granite 8B)** retrieves the playbook entry for the exact failure code
  and decides against it. Unknown code → stay conservative, flag for a human.

---

## 3. THE PIPELINE — run it live  (~45s)

```bash
python ingest.py --offline --merge
```

> "Three official sources in, structured entries out, cross-verified where sources overlap,
> then a diff against the current playbook — added / changed / unchanged. Nothing merges
> without a human running `--merge --yes`. New failure modes it can't map become
> `proposed_new_codes` — a human edits the taxonomy and the guardrails, never the pipeline."

*(If the live Gemma key is configured: run `python ingest.py --merge` instead — show real
proposed changes.)*

---

## 4. AFTER — same failure, knowledge-grounded  (~45s)

```bash
python - <<'PY'
import os; os.environ["RECOUP_DISABLE_LLM"] = "1"
from models import *
from agent import RecoveryAgent
from policy import PolicyGuardrailEngine

ctx = FailedPaymentContext(
    transaction_id="pay_DEMO_1", order_id="o1", customer_id="c1", customer_name="Ananya Iyer",
    amount_inr=649.0, payment_method=PaymentMethod.UPI_AUTOPAY,
    failure_category=FailureCategory.MANDATE_LIFECYCLE,
    error_code=FailureCode.PRE_DEBIT_NOTIFICATION_MISSING,
    error_message="Recurring debit attempted without the mandatory 24h pre-debit notification.")

d = RecoveryAgent(use_playbook=True).decide(ctx)           # <-- with the playbook
print("action        :", d.recommended_action.value)
print("grounded on   :", d.playbook_entry_used)
print("reasoning     :", d.reasoning_summary)

# and the guardrail has teeth: force an unsafe retry, watch policy override it
bad = d.model_copy(update={"recommended_action": RecoveryActionType.DYNAMIC_BACKOFF_RETRY})
v = PolicyGuardrailEngine.validate(ctx, bad)
print("forced retry  : permitted =", v.is_permitted, "| rule =", v.applied_rule)
PY
```

> "Now it schedules the debit *after* sending the 24-hour notice — the compliant path — and
> cites the RBI entry it used. And if the model had tried a silent retry anyway, the
> deterministic guardrail `RULE_PRE_DEBIT_NOTIFICATION_REQUIRED` blocks it."

Then in the browser: `http://localhost:8000/api/playbook?code=pre_debit_notification_missing`
— show the entry with its `sources`.

---

## 5. THE NUMBER — three-arm benchmark  (~40s)

```bash
RECOUP_DISABLE_LLM=1 python benchmark.py
```

Point at:
- **Recovery rate: 39.5% (baseline) → 61.5% (AI) → 64.0% (AI + Playbook).**
- **Policy violations: 38 → 7 → 7.**
- Rail breakdown: **Mandates (eNACH) +41 pts, UPI AutoPay +32, UPI +29** vs baseline.

> "The knowledge base adds +2.5 points on top of the un-grounded agent in fully deterministic
> mode — that's the floor; with the live LLM the gap is bigger because an un-grounded model
> picks unsafe retries on codes it doesn't know. Recovery *rate* is the honest headline —
> the rupee figure swings on a few big enterprise transactions."

---

## 6. ROADMAP — 20s

> "Next: the `reported` and `anecdotal` source tiers (trade press, then forums — for
> *discovering* failure modes, still verified against official docs before merge), an
> event-driven watcher on RBI / NPCI circular feeds, and the automated pytest suite."

---

## One-liner if a step fails on camera

Everything runs without a GPU and without network: `RECOUP_DISABLE_LLM=1` for decisioning,
`python ingest.py --offline` for the pipeline.
