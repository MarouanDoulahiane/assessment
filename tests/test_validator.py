from datetime import date, timedelta

from coach import validator
from coach.models import AthleteState, Proposal, Session

PLAN_START = date(2026, 7, 13)


def make_state(daily_load: float = 45.0, race_date: date | None = None,
               last_day_hard: bool = False) -> AthleteState:
    """28 days of steady history ending the day before PLAN_START."""
    history = []
    for i in range(28):
        day = PLAN_START - timedelta(days=28 - i)
        hard_boundary = last_day_hard and i == 27
        history.append(Session(
            day=day, kind="run",
            intensity="hard" if hard_boundary else "easy",
            load=daily_load, status="completed",
        ))
    return AthleteState(
        name="t", sport="running", race_date=race_date,
        plan_start=PLAN_START, history=tuple(history),
    )


def make_plan(loads: list[float], intensities: list[str] | None = None) -> Proposal:
    intensities = intensities or ["easy"] * 7
    return Proposal(
        days=tuple(
            Session(day=PLAN_START + timedelta(days=i), kind="run",
                    intensity=intensities[i], load=loads[i])
            for i in range(7)
        ),
        rationale="test", source="scripted",
    )


def rules_of(violations, severity=None):
    return [v.rule for v in violations if severity is None or v.severity == severity]


# ---------------------------------------------------------------- ACWR band

def test_acwr_spike_is_error():
    state = make_state(daily_load=45)          # chronic ~45/day
    plan = make_plan([100] * 7)                # acute ramps to ~100/day -> ACWR >> 1.3
    v = validator.check_acwr_band(state, plan)
    assert rules_of(v, "error") == ["acwr_band"]
    assert v[0].observed > 1.3


def test_acwr_underload_is_warning_not_error():
    state = make_state(daily_load=45)
    plan = make_plan([10] * 7)                 # big drop -> ACWR < 0.8
    v = validator.check_acwr_band(state, plan)
    assert rules_of(v, "warning") == ["acwr_band"]
    assert rules_of(v, "error") == []


def test_acwr_steady_plan_is_clean():
    state = make_state(daily_load=45)
    plan = make_plan([45] * 7)
    assert validator.check_acwr_band(state, plan) == []


def test_acwr_skipped_without_history():
    state = AthleteState(name="new", sport="running", race_date=None,
                         plan_start=PLAN_START, history=())
    plan = make_plan([45] * 7)
    assert validator.check_acwr_band(state, plan) == []


# ---------------------------------------------------------------- ramp cap

def test_ramp_over_cap_is_error():
    state = make_state(daily_load=45)          # reference week = 315
    plan = make_plan([60] * 7)                 # 420 > 315 * 1.10 = 346.5
    v = validator.check_weekly_ramp(state, plan)
    assert rules_of(v, "error") == ["weekly_ramp"]
    assert v[0].observed == 420
    assert v[0].limit == 346.5


def test_ramp_within_cap_passes():
    state = make_state(daily_load=45)
    plan = make_plan([48] * 7)                 # 336 <= 346.5
    assert validator.check_weekly_ramp(state, plan) == []


# ---------------------------------------------------------------- spacing

def test_consecutive_hard_days_error():
    state = make_state()
    plan = make_plan([45] * 7, ["hard", "hard", "easy", "easy", "easy", "easy", "easy"])
    v = validator.check_hard_day_spacing(state, plan)
    assert rules_of(v, "error") == ["hard_day_spacing"]


def test_spaced_hard_days_pass():
    state = make_state()
    plan = make_plan([45] * 7, ["hard", "easy", "hard", "easy", "hard", "easy", "easy"])
    assert validator.check_hard_day_spacing(state, plan) == []


def test_spacing_checks_boundary_with_history():
    state = make_state(last_day_hard=True)     # yesterday was hard
    plan = make_plan([45] * 7, ["hard", "easy", "easy", "easy", "easy", "easy", "easy"])
    v = validator.check_hard_day_spacing(state, plan)
    assert rules_of(v, "error") == ["hard_day_spacing"]


def test_missed_hard_day_does_not_block_boundary():
    state = make_state(last_day_hard=True)
    # same as above but yesterday's hard session was missed
    history = list(state.history)
    last = history[-1]
    history[-1] = Session(day=last.day, kind=last.kind, intensity="hard",
                          load=last.load, status="missed")
    state = AthleteState(name="t", sport="running", race_date=None,
                         plan_start=PLAN_START, history=tuple(history))
    plan = make_plan([45] * 7, ["hard", "easy", "easy", "easy", "easy", "easy", "easy"])
    assert validator.check_hard_day_spacing(state, plan) == []


# ---------------------------------------------------------------- taper

def test_taper_volume_cap():
    race = PLAN_START + timedelta(days=6)      # race at end of this week
    state = make_state(daily_load=45, race_date=race)   # chronic weekly = 315
    plan = make_plan([45] * 7)                 # 315 > 0.6 * 315 = 189
    v = validator.check_taper(state, plan)
    assert "taper" in rules_of(v, "error")


def test_taper_quiet_days_before_race():
    race = PLAN_START + timedelta(days=6)
    state = make_state(daily_load=45, race_date=race)
    intensities = ["easy", "easy", "easy", "easy", "moderate", "easy", "hard"]
    # day 4 = race-2 (moderate -> violation); day 6 = race day itself (allowed)
    plan = make_plan([20, 20, 20, 20, 20, 10, 45], intensities)
    v = validator.check_taper(state, plan)
    quiet = [x for x in v if "non-easy session" in x.message]
    assert len(quiet) == 1
    assert quiet[0].days == ((PLAN_START + timedelta(days=4)).isoformat(),)


def test_compliant_taper_week_is_clean():
    race = PLAN_START + timedelta(days=6)
    state = make_state(daily_load=45, race_date=race)
    plan = make_plan([30, 25, 0, 25, 20, 10, 45],
                     ["easy", "easy", "rest", "easy", "easy", "rest", "hard"])
    # total 155 <= 189; race day itself may be hard
    assert validator.check_taper(state, plan) == []


def test_no_race_no_taper_rules():
    state = make_state(race_date=None)
    plan = make_plan([100] * 7, ["hard"] * 7)
    assert validator.check_taper(state, plan) == []


# ---------------------------------------------------------------- validate()

def test_validate_orders_errors_before_warnings():
    state = make_state(daily_load=45)
    plan = make_plan([90] * 7, ["hard", "hard", "easy", "easy", "easy", "easy", "easy"])
    v = validator.validate(state, plan)
    severities = [x.severity for x in v]
    assert severities == sorted(severities, key=lambda s: s != "error")
    assert len(validator.errors(v)) >= 2   # ramp + spacing (+ acwr)
