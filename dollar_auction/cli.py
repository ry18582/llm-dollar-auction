"""Command-line entry point.

    python3 -m dollar_auction run configs/experiments/mvp_mock.json
    python3 -m dollar_auction replay runs/<run_id>
    python3 -m dollar_auction verify runs/<run_id>
    python3 -m dollar_auction report runs/<run_id>
    python3 -m dollar_auction list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import CONFIG_DIR, ConfigError, rules_from
from .replay import render, verify
from .report import rebuild_report
from .runner import RUNS_DIR, run_experiment


def _latest_run() -> Path:
    runs = sorted(p for p in RUNS_DIR.glob("*") if p.is_dir())
    if not runs:
        raise SystemExit("no runs yet — try: python3 -m dollar_auction run configs/experiments/mvp_mock.json")
    return runs[-1]


def _resolve(arg: str | None) -> Path:
    if arg in (None, "latest"):
        return _latest_run()
    path = Path(arg)
    if not path.is_dir():
        raise SystemExit(f"not a run directory: {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dollar_auction", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run an experiment")
    p_run.add_argument("experiment", help="path to an experiment JSON (or its bare name)")
    p_run.add_argument("--quiet", action="store_true")

    p_replay = sub.add_parser("replay", help="print a logged game as a transcript")
    p_replay.add_argument("run", nargs="?", default="latest")
    p_replay.add_argument("--game", type=int, default=0)

    p_verify = sub.add_parser("verify", help="check a run replays deterministically")
    p_verify.add_argument("run", nargs="?", default="latest")

    p_report = sub.add_parser("report", help="rebuild report.md from metrics.json")
    p_report.add_argument("run", nargs="?", default="latest")

    p_gui = sub.add_parser("gui", help="open the local web GUI in a browser")
    p_gui.add_argument("--port", type=int, default=8765)
    p_gui.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address (default 127.0.0.1). Use 0.0.0.0 only if WSL localhost "
             "forwarding is broken — it exposes an unauthenticated UI to your network.",
    )
    p_gui.add_argument("--no-browser", action="store_true")

    sub.add_parser("doctor", help="check API keys work before spending money")
    sub.add_parser("list", help="list available experiments and rosters")

    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            run_dir = run_experiment(args.experiment, quiet=args.quiet)
            print(f"\nrun written to {run_dir}")
            print(f"  report:  {run_dir / 'report.md'}")
            print(f"  charts:  {run_dir / 'escalation.svg'}, {run_dir / 'payoffs.svg'}")
            return 0

        if args.command == "replay":
            run_dir = _resolve(args.run)
            log = run_dir / f"game_{args.game:03d}.jsonl"
            if not log.exists():
                raise SystemExit(f"no such game log: {log}")
            print(render(log))
            return 0

        if args.command == "verify":
            run_dir = _resolve(args.run)
            manifest = json.loads((run_dir / "manifest.json").read_text())
            rules = rules_from(manifest["experiment"])
            budgets = {
                a["name"]: float(a.get("budget", rules.default_budget)) for a in manifest["agents"]
            }
            failures = 0
            for log in sorted(run_dir.glob("game_*.jsonl")):
                ok, problems = verify(log, rules, budgets)
                print(f"{log.name}: {'OK' if ok else 'DIVERGED'}")
                for p in problems:
                    print(f"    {p}")
                failures += 0 if ok else 1
            return 1 if failures else 0

        if args.command == "report":
            path = rebuild_report(_resolve(args.run))
            print(f"rewrote {path}")
            return 0

        if args.command == "gui":
            from .server import serve

            serve(host=args.host, port=args.port, open_browser=not args.no_browser)
            return 0

        if args.command == "doctor":
            from .doctor import run as run_doctor

            return run_doctor()

        if args.command == "list":
            print("experiments:")
            for p in sorted((CONFIG_DIR / "experiments").glob("*.json")):
                print(f"  {p.stem}  ({p})")
            print("\nrosters:")
            for d in sorted((CONFIG_DIR / "agents").iterdir()):
                if d.is_dir():
                    members = sorted(p.stem for p in d.glob("*.json"))
                    print(f"  {d.name}: {len(members)} agents")
                    for m in members:
                        print(f"    - {m}")
            return 0

    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
