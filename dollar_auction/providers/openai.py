"""OpenAI Chat Completions adapter (raw HTTP)."""

from __future__ import annotations

import os

from .base import Completion, Provider, ProviderError

ENDPOINT = "https://api.openai.com/v1/chat/completions"


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, model: str = "gpt-5", **kw):
        super().__init__(model, **kw)
        self.api_key = os.environ.get("OPENAI_API_KEY")

    def complete(self, system: str, user: str) -> Completion:
        if not self.api_key:
            raise ProviderError("openai: OPENAI_API_KEY is not set")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Newer models reject `max_tokens`; this is the accepted spelling.
            "max_completion_tokens": self.max_tokens,
        }
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.api_key}",
        }

        data, latency = self._post(ENDPOINT, headers, payload)

        choices = data.get("choices") or []
        text = choices[0]["message"].get("content", "") if choices else ""
        finish = choices[0].get("finish_reason") if choices else None
        usage = data.get("usage") or {}

        return Completion(
            text=text or "",
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=latency,
            stop_reason=finish,
        )
