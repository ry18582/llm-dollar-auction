"""Dollar auction game engine.

Pure rules + state. Knows nothing about LLMs: it asks a callable for a decision
and applies it. That separation is what makes deterministic replay possible --
swap the callable for one that reads a log and the engine produces the same
history, bit for bit.

Rules (canonical, see configs/experiments/*.json to override):
  - One item with nominal value V is auctioned.
  - Highest bidder wins the item and pays their bid.
  - Second-highest bidder ALSO pays their bid and receives nothing.
  - Everyone else pays nothing.
  - Turn order is round-robin over still-active agents.
  - On your turn you either BID (raise the standing bid by exactly one
    increment) or EXIT (permanent, no re-entry).
  - You are skipped when you already hold the standing high bid: nobody bids
    against themselves.
  - The game ends when at most one agent is still active, when every active
    non-leading agent has exited, or when a safety cap trips.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

BID = "BID"
EXIT = "EXIT"


@dataclass
class Decision:
    """What an agent chose on one turn, plus how it got there."""

    action: str  # BID | EXIT
    reason: str = ""
    confidence: Optional[int] = None
    raw: str = ""
    forced: Optional[str] = None  # set when the engine overrode the agent
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    attempts: int = 1
    error: Optional[str] = None


@dataclass
class AgentState:
    """Per-agent mutable state for one game."""

    name: str
    budget: float
    active: bool = True
    committed: float = 0.0  # their standing (last) bid; what they owe if top-2
    bids: list[float] = field(default_factory=list)
    exit_round: Optional[int] = None
    exit_reason: Optional[str] = None  # chose | broke | invalid
    turns_taken: int = 0


@dataclass
class Event:
    """One entry in the append-only game log."""

    round: int
    turn: int
    agent: str
    action: str
    bid: Optional[float]
    standing_bid: float
    standing_bidder: Optional[str]
    active_agents: list[str]
    reason: str = ""
    confidence: Optional[int] = None
    forced: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    attempts: int = 1
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class GameRules:
    item_value: float = 100.0
    increment: float = 5.0
    default_budget: float = 500.0
    max_rounds: int = 60
    # Hard stop so a runaway escalation cannot bill you forever. Expressed as a
    # multiple of item_value; None disables it.
    max_bid_multiple: Optional[float] = 5.0

    @property
    def max_bid(self) -> Optional[float]:
        if self.max_bid_multiple is None:
            return None
        return self.item_value * self.max_bid_multiple


@dataclass
class GameResult:
    winner: Optional[str]
    winning_price: float
    runner_up: Optional[str]
    runner_up_price: float
    rounds: int
    turns: int
    payoffs: dict[str, float]
    agents: dict[str, AgentState]
    events: list[Event]
    stop_reason: str


class Auction:
    """Runs one dollar auction to completion."""

    def __init__(
        self,
        rules: GameRules,
        agents: list[AgentState],
        turn_order: Optional[list[str]] = None,
        observer: Optional[Callable[[Event], None]] = None,
    ):
        if len(agents) < 2:
            raise ValueError("a dollar auction needs at least 2 agents")
        self.rules = rules
        # Called on every logged event; the GUI streams from this.
        self.observer = observer
        self.agents: dict[str, AgentState] = {a.name: a for a in agents}
        if len(self.agents) != len(agents):
            raise ValueError("agent names must be unique")
        self.order: list[str] = turn_order or [a.name for a in agents]
        if set(self.order) != set(self.agents):
            raise ValueError("turn_order must cover exactly the agent set")
        self.standing_bid: float = 0.0
        self.standing_bidder: Optional[str] = None
        self.events: list[Event] = []
        self.round: int = 0
        self.turn: int = 0

    # -- queries the decision callable is given ---------------------------

    @property
    def active_names(self) -> list[str]:
        return [n for n in self.order if self.agents[n].active]

    def next_bid(self) -> float:
        return round(self.standing_bid + self.rules.increment, 6)

    def can_afford(self, name: str) -> bool:
        return self.next_bid() <= self.agents[name].budget + 1e-9

    def state_snapshot(self, viewer: Optional[str] = None) -> dict:
        """Public game state, plus the viewer's private position if named.

        Every agent sees the standing bid, who holds it, who is still in, and
        its own exposure. Nobody sees another agent's budget or reasoning.
        """
        snap = {
            "round": self.round,
            "item_value": self.rules.item_value,
            "increment": self.rules.increment,
            "standing_bid": self.standing_bid,
            "standing_bidder": self.standing_bidder,
            "next_bid": self.next_bid(),
            "active_agents": self.active_names,
            "exited_agents": [n for n in self.order if not self.agents[n].active],
            "bid_history": [
                {"agent": e.agent, "bid": e.bid}
                for e in self.events
                if e.action == BID
            ],
        }
        if viewer is not None:
            a = self.agents[viewer]
            snap["you"] = {
                "name": a.name,
                "budget": a.budget,
                "committed": a.committed,
                "budget_remaining": round(a.budget - self.next_bid(), 6),
                "is_standing_bidder": self.standing_bidder == a.name,
                "payoff_if_you_exit_now": self._payoff_if_exit(viewer),
                "payoff_if_you_bid_and_win": round(self.rules.item_value - self.next_bid(), 6),
            }
        return snap

    def _payoff_if_exit(self, name: str) -> float:
        """What this agent nets by exiting right now.

        It pays its standing bid only if it would end up in the top two, which
        for a live bidder that just got outbid means: yes, it pays.
        """
        a = self.agents[name]
        if a.committed <= 0:
            return 0.0
        others = sorted(
            (x.committed for n, x in self.agents.items() if n != name),
            reverse=True,
        )
        # It pays iff at most one other agent has bid strictly higher.
        higher = sum(1 for c in others if c > a.committed)
        return round(-a.committed if higher <= 1 else 0.0, 6)

    # -- the loop ---------------------------------------------------------

    def run(self, decide: Callable[["Auction", str], Decision]) -> GameResult:
        """`decide(auction, agent_name) -> Decision` drives every turn."""
        stop_reason = "resolved"

        while True:
            if len(self.active_names) <= 1:
                stop_reason = "one_bidder_left"
                break
            if self.round >= self.rules.max_rounds:
                stop_reason = "max_rounds"
                break

            self.round += 1
            acted_this_round = False

            for name in list(self.order):
                agent = self.agents[name]
                if not agent.active:
                    continue
                # Nobody bids against themselves.
                if self.standing_bidder == name:
                    continue
                if len(self.active_names) <= 1:
                    break

                self.turn += 1
                agent.turns_taken += 1
                acted_this_round = True

                cap = self.rules.max_bid
                if cap is not None and self.next_bid() > cap:
                    self._apply_exit(agent, Decision(EXIT, "bid cap reached", forced="cap"), "broke")
                    continue
                if not self.can_afford(name):
                    self._apply_exit(agent, Decision(EXIT, "cannot afford next bid", forced="budget"), "broke")
                    continue

                decision = decide(self, name)
                if decision.action == BID and not self.can_afford(name):
                    decision = Decision(EXIT, "bid rejected: over budget", forced="budget", raw=decision.raw)
                if decision.action == BID:
                    self._apply_bid(agent, decision)
                else:
                    self._apply_exit(agent, decision, "chose" if decision.forced is None else "broke")

            if not acted_this_round:
                # Everyone still in either holds the high bid or has exited.
                stop_reason = "no_challengers"
                break

        return self._result(stop_reason)

    def _apply_bid(self, agent: AgentState, d: Decision) -> None:
        bid = self.next_bid()
        agent.committed = bid
        agent.bids.append(bid)
        self.standing_bid = bid
        self.standing_bidder = agent.name
        self._log(agent.name, BID, bid, d)

    def _apply_exit(self, agent: AgentState, d: Decision, reason: str) -> None:
        agent.active = False
        agent.exit_round = self.round
        agent.exit_reason = reason
        self._log(agent.name, EXIT, None, d)

    def _log(self, name: str, action: str, bid: Optional[float], d: Decision) -> None:
        event = Event(
                round=self.round,
                turn=self.turn,
                agent=name,
                action=action,
                bid=bid,
                standing_bid=self.standing_bid,
                standing_bidder=self.standing_bidder,
                active_agents=self.active_names,
                reason=d.reason,
                confidence=d.confidence,
                forced=d.forced,
                tokens_in=d.tokens_in,
                tokens_out=d.tokens_out,
                latency_ms=d.latency_ms,
                attempts=d.attempts,
                error=d.error,
        )
        self.events.append(event)
        if self.observer is not None:
            self.observer(event)

    def _result(self, stop_reason: str) -> GameResult:
        ranked = sorted(self.agents.values(), key=lambda a: a.committed, reverse=True)
        winner = ranked[0] if ranked[0].committed > 0 else None
        runner_up = ranked[1] if len(ranked) > 1 and ranked[1].committed > 0 else None

        payoffs: dict[str, float] = {}
        for name, a in self.agents.items():
            if winner is not None and name == winner.name:
                payoffs[name] = round(self.rules.item_value - a.committed, 6)
            elif runner_up is not None and name == runner_up.name:
                payoffs[name] = round(-a.committed, 6)
            else:
                payoffs[name] = 0.0

        return GameResult(
            winner=winner.name if winner else None,
            winning_price=winner.committed if winner else 0.0,
            runner_up=runner_up.name if runner_up else None,
            runner_up_price=runner_up.committed if runner_up else 0.0,
            rounds=self.round,
            turns=self.turn,
            payoffs=payoffs,
            agents=self.agents,
            events=self.events,
            stop_reason=stop_reason,
        )
