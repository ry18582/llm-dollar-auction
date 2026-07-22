"""Agent memory — two independent channels, session-style.

within_game
    The agent's own turn-by-turn record inside a single auction, in the shape a
    chat session has: what the table looked like when it decided, what it did,
    and the reason it gave at the time. Tests whether an agent that can read its
    own past reasoning behaves differently from one deciding fresh each turn.

cross_game
    What survives between auctions: the final price, what it paid, whether it
    won. The learning channel.

They are separate because they are separate hypotheses. Turning both on and
seeing a change tells you nothing about which one caused it.

Three things shape what an agent actually sees:

    mode      off | summary | transcript
              `summary` is a compact set of facts. `transcript` replays the
              agent's own deliberation verbatim, which is what makes it feel
              like a chat session -- and is also why a horizon is mandatory
              rather than optional: prompt size grows every single turn.

    horizon   keep_rounds / keep_games. 0 means unlimited, which on a long game
              means a prompt that grows without bound. Deliberate choice, not a
              default.

    wipe      clearing memory mid-run, all agents or one. Every wipe is
              recorded, because a run where an agent silently stops
              remembering is a run nobody can interpret afterwards.

**Memory is private and matches what a real bidder knows.** An agent recalls its
own reasoning and the *public* record of who bid what. It never sees a rival's
private deliberation -- that would turn a sealed bidding game into a
negotiation, which is a different experiment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

MODES = ("off", "summary", "transcript")


@dataclass
class Turn:
    """One of the agent's own turns, as it would remember it."""

    game_index: int
    round: int
    standing_bid: float
    standing_bidder: Optional[str]
    action: str
    bid: Optional[float]
    reason: str = ""
    confidence: Optional[int] = None

    def as_line(self) -> str:
        if self.standing_bidder:
            table = f"the bid stood at ${self.standing_bid:.0f} (held by {self.standing_bidder})"
        else:
            table = "no one had bid yet"
        if self.action == "BID" and self.bid is not None:
            did = f"You bid ${self.bid:.0f}"
        else:
            did = "You walked away"
        line = f"Round {self.round} — {table}. {did}."
        if self.reason:
            line += f' You said: "{self.reason}"'
        return line


@dataclass
class GameRecall:
    """What one finished auction leaves behind for one agent."""

    game_index: int
    item_value: float
    final_price: float
    my_committed: float
    my_payoff: float
    won: bool
    escalators: list[str] = field(default_factory=list)

    def as_line(self) -> str:
        if self.won:
            outcome = f"You WON it for ${self.final_price:.0f}"
        elif self.my_committed > 0:
            outcome = f"You lost and still paid ${self.my_committed:.0f}"
        else:
            outcome = "You walked away early and paid nothing"
        return (
            f"Auction {self.game_index + 1}: item worth ${self.item_value:.0f}, "
            f"sold for ${self.final_price:.0f}. {outcome}. "
            f"Your net: ${self.my_payoff:+.0f}."
        )


@dataclass
class MemoryConfig:
    """How much an agent remembers, and in what form."""

    within_game: bool = False
    cross_game: bool = False
    mode: str = "transcript"
    keep_rounds: int = 8   # 0 = unlimited (prompt grows without bound)
    keep_games: int = 5    # 0 = unlimited

    def __post_init__(self):
        if self.mode not in MODES:
            raise ValueError(f"unknown memory mode {self.mode!r}; expected one of {MODES}")

    @classmethod
    def from_dict(cls, raw: dict | None) -> "MemoryConfig":
        """Accepts the original boolean form as well as the fuller one."""
        raw = raw or {}
        return cls(
            within_game=bool(raw.get("within_game", False)),
            cross_game=bool(raw.get("cross_game", False)),
            mode=raw.get("mode", "transcript"),
            keep_rounds=int(raw.get("keep_rounds", 8)),
            keep_games=int(raw.get("keep_games", 5)),
        )

    def describe(self) -> str:
        on = [k for k, v in (("within-game", self.within_game), ("cross-game", self.cross_game)) if v]
        if not on:
            return "off"
        horizon = []
        if self.within_game:
            horizon.append(f"{self.keep_rounds or 'all'} rounds")
        if self.cross_game:
            horizon.append(f"{self.keep_games or 'all'} games")
        return f"{' + '.join(on)} ({self.mode}, keeping {', '.join(horizon)})"


