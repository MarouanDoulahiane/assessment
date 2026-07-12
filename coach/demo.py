"""Runnable demo: prints the full adaptation trace for a fixture athlete.

    python3 -m coach.demo fixtures/athlete_missed_two.json
    python3 -m coach.demo fixtures/athlete_missed_two.json --proposer stubborn
    python3 -m coach.demo fixtures/athlete_missed_two.json --proposer anthropic  # needs API key
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .models import load_state
from .orchestrator import AdaptationResult, adapt_week
from .proposer import demo_proposer, stubborn_proposer

MARK = {"error": "✗", "warning": "⚠"}
DIVIDER = "─" * 74


def _print_header(title: str) -> None:
    print(f"\n══ {title} " + "═" * max(0, 70 - len(title)))


def _print_plan(days: list[dict]) -> None:
    for d in days:
        load = f"{d['load']:>5.0f}" if d["load"] else "    –"
        print(f"    {d['date']}  {d['kind']:<9} {d['intensity']:<9} {load}  {d['note']}")


def render(result: AdaptationResult) -> None:
    for event in result.trace:
        if event.kind == "state_gathered":
            s = event.data
            _print_header("ATHLETE STATE")
            race = f"race {s['race_date']}" if s["race_date"] else "no race scheduled"
            print(f"  {s['athlete']} · {s['sport']} · {race} · planning week of {s['plan_start']}")
            print(f"  last 7d load {s['last_7d_load']:.0f} vs chronic weekly avg {s['chronic_weekly_avg']:.0f}"
                  f" · ACWR at plan start: {s['acwr_at_plan_start']}")
            for m in s["missed_sessions"]:
                print(f"  MISSED: {m['date']} {m['kind']} ({m['intensity']}, load {m['load']:.0f})")

        elif event.kind == "proposal":
            _print_header(f"ATTEMPT {event.attempt} — proposal ({event.data['source']})")
            print(f"  rationale: {event.data['rationale']}")
            _print_plan(event.data["days"])
            print(f"    {'week total':>40} {event.data['week_total']:>6.0f}")

        elif event.kind == "validation":
            for v in event.data["violations"]:
                print(f"  {MARK[v['severity']]} {v['rule']}: {v['message']}")
            if event.data["verdict"] == "accepted":
                print(f"  ✓ ACCEPTED on attempt {event.attempt}"
                      f" ({event.data['warning_count']} warning(s), 0 errors)")
            else:
                print(f"  → REJECTED: {event.data['error_count']} error(s)")

        elif event.kind == "feedback":
            n = len(event.data["sent_to_proposer"]["violations"])
            print(f"  ↩ feedback sent to proposer ({n} violations, structured JSON) — retrying")

        elif event.kind == "fallback":
            _print_header("FALLBACK — rules-only plan (LLM never complied)")
            print(f"  reason: {event.data['reason']}")
            _print_plan(event.data["days"])
            print(f"    {'week total':>40} {event.data['week_total']:>6.0f}")

        elif event.kind == "final":
            f = event.data
            _print_header("RESULT")
            src = "rules-only fallback" if f["used_fallback"] else f"LLM proposal (attempt {event.attempt})"
            review = "YES — flagged for coach sign-off" if f["needs_human_review"] else "not required"
            print(f"  plan source: {src} · week total {f['week_total']:.0f} · human review: {review}")
            arc = " → ".join(
                f"{p['acwr']:.2f}" if p["acwr"] is not None else "–"
                for p in f["acwr_trajectory"]
            )
            print(f"  projected ACWR through the week: {arc}")
    print(DIVIDER)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", help="path to athlete state JSON")
    parser.add_argument("--proposer", choices=["scripted", "stubborn", "anthropic"],
                        default="scripted")
    parser.add_argument("--trace-out", default="trace.json")
    args = parser.parse_args(argv)

    state = load_state(args.fixture)
    if args.proposer == "anthropic":
        from .proposer import AnthropicProposer  # optional dep, imported lazily
        proposer = AnthropicProposer()
    elif args.proposer == "stubborn":
        proposer = stubborn_proposer()
    else:
        proposer = demo_proposer()

    result = adapt_week(state, proposer)
    render(result)

    Path(args.trace_out).write_text(result.trace_json())
    print(f"  structured trace written to {args.trace_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
