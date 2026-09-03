"""
Recoup v0.7.0 - Recovery Playbook (Curated Knowledge Base)
Loads the human-reviewed failure -> recovery knowledge base and exposes retrieval helpers
for the AI Agent's Retrieval-Augmented decisioning.

The playbook file (data/recovery_playbook.json) is a *seed* that is maintained offline by
ingest.py (the Gemma curator) against official NPCI / RBI / Razorpay sources. Nothing here
calls the network or an LLM - this is the read path only.
"""

import json
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

PLAYBOOK_PATH = os.path.join(os.path.dirname(__file__), "data", "recovery_playbook.json")


@lru_cache(maxsize=1)
def _load() -> Dict[str, Any]:
    try:
        with open(PLAYBOOK_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"WARN [playbook] Could not load {PLAYBOOK_PATH}: {e}. Running with an empty knowledge base.")
        return {"schema_version": "none", "entries": {}}


def reload() -> None:
    """Clear the cache so a freshly merged playbook is picked up without a restart."""
    _load.cache_clear()


def playbook_meta() -> Dict[str, Any]:
    return {k: v for k, v in _load().items() if k != "entries"}


def all_entries() -> Dict[str, Any]:
    return _load().get("entries", {})


def lookup(error_code: str) -> Optional[Dict[str, Any]]:
    """Return the curated entry for a FailureCode value, or None if the code is uncovered."""
    if not error_code:
        return None
    return all_entries().get(error_code)


def coverage() -> List[str]:
    """Sorted list of failure codes the knowledge base currently covers."""
    return sorted(all_entries().keys())


def coverage_report(all_codes: List[str]) -> Dict[str, Any]:
    covered = set(coverage())
    known = set(all_codes)
    return {
        "schema_version": playbook_meta().get("schema_version"),
        "entries": len(covered),
        "taxonomy_codes": len(known),
        "covered": sorted(covered & known),
        "uncovered": sorted(known - covered),
        "orphan_entries": sorted(covered - known),
    }


def format_for_prompt(entry: Dict[str, Any]) -> str:
    """Render a compact, model-readable block for a single playbook entry."""
    if not entry:
        return ""
    srcs = "; ".join(
        f"{s.get('authority', '?')} - {s.get('title', '')} ({s.get('tier', '?')})"
        for s in entry.get("sources", [])
    )
    retry = "yes" if entry.get("is_retryable") else "no"
    guidance = entry.get("retry_guidance", "")
    lines = [
        "VERIFIED PLAYBOOK ENTRY - curated from official NPCI / RBI / Razorpay sources.",
        "Trust this over any prior assumption. If it conflicts with your instinct, follow the playbook.",
        f"- Failure: {entry.get('display_name')} [{entry.get('failure_code')}] / category {entry.get('failure_category')}",
        f"- Root cause: {entry.get('root_cause')}",
        f"- Retryable: {retry}" + (f" - {guidance}" if guidance else ""),
        f"- Recommended action: {entry.get('recommended_action')}",
        f"- Customer explanation to adapt (do not quote verbatim): {entry.get('customer_explanation')}",
    ]
    if entry.get("agent_notes"):
        lines.append(f"- Operator notes: {entry['agent_notes']}")
    if srcs:
        lines.append(f"- Sources: {srcs}")
    return "\n".join(lines)


if __name__ == "__main__":
    from models import FailureCode

    rep = coverage_report([c.value for c in FailureCode])
    print(json.dumps(rep, indent=2))
