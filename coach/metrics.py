"""Training-load math. Pure functions only — no I/O, no state.

ACWR uses the rolling-average method (Gabbett): acute = 7-day mean daily
load, chronic = 28-day mean daily load, both windows inclusive of the day
being scored. Proposed plan days are treated as if completed, so the
validator scores the *projected* ACWR the plan would produce.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from .models import Proposal, Session

ACUTE_DAYS = 7
CHRONIC_DAYS = 28


def daily_loads(sessions: Iterable[Session]) -> dict[date, float]:
    """Effective load per calendar day (missed/rest count as zero)."""
    out: dict[date, float] = {}
    for s in sessions:
        out[s.day] = out.get(s.day, 0.0) + s.effective_load
    return out


def window_total(loads: dict[date, float], end: date, days: int) -> float:
    start = end - timedelta(days=days - 1)
    return sum(v for d, v in loads.items() if start <= d <= end)


def window_mean(loads: dict[date, float], end: date, days: int) -> float:
    return window_total(loads, end, days) / days


def acwr(loads: dict[date, float], day: date) -> float | None:
    """Acute:chronic workload ratio on `day`; None if chronic load is zero."""
    chronic = window_mean(loads, day, CHRONIC_DAYS)
    if chronic <= 0:
        return None
    return window_mean(loads, day, ACUTE_DAYS) / chronic


def combined_loads(history: Iterable[Session], plan: Proposal) -> dict[date, float]:
    loads = daily_loads(history)
    loads.update(daily_loads(plan.days))
    return loads


def acwr_trajectory(history: Iterable[Session], plan: Proposal) -> list[tuple[date, float | None]]:
    """Projected ACWR for each day of the proposed week."""
    loads = combined_loads(history, plan)
    return [(s.day, acwr(loads, s.day)) for s in plan.days]


def plan_total(plan: Proposal) -> float:
    return sum(s.effective_load for s in plan.days)


def reference_weekly_load(history: Iterable[Session], plan_start: date) -> float:
    """Baseline for the ramp cap: the larger of last week's total and the
    28-day average weekly total. Using the max avoids punishing an athlete
    for one depressed week (e.g. missed sessions) while still capping
    growth against their chronic base."""
    loads = daily_loads(history)
    end = plan_start - timedelta(days=1)
    last_week = window_total(loads, end, ACUTE_DAYS)
    chronic_weekly = window_total(loads, end, CHRONIC_DAYS) / 4.0
    return max(last_week, chronic_weekly)


def chronic_weekly_load(history: Iterable[Session], plan_start: date) -> float:
    loads = daily_loads(history)
    return window_total(loads, plan_start - timedelta(days=1), CHRONIC_DAYS) / 4.0
