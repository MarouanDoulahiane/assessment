from datetime import date, timedelta

from coach import metrics
from coach.models import Proposal, Session


def _sessions(start: date, loads: list[float], status: str = "completed") -> list[Session]:
    return [
        Session(day=start + timedelta(days=i), kind="run",
                intensity="easy" if load else "rest", load=load, status=status)
        for i, load in enumerate(loads)
    ]


def test_missed_sessions_contribute_zero_load():
    day = date(2026, 7, 1)
    completed = Session(day=day, kind="run", intensity="easy", load=50, status="completed")
    missed = Session(day=day + timedelta(days=1), kind="run", intensity="easy", load=50, status="missed")
    loads = metrics.daily_loads([completed, missed])
    assert loads[completed.day] == 50
    assert loads[missed.day] == 0


def test_window_total_inclusive_bounds():
    start = date(2026, 7, 1)
    loads = metrics.daily_loads(_sessions(start, [10] * 10))
    # 7-day window ending day 6 covers days 0..6
    assert metrics.window_total(loads, start + timedelta(days=6), 7) == 70


def test_acwr_none_without_chronic_base():
    assert metrics.acwr({}, date(2026, 7, 1)) is None


def test_acwr_steady_load_is_one():
    start = date(2026, 6, 1)
    loads = metrics.daily_loads(_sessions(start, [40] * 28))
    ratio = metrics.acwr(loads, start + timedelta(days=27))
    assert abs(ratio - 1.0) < 1e-9


def test_acwr_trajectory_covers_every_plan_day():
    start = date(2026, 6, 15)
    history = _sessions(start, [40] * 28)
    plan = Proposal(
        days=tuple(_sessions(start + timedelta(days=28), [40] * 7, status="planned")),
        rationale="", source="scripted",
    )
    traj = metrics.acwr_trajectory(history, plan)
    assert len(traj) == 7
    assert all(r is not None for _, r in traj)


def test_reference_weekly_uses_max_of_last_week_and_chronic():
    start = date(2026, 6, 15)
    plan_start = start + timedelta(days=28)
    # 3 normal weeks at 280, then a depressed week at 70
    loads = [40] * 21 + [10] * 7
    history = _sessions(start, loads)
    ref = metrics.reference_weekly_load(history, plan_start)
    # last week total = 70; chronic weekly = (3*280 + 70)/4 = 227.5 -> use chronic
    assert ref == 227.5
