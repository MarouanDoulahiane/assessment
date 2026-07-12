# RECON — aitrainingplan.app (fetched 2026-07-12)

Built by Thomas Prommer (CEO, Ironman, software architect). Live in beta, waitlist, Google sign-in. 34 features, all marked "Live".

## What ALREADY ships — do not pitch this back at them

**Training load science is already surfaced.** Real-time CTL/ATL/TSB curves with "ACWR injury risk scoring", mechanical load tracking (running impact vs cardio stress), weekly TSS by sport, "workload monitoring alerts you early". They know Gabbett; they display it.

**Adaptation already exists.** "Adaptive Scheduling — auto-reshuffles missed sessions", sessions "moved to available days rather than being lost", injury management "auto-adjusts training — reducing run load, substituting cross-training", chat-requested changes "applied in real time".

**Multi-model AI is the headline.** "Two AI models debate your data independently, then synthesize one personalized plan." User picks engine (ChatGPT / Claude / Gemini). Disagreements "surface as options for you to review".

**Transparency features exist.** "AI Interactions History — full audit trail of AI decisions and plan changes with reasoning". "Context Manager — control what data and context your AI coaches can access". "AI Prompt Editor — customize coaching personality, style preferences, priority rules."

**Integration stack is done.** Garmin, Strava, Intervals.icu, Apple Health, Zwift, blood panels, HRV/sleep. Plus nutrition periodization, race prediction, FTP/CSS/lactate testing.

## The seams (from /how-it-works/)

The pipeline is literally: **"Raw data is cleaned, normalized, and compressed into an AI-ready prompt" → "Run prompt" (manually or automatically) → "Get training plan."**

1. **The LLM is the planner, not a proposer.** Whatever the model emits becomes the plan. ACWR exists as *monitoring and alerts* — a dashboard the athlete watches — not as a gate the plan must pass before it reaches the calendar.
2. **Safety rules live in prompts, and they're user-editable.** The Prompt Editor exposes "priority rules" to the athlete. Any guardrail expressed in a prompt can be diluted, contradicted, or deleted by the person it protects — the injured-but-motivated athlete is exactly who will do it.
3. **Multi-model consensus is a second opinion, not verification.** Two LLMs agreeing is correlated error, not a check. And when they disagree, adjudication is punted to the athlete — the least qualified party on load management.
4. **Adaptation is trigger-and-trust.** "Run prompt" fires, plan replaces plan. No visible re-validation step between an adaptation and the calendar.

## 3 gaps a senior agentic engineer attacks

**1. Deterministic enforcement layer between the LLM and the calendar.**
Evidence: ACWR is scored and displayed, never enforced; priority rules are prompt-text. Build: a validator module — ACWR band, weekly ramp cap, taper constraints, hard-day spacing — as pure functions with unit tests. LLM proposes 7 days; validator disposes; violations feed back for bounded retry; rules-only fallback + human-review flag if the model can't comply. Safety becomes a property of code, not of prompt phrasing or model choice. *(This is the scaffold in this repo.)*

**2. Eval harness for coaching quality — every prompt edit is an untested deploy.**
Evidence: users edit coaching prompts and swap engines freely; "debate" is vibes-consensus with no ground truth. Build: golden athlete fixtures (post-injury, pre-race taper, overreached, beginner) + property tests ("no generated plan ever leaves the ACWR band", "taper week never ramps") run against every prompt template change and model version bump. The validator from gap 1 doubles as the eval oracle, so this is cheap once gap 1 exists.

**3. Event-driven agency with bounded authority.**
Evidence: adaptation is user-triggered ("run prompt", chat requests); the athlete is the event loop. Build: webhooks (Garmin sync shows missed session, HRV crash, illness flag) drive a perception→propose→validate→act loop that auto-applies changes *inside* the safety envelope and escalates to the athlete with a diff + reasoning when outside it. Their existing "AI Interactions History" is the natural sink for machine-checkable decision traces — extend it, don't replace it.

**Positioning line:** they've built the data plane and the prompt plane; the missing piece is a *control plane* — deterministic validation, evals, and bounded autonomy. That's the agentic-engineering job.
