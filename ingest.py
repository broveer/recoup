"""
Recoup v0.7.0 - Knowledge Pipeline (offline curator)
=====================================================
Reads operator-collected extracts of official sources (data/sources/*.md), asks a stronger
"curator" LLM (Gemma-class, via an OpenAI-compatible API) to distil them into structured
recovery-playbook entries, cross-verifies entries that appear in more than one source, and
writes a *proposed* playbook for human review (data/playbook_proposed.json).

Nothing here runs on the live decision path. The curator's output never reaches the runtime
agent until a human merges it:  ingest.py  ->  review  ->  recovery_playbook.json  ->  agent

Usage
-----
  python ingest.py                       # call the live curator, write playbook_proposed.json
  python ingest.py --offline             # no network; deterministic stub curator (CI / demo)
  python ingest.py --merge               # show the review diff vs the current playbook
  python ingest.py --merge --yes         # apply added/changed entries to recovery_playbook.json

Environment (live mode — Hyper by Charm, an OpenAI-compatible endpoint)
  HYPER_API_KEY             secret (never committed; .env is git-ignored)
  RECOUP_CURATOR_MODEL      the Gemma model id on Hyper (e.g. gemma-...); required for live runs
  RECOUP_CURATOR_BASE_URL   optional override (default https://hyper.charm.sh/v1)
"""

import argparse
import json
import os
import re
import sys
import glob
from datetime import date
from typing import Any, Dict, List

import playbook
from models import FailureCategory, FailureCode, RecoveryActionType

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

HERE = os.path.dirname(__file__)


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency). .env is git-ignored; values already in the
    environment win. Lets `python ingest.py --merge` pick up HYPER_API_KEY from a file."""
    path = os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return
    for line in open(path, "r", encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv()

SOURCES_DIR = os.path.join(HERE, "data", "sources")
PROPOSED_PATH = os.path.join(HERE, "data", "playbook_proposed.json")
PLAYBOOK_PATH = os.path.join(HERE, "data", "recovery_playbook.json")

VALID_ACTIONS = [a.value for a in RecoveryActionType]
VALID_CATEGORIES = [c.value for c in FailureCategory]
VALID_CODES = [c.value for c in FailureCode]

CURATOR_SYSTEM = f"""You are a payments-compliance analyst curating a machine-readable recovery
playbook for Indian payment rails. You are given a plain-language extract of ONE official source
(NPCI, RBI, or Razorpay). Produce ONLY facts that are stated or directly implied by the extract.
Never invent numbers, error codes, or regulations.

Return a single JSON object:
{{
  "entries": [
    {{
      "failure_code": one of {VALID_CODES},
      "failure_category": one of {VALID_CATEGORIES},
      "display_name": short label,
      "root_cause": 1-3 sentences grounded in the extract,
      "is_retryable": boolean,
      "retry_guidance": one sentence,
      "recommended_action": one of {VALID_ACTIONS},
      "customer_explanation": one calm sentence a merchant could send the customer,
      "agent_notes": optional operator hint,
      "confidence": "high" | "medium" | "low"
    }}
  ],
  "proposed_new_codes": [
    {{ "suggested_code": snake_case, "why": "what the extract describes that no existing code covers" }}
  ]
}}

Rules:
- Use an existing failure_code where one fits. Only use proposed_new_codes for a genuinely
  uncovered failure mode - do NOT also emit an entry for it.
- recommended_action must be safe: never 'dynamic_backoff_retry' or 'smart_dunning_schedule' for a
  dead/paused mandate, an invalid card token, or a breached limit (those cannot succeed on retry).
