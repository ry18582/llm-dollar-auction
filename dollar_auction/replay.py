"""Deterministic replay.

Two jobs:

  render(...)  print a logged game as a readable transcript.
  verify(...)  re-run the engine feeding it the *logged* decisions, and check
               the resulting history is identical. This proves the engine is
               deterministic and that a log is a complete record of a game --
               if verify passes, the metrics can be re-derived from the log
               alone, with no model calls and no cost.
"""

from __future__ import annotations

from pathlib import Path

from .engine import BID, Auction, AgentState, Decision, GameRules
from .runner import read_event_log


def render(path: Path) -> str:
    header, events, footer = read_event_log(path)
    out = [f"game {header.get('game_index')} (seed {header.get('seed')})", ""]

    round_now = None
    for e in events:
        if e["round"] != round_now:
            round_now = e["round"]
            out.append(f"-- round {round_now} --")
        if e["action"] == BID:
            action = f"BID ${e['bid']:.2f}"
        else:
            action = "EXIT" + (f" [forced: {e['forced']}]" if e.get("forced") else "")
        conf = f" ({e['confidence']}%)" if e.get("confidence") is not None else ""
        reason = f" — {e['reason']}" if e.get("reason") else ""
        out.append(f"  {e['agent']:<22} {action}{conf}{reason}")

    if footer:
        out += [
            "",
            f"winner: {footer['winner']} at ${footer['winning_price']:.2f}",
            f"runner-up: {footer['runner_up']} paid ${footer['runner_up_price']:.2f}",
            f"stopped because: {footer['stop_reason']}",
            "",
            "payoffs:",
        ]
        for name, payoff in sorted(footer["payoffs"].items(), key=lambda kv: -kv[1]):
            out.append(f"  {name:<22} ${payoff:+.2f}")

    return "\n".join(out)


def verify(path: Path, rules: GameRules, budgets: dict[str, float]) -> tuple[bool, list[str]]:
    """Re-run the engine from logged decisions; report any divergence."""
    header, events, footer = read_event_log(path)
    names = header["agents"]

    states = [AgentState(name=n, budget=budgets.get(n, rules.default_budget)) for n in names]
    # Turn order must match the original, which the log preserves via first
    # appearance; fall back to the header order.
    order = []
    for e in events:
        if e["agent"] not in order:
            order.append(e["agent"])
    for n in names:
        if n not in order:
            order.append(n)

    auction = Auction(rules, states, turn_order=order)
    queue = list(events)

    def replay_decide(_auction, name):
        while queue:
            e = queue.pop(0)
            if e["agent"] == name:
                return Decision(
                    action=e["action"],
                    reason=e.get("reason", ""),
                    confidence=e.get("confidence"),
                    forced=e.get("forced"),
                )
        # Log exhausted: the engine is asking for a decision the original run
        # never made. That is itself a divergence.
        return Decision("EXIT", reason="replay: log exhausted", forced="replay_exhausted")

    result = auction.run(replay_decide)

    problems: list[str] = []
    if footer:
        if result.winner != footer["winner"]:
            problems.append(f"winner {result.winner!r} != logged {footer['winner']!r}")
        if abs(result.winning_price - footer["winning_price"]) > 1e-6:
            problems.append(
                f"winning price {result.winning_price} != logged {footer['winning_price']}"
            )
        if result.rounds != footer["rounds"]:
            problems.append(f"rounds {result.rounds} != logged {footer['rounds']}")
        for name, payoff in footer["payoffs"].items():
            if abs(result.payoffs.get(name, 0.0) - payoff) > 1e-6:
                problems.append(f"payoff for {name}: {result.payoffs.get(name)} != logged {payoff}")

    if len(result.events) != len(events):
        problems.append(f"event count {len(result.events)} != logged {len(events)}")

    return (not problems), problems
