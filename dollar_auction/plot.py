"""Hand-rolled SVG charts — no matplotlib, no pip.

Two charts per run:
  escalation.svg  bid vs. turn, one line per agent, with the item's value drawn
                  as a reference line. Everything above that line is money the
                  bidders are burning.
  payoffs.svg     final payoff per agent, zero-baselined.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .engine import GameRules
from .runner import read_event_log

# Colour-blind-safe categorical palette, ordered for maximum separation.
PALETTE = [
    "#4269d0", "#efb118", "#ff725c", "#6cc5b0", "#3ca951", "#ff8ab7",
    "#a463f2", "#97bbf5", "#9c6b4e", "#9498a0", "#1f77b4", "#d62728",
    "#2ca02c", "#e377c2", "#8c564b", "#7f7f7f",
]

W, H = 900, 480
PAD_L, PAD_R, PAD_T, PAD_B = 70, 190, 40, 55

CSS = """
  .bg   { fill: #ffffff; }
  .axis { stroke: #c8ccd4; stroke-width: 1; }
  .grid { stroke: #eceef2; stroke-width: 1; }
  .lbl  { font: 12px system-ui, sans-serif; fill: #4a4f58; }
  .ttl  { font: 600 15px system-ui, sans-serif; fill: #1c1f24; }
  .ref  { stroke: #d1495b; stroke-width: 1.5; stroke-dasharray: 5 4; }
  .refl { font: 11px system-ui, sans-serif; fill: #d1495b; }
  @media (prefers-color-scheme: dark) {
    .bg   { fill: #16181d; }
    .axis { stroke: #464b55; }
    .grid { stroke: #24272e; }
    .lbl  { fill: #a9b0bb; }
    .ttl  { fill: #f0f2f5; }
  }
"""


def _esc(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def _frame(title: str, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'role="img" aria-label="{_esc(title)}">'
        f"<style>{CSS}</style>"
        f'<rect class="bg" width="{W}" height="{H}"/>'
        f'<text class="ttl" x="{PAD_L}" y="24">{_esc(title)}</text>'
        f"{body}</svg>\n"
    )


def escalation_svg(games: list[tuple[dict, list[dict], dict]], rules: GameRules) -> str:
    """Bid trajectories. Multiple games are overlaid, the first at full opacity."""
    series: list[tuple[str, list[tuple[int, float]], int]] = []
    names: list[str] = []
    for gi, (_, events, _) in enumerate(games):
        by_agent: dict[str, list[tuple[int, float]]] = {}
        for e in events:
            if e["action"] == "BID" and e.get("bid") is not None:
                by_agent.setdefault(e["agent"], []).append((e["turn"], float(e["bid"])))
        for name, pts in by_agent.items():
            if name not in names:
                names.append(name)
            series.append((name, pts, gi))

    if not series:
        return _frame("Escalation — no bids recorded", "")

    max_turn = max(t for _, pts, _ in series for t, _ in pts)
    max_bid = max(max(b for _, b in pts) for _, pts, _ in series)
    y_max = max(max_bid, rules.item_value) * 1.12
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B

    def x(turn: float) -> float:
        return PAD_L + (turn / max(max_turn, 1)) * plot_w

    def y(bid: float) -> float:
        return PAD_T + plot_h - (bid / y_max) * plot_h

    parts: list[str] = []

    # Gridlines + y labels.
    for i in range(6):
        val = y_max * i / 5
        yy = y(val)
        parts.append(f'<line class="grid" x1="{PAD_L}" y1="{yy:.1f}" x2="{PAD_L + plot_w}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="lbl" x="{PAD_L - 10}" y="{yy + 4:.1f}" text-anchor="end">${val:.0f}</text>')

    parts.append(f'<line class="axis" x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{PAD_L + plot_w}" y2="{PAD_T + plot_h}"/>')
    parts.append(f'<line class="axis" x1="{PAD_L}" y1="{PAD_T}" x2="{PAD_L}" y2="{PAD_T + plot_h}"/>')

    # x labels.
    for i in range(6):
        turn = max_turn * i / 5
        xx = x(turn)
        parts.append(f'<text class="lbl" x="{xx:.1f}" y="{PAD_T + plot_h + 20:.1f}" text-anchor="middle">{turn:.0f}</text>')
    parts.append(
        f'<text class="lbl" x="{PAD_L + plot_w / 2:.1f}" y="{H - 14}" text-anchor="middle">turn</text>'
    )

    # Item value reference line — the break-even frontier.
    vy = y(rules.item_value)
    parts.append(f'<line class="ref" x1="{PAD_L}" y1="{vy:.1f}" x2="{PAD_L + plot_w}" y2="{vy:.1f}"/>')
    parts.append(f'<text class="refl" x="{PAD_L + 6}" y="{vy - 6:.1f}">item value ${rules.item_value:.0f}</text>')

    colour = {name: PALETTE[i % len(PALETTE)] for i, name in enumerate(names)}
    for name, pts, gi in series:
        pts = sorted(pts)
        d = " ".join(f"{'M' if i == 0 else 'L'}{x(t):.1f},{y(b):.1f}" for i, (t, b) in enumerate(pts))
        opacity = 1.0 if gi == 0 else 0.25
        parts.append(
            f'<path d="{d}" fill="none" stroke="{colour[name]}" stroke-width="2" '
            f'stroke-linejoin="round" opacity="{opacity}"/>'
        )
        if gi == 0:
            for t, b in pts:
                parts.append(f'<circle cx="{x(t):.1f}" cy="{y(b):.1f}" r="3" fill="{colour[name]}"/>')

    # Legend.
    for i, name in enumerate(names):
        ly = PAD_T + 8 + i * 20
        parts.append(f'<rect x="{W - PAD_R + 14}" y="{ly - 8}" width="11" height="11" rx="2" fill="{colour[name]}"/>')
        parts.append(f'<text class="lbl" x="{W - PAD_R + 32}" y="{ly + 1}">{_esc(name)}</text>')

    return _frame("Escalation: bids over the course of the auction", "".join(parts))


def payoff_svg(games: list[tuple[dict, list[dict], dict]]) -> str:
    totals: dict[str, float] = {}
    count = 0
    for _, _, footer in games:
        if not footer:
            continue
        count += 1
        for name, payoff in footer.get("payoffs", {}).items():
            totals[name] = totals.get(name, 0.0) + float(payoff)

    if not totals or count == 0:
        return _frame("Payoffs — no results recorded", "")

    means = {n: v / count for n, v in totals.items()}
    names = sorted(means, key=lambda n: means[n], reverse=True)

    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    hi = max(max(means.values()), 0.0)
    lo = min(min(means.values()), 0.0)
    span = (hi - lo) or 1.0
    pad = span * 0.1
    hi, lo = hi + pad, lo - pad
    span = hi - lo

    def y(v: float) -> float:
        return PAD_T + plot_h - ((v - lo) / span) * plot_h

    parts: list[str] = []
    for i in range(6):
        val = lo + span * i / 5
        yy = y(val)
        parts.append(f'<line class="grid" x1="{PAD_L}" y1="{yy:.1f}" x2="{PAD_L + plot_w}" y2="{yy:.1f}"/>')
        parts.append(f'<text class="lbl" x="{PAD_L - 10}" y="{yy + 4:.1f}" text-anchor="end">${val:.0f}</text>')

    zero = y(0.0)
    parts.append(f'<line class="axis" x1="{PAD_L}" y1="{zero:.1f}" x2="{PAD_L + plot_w}" y2="{zero:.1f}"/>')

    slot = plot_w / max(len(names), 1)
    bar_w = min(slot * 0.62, 54)
    for i, name in enumerate(names):
        v = means[name]
        cx = PAD_L + slot * (i + 0.5)
        top = y(max(v, 0.0))
        height = abs(y(v) - zero)
        fill = "#3ca951" if v >= 0 else "#d1495b"
        parts.append(
            f'<rect x="{cx - bar_w / 2:.1f}" y="{top:.1f}" width="{bar_w:.1f}" '
            f'height="{max(height, 1):.1f}" rx="3" fill="{fill}"/>'
        )
        label_y = top - 7 if v >= 0 else top + height + 15
        parts.append(f'<text class="lbl" x="{cx:.1f}" y="{label_y:.1f}" text-anchor="middle">${v:.0f}</text>')
        parts.append(
            f'<text class="lbl" x="{cx:.1f}" y="{PAD_T + plot_h + 22:.1f}" text-anchor="middle" '
            f'transform="rotate(-18 {cx:.1f} {PAD_T + plot_h + 22:.1f})">{_esc(name)}</text>'
        )

    title = "Final payoff by agent" + (f" (mean of {count} games)" if count > 1 else "")
    return _frame(title, "".join(parts))


def write_charts(run_dir: Path, log_paths: Iterable[Path], rules: GameRules) -> None:
    games = [read_event_log(p) for p in sorted(log_paths)]
    (run_dir / "escalation.svg").write_text(escalation_svg(games, rules))
    (run_dir / "payoffs.svg").write_text(payoff_svg(games))
