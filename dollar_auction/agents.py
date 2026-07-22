"""Agents: config -> provider -> parsed Decision.

This module owns the only place where free-form model text becomes a typed
action. Everything downstream sees `Decision`, never a string.
"""

from __future__ import annotations

import re
from typing import Optional

from .engine import BID, EXIT, Auction, Decision
from .memory import AgentMemory, Turn
from .prompts import reflection_prompt, round_prompt, system_prompt
from .providers import Provider, ProviderError, build_provider

DECISION_RE = re.compile(r"decision\s*[:\-]\s*\**\s*(BID|EXIT)", re.IGNORECASE)
REASON_RE = re.compile(r"reason\s*[:\-]\s*(.+)", re.IGNORECASE)
CONFIDENCE_RE = re.compile(r"confidence\s*[:\-]\s*\**\s*(\d{1,3})", re.IGNORECASE)
# Last-resort: a bare BID/EXIT on its own somewhere in the reply.
BARE_RE = re.compile(r"\b(BID|EXIT)\b")
# Provider-specific names for "I ran out of output budget".
TRUNCATED = {"MAX_TOKENS", "LENGTH", "MAX_OUTPUT_TOKENS"}


class Agent:
    """One bidder: a config, a provider, and a prompt policy."""

    def __init__(
        self,
        config: dict,
        rules: dict,
        *,
        seed: int = 0,
        max_parse_retries: int = 2,
        memory: AgentMemory | None = None,
        game_index: int = 0,
    ):
        self.config = config
        self.game_index = game_index
        self.memory = memory or AgentMemory(name=config["name"])
        self.name = config["name"]
        self.rules = rules
        self.max_parse_retries = max_parse_retries
        self.reflect_every: Optional[int] = config.get("reflect_every")
        self.provider: Provider = build_provider(
            config.get("model", {"provider": "mock"}),
            traits=config.get("traits", {}),
            seed=seed,
        )
        self._system = system_prompt(config, rules)

    # -- the callable the engine drives ----------------------------------

    def decide(self, auction: Auction, name: str) -> Decision:
        # Captured before the decision is applied, so the agent remembers the
        # table as it looked when it chose -- not as it looked afterwards.
        standing_bid = auction.standing_bid
        standing_bidder = auction.standing_bidder
        next_bid = auction.next_bid()

        decision = self._decide(auction, name)

        self.memory.record_turn(
            Turn(
                game_index=self.game_index,
                round=auction.round,
                standing_bid=standing_bid,
                standing_bidder=standing_bidder,
                action=decision.action,
                bid=next_bid if decision.action == BID else None,
                reason=decision.reason,
                confidence=decision.confidence,
            )
        )
        return decision

    def _decide(self, auction: Auction, _name: str) -> Decision:
        state = auction.state_snapshot(self.name)
        # Memory travels inside the state block so the scripted provider reacts
        # to the toggles too, not just the prose-reading models.
        state["memory"] = self.memory.as_state()
        prompt = round_prompt(state, self.memory.prompt_block())

        if self.reflect_every and state["round"] % self.reflect_every == 0:
            prompt = f"{reflection_prompt(state)}\n\n---\n\n{prompt}"

        tokens_in = tokens_out = 0
        latency = 0.0
        last_raw = ""

        for attempt in range(1, self.max_parse_retries + 2):
            try:
                completion = self.provider.complete(self._system, prompt)
            except ProviderError as e:
                # A dead provider must not silently become a strategic choice.
                return Decision(
                    EXIT,
                    reason="provider error",
                    forced="provider_error",
                    error=str(e),
                    attempts=attempt,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency,
                )

            tokens_in += completion.tokens_in
            tokens_out += completion.tokens_out
            latency += completion.latency_ms
            last_raw = completion.text

            if completion.stop_reason == "refusal":
                return Decision(
                    EXIT,
                    reason="model refused",
                    forced="refusal",
                    raw=last_raw,
                    error="stop_reason=refusal",
                    attempts=attempt,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency,
                )

            # A truncated reply can still contain "Decision: BID" and parse
            # cleanly, yielding a decision with a half-sentence reason and no
            # confidence. Treat it as a failure and retry with more room.
            truncated = str(completion.stop_reason or "").upper() in TRUNCATED
            if truncated and attempt <= self.max_parse_retries:
                self.provider.max_tokens = min(self.provider.max_tokens * 4, 8192)
                continue

            parsed = parse_decision(completion.text)
            if parsed is not None:
                action, reason, confidence = parsed
                return Decision(
                    action=action,
                    reason=reason,
                    confidence=confidence,
                    raw=last_raw,
                    error="reply truncated (max tokens)" if truncated else None,
                    attempts=attempt,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    latency_ms=latency,
                )

            prompt = (
                f"{prompt}\n\nYour previous reply could not be parsed. "
                "Reply with exactly:\nDecision: BID or EXIT\nReason: one sentence\n"
                "Confidence: an integer 0-100"
            )

        # Unparseable after retries. Forcing EXIT is the conservative choice and
        # it is logged as forced, so it never gets mistaken for a real decision.
        return Decision(
            EXIT,
            reason="unparseable response",
            forced="parse_failure",
            raw=last_raw,
            error="could not parse a decision",
            attempts=self.max_parse_retries + 1,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency,
        )


def parse_decision(text: str) -> Optional[tuple[str, str, Optional[int]]]:
    """Pull (action, reason, confidence) out of a model reply, or None."""
    if not text:
        return None

    match = DECISION_RE.search(text)
    action = match.group(1).upper() if match else None

    if action is None:
        bare = BARE_RE.findall(text.upper())
        # Only trust a bare token when the reply is unambiguous about it.
        if bare and len(set(bare)) == 1:
            action = bare[0]

    if action not in (BID, EXIT):
        return None

    reason_match = REASON_RE.search(text)
    reason = reason_match.group(1).strip() if reason_match else ""

    conf_match = CONFIDENCE_RE.search(text)
    confidence = None
    if conf_match:
        confidence = max(0, min(100, int(conf_match.group(1))))

    return action, reason, confidence


def build_agents(
    configs: list[dict],
    rules: dict,
    *,
    seed: int = 0,
    memories: dict[str, AgentMemory] | None = None,
    game_index: int = 0,
) -> dict[str, Agent]:
    memories = memories or {}
    return {
        c["name"]: Agent(
            c, rules, seed=seed, memory=memories.get(c["name"]), game_index=game_index
        )
        for c in configs
    }
