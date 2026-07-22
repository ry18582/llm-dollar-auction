"""Google Gemini generateContent adapter (raw HTTP).

Note on token budgets: current Gemini models think before answering, and the
thinking is billed against `maxOutputTokens`. A budget sized for the visible
reply alone gets consumed by thinking and the answer arrives truncated with
`finishReason: MAX_TOKENS` -- measured here, a 256-token budget spent 241 on
thinking and cut the reply mid-sentence. That is worse than an error, because
the truncated text still contains "Decision: BID" and parses cleanly.

So: give Gemini room (1024+ for this task), and pass `finishReason` up as
`stop_reason` so the agent layer can detect truncation and retry.
"""

from __future__ import annotations

import os

from .base import Completion, Provider, ProviderError

BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GoogleProvider(Provider):
    name = "google"

    def __init__(self, model: str = "gemini-3-flash-preview", **kw):
        super().__init__(model, **kw)
        self.api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

    def complete(self, system: str, user: str) -> Completion:
        if not self.api_key:
            raise ProviderError("google: GEMINI_API_KEY (or GOOGLE_API_KEY) is not set")

        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"maxOutputTokens": self.max_tokens},
        }
        headers = {
            "content-type": "application/json",
            "x-goog-api-key": self.api_key,
        }
        url = f"{BASE}/{self.model}:generateContent"

        data, latency = self._post(url, headers, payload)

        candidates = data.get("candidates") or []
        text = ""
        finish = None
        if candidates:
            finish = candidates[0].get("finishReason")
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts)
        usage = data.get("usageMetadata") or {}

        return Completion(
            text=text,
            tokens_in=usage.get("promptTokenCount", 0),
            tokens_out=usage.get("candidatesTokenCount", 0),
            latency_ms=latency,
            stop_reason=finish,
        )