- 'escalate_to_human' is for suspected fraud/risk or >= Rs 50,000 only.
- Output JSON only. No prose, no markdown fences."""


# --------------------------------------------------------------------------- IO
def load_sources() -> List[Dict[str, Any]]:
    out = []
    for path in sorted(glob.glob(os.path.join(SOURCES_DIR, "*.md"))):
        text = open(path, "r", encoding="utf-8").read()
        meta = {"name": os.path.basename(path), "authority": "?", "tier": "authoritative",
                "urls": [], "retrieved": str(date.today()), "text": text}
        for key in ("authority", "tier", "retrieved"):
            m = re.search(rf"^-\s*{key}:\s*(.+)$", text, re.MULTILINE)
            if m:
                meta[key] = m.group(1).strip()
        meta["urls"] = re.findall(r"https?://\S+", text)
        out.append(meta)
    return out


# ---------------------------------------------------------------- curator calls
HYPER_BASE_URL = "https://hyper.charm.sh/v1"  # Hyper by Charm — OpenAI-compatible


def _curator_client():
    """OpenAI client pointed at Hyper. Imported lazily so --offline needs no dependency."""
    try:
        from openai import OpenAI
    except ImportError:
        raise SystemExit("Live curator needs the 'openai' package: pip install openai  (or run --offline)")
    key = os.getenv("HYPER_API_KEY") or os.getenv("RECOUP_CURATOR_API_KEY")
    if not key:
        raise SystemExit("Set HYPER_API_KEY (Hyper by Charm), or run with --offline.")
    base = os.getenv("RECOUP_CURATOR_BASE_URL", HYPER_BASE_URL)
    return OpenAI(base_url=base, api_key=key, timeout=120.0)


def call_curator_live(source_text: str) -> Dict[str, Any]:
    model = os.getenv("RECOUP_CURATOR_MODEL")
    if not model:
        raise SystemExit(
            "Set RECOUP_CURATOR_MODEL to the Gemma model id on Hyper "
            "(see https://hyper.charm.sh), or run with --offline."
        )
    client = _curator_client()
    kwargs = dict(
        model=model,
        temperature=0.2,
        messages=[
            {"role": "system", "content": CURATOR_SYSTEM},
            {"role": "user", "content": source_text},
        ],
    )
    try:
        resp = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
    except Exception:
        resp = client.chat.completions.create(**kwargs)  # endpoint may not accept response_format
    content = resp.choices[0].message.content
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)
    return json.loads(content)


def call_curator_offline(source: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic stand-in: re-derives entries for this source's authority from the current
    playbook, stamps today's retrieval date, and raises one plausible new-code proposal.
    Lets the diff/merge path run with no network (CI, offline demo)."""
    authority = source["authority"]
    entries = []
    for code, e in playbook.all_entries().items():
        if any(s.get("authority") == authority for s in e.get("sources", [])):
            c = json.loads(json.dumps(e))
            c.pop("sources", None)
            c["confidence"] = c.get("confidence", "high")
            entries.append(c)
    proposals = {
        "NPCI": [{"suggested_code": "upi_beneficiary_bank_offline",
                  "why": "extract distinguishes payer-side vs beneficiary-side unavailability; "
                         "no code captures a healthy remitter with an offline beneficiary bank"}],
        "RBI": [{"suggested_code": "mandate_bank_not_live_on_enach",
                 "why": "sponsor/destination bank not live on the e-mandate rail is distinct from a revoked mandate"}],
        "Razorpay": [{"suggested_code": "issuer_auth_server_down",
                      "why": "issuer ACS/auth server unavailable is a transient sub-case worth separating from bank_downtime"}],
    }.get(authority, [])
    return {"entries": entries, "proposed_new_codes": proposals}


