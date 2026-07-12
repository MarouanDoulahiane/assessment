"""Training-load safety rules as pure functions.

THE DESIGN CONSTRAINT OF THIS REPO: these rules never live in a prompt.
The LLM proposes; this module disposes. Every rule takes (state, plan)
and returns Violations — deterministic, unit-tested, prompt-injection-proof.

Severity is asymmetric on purpose:
  - overload (ACWR high, ramp, spacing, taper) -> "error": blocks the plan
  - underload (ACWR low)                       -> "warning": recorded only,
    because after missed sessions *no* legal plan can instantly restore
    ACWR without breaking the ramp cap; undertraining is a soft risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from . import metrics
from .models import AthleteState, Proposal, Violation


@dataclass(frozen=True)
class RuleConfig:
    acwr_min: float = 0.80
    acwr_max: float = 1.30
    ramp_max: float = 1.10          # +10% weekly load growth cap
    taper_window_days: int = 14     # taper rules engage this close to a race
    taper_cap_fraction: float = 0.60  # of chronic weekly load
    race_quiet_days: int = 2        # days before race: easy/rest only


DEFAULT_CONFIG = RuleConfig()


def check_acwr_band(state: AthleteState, plan: Proposal, cfg: RuleConfig = DEFAULT_CONFIG) -> list[Violation]:
    hist_loads = metrics.daily_loads(state.history)
    if metrics.window_mean(hist_loads, state.plan_start - timedelta(days=1), metrics.CHRONIC_DAYS) <= 0:
        return []  # no chronic base before the plan (new athlete) — the band is meaningless
    over: list[tuple[str, float]] = []
    under: list[tuple[str, float]] = []
    for day, ratio in metrics.acwr_trajectory(state.history, plan):
        if ratio is None:
            continue  # no chronic base (new athlete) — band is meaningless
        if ratio > cfg.acwr_max:
            over.append((day.isoformat(), ratio))
        elif ratio < cfg.acwr_min:
            under.append((day.isoformat(), ratio))
    out: list[Violation] = []
    if over:
        worst = max(r for _, r in over)
        out.append(Violation(
            rule="acwr_band", severity="error",
            message=f"projected ACWR peaks at {worst:.2f}, above safe max {cfg.acwr_max:.2f} (injury-risk zone)",
            observed=round(worst, 3), limit=cfg.acwr_max,
            days=tuple(d for d, _ in over),
        ))
    if under:
        lowest = min(r for _, r in under)
        out.append(Violation(
            rule="acwr_band", severity="warning",
            message=f"projected ACWR dips to {lowest:.2f}, below {cfg.acwr_min:.2f} (detraining; expected when returning from missed sessions)",
            observed=round(lowest, 3), limit=cfg.acwr_min,
            days=tuple(d for d, _ in under),
        ))
    return out


def check_weekly_ramp(state: AthleteState, plan: Proposal, cfg: RuleConfig = DEFAULT_CONFIG) -> list[Violation]:
    reference = metrics.reference_weekly_load(state.history, state.plan_start)
    if reference <= 0:
        return []
    cap = cfg.ramp_max * reference
    total = metrics.plan_total(plan)
    if total <= cap:
        return []
    return [Violation(
        rule="weekly_ramp", severity="error",
        message=f"week total {total:.0f} exceeds ramp cap {cap:.0f} "
                f"(+{(total / reference - 1) * 100:.0f}% vs reference week {reference:.0f}; max +{(cfg.ramp_max - 1) * 100:.0f}%)",
        observed=round(total, 1), limit=round(cap, 1),
    )]


def check_hard_day_spacing(state: AthleteState, plan: Proposal, cfg: RuleConfig = DEFAULT_CONFIG) -> list[Violation]:
    """No hard sessions on consecutive calendar days (min 48h between)."""
    hard_days = sorted(
        [s.day for s in plan.days if s.intensity == "hard"]
        + [s.day for s in state.history
           if s.intensity == "hard" and s.status != "missed"
           and s.day == state.plan_start - timedelta(days=1)]
    )
    pairs = [
        (a, b) for a, b in zip(hard_days, hard_days[1:])
        if (b - a).days < 2
    ]
    if not pairs:
        return []
    return [Violation(
        rule="hard_day_spacing", severity="error",
        message="hard sessions on consecutive days: "
                + ", ".join(f"{a.isoformat()}→{b.isoformat()}" for a, b in pairs)
                + " (min 48h between hard efforts)",
        days=tuple(d.isoformat() for pair in pairs for d in pair),
    )]


def check_taper(state: AthleteState, plan: Proposal, cfg: RuleConfig = DEFAULT_CONFIG) -> list[Violation]:
    if state.race_date is None:
        return []
    out: list[Violation] = []
    days_to_race = (state.race_date - state.plan_start).days
    # 1) volume cap once inside the taper window
    if 0 <= days_to_race <= cfg.taper_window_days:
        cap = cfg.taper_cap_fraction * metrics.chronic_weekly_load(state.history, state.plan_start)
        total = metrics.plan_total(plan)
        if cap > 0 and total > cap:
            out.append(Violation(
                rule="taper", severity="error",
                message=f"race in {days_to_race}d: taper week total {total:.0f} exceeds "
                        f"{cfg.taper_cap_fraction:.0%} of chronic weekly load ({cap:.0f})",
                observed=round(total, 1), limit=round(cap, 1),
            ))
    # 2) quiet days immediately before the race
    quiet = {state.race_date - timedelta(days=i) for i in range(1, cfg.race_quiet_days + 1)}
    noisy = [s for s in plan.days if s.day in quiet and s.intensity not in ("rest", "easy")]
    if noisy:
        out.append(Violation(
            rule="taper", severity="error",
            message=f"non-easy session within {cfg.race_quiet_days} days of race: "
                    + ", ".join(f"{s.day.isoformat()} ({s.intensity})" for s in noisy),
            days=tuple(s.day.isoformat() for s in noisy),
        ))
    return out


ALL_CHECKS = (check_acwr_band, check_weekly_ramp, check_hard_day_spacing, check_taper)


def validate(state: AthleteState, plan: Proposal, cfg: RuleConfig = DEFAULT_CONFIG) -> list[Violation]:
    """Run every rule; errors first, then warnings."""
    violations: list[Violation] = []
    for check in ALL_CHECKS:
        violations.extend(check(state, plan, cfg))
    return sorted(violations, key=lambda v: (v.severity != "error", v.rule))


def errors(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if v.severity == "error"]
