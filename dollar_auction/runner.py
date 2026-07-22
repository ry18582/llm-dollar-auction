"""Run orchestration: config in, run directory out.

A run directory is the unit of reproducibility:

    runs/<run_id>/
      manifest.json     experiment, resolved rules, agent configs, seed
      game_000.jsonl    one JSON object per event, append-only
      metrics.json      per-game + aggregate metrics
      report.md         human-readable summary
      escalation.svg    bid-by-round chart
      payoffs.svg       final payoff chart

Everything needed to re-derive the numbers is in the directory. Nothing needed
to re-derive them lives only in memory.
"""

from __future__ import annotations

import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .agents import build_agents
from .config import CONFIG_DIR, REPO_ROOT, load_experiment, load_roster, rules_from
from .engine import AgentState, Auction, GameResult
from .memory import GameRecall, MemoryConfig, build_memories
from .turnorder import order_for_game
from .metrics import aggregate, game_metrics

RUNS_DIR = REPO_ROOT / "runs"


def run_experiment(
    experiment_path: str | dict,
    *,
    runs_dir: Path | None = None,
    quiet: bool = False,
    observer=None,
    on_ready=None,
) -> Path:
    exp = experiment_path if isinstance(experiment_path, dict) else load_experiment(experiment_path)
    rules = rules_from(exp)
    agent_configs = load_roster(exp["roster"], exp["agents"], exp.get("overrides", {}))

    runs_dir = runs_dir or RUNS_DIR
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = runs_dir / f"{stamp}_{exp['name']}"
    run_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "run_id": run_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "experiment": exp,
        "rules": rules.__dict__,
        "agents": agent_configs,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    # Memory objects outlive individual games -- that is the whole point of
    # the cross-game switch -- so they are built once, here.
    mem_cfg = MemoryConfig.from_dict(exp.get("memory"))
    memories = build_memories([c["name"] for c in agent_configs], config=mem_cfg)
    # Hand the live memory objects out so a GUI can wipe them mid-run.
    if on_ready is not None:
        on_ready(memories)

    games = []
    for game_index in range(int(exp["repeats"])):
        seed = int(exp["seed"]) + game_index
        if observer is not None:
            observer({"type": "game_start", "game_index": game_index, "seed": seed})

        result = play_one_game(
            agent_configs,
            rules,
            seed=seed,
            memories=memories,
            observer=observer,
            turn_order=exp.get("turn_order", "rotate"),
            game_index=game_index,
        )
        wipes = [w for m in memories.values() for w in m.wipes
                 if w["game_index"] == game_index]
        _remember(result, rules, memories, game_index)
        _check_provider_health(result, game_index)

        log_path = run_dir / f"game_{game_index:03d}.jsonl"
        write_event_log(log_path, result, game_index=game_index, seed=seed, wipes=wipes)

        m = game_metrics(result, rules)
        m["game_index"] = game_index
        m["seed"] = seed
        games.append(m)

        if observer is not None:
            observer({"type": "game_end", "game_index": game_index, **{
                k: m[k] for k in ("winner", "winning_price", "runner_up",
                                  "runner_up_price", "rounds", "escalation_ratio")
            }, "payoffs": result.payoffs})

        if not quiet:
            print(
                f"  game {game_index}: {m['winner']} won at ${m['winning_price']:.2f} "
                f"({m['escalation_ratio']:.2f}x value, {m['rounds']} rounds)"
            )

    metrics = {"games": games, "aggregate": aggregate(games)}
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

    # Written here rather than by a separate command so a run directory is
    # never half-finished.
    from .plot import write_charts
    from .report import write_report

    write_report(run_dir, manifest, metrics)
    write_charts(run_dir, run_dir.glob("game_*.jsonl"), rules)

    return run_dir