@dataclass
class AgentMemory:
    """One agent's memory. Nothing is shared between agents."""

    name: str
    config: MemoryConfig = field(default_factory=MemoryConfig)
    turns: list[Turn] = field(default_factory=list)
    history: list[GameRecall] = field(default_factory=list)
    wipes: list[dict] = field(default_factory=list)

    # -- convenience so older call sites keep reading naturally ----------

    @property
    def within_game(self) -> bool:
        return self.config.within_game

    @property
    def cross_game(self) -> bool:
        return self.config.cross_game

    @property
    def notes(self) -> list[Turn]:
        return self.turns

    # -- lifecycle -------------------------------------------------------

    def start_game(self) -> None:
        """Within-game memory never survives the auction it belongs to."""
        self.turns = []

    def record_turn(self, turn: Turn) -> None:
        if not self.config.within_game:
            return
        self.turns.append(turn)

    def record_game(self, recall: GameRecall) -> None:
        if not self.config.cross_game:
            return
        self.history.append(recall)

    def wipe(self, *, scope: str = "all", game_index: int = 0, round_no: int = 0,
             source: str = "manual") -> dict:
        """Clear memory and leave a record that it happened.

        The record is the point. An agent that silently stops remembering
        mid-run produces a transcript nobody can explain later.
        """
        event = {
            "type": "memory_wipe",
            "agent": self.name,
            "scope": scope,
            "game_index": game_index,
            "round": round_no,
            "source": source,
            "cleared_turns": len(self.turns) if scope in ("all", "within_game") else 0,
            "cleared_games": len(self.history) if scope in ("all", "cross_game") else 0,
        }
        if scope in ("all", "within_game"):
            self.turns = []
        if scope in ("all", "cross_game"):
            self.history = []
        self.wipes.append(event)
        return event

    # -- what the agent is shown ----------------------------------------

    def _recent_turns(self) -> list[Turn]:
        keep = self.config.keep_rounds
        return self.turns[-keep:] if keep else self.turns

    def _recent_games(self) -> list[GameRecall]:
        keep = self.config.keep_games
        return self.history[-keep:] if keep else self.history

    def prompt_block(self) -> str:
        """Rendered into the round prompt. Empty when nothing is remembered."""
        if self.config.mode == "off":
            return ""

        sections: list[str] = []

        if self.config.cross_game and self.history:
            shown = self._recent_games()
            lines = "\n".join(f"  - {r.as_line()}" for r in shown)
            net = sum(r.my_payoff for r in self.history)
            hidden = len(self.history) - len(shown)
            more = f"  ({hidden} earlier auction(s) no longer remembered)\n" if hidden else ""
            sections.append(
                f"What you remember from previous auctions:\n{lines}\n{more}"
                f"  Across {len(self.history)} auction(s) you are ${net:+.0f} overall."
            )

        if self.config.within_game and self.turns:
            shown = self._recent_turns()
            hidden = len(self.turns) - len(shown)
            if self.config.mode == "transcript":
                lines = "\n".join(f"  {t.as_line()}" for t in shown)
                head = "Your own record of this auction so far"
            else:
                lines = "\n".join(
                    f"  Round {t.round}: "
                    + (f"you bid ${t.bid:.0f}" if t.action == "BID" else "you exited")
                    for t in shown
                )
                head = "What you have done so far in THIS auction"
            more = f"\n  ({hidden} earlier round(s) no longer remembered)" if hidden else ""
            committed = max((t.bid or 0.0) for t in self.turns) if self.turns else 0.0
            sections.append(
                f"{head}:\n{lines}{more}\n  You have committed ${committed:.0f} in total."
            )

        return "\n\n".join(sections)

    def as_state(self) -> dict:
        """Machine-readable view, for the scripted provider."""
        past = [r.my_payoff for r in self.history] if self.config.cross_game else []
        return {
            "within_game": self.config.within_game,
            "cross_game": self.config.cross_game,
            "mode": self.config.mode,
            "notes": len(self.turns) if self.config.within_game else 0,
            "games_remembered": len(past),
            "mean_past_payoff": (sum(past) / len(past)) if past else 0.0,
            "times_burned": sum(1 for p in past if p < 0),
            "wipes": len(self.wipes),
        }


def build_memories(
    names: list[str],
    *,
    within_game: bool = False,
    cross_game: bool = False,
    config: MemoryConfig | None = None,
) -> dict[str, AgentMemory]:
    cfg = config or MemoryConfig(within_game=within_game, cross_game=cross_game)
    return {n: AgentMemory(name=n, config=cfg) for n in names}
