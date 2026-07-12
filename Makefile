.PHONY: demo demo-fallback demo-live test fixture

# Full adaptation trace: LLM overreaches, validator rejects, retry passes.
demo:
	python3 -m coach.demo fixtures/athlete_missed_two.json

# Proposer never complies -> rules-only fallback + human-review flag.
demo-fallback:
	python3 -m coach.demo fixtures/athlete_missed_two.json --proposer stubborn

# Real Claude proposer (requires `pip install anthropic` + ANTHROPIC_API_KEY).
demo-live:
	python3 -m coach.demo fixtures/athlete_missed_two.json --proposer anthropic

test:
	python3 -m pytest tests/ -q

# Regenerate the fixture from scripts/make_fixture.py
fixture:
	python3 scripts/make_fixture.py