# ------------------------------------------------------------------ assembly
def extract_all(sources: List[Dict[str, Any]], offline: bool) -> Dict[str, Any]:
    by_code: Dict[str, List[Dict[str, Any]]] = {}
    proposed_new: List[Dict[str, Any]] = []
    per_source_counts = {}

    for src in sources:
        print(f"  curator <- {src['name']}  ({src['authority']}, {src['tier']})")
        result = call_curator_offline(src) if offline else call_curator_live(src["text"])
        raw_entries = result.get("entries", [])
        per_source_counts[src["name"]] = len(raw_entries)
        for e in raw_entries:
            code = e.get("failure_code")
            if code not in VALID_CODES:
                proposed_new.append({"suggested_code": code or "<missing>",
                                     "why": f"curator emitted an entry for an unknown code from {src['name']}"})
                continue
            if e.get("recommended_action") not in VALID_ACTIONS:
                print(f"    ! dropped {code}: invalid action {e.get('recommended_action')!r}")
                continue
            e = dict(e)
            e["_source"] = {"authority": src["authority"], "title": src["name"],
                            "tier": src["tier"], "url": (src["urls"][0] if src["urls"] else None),
                            "retrieved": src["retrieved"]}
            by_code.setdefault(code, []).append(e)
        for p in result.get("proposed_new_codes", []):
            p = dict(p)
            p["from_source"] = src["name"]
            proposed_new.append(p)

    entries: Dict[str, Any] = {}
    cross_verified = []
    for code, variants in by_code.items():
        merged = reconcile(code, variants)
        entries[code] = merged
        if len(variants) > 1:
            cross_verified.append(code)

    return {
        "schema_version": "0.7.0",
        "generated_at": str(date.today()),
        "curator": "offline-stub" if offline else os.getenv("RECOUP_CURATOR_MODEL"),
        "sources_ingested": [s["name"] for s in sources],
        "entries_per_source": per_source_counts,
        "cross_verified_codes": sorted(cross_verified),
        "entries": entries,
        "proposed_new_codes": proposed_new,
    }


