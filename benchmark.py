"""
Recoup v0.7.0 - Comparative Benchmark & Evaluation Runner
Three-arm A/B/C across a held-out cohort of Indian payment failures:

  1. Rule Baseline        - static error-code lookup table (industry-standard dunning)
  2. AI Agent (no KB)     - LLM/heuristic with NO knowledge grounding  (the "before")
  3. AI Agent + Playbook  - same engine, retrieval-augmented with the curated
                            NPCI / RBI / Razorpay recovery playbook       (the "after")

Set RECOUP_DISABLE_LLM=1 for a fast, fully reproducible run (heuristic decisioning);
the knowledge-grounding effect is preserved in the heuristic fallback.
"""

import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

import json
import os
import random
import zlib
from typing import Dict, Tuple

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from models import (
    FailedPaymentContext,
    AgentDecision,
    PolicyVerdict,
    RecoveryActionType,
    FailureCategory,
    FailureCode,
)
from policy import PolicyGuardrailEngine
from baseline import RuleBasedBaselineEngine
from agent import RecoveryAgent
from dataset import load_dataset

console = Console(force_terminal=True, safe_box=True, width=118)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SUMMARY_PATH = os.path.join(DATA_DIR, "benchmark_summary.json")

RAIL_OF = {
    "upi_intent": "UPI", "upi_collect": "UPI", "upi_autopay": "UPI AutoPay",
    "card_credit": "Cards", "card_debit": "Cards",
    "emandate": "Mandates (eNACH)", "netbanking": "Netbanking",
}


# A few failure codes recover differently from their category default (a category-keyed model
# cannot see that a locked UPI PIN or a lapsed collect request needs a specific route).
_CODE_OVERRIDES = {
    # code -> {action_value: probability}   (channel-agnostic; missing actions fall through)
    "upi_mpin_attempts_exceeded": {
        "method_switch_nudge": 0.62, "alternative_payment_link": 0.18,
        "dynamic_backoff_retry": 0.04, "smart_dunning_schedule": 0.06,
    },
    "upi_collect_expired": {
        "alternative_payment_link": 0.70, "method_switch_nudge": 0.55,
        "dynamic_backoff_retry": 0.10,
    },
}


