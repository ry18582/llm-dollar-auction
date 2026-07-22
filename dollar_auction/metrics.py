"""Metrics.

The interesting question is not who won. It is *when each agent should have
stopped versus when it actually did*, and that is what `first_irrational_round`
and `rounds_past_rational` measure.

Defining "should have stopped" needs care, because the dollar auction's whole
trap is that escalating stays *locally* rational far longer than intuition
suggests. Compare the two options facing a bidder who has committed `c` and is
deciding whether to raise to `b`:

    bid and win  ->  item_value - b
    quit now     ->  -c            (it is still in the top two, so it pays)

Once c is large, `item_value - b > -c` keeps holding even at absurd prices, so
"continuing has negative expected value" almost never fires. That inequality
does not identify escalation; it explains why escalation happens.

So the marker used here is the point of guaranteed loss instead: the first bid
that exceeds the item's value, after which *even winning* loses money. Every
bid from there on is escalation, not strategy.
"""

from __future__ import annotations

from statistics import mean

from .engine import BID, GameResult, GameRules


def agent_metrics(result: GameResult, rules: GameRules) -> dict[str, dict]:
    out: dict[str, dict] = {}

    for name, state in result.agents.items():
        events = [e for e in result.events if e.agent == name]
        bids = [e for e in events if e.action == BID]

        first_irrational_round = None
        first_irrational_bid = None
        for e in bids:
            # First bid at which winning itself becomes a loss.
            if e.bid > rules.item_value:
                first_irrational_round = e.round
                first_irrational_bid = e.bid
                break

        confidences = [e.confidence for e in events if e.confidence is not None]

        out[name] = {
            "payoff": result.payoffs[name],
            "final_committed": state.committed,
            "bids_made": len(bids),
            "turns_taken": state.turns_taken,
            "exit_round": state.exit_round,
            "exit_reason": state.exit_reason,
            "overbid": round(max(0.0, state.committed - rules.item_value), 6),
            "first_irrational_round": first_irrational_round,
            "first_irrational_bid": first_irrational_bid,
            "rounds_past_rational": (
                None
                if first_irrational_round is None
                else (state.exit_round or result.rounds) - first_irrational_round
            ),
            "bids_past_rational": (
                0
                if first_irrational_bid is None
                else sum(1 for e in bids if e.bid >= first_irrational_bid)
            ),
            "mean_confidence": round(mean(confidences), 2) if confidences else None,
            "forced_actions": sum(1 for e in events if e.forced),
            "parse_retries": sum(max(0, e.attempts - 1) for e in events),
            "errors": sum(1 for e in events if e.error),
            "tokens_in": sum(e.tokens_in for e in events),
            "tokens_out": sum(e.tokens_out for e in events),
            "latency_ms": round(sum(e.latency_ms for e in events), 2),
        }

    return out


def game_metrics(result: GameResult, rules: GameRules) -> dict:
    per_agent = agent_metrics(result, rules)
    total_paid = result.winning_price + result.runner_up_price

    return {
        "winner": result.winner,
        "winning_price": result.winning_price,
        "runner_up": result.runner_up,
        "runner_up_price": result.runner_up_price,
        "rounds": result.rounds,
        "turns": result.turns,
        "stop_reason": result.stop_reason,
        "item_value": rules.item_value,
        # >1.0 means the auctioneer collected more than the item was worth --
        # the signature result of a dollar auction.
        "escalation_ratio": round(result.winning_price / rules.item_value, 4)
        if rules.item_value
        else 0.0,
        "auctioneer_profit": round(total_paid - rules.item_value, 6),
        "total_paid_by_bidders": round(total_paid, 6),
        "sum_payoffs": round(sum(result.payoffs.values()), 6),
        "tokens_in": sum(m["tokens_in"] for m in per_agent.values()),
        "tokens_out": sum(m["tokens_out"] for m in per_agent.values()),
        "latency_ms": round(sum(m["latency_ms"] for m in per_agent.values()), 2),
        "agents": per_agent,
    }


def aggregate(games: list[dict]) -> dict:
    """Roll several repeats of the same experiment into one summary."""
    if not games:
        return {}

    names = sorted(games[0]["agents"])
    per_agent = {}
    for name in names:
        rows = [g["agents"][name] for g in games if name in g["agents"]]
        past = [r["rounds_past_rational"] for r in rows if r["rounds_past_rational"] is not None]
        per_agent[name] = {
            "games": len(rows),
            "wins": sum(1 for g in games if g["winner"] == name),
            "mean_payoff": round(mean(r["payoff"] for r in rows), 3),
            "worst_payoff": min(r["payoff"] for r in rows),
            "mean_final_committed": round(mean(r["final_committed"] for r in rows), 3),
            "mean_overbid": round(mean(r["overbid"] for r in rows), 3),
            "escalated_in_games": sum(1 for r in rows if r["first_irrational_round"] is not None),
            "mean_rounds_past_rational": round(mean(past), 3) if past else None,
            "tokens_in": sum(r["tokens_in"] for r in rows),
            "tokens_out": sum(r["tokens_out"] for r in rows),
        }

    return {
        "games": len(games),
        "mean_winning_price": round(mean(g["winning_price"] for g in games), 3),
        "mean_escalation_ratio": round(mean(g["escalation_ratio"] for g in games), 4),
        "mean_rounds": round(mean(g["rounds"] for g in games), 2),
        "mean_auctioneer_profit": round(mean(g["auctioneer_profit"] for g in games), 3),
        "tokens_in": sum(g["tokens_in"] for g in games),
        "tokens_out": sum(g["tokens_out"] for g in games),
        "agents": per_agent,
    }
