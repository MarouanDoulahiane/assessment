"""The adaptation loop.

    gather state -> LLM proposes 7 days -> validator scores
        -> errors? feed violations back, retry (max 2)
        -> still failing? rules-only fallback + flag for human review

Every step lands in a structured trace: what was proposed, what was
rejected, why, and the resulting ACWR trajectory.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from . import metrics
from .fallback import build_fallback_plan
from .models import AthleteState, Proposal, Violation, session_to_dict
from .proposer import Proposer, feedback_from
from .validator import DEFAULT_CONFIG, RuleConfig, errors, validate

MAX_RETRIES = 2


@dataclass(frozen=True)
class TraceEvent:
    kind: str            # state_gathered | proposal | validation | feedback | fallback | final
    attempt: int         # 0 for non-attempt events
    data: dict[str, Any]


@dataclass
class AdaptationResult:
    plan: Proposal
    violations: list[Violation]          # violations of the *accepted* plan (warnings only, unless fallback failed too)
    accepted_attempt: int                # 0 when fallback used
    used_fallback: bool
    needs_human_review: bool
    trace: list[TraceEvent] = field(default_factory=list)

    def acwr_trajectory(self, state: AthleteState) -> list[tuple[str, float | None]]:
        return [(d.isoformat(), r) for d, r in metrics.acwr_trajectory(state.history, self.plan)]

    def trace_json(self) -> str:
        return json.dumps([{"kind": e.kind, "attempt": e.attempt, **e.data} for e in self.trace],
                          indent=2, default=str)


def _state_summary(state: AthleteState) -> dict:
    loads = metrics.daily_loads(state.history)
    end = state.plan_start - timedelta(days=1)
    ratio = metrics.acwr(loads, end)
    return {
        "athlete": state.name,
        "sport": state.sport,
        "race_date": state.race_date.isoformat() if state.race_date else None,
        "plan_start": state.plan_start.isoformat(),
        "last_7d_load": round(metrics.window_total(loads, end, 7), 1),
        "chronic_weekly_avg": round(metrics.chronic_weekly_load(state.history, state.plan_start), 1),
        "acwr_at_plan_start": round(ratio, 3) if ratio is not None else None,
        "missed_sessions": [session_to_dict(s) for s in state.history if s.status == "missed"],
    }


def adapt_week(
    state: AthleteState,
    proposer: Proposer,
    cfg: RuleConfig = DEFAULT_CONFIG,
    max_retries: int = MAX_RETRIES,
) -> AdaptationResult:
    trace: list[TraceEvent] = [TraceEvent("state_gathered", 0, _state_summary(state))]
    feedback: dict | None = None

    for attempt in range(1, max_retries + 2):  # initial attempt + max_retries
        proposal = proposer.propose(state, feedback)
        trace.append(TraceEvent("proposal", attempt, {
            "source": proposal.source,
            "rationale": proposal.rationale,
            "days": [session_to_dict(s) for s in proposal.days],
            "week_total": metrics.plan_total(proposal),
        }))

        violations = validate(state, proposal, cfg)
        errs = errors(violations)
        trace.append(TraceEvent("validation", attempt, {
            "violations": [v.to_dict() for v in violations],
            "error_count": len(errs),
            "warning_count": len(violations) - len(errs),
            "verdict": "accepted" if not errs else "rejected",
        }))

        if not errs:
            result = AdaptationResult(
                plan=proposal, violations=violations,
                accepted_attempt=attempt, used_fallback=False,
                needs_human_review=False, trace=trace,
            )
            trace.append(_final_event(state, result))
            return result

        feedback = feedback_from(violations, proposal)
        if attempt <= max_retries:
            trace.append(TraceEvent("feedback", attempt, {
                "sent_to_proposer": feedback,
            }))

    # All attempts failed validation: deterministic floor + human flag.
    plan = build_fallback_plan(state, cfg)
    violations = validate(state, plan, cfg)
    trace.append(TraceEvent("fallback", 0, {
        "reason": f"no compliant proposal after {max_retries + 1} attempts",
        "days": [session_to_dict(s) for s in plan.days],
        "week_total": metrics.plan_total(plan),
        "residual_violations": [v.to_dict() for v in violations],
    }))
    result = AdaptationResult(
        plan=plan, violations=violations,
        accepted_attempt=0, used_fallback=True,
        needs_human_review=True, trace=trace,
    )
    trace.append(_final_event(state, result))
    return result


def _final_event(state: AthleteState, result: AdaptationResult) -> TraceEvent:
    return TraceEvent("final", result.accepted_attempt, {
        "source": result.plan.source,
        "used_fallback": result.used_fallback,
        "needs_human_review": result.needs_human_review,
        "week_total": metrics.plan_total(result.plan),
        "acwr_trajectory": [
            {"date": d, "acwr": round(r, 3) if r is not None else None}
            for d, r in result.acwr_trajectory(state)
        ],
    })
