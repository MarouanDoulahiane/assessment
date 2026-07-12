"""Plan proposers. The orchestrator only needs `propose(state, feedback)`.

- ScriptedProposer: deterministic canned plans (offline demo + tests).
- AnthropicProposer: real LLM via forced tool call (strict JSON schema).
  Optional — requires `pip install anthropic` and ANTHROPIC_API_KEY.

Note what the proposers do NOT contain: safety rules. Prompts describe the
athlete and relay validator feedback; enforcement stays in validator.py.
"""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Protocol

from . import metrics
from .models import AthleteState, Proposal, Session, Violation, session_to_dict


class Proposer(Protocol):
    name: str

    def propose(self, state: AthleteState, feedback: dict | None) -> Proposal: ...


# ---------------------------------------------------------------- scripted

class ScriptedProposer:
    """Pops one canned plan per attempt. Emulates LLM behavior offline."""

    name = "scripted-llm"

    def __init__(self, plans: list[list[tuple[str, str, float, str]]]):
        # each plan: 7 tuples of (kind, intensity, load, note)
        self._plans = list(plans)
        self._i = 0

    def propose(self, state: AthleteState, feedback: dict | None) -> Proposal:
        plan = self._plans[min(self._i, len(self._plans) - 1)]
        self._i += 1
        days = tuple(
            Session(
                day=state.plan_start + timedelta(days=i),
                kind=kind, intensity=intensity, load=load, note=note,
            )
            for i, (kind, intensity, load, note) in enumerate(plan)
        )
        rationale = (
            "Athlete missed sessions — front-load the week to catch up on lost volume."
            if feedback is None
            else "Revised after validator feedback: reduced volume, respected hard-day spacing."
        )
        return Proposal(days=days, rationale=rationale, source="scripted")


AGGRESSIVE_WEEK = [
    ("run", "hard", 70.0, "make up Saturday's missed long run"),
    ("intervals", "hard", 95.0, "VO2max session to regain sharpness"),
    ("run", "moderate", 60.0, "steady aerobic"),
    ("intervals", "hard", 85.0, "threshold repeats"),
    ("run", "easy", 50.0, "recovery jog"),
    ("long_run", "hard", 110.0, "extended long run to rebuild endurance"),
    ("run", "moderate", 65.0, "progression run"),
]

CORRECTED_WEEK = [
    ("run", "easy", 50.0, "gentle re-entry after missed days"),
    ("run", "easy", 45.0, "aerobic maintenance"),
    ("rest", "rest", 0.0, "full rest"),
    ("run", "moderate", 60.0, "steady state"),
    ("run", "easy", 40.0, "recovery"),
    ("long_run", "moderate", 70.0, "long run at conversational pace"),
    ("run", "easy", 40.0, "shakeout"),
]


def demo_proposer() -> ScriptedProposer:
    """Attempt 1 overreaches (classic 'catch up' error); attempt 2 complies."""
    return ScriptedProposer([AGGRESSIVE_WEEK, CORRECTED_WEEK])


def stubborn_proposer() -> ScriptedProposer:
    """Never complies — exercises the fallback + human-review path."""
    return ScriptedProposer([AGGRESSIVE_WEEK])


# ---------------------------------------------------------------- anthropic

PLAN_TOOL = {
    "name": "propose_week",
    "description": "Propose the next 7 days of training. Provide exactly 7 days, "
                   "consecutive calendar dates starting at plan_start.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "days": {
                "type": "array",
                "description": "Exactly 7 consecutive days starting at plan_start.",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "ISO date YYYY-MM-DD"},
                        "kind": {"type": "string", "description": "run | long_run | intervals | rest | race"},
                        "intensity": {"type": "string", "enum": ["rest", "easy", "moderate", "hard"]},
                        "load": {"type": "number", "description": "session load in sRPE units; 0 for rest"},
                        "note": {"type": "string"},
                    },
                    "required": ["date", "kind", "intensity", "load", "note"],
                    "additionalProperties": False,
                },
            },
            "rationale": {"type": "string"},
        },
        "required": ["days", "rationale"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = (
    "You are an endurance-coaching assistant that proposes the next 7 days of "
    "training for one athlete. You PROPOSE ONLY: a deterministic validator "
    "(not you) enforces all training-load safety rules and will reject unsafe "
    "plans with structured violations. If the user message contains validator "
    "violations, produce a revised week that clears every error-severity "
    "violation. Respond only via the propose_week tool."
)


class AnthropicProposer:
    name = "claude"

    def __init__(self, model: str = "claude-opus-4-8"):
        import anthropic  # optional dependency; import here so offline demo never needs it
        self._client = anthropic.Anthropic()
        self._model = model

    def propose(self, state: AthleteState, feedback: dict | None) -> Proposal:
        content = json.dumps(self._describe(state, feedback), indent=2)
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=[PLAN_TOOL],
            tool_choice={"type": "tool", "name": "propose_week"},
            messages=[{"role": "user", "content": content}],
        )
        block = next((b for b in response.content if b.type == "tool_use"), None)
        if block is None:
            raise RuntimeError(f"no tool_use block returned (stop_reason={response.stop_reason})")
        payload = block.input
        if len(payload["days"]) != 7:
            raise RuntimeError(f"proposal has {len(payload['days'])} days, expected 7")
        days = tuple(
            Session(
                day=state.plan_start + timedelta(days=i),  # trust our calendar, not the model's date strings
                kind=d["kind"], intensity=d["intensity"],
                load=float(d["load"]), note=d.get("note", ""),
            )
            for i, d in enumerate(payload["days"])
        )
        return Proposal(days=days, rationale=payload["rationale"], source="llm")

    @staticmethod
    def _describe(state: AthleteState, feedback: dict | None) -> dict:
        loads = metrics.daily_loads(state.history)
        end = state.plan_start - timedelta(days=1)
        doc = {
            "athlete": {
                "name": state.name, "sport": state.sport,
                "race_date": state.race_date.isoformat() if state.race_date else None,
                "plan_start": state.plan_start.isoformat(),
                "notes": state.notes,
            },
            "recent_28_days": [session_to_dict(s) for s in state.history[-28:]],
            "missed_sessions": [session_to_dict(s) for s in state.history if s.status == "missed"],
            "load_summary": {
                "last_7d_total": metrics.window_total(loads, end, 7),
                "chronic_weekly_avg": metrics.chronic_weekly_load(state.history, state.plan_start),
                "current_acwr": metrics.acwr(loads, end),
            },
        }
        if feedback:
            doc["validator_feedback"] = feedback
        return doc


def feedback_from(violations: list[Violation], proposal: Proposal) -> dict:
    """Structured feedback the proposer gets on retry."""
    return {
        "rejected_plan": [session_to_dict(s) for s in proposal.days],
        "violations": [v.to_dict() for v in violations],
        "instruction": "Revise the week so every error-severity violation is resolved. "
                       "Warnings are informational.",
    }
