"""Generate fixtures/athlete_missed_two.json — a runner with 4 weeks of
consistent history who missed her two most recent sessions (long run +
easy run), the classic 'tempted to cram it back in' scenario.

Run: python3 scripts/make_fixture.py
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

PLAN_START = date(2026, 7, 13)  # Monday
WEEK = [  # Mon..Sun: (kind, intensity, load)
    ("rest", "rest", 0.0),
    ("intervals", "moderate", 55.0),
    ("run", "easy", 45.0),
    ("intervals", "hard", 70.0),
    ("run", "easy", 40.0),
    ("long_run", "hard", 90.0),
    ("run", "easy", 50.0),
]
MISSED = {date(2026, 7, 11), date(2026, 7, 12)}  # Sat long run + Sun easy run

history = []
day = PLAN_START - timedelta(days=28)
while day < PLAN_START:
    kind, intensity, load = WEEK[day.weekday()]
    history.append({
        "date": day.isoformat(),
        "kind": kind,
        "intensity": intensity,
        "load": load,
        "status": "missed" if day in MISSED else "completed",
        "note": "missed — work travel" if day in MISSED else "",
    })
    day += timedelta(days=1)

fixture = {
    "athlete": {
        "name": "Maya K.",
        "sport": "running (marathon build)",
        "race_date": "2026-08-16",
        "plan_start": PLAN_START.isoformat(),
        "notes": "Missed the weekend block (work travel). Feels fresh, eager to catch up.",
    },
    "history": history,
}

out = Path(__file__).resolve().parent.parent / "fixtures" / "athlete_missed_two.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(fixture, indent=2) + "\n")
print(f"wrote {out} ({len(history)} history days)")