class RealisticOutcomeSimulator:
    """Simulates real-world recovery outcomes from action type, channel and failure context."""

    @staticmethod
    def simulate(context: FailedPaymentContext, verdict: PolicyVerdict, decision: AgentDecision, seed: int) -> Tuple[bool, float, float]:
        # zlib.crc32 (not hash()) so runs are reproducible across processes / platforms
        random.seed(seed + zlib.crc32(context.transaction_id.encode()))
        action = verdict.enforced_action
        cat = context.failure_category
        code = context.error_code
        amt = context.amount_inr
        wa = decision.channel == "whatsapp"

        cost = 0.0
        if action in (RecoveryActionType.ALTERNATIVE_PAYMENT_LINK, RecoveryActionType.METHOD_SWITCH_NUDGE):
            cost += 0.20
        elif action in (RecoveryActionType.DYNAMIC_BACKOFF_RETRY, RecoveryActionType.SMART_DUNNING_SCHEDULE):
            cost += 5.00

        override = _CODE_OVERRIDES.get(code.value)
        if override is not None and action.value in override:
            ok = random.random() < override[action.value]
            return ok, (amt if ok else 0.0), cost
        if action == RecoveryActionType.IMMEDIATE_STOP:
            return False, 0.0, cost

        if action == RecoveryActionType.ESCALATE_TO_HUMAN:
            prob = 0.80 if cat == FailureCategory.HIGH_VALUE_AMBIGUITY else 0.70
            ok = random.random() < prob
            return ok, (amt if ok else 0.0), cost

        if action == RecoveryActionType.DYNAMIC_BACKOFF_RETRY:
            if cat == FailureCategory.TRANSIENT_TECHNICAL:
                prob = 0.85 if decision.backoff_seconds <= 3600 else 0.55
            elif cat == FailureCategory.PSP_UNAVAILABLE:
                prob = 0.72 if decision.backoff_seconds <= 1800 else 0.48
            else:
                prob = 0.07  # retrying a limit / dead mandate / dead token almost never works
            ok = random.random() < prob
            return ok, (amt if ok else 0.0), cost

        if action == RecoveryActionType.ALTERNATIVE_PAYMENT_LINK:
            if cat == FailureCategory.AUTHENTICATION_DROP:
                prob = 0.75 if wa else 0.25
            elif cat == FailureCategory.MANDATE_LIFECYCLE:
                prob = 0.55 if wa else 0.28
            elif cat == FailureCategory.COMPLIANCE_TOKENIZATION:
                prob = 0.58 if wa else 0.30
            elif cat == FailureCategory.LIMIT_EXCEEDED:
                prob = 0.16 if wa else 0.08   # a link back to the same capped rail just hits the wall again
            elif cat == FailureCategory.PSP_UNAVAILABLE:
                prob = 0.40 if wa else 0.22
            elif cat == FailureCategory.METHOD_RESTRICTION:
                prob = 0.15 if wa else 0.08   # link reopens the same disabled card; needs a method switch
            elif cat == FailureCategory.HIGH_VALUE_AMBIGUITY:
                prob = 0.15
            else:
                prob = 0.35
            ok = random.random() < prob
            return ok, (amt if ok else 0.0), cost

        if action == RecoveryActionType.METHOD_SWITCH_NUDGE:
            if cat == FailureCategory.LIMIT_EXCEEDED:
                prob = 0.62 if wa else 0.40
            elif cat == FailureCategory.METHOD_RESTRICTION:
                prob = 0.60 if wa else 0.35
            elif cat == FailureCategory.PSP_UNAVAILABLE:
                prob = 0.66 if wa else 0.42
            elif cat == FailureCategory.COMPLIANCE_TOKENIZATION:
                prob = 0.50 if wa else 0.30
            elif cat == FailureCategory.MANDATE_LIFECYCLE:
                prob = 0.45 if wa else 0.25
            elif cat == FailureCategory.AUTHENTICATION_DROP:
                prob = 0.55 if wa else 0.30
            else:
                prob = 0.35
            ok = random.random() < prob
            return ok, (amt if ok else 0.0), cost

        if action == RecoveryActionType.SMART_DUNNING_SCHEDULE:
            if cat == FailureCategory.CUSTOMER_LIQUIDITY:
                prob = 0.65 if wa else 0.30
            elif cat == FailureCategory.MANDATE_LIFECYCLE:
                prob = 0.60 if code == FailureCode.PRE_DEBIT_NOTIFICATION_MISSING else 0.12
            elif cat == FailureCategory.LIMIT_EXCEEDED:
                prob = 0.55 if code in (FailureCode.UPI_DAILY_LIMIT, FailureCode.UPI_NEW_USER_LIMIT) else 0.10
            else:
                prob = 0.20
            ok = random.random() < prob
            return ok, (amt if ok else 0.0), cost

        return False, 0.0, cost


def _blank() -> Dict:
    return {"recovered_count": 0, "recovered_inr": 0.0, "total_cost_inr": 0.0,
            "violations": 0, "escalations": 0, "stopped": 0}


def _evaluate(ctx, decision, seed, bucket, rails, rail_key):
    verdict = PolicyGuardrailEngine.validate(ctx, decision)
    if not verdict.is_permitted:
        bucket["violations"] += 1
    if verdict.enforced_action == RecoveryActionType.ESCALATE_TO_HUMAN:
        bucket["escalations"] += 1
    elif verdict.enforced_action == RecoveryActionType.IMMEDIATE_STOP:
        bucket["stopped"] += 1
    rec, amt, cost = RealisticOutcomeSimulator.simulate(ctx, verdict, decision, seed)
    if rec:
        bucket["recovered_count"] += 1
        bucket["recovered_inr"] += amt
        rails[rail_key][1] += 1
    bucket["total_cost_inr"] += cost
    rails[rail_key][0] += 1