def play_one_game(
    agent_configs: list[dict],
    rules,
    *,
    seed: int,
    memories=None,
    observer=None,
    turn_order: str = "rotate",
    game_index: int = 0,
) -> GameResult:
    memories = memories or {}
    for mem in memories.values():
        mem.start_game()

    agents = build_agents(
        agent_configs, rules.__dict__, seed=seed, memories=memories, game_index=game_index
    )
    states = [
        AgentState(name=c["name"], budget=float(c.get("budget", rules.default_budget)))
        for c in agent_configs
    ]

    def on_event(event):
        if observer is not None:
            observer({"type": "event", **event.to_dict()})

    order = order_for_game(
        [c["name"] for c in agent_configs],
        policy=turn_order,
        game_index=game_index,
        seed=seed,
    )
    auction = Auction(
        rules, states, turn_order=order, observer=on_event if observer else None
    )

    def decide(auction_, name):
        return agents[name].decide(auction_, name)

    return auction.run(decide)


class ProviderFailure(RuntimeError):
    """Raised when a game was decided by provider errors rather than agents."""


def _check_provider_health(result: GameResult, game_index: int) -> None:
    """Refuse to pass off a broken run as an experiment.

    A failed API call becomes a forced EXIT, so a game with a dead key or an
    exhausted quota still *finishes* -- every agent quits on turn one and the
    report looks superficially normal. That is the worst kind of failure: it
    produces data that is indistinguishable from a result unless you read the
    forced-action count. So it stops here instead.
    """
    errored = [e for e in result.events if e.forced == "provider_error"]
    if not errored:
        return

    total = len(result.events)
    detail = errored[0].error or "no detail"
    summary = (
        f"game {game_index}: {len(errored)} of {total} decisions failed at the "
        f"provider, so the result is an artefact of the failure, not of the agents.\n"
        f"  first error: {detail[:400]}"
    )
    # Any provider error at all invalidates the affected decisions; a majority
    # invalidates the whole game.
    if len(errored) * 2 >= total:
        raise ProviderFailure(
            summary + "\n\nRun `python3 -m dollar_auction doctor` to check credentials "
            "and quota before retrying."
        )
    print(f"  WARNING — {summary}")


def _remember(result: GameResult, rules, memories: dict, game_index: int) -> None:
    """Hand each agent what it is allowed to carry into the next auction."""
    escalators = [
        name
        for name, state in result.agents.items()
        if state.committed > rules.item_value
    ]
    for name, mem in memories.items():
        state = result.agents.get(name)
        if state is None:
            continue
        mem.record_game(
            GameRecall(
                game_index=game_index,
                item_value=rules.item_value,
                final_price=result.winning_price,
                my_committed=state.committed,
                my_payoff=result.payoffs.get(name, 0.0),
                won=(result.winner == name),
                escalators=[e for e in escalators if e != name],
            )
        )


def write_event_log(
    path: Path, result: GameResult, *, game_index: int, seed: int, wipes=None
) -> None:
    with path.open("w") as fh:
        header = {
            "type": "game_start",
            "game_index": game_index,
            "seed": seed,
            "agents": sorted(result.agents),
        }
        fh.write(json.dumps(header) + "\n")
        for event in result.events:
            fh.write(json.dumps({"type": "event", **event.to_dict()}) + "\n")
        # Wipes are part of the record: a run where an agent silently stopped
        # remembering would be uninterpretable afterwards.
        for wipe in wipes or []:
            fh.write(json.dumps(wipe) + "\n")
        footer = {
            "type": "game_end",
            "winner": result.winner,
            "winning_price": result.winning_price,
            "runner_up": result.runner_up,
            "runner_up_price": result.runner_up_price,
            "rounds": result.rounds,
            "stop_reason": result.stop_reason,
            "payoffs": result.payoffs,
        }
        fh.write(json.dumps(footer) + "\n")


def read_event_log(path: Path) -> tuple[dict, list[dict], dict]:
    header: dict = {}
    events: list[dict] = []
    footer: dict = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        kind = row.get("type")
        if kind == "game_start":
            header = row
        elif kind == "event":
            events.append(row)
        elif kind == "game_end":
            footer = row
    return header, events, footer
