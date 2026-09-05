# Engineering Journal — Recoup

> How the hard calls were made. Each entry: the problem we hit, the options we weighed,
> what we chose, and the trade-off we knowingly accepted.

The `v0.7.0` work below is the "Knowledge-Grounded Recovery" milestone and the substance of
the `v1.0.0` submission tag. Earlier milestones (`v0.1.0`–`v0.6.0`) are summarised in
[README.md](README.md).

---

## v0.7.0 — Knowledge-Grounded Recovery

### Problem 1 — The agent only understood a fraction of real Indian payment failures

**Symptom.** The taxonomy shipped 7 failure categories and 12 error codes. Real Indian
checkout failures include whole classes it had no representation for: UPI per-transaction
and daily limits, the new-UPI-user 24h cooling cap, UPI PIN lockouts, eNACH / UPI AutoPay
mandate lifecycle (paused, revoked, over-limit), the RBI 24-hour pre-debit notification
rule, RBI card-on-file tokenisation failures, and card on/off controls. The webhook's
`map_razorpay_error_to_taxonomy()` was a five-branch keyword match that funnelled all of
these into `authentication_drop / payment_cancelled_by_user`.

**Options.**
1. Fine-tune the runtime model on a corpus of failure examples.
2. Keep the model as-is, expand the taxonomy, and give the agent a **retrieval knowledge
   base** (RAG) of curated failure → recovery entries.

**Decision.** Option 2. Expanded to 11 categories / 26 codes and built
[`data/recovery_playbook.json`](data/recovery_playbook.json) — one reviewed entry per code
(root cause, retryable flag, recommended action, customer explanation, provenance).

**Why.** Fine-tuning is a multi-day commitment (data prep, an eval harness, and regression
risk against the deterministic guardrails) for a submission that is two days out. RAG gets
most of the benefit at a fraction of the risk, and a knowledge base is **inspectable and
citable** in a way model weights are not — which matters for a financial system.

**Trade-off accepted.** The agent is only as current as the last playbook merge. Addressed
by Problem 4.

---

### Problem 2 — "Should the agent read Reddit live when it doesn't know something?"

The original instinct was: when the agent is unsure, fetch community answers (Reddit and
other forums) at decision time, cross-check several of them, and reason over the result —
with a filter for sarcasm and jokes so they don't poison the answer.

**Why we did not do this.**

- **Uncertainty is not a reliable trigger.** An 8B model rarely "feels" stuck — it produces
  a confident, plausible answer for almost any input. A trigger on self-reported confidence
  is a trigger on a noisy number.
- **Untrusted content on the decision path re-opens the injection surface.** The product's
  claim is deterministic, zero-jailbreak guardrails. Pulling arbitrary forum text into the
  prompt at decision time undoes that. Cross-checking three comments does not help if two
  are wrong and the model still weighs them.
- **A payments decision must be reproducible.** Live retrieval means the same failed payment
  yields different actions on different days depending on what is on a forum that morning.
- **Forum consensus ≠ correct.** Upvotes reward relatable answers ("just call your bank"),
  not the action that maps to a structured recovery step.

**Decision.** Move every part of that idea **off the decision path and into an offline
pipeline** (Problem 4). The cross-verification and source-quality logic is good engineering —
it just belongs at build time, behind a human review gate.

**What the runtime does instead when it hits an unknown code:** it does not improvise. The
system prompt instructs the agent, when no playbook entry is supplied, to stay conservative,
set `requires_human_approval = true`, and cap confidence at 0.5.

---

### Problem 3 — Two model tiers, and keeping the strong one away from live money

We wanted a stronger model (Gemma-class, ~26B MoE) for the reasoning-heavy curation work,
without it ever touching a real payment decision.

**Decision.** A two-tier split:

| Tier | Model | Runs | Sees |
| --- | --- | --- | --- |
| Curator | Gemma 26B-A4B (metered API) | offline, on a schedule | raw source extracts |
| Runtime | Granite 4.1 8B (local GPU) | on the webhook path | only the *merged, reviewed* playbook |

**Why.** The curator's output passes through a human review gate before it can influence the
runtime agent, so the "deterministic / auditable" property survives even though the curator
is a large model consuming messy input. Metered credits suit a bounded monthly batch job.

**Trade-off accepted.** Freshness is bounded by the batch cadence, not real-time. Acceptable —
regulations and failure-mode phrasing move on weeks-to-months timescales, not minutes.

---

### Problem 4 — Making the knowledge base stay current without a human re-writing it

**Decision.** [`ingest.py`](ingest.py) — an offline curator pipeline:

```
data/sources/*.md   →   Gemma curator   →   cross-verify   →   data/playbook_proposed.json
      (operator extracts of        (structured extraction,     (diff vs current playbook:
       NPCI / RBI / Razorpay)       safe-action constraints)     added / changed / unchanged)
                                                                        │
                                                          human review  ▼
                                                   ┌─────────────────────────────────┐
                                                   │  python ingest.py --merge --yes │
                                                   └─────────────────────────────────┘
                                                                        │
                                                        data/recovery_playbook.json  →  agent
```