def reconcile(code: str, variants: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Cross-verify: agree on action by majority (ties -> the safer / least-retrying option),
    keep the longest root_cause, union the sources, and flag any disagreement."""
    safety_rank = {  # lower = safer / less likely to burn a bank hit
        "immediate_stop": 0, "escalate_to_human": 1, "method_switch_nudge": 2,
        "alternative_payment_link": 3, "smart_dunning_schedule": 4, "dynamic_backoff_retry": 5,
    }
    actions = [v["recommended_action"] for v in variants]
    counts = {a: actions.count(a) for a in set(actions)}
    top = max(counts.values())
    winners = sorted([a for a, n in counts.items() if n == top], key=lambda a: safety_rank.get(a, 9))
    action = winners[0]

    base = max(variants, key=lambda v: len(v.get("root_cause", "")))
    sources = []
    for v in variants:
        s = v.get("_source")
        if s and s not in sources:
            sources.append(s)
    return {
        "failure_code": code,
        "failure_category": base.get("failure_category"),
        "display_name": base.get("display_name"),
        "root_cause": base.get("root_cause"),
        "is_retryable": bool(base.get("is_retryable", False)),
        "retry_guidance": base.get("retry_guidance", ""),
        "recommended_action": action,
        "customer_explanation": base.get("customer_explanation"),
        "agent_notes": base.get("agent_notes", ""),
        "confidence": "high" if len(sources) > 1 and len(set(actions)) == 1 else base.get("confidence", "medium"),
        "action_agreement": counts,
        "sources": sources,
    }


# ------------------------------------------------------------------ review
def diff_against_current(proposed: Dict[str, Any]) -> Dict[str, List[str]]:
    cur = playbook.all_entries()
    added, changed, unchanged = [], [], []
    for code, e in proposed["entries"].items():
        if code not in cur:
            added.append(code)
        elif (e["recommended_action"] != cur[code].get("recommended_action")
              or bool(e["is_retryable"]) != bool(cur[code].get("is_retryable"))):
            changed.append(code)
        else:
            unchanged.append(code)
    return {"added": sorted(added), "changed": sorted(changed), "unchanged": sorted(unchanged)}


def print_review(proposed: Dict[str, Any]) -> None:
    from rich.console import Console
    from rich.table import Table
    c = Console(force_terminal=True, width=118)
    d = diff_against_current(proposed)
    cur = playbook.all_entries()

    c.print(f"\n[bold]Proposed playbook[/bold]  curator=[cyan]{proposed['curator']}[/cyan]  "
            f"sources={proposed['sources_ingested']}")
    c.print(f"cross-verified across >1 source: [green]{proposed['cross_verified_codes'] or '-'}[/green]")

    t = Table(show_header=True, header_style="bold magenta", expand=True)
    t.add_column("failure_code", style="cyan")
    t.add_column("status")
    t.add_column("current action")
    t.add_column("proposed action")
    for code in d["changed"]:
        t.add_row(code, "[yellow]CHANGED[/yellow]", cur[code].get("recommended_action"),
                  proposed["entries"][code]["recommended_action"])
    for code in d["added"]:
        t.add_row(code, "[green]ADDED[/green]", "-", proposed["entries"][code]["recommended_action"])
    for code in d["unchanged"][:6]:
        t.add_row(code, "[dim]unchanged[/dim]", cur[code].get("recommended_action"),
                  proposed["entries"][code]["recommended_action"])
    if len(d["unchanged"]) > 6:
        t.add_row("...", f"[dim]+{len(d['unchanged']) - 6} more unchanged[/dim]", "", "")
    c.print(t)

    if proposed["proposed_new_codes"]:
        c.print("[bold]Proposed NEW failure codes[/bold] (need a human to add to models.py + policy.py):")
        for p in proposed["proposed_new_codes"]:
            c.print(f"  [green]+[/green] {p.get('suggested_code')}  [dim]{p.get('why','')}[/dim]")
    c.print(f"\nSummary: [green]{len(d['added'])} added[/green], [yellow]{len(d['changed'])} changed[/yellow], "
            f"[dim]{len(d['unchanged'])} unchanged[/dim].  "
            f"Merge with:  [bold]python ingest.py --merge --yes[/bold]\n")


def merge(proposed: Dict[str, Any]) -> None:
    with open(PLAYBOOK_PATH, "r", encoding="utf-8") as f:
        pb = json.load(f)
    d = diff_against_current(proposed)
    for code in d["added"] + d["changed"]:
        e = dict(proposed["entries"][code])
        e.pop("action_agreement", None)
        pb["entries"][code] = e
    pb["generated_at"] = str(date.today())
    pb.setdefault("provenance", "")
    pb["last_merge"] = {
        "at": str(date.today()), "curator": proposed["curator"],
        "sources": proposed["sources_ingested"],
        "added": d["added"], "changed": d["changed"],
    }
    with open(PLAYBOOK_PATH, "w", encoding="utf-8") as f:
        json.dump(pb, f, indent=2, ensure_ascii=False)
    playbook.reload()
    print(f"Merged into {os.path.basename(PLAYBOOK_PATH)}: "
          f"{len(d['added'])} added, {len(d['changed'])} changed. "
          f"{len(proposed['proposed_new_codes'])} new-code proposal(s) still need a human.")


# ------------------------------------------------------------------ main
def main() -> None:
    ap = argparse.ArgumentParser(description="Recoup knowledge pipeline (offline curator).")
    ap.add_argument("--offline", action="store_true", help="no network; deterministic stub curator")
    ap.add_argument("--merge", action="store_true", help="show the review diff vs the current playbook")
    ap.add_argument("--yes", action="store_true", help="with --merge, actually write recovery_playbook.json")
    args = ap.parse_args()

    sources = load_sources()
    if not sources:
        raise SystemExit(f"No sources in {SOURCES_DIR}")
    print(f"Ingesting {len(sources)} source(s) [{'offline' if args.offline else 'live curator'}]")

    proposed = extract_all(sources, offline=args.offline)
    with open(PROPOSED_PATH, "w", encoding="utf-8") as f:
        json.dump(proposed, f, indent=2, ensure_ascii=False)
    print(f"Wrote {os.path.relpath(PROPOSED_PATH, HERE)}  "
          f"({len(proposed['entries'])} entries, {len(proposed['proposed_new_codes'])} new-code proposals)")

    if args.merge:
        print_review(proposed)
        if args.yes:
            merge(proposed)
        else:
            print("Dry run. Re-run with --merge --yes to apply.")


if __name__ == "__main__":
    main()
