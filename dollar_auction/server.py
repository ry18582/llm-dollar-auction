"""Local web GUI — stdlib http.server only.

There is no tkinter and no X display on this machine, so the GUI is a small
local web app you open in a browser. It serves three things:

    GET  /              the single-page UI
    GET  /api/meta      rosters, agents and their traits, providers
    POST /api/run       start a run in a background thread
    GET  /api/events    poll for everything that has happened since index N

Polling rather than SSE: a run is a few hundred events and the client is on
localhost, so a 120 ms poll is simpler and survives a reconnect without any
replay machinery.

Binds to 127.0.0.1 only. This is a local research tool, not a service: there is
no authentication, and starting a run spends real money when a live provider is
selected, so it must not be exposed to a network.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import CONFIG_DIR, load_json
from .runner import run_experiment

GUI_DIR = Path(__file__).resolve().parent / "gui"

PROVIDERS = [
    {"id": "mock", "label": "Scripted (free, instant)", "models": ["mock"], "key": None},
    {
        "id": "anthropic",
        "label": "Anthropic",
        "models": ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"],
        "key": "ANTHROPIC_API_KEY",
    },
    {"id": "openai", "label": "OpenAI", "models": ["gpt-5"], "key": "OPENAI_API_KEY"},
    {
        "id": "google",
        "label": "Google",
        "models": ["gemini-2.5-pro", "gemini-2.5-flash"],
        "key": "GEMINI_API_KEY",
    },
]


class RunSession:
    """One run in flight. Events accumulate; the browser polls for them."""

    def __init__(self):
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.running = False
        self.cancelled = False
        self.run_dir: str | None = None
        self.error: str | None = None
        self.memories: dict = {}
        self.game_index = 0
        self.round = 0

    def emit(self, event: dict) -> None:
        with self.lock:
            self.events.append(event)

    def since(self, index: int) -> tuple[list[dict], bool, str | None, str | None]:
        with self.lock:
            return list(self.events[index:]), self.running, self.run_dir, self.error

    def reset(self) -> None:
        with self.lock:
            self.events = []
            self.running = True
            self.cancelled = False
            self.run_dir = None
            self.error = None
            self.memories = {}
            self.game_index = 0
            self.round = 0


SESSION = RunSession()


class Cancelled(RuntimeError):
    pass


def _read_roster(roster: str) -> list[dict]:
    directory = CONFIG_DIR / "agents" / roster
    out = []
    for path in sorted(directory.glob("*.json")):
        cfg = load_json(path)
        out.append(
            {
                "id": path.stem,
                "name": cfg["name"],
                "traits": cfg.get("traits", {}),
                "notes": cfg.get("strategy_notes", ""),
            }
        )
    return out


def _scenarios() -> list[dict]:
    out = []
    for path in sorted((CONFIG_DIR / "experiments").glob("*.json")):
        try:
            cfg = load_json(path)
        except Exception:
            continue
        providers = {cfg.get("overrides", {}).get("model", {}).get("provider", "mixed")}
        out.append(
            {
                "id": path.stem,
                "name": cfg.get("name", path.stem),
                "description": cfg.get("description", ""),
                "roster": cfg.get("roster"),
                "agents": cfg.get("agents", []),
                "repeats": cfg.get("repeats", 1),
                "memory": cfg.get("memory", {}),
                "turn_order": cfg.get("turn_order", "rotate"),
                "item_value": cfg.get("rules", {}).get("item_value", 100),
                "increment": cfg.get("rules", {}).get("increment", 5),
                "seed": cfg.get("seed", 7),
                "provider": next(iter(providers)) or "mixed",
            }
        )
    return out


def _meta() -> dict:
    import os

    providers = []
    for p in PROVIDERS:
        providers.append({**p, "available": p["key"] is None or bool(os.environ.get(p["key"]))})
    rosters = {}
    for d in sorted((CONFIG_DIR / "agents").iterdir()):
        if d.is_dir():
            rosters[d.name] = _read_roster(d.name)
    return {"rosters": rosters, "providers": providers, "scenarios": _scenarios()}


def _start_run(payload: dict) -> None:
    SESSION.reset()

    def observer(event: dict) -> None:
        if SESSION.cancelled:
            raise Cancelled("stopped by user")
        if event.get("type") == "game_start":
            SESSION.game_index = event.get("game_index", 0)
        elif event.get("type") == "event":
            SESSION.round = event.get("round", 0)
        SESSION.emit(event)

    def on_ready(memories: dict) -> None:
        with SESSION.lock:
            SESSION.memories = memories

    def work():
        try:
            # A named scenario runs exactly as written on disk, so what the GUI
            # runs and what the CLI runs are the same experiment.
            if payload.get("scenario"):
                from .config import load_experiment

                exp = load_experiment(payload["scenario"] + ".json")
                run_dir = run_experiment(exp, quiet=True, observer=observer, on_ready=on_ready)
                metrics = json.loads((run_dir / "metrics.json").read_text())
                SESSION.emit({"type": "done", "run_id": run_dir.name, "metrics": metrics})
                with SESSION.lock:
                    SESSION.run_dir = str(run_dir)
                return

            provider = payload.get("provider", "mock")
            model_block = {"provider": provider, "max_tokens": 256}
            if provider != "mock":
                model_block["model"] = payload.get("model")

            exp = {
                "name": payload.get("name", "gui"),
                "roster": payload["roster"],
                "agents": payload["agents"],
                "seed": int(payload.get("seed", 7)),
                "repeats": int(payload.get("repeats", 3)),
                "rules": {
                    "item_value": float(payload.get("item_value", 100)),
                    "increment": float(payload.get("increment", 5)),
                    "default_budget": float(payload.get("budget", 500)),
                    "max_rounds": int(payload.get("max_rounds", 60)),
                    "max_bid_multiple": 5.0,
                },
                "memory": {
                    "within_game": bool(payload.get("within_game", False)),
                    "cross_game": bool(payload.get("cross_game", False)),
                    "mode": payload.get("memory_mode", "transcript"),
                    "keep_rounds": int(payload.get("keep_rounds", 8)),
                    "keep_games": int(payload.get("keep_games", 5)),
                },
                "turn_order": payload.get("turn_order", "rotate"),
                "overrides": {"model": model_block},
            }
            run_dir = run_experiment(exp, quiet=True, observer=observer, on_ready=on_ready)
            metrics = json.loads((run_dir / "metrics.json").read_text())
            SESSION.emit({"type": "done", "run_id": run_dir.name, "metrics": metrics})
            with SESSION.lock:
                SESSION.run_dir = str(run_dir)
        except Cancelled:
            SESSION.emit({"type": "cancelled"})
        except Exception as e:  # surfaced in the UI rather than only the console
            with SESSION.lock:
                SESSION.error = f"{type(e).__name__}: {e}"
            SESSION.emit({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            with SESSION.lock:
                SESSION.running = False

    threading.Thread(target=work, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the console readable
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            html = (GUI_DIR / "index.html").read_bytes()
            return self._send(200, html, "text/html; charset=utf-8")

        if path == "/api/meta":
            return self._json(_meta())

        if path == "/api/events":
            query = self.path.split("?", 1)[1] if "?" in self.path else ""
            since = 0
            for part in query.split("&"):
                if part.startswith("since="):
                    since = int(part[6:] or 0)
            events, running, run_dir, error = SESSION.since(since)
            return self._json(
                {
                    "events": events,
                    "next": since + len(events),
                    "running": running,
                    "run_dir": run_dir,
                    "error": error,
                }
            )

        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")

        if path == "/api/run":
            with SESSION.lock:
                busy = SESSION.running
            if busy:
                return self._json({"error": "a run is already in progress"}, 409)
            if not payload.get("scenario") and len(payload.get("agents", [])) < 2:
                return self._json({"error": "select at least 2 agents"}, 400)
            _start_run(payload)
            return self._json({"ok": True})

        if path == "/api/wipe":
            agent = payload.get("agent")
            scope = payload.get("scope", "all")
            with SESSION.lock:
                memories = dict(SESSION.memories)
                running = SESSION.running
                gi, rd = SESSION.game_index, SESSION.round
            if not memories:
                return self._json({"error": "no run in progress to wipe"}, 409)
            if not running:
                # The logs are already written. Wiping now would clear memory
                # that nothing will read again, and leave no trace in the
                # record -- so refuse rather than appear to do something.
                return self._json(
                    {"error": "run already finished — a wipe now would not affect "
                              "any decision or appear in the logs"},
                    409,
                )

            targets = [memories[agent]] if agent in memories else list(memories.values())
            if agent and agent not in memories:
                return self._json({"error": f"unknown agent {agent!r}"}, 404)

            events = [
                m.wipe(scope=scope, game_index=gi, round_no=rd, source="gui")
                for m in targets
            ]
            for e in events:
                SESSION.emit(e)
            return self._json({"ok": True, "wiped": [e["agent"] for e in events]})

        if path == "/api/stop":
            SESSION.cancelled = True
            return self._json({"ok": True})

        return self._json({"error": "not found"}, 404)


DEFAULT_PORT = 8765


def port_is_free(host: str, port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def free_ports(host: str, start: int, count: int = 3) -> list[int]:
    found, port = [], start
    while len(found) < count and port < start + 60:
        if port_is_free(host, port):
            found.append(port)
        port += 1
    return found


def who_has_it(port: int) -> str:
    """Best-effort: name the process holding a port, so the clash is explicable."""
    import glob
    import os

    try:
        target = f"{port:04X}"
        inodes = set()
        for table in ("/proc/net/tcp", "/proc/net/tcp6"):
            try:
                for line in open(table).read().splitlines()[1:]:
                    f = line.split()
                    if f[1].split(":")[1] == target and f[3] == "0A":  # 0A = LISTEN
                        inodes.add(f[9])
            except OSError:
                pass
        for fd in glob.glob("/proc/[0-9]*/fd/*"):
            try:
                if os.readlink(fd).strip("socket:[]") in inodes:
                    pid = fd.split("/")[2]
                    cmd = open(f"/proc/{pid}/cmdline").read().replace("\0", " ").strip()
                    return f"pid {pid} — {cmd[:70]}"
            except OSError:
                continue
    except Exception:  # noqa: BLE001 - diagnostics must never break startup
        pass
    return ""


def choose_port(host: str, requested: int | None, interactive: bool) -> int:
    """Settle on a port, asking when there is a person to ask.

    `--port N` is an explicit instruction, so it is honoured without a prompt.
    Otherwise, in a terminal, offer a choice -- a silent default is the reason
    a busy port turns into a confusing crash rather than a decision.
    """
    if requested is not None:
        if port_is_free(host, requested):
            return requested
        holder = who_has_it(requested)
        raise SystemExit(
            f"Port {requested} is already in use"
            + (f"\n  held by: {holder}" if holder else "")
            + f"\n  free nearby: {', '.join(str(p) for p in free_ports(host, requested)) or 'none found'}"
            + f"\n  try: python3 -m dollar_auction gui --port <port>"
        )

    if not interactive:
        # No one to ask: take the default, or the next free port.
        return DEFAULT_PORT if port_is_free(host, DEFAULT_PORT) else free_ports(host, DEFAULT_PORT)[0]

    default_free = port_is_free(host, DEFAULT_PORT)
    if default_free:
        suggestion = DEFAULT_PORT
        print(f"Port {DEFAULT_PORT} is free.")
    else:
        holder = who_has_it(DEFAULT_PORT)
        options = free_ports(host, DEFAULT_PORT + 1)
        suggestion = options[0] if options else DEFAULT_PORT + 1
        print(f"Port {DEFAULT_PORT} is already in use.")
        if holder:
            print(f"  held by: {holder}")
        if options:
            print(f"  free nearby: {', '.join(str(p) for p in options)}")

    while True:
        try:
            answer = input(f"Which port? [{suggestion}] ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return suggestion
        if not answer:
            return suggestion
        if not answer.isdigit():
            print("  Enter a number, or press Enter to accept the suggestion.")
            continue
        port = int(answer)
        if not (1024 <= port <= 65535):
            print("  Pick something between 1024 and 65535.")
            continue
        if not port_is_free(host, port):
            holder = who_has_it(port)
            print(f"  {port} is also in use{' — ' + holder if holder else ''}. Try another.")
            continue
        return port


def serve(
    host: str = "127.0.0.1",
    port: int | None = None,
    open_browser: bool = True,
    interactive: bool | None = None,
) -> None:
    if interactive is None:
        interactive = sys.stdin.isatty()
    port = choose_port(host, port, interactive)

    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError as e:
        # Only reachable if something grabbed the port between check and bind.
        raise SystemExit(f"cannot bind {host}:{port} — {e}") from None

    display_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    url = f"http://{display_host}:{port}/"
    print(f"Dollar auction GUI: {url}")

    if host not in ("127.0.0.1", "localhost"):
        # Opt-in only. No authentication, and a run on a live provider spends
        # real money, so this must be a deliberate choice on a trusted network.
        import socket

        try:
            lan = socket.gethostbyname(socket.gethostname())
            print(f"  also reachable on this machine's network at http://{lan}:{port}/")
        except OSError:
            pass
        print("  WARNING: bound beyond loopback. No authentication — anyone who can")
        print("  reach this port can start runs that spend your API credits.")

    print("(press Ctrl-C to stop)")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
