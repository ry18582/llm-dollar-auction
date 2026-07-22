"""Deterministic scripted provider — the whole harness runs with zero API keys.

The mock reads the `<state>` JSON block the round prompt embeds and applies a
closed-form policy derived from the agent's traits. It is not pretending to be
an LLM; it exists so the engine, logging, metrics, report, and plots can be
developed and regression-tested for free, and so a run is reproducible.

Policy: each agent carries a private walk-away price and bids while the next
bid is under it.

    walk_away = item_value * (base + sunk_stretch) + noise

`base` comes from the agent's standing traits -- competitive, status-driven
agents tolerate a higher price; disciplined and reflective ones stop early.
`sunk_stretch` is the sunk-cost effect: the threshold rises as the agent's own
committed total grows, scaled by its loss aversion.

Note the stretch coefficient is deliberately below 1. The threshold chases the
agent's committed total but never catches it, so escalation converges to a
finite price instead of running to the budget cap. A coefficient at or above 1
produces an agent that literally cannot stop -- which is a degenerate run, not
an interesting one.
"""

from __future__ import annotations

import hashlib
import json
import random
import re

from .base import Completion, Provider

STATE_RE = re.compile(r"<state>(.*?)</state>", re.DOTALL)


class MockProvider(Provider):
    name = "mock"

    def __init__(self, model: str = "mock", traits: dict | None = None, seed: int = 0, **kw):
        super().__init__(model, **kw)
        self.traits = traits or {}
        self.seed = seed

    def _t(self, key: str, default: float = 5.0) -> float:
        return float(self.traits.get(key, default))

    def complete(self, system: str, user: str) -> Completion:
        match = STATE_RE.search(user)
        if not match:
            return Completion(text="Decision: EXIT\nReason: no state provided\nConfidence: 0")
        state = json.loads(match.group(1))

        value = state["item_value"]
        next_bid = state["next_bid"]
        me = state["you"]

        # Standing disposition. `heat` is the escalatory side of the agent,
        # weighed against the side that does arithmetic.
        heat = (
            self._t("competitiveness") + self._t("status_sensitivity") + self._t("loss_aversion")
        ) / 3.0
        discipline = self._t("rational_discipline")
        gap = heat - discipline

        base = 1.0 + (0.08 * gap if gap > 0 else 0.04 * gap)
        base -= 0.02 * self._t("reflection")

        # Sunk cost: what it has already sunk raises what it will tolerate.
        sunk_stretch = (self._t("loss_aversion") / 10.0) * (me["committed"] / value) * 0.4

        mem = state.get("memory") or {}

        # Cross-game memory is the learning channel: an agent that remembers
        # being burned lowers what it will pay next time. Reflective agents
        # learn faster from the same evidence.
        if mem.get("cross_game") and mem.get("games_remembered"):
            burned = min(int(mem.get("times_burned", 0)), 5)
            learning_rate = 0.06 + 0.010 * self._t("reflection")
            base -= learning_rate * burned

        # Within-game memory is the self-awareness channel: watching its own
        # commitment climb blunts the sunk-cost pull, but does not remove it.
        if mem.get("within_game") and mem.get("notes"):
            sunk_stretch *= max(0.15, 1.0 - self._t("reflection") / 12.0)

        # Seeded jitter -- impatient agents are noisier. Deterministic per
        # (seed, agent, round) so replays match exactly.
        key = f"{self.seed}:{me['name']}:{state['round']}:{next_bid}"
        rng = random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))
        noise = rng.gauss(0, value * 0.08 * (10 - self._t("patience")) / 10.0)

        walk_away = value * max(0.0, base + sunk_stretch) + noise
        headroom = walk_away - next_bid

        decision = "BID" if headroom > 0 else "EXIT"
        confidence = int(max(0, min(100, 50 + headroom / max(value, 1e-9) * 100)))

        if decision == "BID":
            reason = f"${next_bid:.0f} is still inside what I will pay (${walk_away:.0f})"
        else:
            reason = f"${next_bid:.0f} is past my limit of ${walk_away:.0f}; I stop here"

        text = f"Decision: {decision}\nReason: {reason}\nConfidence: {confidence}"
        return Completion(text=text, tokens_in=0, tokens_out=0, latency_ms=0.0, stop_reason="end_turn")
