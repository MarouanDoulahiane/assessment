"""Core domain types. Frozen dataclasses, JSON in/out, no behavior."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

INTENSITIES = ("rest", "easy", "moderate", "hard")


@dataclass(frozen=True)
class Session:
    day: date
    kind: str          # run | long_run | intervals | rest | race ...
    intensity: str     # rest | easy | moderate | hard
    load: float        # sRPE-style load units; the *planned* load
    status: str = "planned"   # history: completed | missed; plan: planned
    note: str = ""

    @property
    def effective_load(self) -> float:
        """Load that actually counts toward training stress."""
        if self.status == "missed" or self.intensity == "rest":
            return 0.0
        return self.load


@dataclass(frozen=True)
class AthleteState:
    name: str
    sport: str
    race_date: date | None
    plan_start: date          # first day of the week to plan
    history: tuple[Session, ...]   # chronological, ends the day before plan_start
    notes: str = ""


@dataclass(frozen=True)
class Proposal:
    days: tuple[Session, ...]      # exactly 7, consecutive, starting at plan_start
    rationale: str
    source: str                    # "llm" | "scripted" | "fallback"


@dataclass(frozen=True)
class Violation:
    rule: str        # acwr_band | weekly_ramp | hard_day_spacing | taper
    severity: str    # "error" blocks the plan; "warning" is recorded only
    message: str
    observed: float | None = None
    limit: float | None = None
    days: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "observed": self.observed,
            "limit": self.limit,
            "days": list(self.days),
        }


def session_to_dict(s: Session) -> dict:
    return {
        "date": s.day.isoformat(),
        "kind": s.kind,
        "intensity": s.intensity,
        "load": s.load,
        "status": s.status,
        "note": s.note,
    }


def session_from_dict(d: dict) -> Session:
    return Session(
        day=date.fromisoformat(d["date"]),
        kind=d["kind"],
        intensity=d["intensity"],
        load=float(d["load"]),
        status=d.get("status", "planned"),
        note=d.get("note", ""),
    )


def load_state(path: str | Path) -> AthleteState:
    raw = json.loads(Path(path).read_text())
    a = raw["athlete"]
    return AthleteState(
        name=a["name"],
        sport=a["sport"],
        race_date=date.fromisoformat(a["race_date"]) if a.get("race_date") else None,
        plan_start=date.fromisoformat(a["plan_start"]),
        history=tuple(sorted((session_from_dict(s) for s in raw["history"]), key=lambda s: s.day)),
        notes=a.get("notes", ""),
    )