**Design choices that fell out of Problem 2:**

- **Source trust tiers.** `authoritative` (RBI / NPCI / Razorpay) needs one source;
  `reported` (trade press) needs corroboration; `anecdotal` (forums) is never a sole source
  for a resolution — only a signal for *which* failure modes and phrasings to chase down in
  the authoritative docs. `v0.7.0` ships the authoritative tier only.
- **Regulation is flagged, never auto-applied.** If the curator infers a new failure mode it
  emits a `proposed_new_codes` item describing what no existing code covers — a human then
  edits `models.py` and `policy.py`. The pipeline never rewrites a deterministic rule from a
  model's summary of a circular.
- **Cross-verification at merge time.** When a code appears in more than one source, entries
  are reconciled: action by majority, ties broken toward the *safer* (less-retrying) option;
  sources unioned; disagreement recorded in `action_agreement`.
- **Runs with no network.** `--offline` uses a deterministic stub curator so the pipeline
  (and its tests) run in CI and in a no-wifi demo.

**Trade-off accepted.** The shipped `recovery_playbook.json` was bootstrapped by hand for
`v0.7.0` and its figures (UPI limits, cooling windows) need re-verification against live
circulars — the pipeline is how that verification becomes routine, not a one-off.

---

### Problem 5 — Guardrails only covered the old taxonomy

New categories needed deterministic rules, or the policy engine would wave through unsafe
actions on them (silently retrying a revoked mandate burns bank hits; an immediate retry on
a missing pre-debit notification is an RBI breach).

**Decision.** Three rules added to [`policy.py`](policy.py), each blocking a retry-class
action and forcing a safe alternative:

- `RULE_MANDATE_REAUTH_REQUIRED` — dead / paused / over-limit mandate → `alternative_payment_link`.
- `RULE_PRE_DEBIT_NOTIFICATION_REQUIRED` — missing 24h notice → `smart_dunning_schedule` (notify, then debit).
- `RULE_RETOKENIZATION_REQUIRED` — invalid card-on-file token → `alternative_payment_link`.

Plus category retry caps (`MANDATE_LIFECYCLE`, `LIMIT_EXCEEDED`, `COMPLIANCE_TOKENIZATION` → 1;
`PSP_UNAVAILABLE` → 2). The agent proposes; policy still has the last word.

---

### Problem 6 — A benchmark that measures the knowledge base, not just "AI vs no-AI"

The `v0.6.0` benchmark compared a rule baseline to the AI agent. To show the *knowledge
base's* contribution we needed to hold the model fixed and vary only grounding.

**Decision.** Three arms in [`benchmark.py`](benchmark.py): **Rule Baseline**, **AI (no KB)**
(`RecoveryAgent(use_playbook=False)` — pre-`v0.7` behaviour), **AI + Playbook**. Same engine,
same 200-case held-out cohort; the only difference between arms 2 and 3 is retrieval.

**Honesty notes baked into the writeup:**

- **Recovery *rate* is the headline, not ₹.** A handful of large enterprise transactions
  dominate the rupee figure and make it swing on reseeding; the count-based rate is stable.
- **`RECOUP_DISABLE_LLM=1` is the reproducible floor.** In deterministic heuristic mode the
  KB adds **+4.0 points / +8 transactions** (54.5% → 58.5%). That is a floor: the ungrounded
  *heuristic* fallback is deliberately competent, so the gap it shows is small. With the live
  LLM in the loop the gap is larger, because an ungrounded model picks retry-class actions on
  unfamiliar codes that both convert worse *and* trip the new guardrails.
- **The rail breakdown is where the taxonomy work shows:** UPI AutoPay +36 pts, UPI +35,
  Netbanking +19, Mandates (eNACH) +18, Cards +11 vs the rule baseline (34.5% → 58.5% overall).
- **Reproducibility bug fixed here.** The outcome simulator seeded its RNG with `hash(tx_id)`,
  which Python salts per-process — so "the benchmark" produced different numbers every run.
  Switched to `zlib.crc32`; the three arms are now byte-identical across runs and platforms.

**Bug found while building this.** The outcome simulator had no branch for
`method_switch_nudge` — it fell through to "guaranteed failure". Since the playbook picks
that action for every limit / card-control case, the KB arm was being silently punished.
Fixed, plus code-level outcome overrides for two UPI codes whose recovery mechanics differ
from their category default (a locked UPI PIN, a lapsed collect request).

---

### Problem 7 — Small correctness issues found in passing

- `AgentDecision` was being constructed with a `decision_model=` kwarg that the model didn't
  declare — Pydantic silently dropped it. Added the field (plus `knowledge_grounded` and
  `playbook_entry_used`, which the UI and audit log now surface).
- `/api/benchmark-summary` returned a hard-coded dict. It now serves
  `data/benchmark_summary.json`, the actual output of the last `benchmark.py` run, with the
  old dict kept only as a fallback.
- No `requirements.txt` existed. Added one.
