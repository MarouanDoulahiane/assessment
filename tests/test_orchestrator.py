import json
from datetime import date, timedelta

from coach.fallback import build_fallback_plan
from coach.models import AthleteState, Session
from coach.orchestrator import adapt_week
from coach.proposer import (AGGRESSIVE_WEEK, CORRECTED_WEEK, ScriptedProposer,
                            demo_proposer, stubborn_proposer)
from coach.validator import errors

PLAN_START = date(2026, 7, 13)


def make_state() -> AthleteState:
    history = tuple(
        Session(day=PLAN_START - timedelta(days=28 - i), kind="run",
                intensity="easy", load=45.0, status="completed")
        for i in range(28)
    )
    return AthleteState(name="t", sport="running", race_date=None,
                        plan_start=PLAN_START, history=history)


def good_week():
    return [("run", "easy", 45.0, "")] * 7  # steady state — always compliant


def test_accepts_compliant_plan_first_try():
    result = adapt_week(make_state(), ScriptedProposer([good_week()]))
    assert result.accepted_attempt == 1
    assert not result.used_fallback
    assert not result.needs_human_review
    assert errors(result.violations) == []


def test_retries_then_accepts():
    result = adapt_week(make_state(), ScriptedProposer([AGGRESSIVE_WEEK, good_week()]))
    assert result.accepted_attempt == 2
    assert not result.used_fallback
    kinds = [e.kind for e in result.trace]
    assert kinds.count("proposal") == 2
    assert "feedback" in kinds          # violations were fed back to the proposer
    verdicts = [e.data["verdict"] for e in result.trace if e.kind == "validation"]
    assert verdicts == ["rejected", "accepted"]


def test_falls_back_after_max_retries_and_flags_review():
    result = adapt_week(make_state(), stubborn_proposer(), max_retries=2)
    assert result.used_fallback
    assert result.needs_human_review
    assert result.accepted_attempt == 0
    assert result.plan.source == "fallback"
    kinds = [e.kind for e in result.trace]
    assert kinds.count("proposal") == 3          # initial + 2 retries
    assert kinds.count("fallback") == 1
    # the deterministic floor itself must be safe
    assert errors(result.violations) == []


def test_fallback_plan_is_always_compliant():
    state = make_state()
    plan = build_fallback_plan(state)
    from coach.validator import validate
    assert errors(validate(state, plan)) == []
    assert all(s.intensity != "hard" for s in plan.days)


def test_feedback_contains_rejected_plan_and_violations():
    result = adapt_week(make_state(), ScriptedProposer([AGGRESSIVE_WEEK, good_week()]))
    feedback = next(e for e in result.trace if e.kind == "feedback").data["sent_to_proposer"]
    assert len(feedback["rejected_plan"]) == 7
    assert any(v["severity"] == "error" for v in feedback["violations"])
    assert "instruction" in feedback


def test_trace_is_json_serializable_and_ends_with_final():
    result = adapt_week(make_state(), demo_proposer())
    payload = json.loads(result.trace_json())
    assert payload[0]["kind"] == "state_gathered"
    assert payload[-1]["kind"] == "final"
    assert "acwr_trajectory" in payload[-1]
    assert len(payload[-1]["acwr_trajectory"]) == 7


def test_demo_scenario_rejects_then_accepts_corrected_week():
    """The exact story `make demo` tells, pinned as a regression test."""
    result = adapt_week(make_state(), ScriptedProposer([AGGRESSIVE_WEEK, CORRECTED_WEEK]))
    assert result.accepted_attempt == 2
    first_validation = next(e for e in result.trace if e.kind == "validation")
    rules = {v["rule"] for v in first_validation.data["violations"] if v["severity"] == "error"}
    assert {"weekly_ramp", "hard_day_spacing", "acwr_band"} <= rules
