"""Pre-flight check: is each provider actually reachable?

This exists because of a specific failure mode. When a provider call fails, an
agent is forced to EXIT and the run *completes* -- it just completes with every
agent quitting immediately. A run against a bad API key therefore looks like a
finished experiment rather than an error, and the only clue is the forced-action
count buried in the report.

So: check the credentials before spending anything, and fail loudly here instead
of quietly there. One tiny call per provider, a few tokens each.

Never prints the key itself -- only its shape, so a truncated paste is visible
without the secret ending up in a terminal log or a screen share.
"""

from __future__ import annotations

import os

from .providers import REGISTRY, ProviderError

CHECKS = [
    ("anthropic", "ANTHROPIC_API_KEY", "claude-haiku-4-5", "sk-ant-..."),
    ("openai", "OPENAI_API_KEY", "gpt-5", "sk-..."),
    ("google", "GEMINI_API_KEY", "gemini-3-flash-preview", "AIza"),
]

PROMPT = "Reply with exactly the word: OK"


def _shape(value: str) -> str:
    """Describe a secret without revealing it."""
    if len(value) < 12:
        return f"{len(value)} chars — suspiciously short, likely a partial paste"
    return f"{value[:7]}…{value[-4:]} ({len(value)} chars)"


def run(verbose: bool = True) -> int:
    print("Provider check\n")
    any_ok = False
    any_configured = False

    for name, env_var, model, expected in CHECKS:
        raw = os.environ.get(env_var, "").strip()

        if not raw:
            print(f"  {name:<10} — no {env_var} set")
            continue

        any_configured = True

        if raw.startswith(('"', "'")) or raw.endswith(('"', "'")):
            print(f"  {name:<10} ✗ {env_var} has surrounding quotes — remove them")
            continue

        print(f"  {name:<10} key {_shape(raw)}", end="", flush=True)

        try:
            # Thinking models spend this budget before emitting text.
            provider = REGISTRY[name](model=model, max_tokens=512)
            result = provider.complete("Answer in one word.", PROMPT)
        except ProviderError as e:
            msg = str(e)
            print("  ✗ FAILED")
            print(f"             {msg[:300]}")
            if "401" in msg or "authentication" in msg.lower():
                print("             → the key was rejected. Check for a typo or a revoked key.")
            elif "429" in msg:
                print("             → rate limited or out of credit. Check billing in the Console.")
            elif "404" in msg:
                print(f"             → model {model!r} not available to this key.")
            continue
        except Exception as e:  # noqa: BLE001 - surface anything unexpected
            print(f"  ✗ {type(e).__name__}: {e}")
            continue

        any_ok = True
        reply = (result.text or "").strip().replace("\n", " ")[:40]
        print(f"  ✓ OK — {model} replied {reply!r} "
              f"({result.tokens_in} in / {result.tokens_out} out, {result.latency_ms:.0f} ms)")

    # Subscription / account auth via the official CLIs.
    from .providers.cli import ADAPTERS, CliProvider, available

    print("\nSubscription & account sign-in (no API key needed)\n")
    for entry in available():
        if not entry["installed"]:
            print(f"  {entry['command']:<10} — not installed ({entry['label']})")
            continue
        print(f"  {entry['command']:<10} found at {entry['path']}", end="", flush=True)
        try:
            provider = CliProvider(command=entry["command"], timeout=120)
            result = provider.complete("Answer in one word.", PROMPT)
        except ProviderError as e:
            print("  ✗ FAILED")
            print(f"             {str(e)[:280]}")
            continue
        any_ok = True
        any_configured = True
        reply = (result.text or "").strip().replace("\n", " ")[:30]
        print(f"  ✓ OK — replied {reply!r} in {result.latency_ms:.0f} ms")
        print(f"             use: {{\"provider\": \"cli\", \"command\": \"{entry['command']}\"}}")
    del ADAPTERS

    print()
    if not any_configured:
        print("No provider keys found.")
        print("  1. Get a key:  https://console.anthropic.com/settings/keys")
        print("  2. Put it in:  .env   (ANTHROPIC_API_KEY=sk-ant-...)")
        print("  3. Load it:    set -a && . ./.env && set +a")
        print("\nOr sign in to an official CLI — no key, uses your plan:")
        print("  claude   (Pro/Max)   gemini   (Google account, free)   codex   (ChatGPT plan)")
        print("\nThe scripted provider needs no key:")
        print("  python3 -m dollar_auction run configs/experiments/mvp_mock.json")
        return 1

    if not any_ok:
        print("Every configured provider failed — fix the above before running.")
        return 1

    print("Ready. Cheapest real run:")
    print("  python3 -m dollar_auction run configs/experiments/s0_smoke_live.json")
    return 0
