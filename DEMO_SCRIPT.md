# Demo Video Script — Recoup v1.0.0 (Knowledge-Grounded Recovery)

Target **4–6 min**. Arc: **the gap → the design call → the pipeline → after → the number →
the problems I hit → close.** Every command is copy-paste runnable and needs **no GPU and no
network** (`RECOUP_DISABLE_LLM=1` + `--offline`). If the GPU is free, drop `RECOUP_DISABLE_LLM`
for the live model — more convincing, slightly slower.

---

## 0. Setup (before you hit record)

```bash
pip install -r requirements.txt
RECOUP_DISABLE_LLM=1 python benchmark.py        # writes data/benchmark_summary.json
python -m uvicorn webhook_server:app --port 8000
```

Two terminals; browser tab on `http://localhost:8000`.

---

## 1. THE GAP — the agent meets a failure it doesn't understand  (~45s)

> "Recoup is an AI agent that recovers failed payments on Indian rails. Until this milestone it
> understood 12 error codes. Real UPI and card failures in India have many more shapes. Here's
> one it couldn't handle — a subscription debit that failed because the bank never sent the
> RBI-mandated 24-hour notice before charging."

```bash
python demo_before.py
```

Expected: `recommended: alternative_payment_link`, `knowledge: NONE - operating on a guess`,
`needs a human: True`.

> "No knowledge base — it defaults to a generic payment link and flags for a human. It has no
> idea this is a compliance rule with one specific correct fix."

---

## 2. THE DESIGN CALL — why not just read the internet  (~60s)

*(Show the two-tier ASCII diagram in [README.md](README.md).)*

> "The obvious idea was: when the agent doesn't know something, have it read Reddit and forums
> live, cross-check a few answers, filter out the sarcasm, and reason it out. I didn't build
> that, for three reasons.
>
> One — an 8B model doesn't reliably know when it's unsure; it answers confidently either way,
> so 'I'm stuck, go look it up' isn't a trigger you can trust.
> Two — pulling live, untrusted web text into a payments decision reopens exactly the
> prompt-injection surface this system is built to close, and it stops being reproducible.
> Three — forum consensus rewards relatable answers, not correct ones.
>
> So instead: an **offline** pipeline. A stronger model — Gemma, on Hyper — reads official
> NPCI, RBI and Razorpay docs on a schedule and drafts structured recovery entries. A human
> reviews every change before it reaches the live agent. The strong model never touches a real
> payment."

---

## 3. THE PIPELINE — run it  (~45s)

```bash
python ingest.py --offline --merge
```

> "Three official sources in. It cross-verifies anything that appears in more than one source,
> then shows a diff against the current playbook — added, changed, unchanged. Nothing merges
> without `--merge --yes`. And if it finds a failure mode no code covers, it *proposes* a new
> one for a human to add to the taxonomy and the guardrails — it never writes a rule itself."

*(Live curator: put `HYPER_API_KEY` and `RECOUP_CURATOR_MODEL` in `.env`, run
`python ingest.py --merge` — narrate "this is the real Gemma model on Hyper proposing changes.")*

---

## 4. AFTER — same failure, knowledge-grounded  (~45s)

```bash
python demo_after.py
```

Expected: `recommended: smart_dunning_schedule`, `grounded on: pre_debit_notification_missing`,
and the forced silent retry returns `permitted: False` / `rule: RULE_PRE_DEBIT_NOTIFICATION_REQUIRED`.

> "Now it schedules the debit *after* the 24-hour notice — the compliant path — and cites the
> RBI entry it used. And if the model had tried to silently retry anyway, the deterministic
> guardrail underneath blocks it. The AI proposes; policy has the last word."

*(Browser: `http://localhost:8000/api/playbook?code=pre_debit_notification_missing` — point at `sources`.)*

---

## 5. THE NUMBER — three-arm benchmark  (~40s)

```bash
RECOUP_DISABLE_LLM=1 python benchmark.py
```

Point at the table:
- **Recovery rate: 34.5% (rule baseline) → 54.5% (AI, no KB) → 58.5% (AI + Playbook).**
- **Policy violations: 38 → 7 → 7.**
- Rail breakdown vs baseline: **UPI AutoPay +36 pts · UPI +35 · Netbanking +19 · Mandates (eNACH) +18 · Cards +11.**

> "Same 200 held-out failures, three arms. The knowledge base alone adds 4 points and 8
> recoveries over the un-grounded agent — fully deterministic, no GPU, no network, same number
> every run. With the live model the gap is bigger, because an un-grounded model actively picks
> unsafe retries on codes it's never seen — and those get caught right here. Recovery *rate* is
> the honest headline; the rupee figure swings on a few big enterprise transactions."

---

## 6. THE PROBLEMS I HIT  (~50s)

*(Talk over the terminal or [ENGINEERING_JOURNAL.md](ENGINEERING_JOURNAL.md) on screen.)*

> "A few things went wrong on the way here.
>
> **My own benchmark wasn't reproducible.** The outcome simulator seeded its randomness from
> Python's `hash()`, which is salted per process — so 'the number' changed every time I ran it.
> Switched to a stable CRC; the three arms are now byte-identical across runs.
>
> **The knowledge base first made things *worse*.** The grounded arm scored *below* the
> un-grounded one. Two bugs: one playbook entry recommended the wrong action for a timeout
> case, and the benchmark's simulator had no branch for the 'switch payment method' action —
> so it silently scored every method-switch as a failure, which is the action the playbook
> picks most. Fixed both; the lift showed up.
>
> **Deciding what the pipeline is allowed to touch.** The curator can draft a playbook entry,
> but a regulatory change needs a human to edit the deterministic guardrails in `policy.py`. I
> drew a hard line there: the pipeline flags a proposed new code, it never rewrites a rule.
>
> All of this, including the calls I reversed, is written up in the engineering journal in the repo."

---

## 7. CLOSE  (~20s)

> "That's Recoup v1.0.0 — knowledge-grounded, deterministic, and honest about where the numbers
> come from. Next up: the trade-press and community source tiers for *discovering* failure
> modes, an event-driven watcher on RBI and NPCI circular feeds, and the automated test suite."

---

## If a step fails on camera

Every command runs with `RECOUP_DISABLE_LLM=1` and `--offline` — no GPU, no network, no API key
anywhere in this script.
