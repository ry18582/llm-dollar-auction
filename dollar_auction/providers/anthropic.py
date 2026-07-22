"""Anthropic Messages API adapter (raw HTTP).

Two things the current API rejects with a 400 that older code habitually sends:
`temperature`/`top_p`/`top_k`, and `thinking.budget_tokens`. Neither appears
below. Bidding decisions are one line long, so thinking stays off entirely --
omitting the field means no thinking on Opus 4.8 / 4.7.
"""

from __future__ import annotations

import os

from .base import Completion, Provider, ProviderError

ENDPOINT = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

# Current model IDs. These are complete as written -- never append a date suffix.
MODELS = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
}


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str = "claude-opus-4-8", **kw):
        super().__init__(MODELS.get(model, model), **kw)
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")

    def complete(self, system: str, user: str) -> Completion:
        if not self.api_key:
            raise ProviderError("anthropic: ANTHROPIC_API_KEY is not set")

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
        }

        data, latency = self._post(ENDPOINT, headers, payload)

        # A refusal is HTTP 200 with an empty/partial content array -- check
        # stop_reason before indexing into content.
        stop_reason = data.get("stop_reason")
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        usage = data.get("usage") or {}

        return Completion(
            text=text,
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
            latency_ms=latency,
            stop_reason=stop_reason,
        )
