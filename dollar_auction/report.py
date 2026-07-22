"""Markdown run report."""

from __future__ import annotations

import json
from pathlib import Path


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_(none)_\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def _fmt(v, dash: str = "—") -> str:
    if v is None:
        return dash
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def build_report(manifest: dict, metrics: dict) -> str:
    exp = manifest["experiment"]
    rules = manifest["rules"]
    games = metrics["games"]
    agg = metrics["aggregate"]

    lines: list[str] = []
    lines.append(f"# Dollar auction — `{exp['name']}`\n")
    lines.append(f"Run `{manifest['run_id']}` · {manifest['created_at']}\n")

    providers = sorted({a.get("model", {}).get("provider", "mock") for a in manifest["agents"]})
    mem = exp.get("memory", {})
    on = [k for k in ("within_game", "cross_game") if mem.get(k)]
    memory = " + ".join(on) if on else "off (every auction played blind)"
    lines.append(
        f"**Setup.** {len(manifest['agents'])} agents from the `{exp['roster']}` roster, "
        f"{agg['games']} game(s), seed {exp['seed']}. Item value ${rules['item_value']:.2f}, "
        f"increment ${rules['increment']:.2f}. Provider(s): {', '.join(providers)}. "
        f"Memory: {memory}.\n"
    )

    if mem.get("cross_game") and len(games) > 1:
        drift = games[0]["winning_price"] - games[-1]["winning_price"]
        if abs(drift) > 1e-9:
            direction = "fell" if drift > 0 else "rose"
            lines.append(
                f"With cross-game memory on, the winning price {direction} from "
                f"${games[0]['winning_price']:.2f} in the first auction to "
                f"${games[-1]['winning_price']:.2f} in the last — a ${abs(drift):.2f} shift "
                f"attributable to what the agents carried between games.\n"
            )

    # -- headline --------------------------------------------------------
    ratio = agg["mean_escalation_ratio"]
    verdict = (
        f"Bidding ran **{ratio:.2f}× past the item's value** on average"
        if ratio > 1
        else f"Bidding stopped at **{ratio:.2f}× the item's value** on average"
    )
    lines.append(
        f"## Headline\n\n{verdict}, with a mean winning price of "
        f"${agg['mean_winning_price']:.2f} over {agg['mean_rounds']:.1f} rounds. "
        f"The auctioneer cleared ${agg['mean_auctioneer_profit']:.2f} per game.\n"
    )

    # -- who pays --------------------------------------------------------
    lines.append("## Who paid\n")
    lines.append(
        "Both of the top two bidders pay. The winner pays and receives the item; "
        "the runner-up pays and receives nothing. Everyone else pays nothing.\n"
    )
    rows = []
    for g in games:
        loss = g["winning_price"] - g["item_value"]
        rows.append([
            str(g["game_index"]),
            f"{g['winner']} — paid ${g['winning_price']:.2f}, got the item "
            f"(net ${g['item_value'] - g['winning_price']:+.2f})",
            f"{g['runner_up']} — paid ${g['runner_up_price']:.2f}, got nothing "
            f"(net ${-g['runner_up_price']:+.2f})",
            f"${g['auctioneer_profit']:.2f}",
        ])
        del loss
    lines.append(_table(["#", "1st — winner (pays)", "2nd — runner-up (also pays)",
                         "auctioneer profit"], rows))

    # -- per game --------------------------------------------------------
    lines.append("## Games\n")
    lines.append(
        _table(
            ["#", "winner", "price", "runner-up", "paid", "rounds", "escalation", "stop"],
            [
                [
                    str(g["game_index"]),
                    _fmt(g["winner"]),
                    f"${g['winning_price']:.2f}",
                    _fmt(g["runner_up"]),
                    f"${g['runner_up_price']:.2f}",
                    str(g["rounds"]),
                    f"{g['escalation_ratio']:.2f}×",
                    g["stop_reason"],
                ]
                for g in games
            ],
        )
    )

    # -- per agent -------------------------------------------------------
    lines.append("## Agents\n")
    lines.append(
        "`past rational` counts the rounds an agent kept bidding after its first bid "
        "above the item's value — the point from which *even winning* loses money. "
        "That is the escalation measure; payoff is not, because the winner and the "
        "runner-up can both lose badly in the same game.\n"
    )
    rows = []
    for name, m in sorted(agg["agents"].items(), key=lambda kv: -kv[1]["mean_payoff"]):
        rows.append(
            [
                name,
                str(m["wins"]),
                f"${m['mean_payoff']:.2f}",
                f"${m['worst_payoff']:.2f}",
                f"${m['mean_final_committed']:.2f}",
                f"${m['mean_overbid']:.2f}",
                f"{m['escalated_in_games']}/{m['games']}",
                _fmt(m["mean_rounds_past_rational"]),
            ]
        )
    lines.append(
        _table(
            ["agent", "wins", "mean payoff", "worst", "mean committed", "mean overbid", "escalated", "past rational"],
            rows,
        )
    )

    # -- health ----------------------------------------------------------
    forced = sum(a["forced_actions"] for g in games for a in g["agents"].values())
    errors = sum(a["errors"] for g in games for a in g["agents"].values())
    retries = sum(a["parse_retries"] for g in games for a in g["agents"].values())
    lines.append("## Run health\n")
    lines.append(
        f"- Tokens: {agg['tokens_in']:,} in / {agg['tokens_out']:,} out\n"
        f"- Forced actions (budget, cap, parse failure, provider error): {forced}\n"
        f"- Parse retries: {retries}\n"
        f"- Errors: {errors}\n"
    )
    if forced or errors:
        lines.append(
            "\n> Forced actions and errors are engine overrides, not agent choices. "
            "A high count here means the behavioural numbers above are diluted — "
            "check the event logs before reading anything into them.\n"
        )

    lines.append("\n## Artifacts\n")
    lines.append(
        "- `escalation.svg` — bid trajectories against the item's value\n"
        "- `payoffs.svg` — final payoff per agent\n"
        "- `game_*.jsonl` — full event log (every decision, reason, confidence, token count)\n"
        "- `metrics.json` — every number in this report\n"
        "- `manifest.json` — exact configs and seed used\n"
    )

    return "\n".join(lines)


def write_report(run_dir: Path, manifest: dict, metrics: dict) -> Path:
    path = run_dir / "report.md"
    path.write_text(build_report(manifest, metrics))
    return path


def rebuild_report(run_dir: Path) -> Path:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    metrics = json.loads((run_dir / "metrics.json").read_text())
    return write_report(run_dir, manifest, metrics)