def run_benchmark(dataset_file: str = "eval_cohort_200.json"):
    console.print("\n[bold cyan]" + "=" * 70 + "[/bold cyan]")
    console.print("[bold yellow]   RECOUP v0.7.0 - KNOWLEDGE-GROUNDED RECOVERY BENCHMARK (A/B/C)   [/bold yellow]")
    console.print("[bold cyan]" + "=" * 70 + "[/bold cyan]\n")

    cohort = load_dataset(dataset_file)
    total_tx = len(cohort)
    total_at_risk = sum(c.amount_inr for c in cohort)
    llm_mode = "heuristic (RECOUP_DISABLE_LLM=1)" if os.getenv("RECOUP_DISABLE_LLM") == "1" else "live LLM w/ heuristic fallback"

    console.print(f"[white]Cohort: [yellow]{total_tx}[/yellow] held-out failures | "
                  f"At risk: [green]₹{total_at_risk:,.2f}[/green] | Decisioning: [cyan]{llm_mode}[/cyan][/white]\n")

    ai_nokb = RecoveryAgent(use_playbook=False)
    ai_kb = RecoveryAgent(use_playbook=True)

    res = {"baseline": _blank(), "ai_nokb": _blank(), "ai_kb": _blank()}
    rails = {arm: {r: [0, 0] for r in set(RAIL_OF.values())} for arm in res}  # rail -> [attempts, recovered]

    with console.status("[green]Running three-arm evaluation..."):
        for idx, ctx in enumerate(cohort):
            seed = 42 + idx
            rk = RAIL_OF.get(ctx.payment_method.value, "UPI")
            _evaluate(ctx, RuleBasedBaselineEngine.decide(ctx), seed, res["baseline"], rails["baseline"], rk)
            _evaluate(ctx, ai_nokb.decide(ctx), seed, res["ai_nokb"], rails["ai_nokb"], rk)
            _evaluate(ctx, ai_kb.decide(ctx), seed, res["ai_kb"], rails["ai_kb"], rk)

    def rate(a):
        return res[a]["recovered_count"] / total_tx * 100

    def net(a):
        return res[a]["recovered_inr"] - res[a]["total_cost_inr"]

    b_rate, nok_rate, kb_rate = rate("baseline"), rate("ai_nokb"), rate("ai_kb")
    b_net, nok_net, kb_net = net("baseline"), net("ai_nokb"), net("ai_kb")

    table = Table(title="Three-Arm Comparative Results", show_header=True, header_style="bold magenta", expand=True)
    table.add_column("Metric", style="cyan", width=30)
    table.add_column("Rule Baseline", justify="right")
    table.add_column("AI (no KB)", justify="right")
    table.add_column("AI + Playbook", justify="right", style="bold green")
    table.add_column("KB Lift", justify="right", style="bold yellow")

    table.add_row("Transactions recovered",
                  str(res["baseline"]["recovered_count"]), str(res["ai_nokb"]["recovered_count"]),
                  str(res["ai_kb"]["recovered_count"]),
                  f"{res['ai_kb']['recovered_count'] - res['ai_nokb']['recovered_count']:+d}")
    table.add_row("Recovery success rate",
                  f"{b_rate:.1f}%", f"{nok_rate:.1f}%", f"{kb_rate:.1f}%", f"{kb_rate - nok_rate:+.1f} pts")
    table.add_row("Gross revenue recovered",
                  f"₹{res['baseline']['recovered_inr']:,.0f}", f"₹{res['ai_nokb']['recovered_inr']:,.0f}",
                  f"₹{res['ai_kb']['recovered_inr']:,.0f}",
                  f"₹{res['ai_kb']['recovered_inr'] - res['ai_nokb']['recovered_inr']:+,.0f}")
    table.add_row("Recovery friction cost",
                  f"₹{res['baseline']['total_cost_inr']:,.2f}", f"₹{res['ai_nokb']['total_cost_inr']:,.2f}",
                  f"₹{res['ai_kb']['total_cost_inr']:,.2f}", "-")
    table.add_row("Net economic value",
                  f"₹{b_net:,.0f}", f"₹{nok_net:,.0f}", f"₹{kb_net:,.0f}", f"₹{kb_net - nok_net:+,.0f}")
    table.add_row("Policy guardrail violations",
                  str(res["baseline"]["violations"]), str(res["ai_nokb"]["violations"]),
                  str(res["ai_kb"]["violations"]),
                  f"{res['ai_kb']['violations'] - res['ai_nokb']['violations']:+d}")
    table.add_row("Human escalations",
                  str(res["baseline"]["escalations"]), str(res["ai_nokb"]["escalations"]),
                  str(res["ai_kb"]["escalations"]), "-")
    table.add_row("Hard stops enforced",
                  str(res["baseline"]["stopped"]), str(res["ai_nokb"]["stopped"]),
                  str(res["ai_kb"]["stopped"]), "-")
    console.print(table)

    # Per-rail recovery-rate breakdown (baseline vs AI + Playbook)
    rb = Table(title="Recovery Rate by Rail  -  Baseline vs AI + Playbook", show_header=True, header_style="bold magenta", expand=True)
    rb.add_column("Rail", style="cyan")
    rb.add_column("Baseline", justify="right")
    rb.add_column("AI + Playbook", justify="right", style="bold green")
    rb.add_column("Lift", justify="right", style="bold yellow")
    rail_summary = []
    for r in sorted(rails["ai_kb"]):
        att_b, rec_b = rails["baseline"][r]
        att_k, rec_k = rails["ai_kb"][r]
        if att_k == 0:
            continue
        pb = rec_b / att_b * 100 if att_b else 0.0
        pk = rec_k / att_k * 100
        rb.add_row(r, f"{pb:.0f}%", f"{pk:.0f}%", f"+{pk - pb:.0f} pts")
        rail_summary.append({"rail": r, "attempts": att_k,
                             "baseline_rate_pct": round(pb, 1), "ai_rate_pct": round(pk, 1),
                             "lift_pts": round(pk - pb, 1)})
    console.print(rb)

    kb_lift_pct = ((kb_net - nok_net) / max(nok_net, 1.0)) * 100
    vs_base_pct = ((kb_net - b_net) / max(b_net, 1.0)) * 100
    console.print(Panel(
        f"[bold green]KNOWLEDGE-BASE LIFT (AI no-KB -> AI + Playbook):[/bold green]\n"
        f"  Recovery rate: [yellow]{nok_rate:.1f}% -> {kb_rate:.1f}%[/yellow]  ({kb_rate - nok_rate:+.1f} points)\n"
        f"  Net revenue:   [yellow]₹{nok_net:,.0f} -> ₹{kb_net:,.0f}[/yellow]  ({kb_lift_pct:+.1f}%)\n"
        f"  Policy violations: [yellow]{res['ai_nokb']['violations']} -> {res['ai_kb']['violations']}[/yellow]\n\n"
        f"[bold cyan]vs Rule Baseline:[/bold cyan] {b_rate:.1f}% -> {kb_rate:.1f}% recovery, "
        f"net ₹{kb_net - b_net:+,.0f} ({vs_base_pct:+.1f}%)",
        title="[bold yellow]Recoup v0.7.0 Evaluation Summary[/bold yellow]", border_style="green"))

    summary = {
        "schema": "recoup.benchmark/0.7.0",
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "dataset_file": dataset_file,
        "decisioning_mode": llm_mode,
        "cohort_size": total_tx,
        "total_at_risk_inr": round(total_at_risk, 2),
        "arms": {
            "baseline": _round_arm(res["baseline"], b_rate, b_net),
            "ai_nokb": _round_arm(res["ai_nokb"], nok_rate, nok_net),
            "ai_kb": _round_arm(res["ai_kb"], kb_rate, kb_net),
        },
        "kb_lift": {
            "recovery_rate_points": round(kb_rate - nok_rate, 1),
            "extra_transactions": res["ai_kb"]["recovered_count"] - res["ai_nokb"]["recovered_count"],
            "net_revenue_inr": round(kb_net - nok_net, 2),
            "net_revenue_pct": round(kb_lift_pct, 1),
            "violations_removed": res["ai_nokb"]["violations"] - res["ai_kb"]["violations"],
        },
        "vs_baseline": {
            "recovery_rate_points": round(kb_rate - b_rate, 1),
            "net_revenue_inr": round(kb_net - b_net, 2),
            "net_revenue_pct": round(vs_base_pct, 1),
        },
        "rail_breakdown": rail_summary,
    }
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    console.print(f"\n[dim]Wrote machine-readable summary -> {SUMMARY_PATH}[/dim]\n")
    return summary


def _round_arm(arm: Dict, rate: float, net_inr: float) -> Dict:
    return {
        "recovered_count": arm["recovered_count"],
        "recovery_rate_pct": round(rate, 1),
        "gross_recovered_inr": round(arm["recovered_inr"], 2),
        "friction_costs_inr": round(arm["total_cost_inr"], 2),
        "net_recovered_inr": round(net_inr, 2),
        "policy_violations": arm["violations"],
        "human_escalations": arm["escalations"],
        "hard_stops": arm["stopped"],
    }


if __name__ == "__main__":
    run_benchmark()
