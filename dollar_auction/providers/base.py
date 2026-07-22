"""Provider interface + shared HTTP plumbing.

Stdlib only, on purpose: this box has no pip, and a dollar auction does not
need an SDK. Every provider speaks the same tiny contract:

    complete(system: str, user: str) -> Completion

so the engine never learns which vendor produced a decision.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional


class ProviderError(RuntimeError):
    """Raised when a provider fails after exhausting retries."""


@dataclass
class Completion:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    stop_reason: Optional[str] = None


class Provider:
    """Base class. Subclasses implement `complete`."""

    name = "base"

    # Free tiers are often a few requests per minute. A shared clock per
    # provider class keeps concurrent agents from racing through the budget.
    _last_call_lock = threading.Lock()
    _last_call_at = 0.0

    def __init__(
        self,
        model: str,
        max_tokens: int = 512,
        timeout: float = 60.0,
        min_interval: float = 0.0,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        # Seconds to leave between requests. 12.0 keeps you under 5/min.
        self.min_interval = min_interval

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        cls = type(self)
        with cls._last_call_lock:
            wait = cls._last_call_at + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            cls._last_call_at = time.monotonic()

    def complete(self, system: str, user: str) -> Completion:  # pragma: no cover
        raise NotImplementedError

    # -- shared HTTP with retry ------------------------------------------

    def _post(
        self,
        url: str,
        headers: dict,
        payload: dict,
        *,
        max_retries: int = 6,
        rng: Optional[random.Random] = None,
    ) -> tuple[dict, float]:
        """POST JSON, retrying 429 / 5xx / connection errors with backoff.

        Returns (parsed_body, latency_ms). Jitter comes from an injected RNG so
        a seeded run stays reproducible.
        """
        rng = rng or random.Random(0)
        body = json.dumps(payload).encode()
        last_err: Optional[str] = None
        started = time.monotonic()

        for attempt in range(max_retries):
            self._throttle()
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    parsed = json.loads(resp.read().decode())
                    return parsed, (time.monotonic() - started) * 1000
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:500]
                last_err = f"HTTP {e.code}: {detail}"
                # 4xx other than rate limiting is our bug, not a blip.
                if e.code not in (408, 409, 429) and e.code < 500:
                    raise ProviderError(f"{self.name}: {last_err}") from e
                # Providers signal the wait in a header OR in the body; Google
                # uses the body, so a header-only reader backs off too little
                # and gives up while the window is still closed.
                delay = (
                    self._retry_after(e)
                    or self._retry_delay_from_body(detail)
                    or (2**attempt + rng.random())
                )
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                last_err = f"{type(e).__name__}: {e}"
                delay = 2**attempt + rng.random()

            if attempt == max_retries - 1:
                break
            time.sleep(min(delay, 90.0))

        raise ProviderError(f"{self.name}: giving up after {max_retries} attempts — {last_err}")

    @staticmethod
    def _retry_delay_from_body(detail: str) -> Optional[float]:
        """Pull a retry delay out of an error body.

        Google returns `"retryDelay": "19s"` in error.details, and repeats it in
        prose as "Please retry in 19.41s". Either is more accurate than guessing.
        """
        for pattern in (r'"retryDelay"\s*:\s*"([\d.]+)s"', r"retry in ([\d.]+)s"):
            m = re.search(pattern, detail)
            if m:
                # A second of headroom: the window is measured server-side.
                return float(m.group(1)) + 1.0
        return None

    @staticmethod
    def _retry_after(err: urllib.error.HTTPError) -> Optional[float]:
        raw = err.headers.get("retry-after") if err.headers else None
        try:
            return float(raw) if raw else None
        except ValueError:
            return None
