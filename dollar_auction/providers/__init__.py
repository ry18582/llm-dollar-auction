"""Provider registry.

An agent config names a provider and a model; this turns that into an object.
Swapping `"provider": "mock"` for `"provider": "anthropic"` is the only change
needed to move a whole experiment from free to live.
"""

from __future__ import annotations

from .anthropic import AnthropicProvider
from .base import Completion, Provider, ProviderError
from .cli import CliProvider
from .google import GoogleProvider
from .mock import MockProvider
from .openai import OpenAIProvider

REGISTRY: dict[str, type[Provider]] = {
    "mock": MockProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "google": GoogleProvider,
    "cli": CliProvider,
}

__all__ = [
    "Completion",
    "Provider",
    "ProviderError",
    "REGISTRY",
    "build_provider",
]


def build_provider(spec: dict, *, traits: dict | None = None, seed: int = 0) -> Provider:
    """Build a provider from an agent config's `model` block.

        {"provider": "anthropic", "model": "claude-opus-4-8", "max_tokens": 256}
    """
    kind = spec.get("provider", "mock")
    try:
        cls = REGISTRY[kind]
    except KeyError:
        raise ValueError(
            f"unknown provider {kind!r}; expected one of {sorted(REGISTRY)}"
        ) from None

    kwargs: dict = {"max_tokens": spec.get("max_tokens", 256)}
    if "model" in spec:
        kwargs["model"] = spec["model"]
    if "timeout" in spec:
        kwargs["timeout"] = spec["timeout"]
    if "min_interval" in spec:
        kwargs["min_interval"] = spec["min_interval"]
    if cls is CliProvider:
        # Which official CLI to drive: claude / gemini / codex.
        kwargs["command"] = spec.get("command", "claude")
        kwargs.setdefault("model", spec.get("model", ""))
    if cls is MockProvider:
        kwargs["traits"] = traits or {}
        kwargs["seed"] = seed
    return cls(**kwargs)
