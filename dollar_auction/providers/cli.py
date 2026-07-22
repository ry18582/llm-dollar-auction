"""Run agents through an official provider CLI, using its own authentication.

The problem this solves: most people do not have an API key, but many already
pay for a subscription. Claude Pro/Max, a ChatGPT plan, and a plain Google
account each come with an official command-line tool that is *authorised to use
that entitlement*:

    claude   Claude Code            Pro / Max sign-in
    gemini   Gemini CLI             Google account sign-in (free tier)
    codex    OpenAI Codex CLI       ChatGPT plan sign-in

So instead of calling the HTTP API with a key, this provider shells out to
whichever tool the user has already logged into. No key, no billing setup.

What you give up, and it is not nothing:

  - **Speed.** Each call starts a process and runs an agent harness: seconds,
    not milliseconds. A 16-agent game becomes minutes.
  - **Token accounting.** These tools do not report usage per call, so
    `tokens_in`/`tokens_out` are zero and the run's cost metrics are blank.
  - **Version pinning.** The API pins an exact model; a CLI may resolve to
    whatever its default currently is. Record the version yourself if a result
    needs to be reproducible months later.
  - **Shared allowance.** Calls draw on the same quota as the user's ordinary
    use of that tool, so a long run competes with their real work.

Use it for access and exploration. Use the API providers when a result needs
precise accounting and a pinned model.

Scope note: this is for a person running the harness on their own machine under
their own account. Pooling subscription credentials to serve other people is a
different thing entirely, and not something this supports.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Optional

from .base import Completion, Provider, ProviderError

# How each tool is invoked headlessly. `system` says whether it accepts a
# separate system prompt; when it does not, the two are concatenated.
ADAPTERS: dict[str, dict] = {
    "claude": {
        "args": ["-p"],
        "system_flag": "--append-system-prompt",
        "model_flag": "--model",
        "label": "Claude Code (Pro/Max sign-in)",
    },
    "gemini": {
        "args": ["-p"],
        "system_flag": None,
        "model_flag": "--model",
        "label": "Gemini CLI (Google account)",
    },
    "codex": {
        "args": ["exec"],
        "system_flag": None,
        "model_flag": "--model",
        "label": "Codex CLI (ChatGPT plan)",
    },
}


class CliProvider(Provider):
    name = "cli"

    def __init__(
        self,
        model: str = "",
        command: str = "claude",
        max_tokens: int = 1024,
        timeout: float = 120.0,
        min_interval: float = 0.0,
    ):
        super().__init__(model, max_tokens=max_tokens, timeout=timeout, min_interval=min_interval)
        self.command = command
        self.adapter = ADAPTERS.get(command, {"args": ["-p"], "system_flag": None,
                                              "model_flag": None, "label": command})

    def _binary(self) -> str:
        path = shutil.which(self.command)
        if not path:
            raise ProviderError(
                f"cli: {self.command!r} is not installed or not on PATH.\n"
                f"  claude -> https://claude.com/code   (Pro/Max)\n"
                f"  gemini -> npm i -g @google/gemini-cli, then `gemini` and sign in\n"
                f"  codex  -> npm i -g @openai/codex, then `codex` and sign in"
            )
        return path

    def complete(self, system: str, user: str) -> Completion:
        binary = self._binary()
        adapter = self.adapter

        argv = [binary, *adapter["args"]]
        prompt = user

        if system:
            if adapter["system_flag"]:
                argv += [adapter["system_flag"], system]
            else:
                # No separate system channel: prepend it, clearly delimited.
                prompt = f"{system}\n\n---\n\n{user}"

        if self.model and adapter["model_flag"]:
            argv += [adapter["model_flag"], self.model]

        # The prompt goes on argv rather than through a shell, so nothing in it
        # can be interpreted as a command.
        argv.append(prompt)

        self._throttle()
        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            raise ProviderError(
                f"cli: {self.command} did not respond within {self.timeout:.0f}s. "
                f"These tools are slow; raise `timeout` in the model config."
            ) from None
        except OSError as e:
            raise ProviderError(f"cli: could not run {self.command}: {e}") from None

        latency = (time.monotonic() - started) * 1000

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:400]
            hint = ""
            low = err.lower()
            if "login" in low or "auth" in low or "sign in" in low:
                hint = f"\n  → run `{self.command}` once interactively and sign in."
            elif "limit" in low or "quota" in low:
                hint = "\n  → the plan's allowance is used up; wait or switch provider."
            raise ProviderError(f"cli: {self.command} exited {proc.returncode}: {err}{hint}")

        text = (proc.stdout or "").strip()
        if not text:
            raise ProviderError(
                f"cli: {self.command} returned nothing. "
                f"stderr: {(proc.stderr or '').strip()[:200]}"
            )

        return Completion(
            text=text,
            tokens_in=0,      # not reported by these tools
            tokens_out=0,
            latency_ms=latency,
            stop_reason="end_turn",
        )


def available() -> list[dict]:
    """Which provider CLIs are installed — used by `doctor` and the GUI."""
    found = []
    for name, adapter in ADAPTERS.items():
        path = shutil.which(name)
        found.append({
            "command": name,
            "label": adapter["label"],
            "installed": bool(path),
            "path": path or "",
        })
    return found
