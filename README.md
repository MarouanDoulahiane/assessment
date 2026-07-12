# Weekly Plan Adaptation — LLM proposes, deterministic code disposes

A multi-step agentic workflow for adapting an endurance athlete's next 7 days
of training. Built as a working demonstration of one architectural claim:

> **Training-load safety rules do not belong in prompts.** They live in
> [`coach/validator.py`](coach/validator.py) as pure functions with unit
> tests. The LLM can propose anything; only plans that pass the validator
> reach the athlete's calendar.

## Run it

```bash
make demo            # athlete who missed 2 sessions; LLM overreaches, gets rejected, retry passes
make demo-fallback   # proposer never complies -> rules-only plan + human-review flag
make test            # 28 unit tests, stdlib + pytest only
make demo-live       # optional: real Claude proposer (pip install anthropic + ANTHROPIC_API_KEY)
```

No dependencies beyond Python 3.10+ and pytest. The default demo uses a
scripted proposer so the loop is reproducible offline; the LLM is a
swappable component behind a 1-method protocol (`propose(state, feedback)`).

## The loop

```
gather athlete state
      │
      ▼
LLM proposes next 7 days ◄──────────┐
      │                             │ violations as structured JSON
      ▼                             │ (max 2 retries)
validator scores plan ── errors ────┘
      │                             │ still failing
      ▼ no errors                   ▼
plan accepted                rules-only fallback plan
                             + needs_human_review flag
```

Every step emits a structured trace event (`state_gathered`, `proposal`,
`validation`, `feedback`, `fallback`, `final`) — printed human-readable and
written to `trace.json`, including the projected ACWR trajectory of the
accepted plan.

## Safety rules (validator.py — pure, tested, never in a prompt)

| Rule | Constraint | Severity |
|---|---|---|
| `acwr_band` | projected acute:chronic workload ratio ≤ 1.30 (7d/28d rolling means) | error |
| `acwr_band` | ACWR ≥ 0.80 | **warning** — see below |
| `weekly_ramp` | week total ≤ +10% vs reference week (max of last week, 28-day avg) | error |
| `hard_day_spacing` | ≥ 48h between hard sessions, incl. boundary with history | error |
| `taper` | inside 14 days of race: week ≤ 60% chronic; race−1/−2 easy or rest | error |

Severity is asymmetric on purpose: after missed sessions **no legal plan can
instantly restore ACWR without breaching the ramp cap** — undertraining is a
recorded warning, overload is a hard stop. That tension is exactly why the
rules must be deterministic code: an LLM asked to "fix the low ACWR" will
happily violate the ramp cap to do it.

## Design decisions I'd defend

- **Validator as pure functions** — deterministic, unit-testable, immune to
  prompt injection and prompt drift, and reusable as the oracle for an eval
  harness over prompt/model changes.
- **Bounded retries with structured feedback** — the LLM gets machine-readable
  violations (rule, observed, limit, offending days), not prose. Two retries,
  then stop: unbounded LLM loops are a cost and latency liability.
- **Deterministic fallback + human flag** — the system degrades to a
  conservative rules-only week, never to "ship the unsafe plan" or "ship
  nothing". `needs_human_review` makes the escalation explicit.
- **Trust boundaries** — the orchestrator re-derives dates from its own
  calendar rather than trusting model-emitted date strings; the real LLM
  proposer forces a strict-schema tool call (`tool_choice`), so output is
  validated JSON, not parsed prose.

## Layout

```
coach/
  models.py        frozen dataclasses, JSON I/O
  metrics.py       ACWR + load math (pure)
  validator.py     the safety rules (pure)  <- the point of the repo
  proposer.py      Proposer protocol: scripted (offline) + Anthropic (live)
  fallback.py      rules-only plan generator
  orchestrator.py  propose -> validate -> retry -> fallback loop + trace
  demo.py          CLI rendering of the trace
fixtures/          athlete with 4 weeks history, 2 missed sessions
scripts/           fixture generator (deterministic)
tests/             metrics, each rule, and all three loop outcomes
```
