# CLAUDE.md — dollar-auction

Multi-agent dollar auction simulator: LLM agents with distinct trait profiles bid
in an auction where the top *two* bidders both pay. Purpose is measuring
escalation and sunk-cost behaviour, not winning.

## Commands

    python3 -m dollar_auction run configs/experiments/mvp_mock.json
    python3 -m dollar_auction replay [run] [--game N]
    python3 -m dollar_auction verify [run]      # replay determinism check
    python3 -m dollar_auction report [run]      # rebuild report.md
    python3 -m dollar_auction gui [--port N] [--host H] [--no-browser]
        omit --port and it asks, showing which ports are free
    python3 -m dollar_auction doctor            # verify API keys work
    python3 -m dollar_auction list
    python3 -m unittest discover -s tests

`run` defaults to the latest under `runs/`.

## Architecture

- `engine.py` — pure auction rules. Takes a `decide(auction, name) -> Decision`
  callable; knows nothing about LLMs. This separation is what makes replay work.
- `providers/` — one interface, `complete(system, user) -> Completion`. Adapters:
  `mock` (scripted, seeded), `anthropic`, `openai`, `google`, and `cli` — which
  shells out to an official provider CLI (claude/gemini/codex) so a subscription
  or account sign-in works without an API key. `cli` reports no token counts.
- `agents.py` — the only place model text becomes a typed action.
- `prompts.py` — system / round / reflection prompts. The round prompt embeds
  state as JSON in `<state>...</state>`; the mock parses it, so scripted and
  real agents see the identical prompt.
- `memory.py` — two independent switches: within-game notes (cleared each
  auction) and cross-game history (persists across repeats). Memory objects are
  built once in `runner.run_experiment` and outlive individual games.
- `server.py` + `gui/index.html` — local web GUI, stdlib `http.server`, polling
  (not SSE). `Auction(observer=...)` is what streams events to it. The intro text
  is a single `<details id="intro">` block at the top of the HTML — it is the
  owner's framing of the project, so edit the wording only when asked.
- `turnorder.py` — seat policy (rotate/fixed/shuffle). Uses a SHA-256 seed, not
  `hash()`, which is per-process randomized and would break replay.
- `docs/agent-policies.md` — the scripted policy in full + provenance of the
  trait and MBTI numbers. Keep it honest; it is the anti-overclaim document.
- `metrics.py`, `report.py`, `plot.py`, `replay.py`, `runner.py`, `config.py`.

## Constraints

- **Stdlib only, by design.** Raw `urllib` for HTTP, JSON not YAML, hand-written
  SVG not matplotlib. The project installs nowhere and runs anywhere Python does.
  Do not add a dependency.
- **Anthropic API:** never send `temperature`, `top_p`, `top_k`, or
  `thinking.budget_tokens` — all return 400 on Opus 4.8 / Sonnet 5. Model IDs
  (`claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5`) are complete as
  written; never append a date suffix.
- Every engine override (budget, bid cap, parse failure, provider error) must be
  logged with `forced` set. A forced action must never look like an agent choice.
- `runs/` is gitignored — it is output, not source.
- A failed provider call becomes a forced EXIT, so a bad key produces a run that
  *looks* finished. `doctor` exists to catch that before money is spent; keep it
  working and point people at it.
- Switching provider in an experiment override REPLACES the agent's model block
  rather than merging it. A model name is meaningless across providers — merging
  once passed `--model mock` to the Claude CLI.
- Never print an API key. `doctor` prints only its shape (prefix…suffix + length).

## Gotchas

- Chart colour: never cycle a categorical palette past its slots. With 16 agents
  the GUI uses emphasis encoding — the two who pay carry hues, everyone else is
  a recessive neutral — not 16 cycled colours.

- The mock's sunk-cost stretch coefficient is deliberately < 1. At >= 1 the
  walk-away threshold outruns the committed total and agents bid to the budget
  cap every game — a degenerate run.
- The GUI binds to 127.0.0.1 with no auth, and a live provider spends real money
  per bid. Do not add a `--host` flag that defaults to anything else.
- Memory must stay private per agent — an agent may recall the public price
  record and its own experience, never a rival's reasoning.
- "First irrational bid" means the first bid *above item value*, not the point
  where expected value turns negative. The latter almost never fires; see the
  `metrics.py` docstring.
