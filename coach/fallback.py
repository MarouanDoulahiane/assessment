"""Rules-only plan generator: the deterministic floor when the LLM can't
produce a compliant week. Conservative by construction — no hard days,
one rest day, volume at 90% of the reference week (inside the ramp cap),
taper-capped when a race is near.
"""
from __future__ import annotations

from datetime import timedelta

from . import metrics
from .models import AthleteState, Proposal, Session
from .validator import RuleConfig, DEFAULT_CONFIG

# (kind, intensity, fraction of weekly target) — fractions sum to 1.0
WEEK_SHAPE = (
    ("run", "easy", 0.16),
    ("run", "easy", 0.14),
    ("rest", "rest", 0.00),
    ("run", "moderate", 0.20),
    ("run", "easy", 0.12),
    ("long_run", "moderate", 0.24),
    ("run", "easy", 0.14),
)


def build_fallback_plan(state: AthleteState, cfg: RuleConfig = DEFAULT_CONFIG) -> Proposal:
    reference = metrics.reference_weekly_load(state.history, state.plan_start)
    target = 0.90 * reference

    tapering = (
        state.race_date is not None
        and 0 <= (state.race_date - state.plan_start).days <= cfg.taper_window_days
    )
    if tapering:
        chronic = metrics.chronic_weekly_load(state.history, state.plan_start)
        target = min(target, 0.55 * chronic)

    days = []
    for i, (kind, intensity, frac) in enumerate(WEEK_SHAPE):
        day = state.plan_start + timedelta(days=i)
        if tapering and intensity == "moderate":
            intensity = "easy"  # taper weeks: nothing above easy
        if state.race_date is not None and abs((state.race_date - day).days) <= cfg.race_quiet_days and day != state.race_date:
            intensity, kind = ("easy", "run") if frac > 0 else ("rest", "rest")
        days.append(Session(
            day=day, kind=kind, intensity=intensity,
            load=round(target * frac, 1),
            status="planned",
            note="rules-only fallback",
        ))
    return Proposal(
        days=tuple(days),
        rationale="Deterministic fallback: 90% of reference weekly load, no hard "
                  "sessions, one rest day. Generated because no LLM proposal "
                  "passed validation.",
        source="fallback",
    )
