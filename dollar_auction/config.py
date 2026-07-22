"""Experiment and agent configuration.

JSON rather than YAML on purpose -- PyYAML is a third-party dependency and this
project has none. An experiment file looks like:

    {
      "name": "mvp_mock",
      "seed": 7,
      "repeats": 1,
      "rules": {"item_value": 100, "increment": 5, "default_budget": 500},
      "roster": "archetypes",
      "agents": ["rational_economist", "ego_defender", ...],
      "overrides": {"model": {"provider": "mock"}}
    }
"""

from __future__ import annotations

import json
from pathlib import Path

from .engine import GameRules

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "configs"


class ConfigError(ValueError):
    pass


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"no such config: {path}") from None
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path} is not valid JSON: {e}") from None


def load_experiment(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists() and not path.is_absolute():
        candidate = CONFIG_DIR / "experiments" / path.name
        if candidate.exists():
            path = candidate
    exp = load_json(path)

    for key in ("name", "roster", "agents"):
        if key not in exp:
            raise ConfigError(f"{path}: experiment is missing required key {key!r}")

    exp.setdefault("seed", 0)
    exp.setdefault("repeats", 1)
    exp.setdefault("rules", {})
    exp.setdefault("overrides", {})
    exp.setdefault("turn_order", "rotate")
    exp["_path"] = str(path)
    return exp


def load_roster(roster: str, names: list[str], overrides: dict) -> list[dict]:
    """Load named agent configs from configs/agents/<roster>/<name>.json."""
    directory = CONFIG_DIR / "agents" / roster
    if not directory.is_dir():
        available = sorted(p.name for p in (CONFIG_DIR / "agents").iterdir() if p.is_dir())
        raise ConfigError(f"no roster {roster!r}; available: {available}")

    agents = []
    for name in names:
        cfg = load_json(directory / f"{name}.json")
        # Overrides are shallow-merged per top-level key so an experiment can
        # swap every agent onto one provider without editing 16 files.
        for key, value in overrides.items():
            existing = cfg.get(key)
            if isinstance(value, dict) and isinstance(existing, dict):
                # Exception: a model block is only meaningful for its own
                # provider. Merging {"provider": "cli"} onto {"provider":
                # "mock", "model": "mock"} leaves model="mock", which then gets
                # handed to a CLI that has never heard of it. Switching
                # provider replaces the block outright.
                switching = (
                    key == "model"
                    and "provider" in value
                    and existing.get("provider") not in (None, value["provider"])
                )
                cfg[key] = dict(value) if switching else {**existing, **value}
            else:
                cfg[key] = value
        agents.append(cfg)

    seen = set()
    for cfg in agents:
        if cfg["name"] in seen:
            raise ConfigError(f"duplicate agent name {cfg['name']!r} in roster")
        seen.add(cfg["name"])
    return agents


def rules_from(exp: dict) -> GameRules:
    r = exp.get("rules", {})
    return GameRules(
        item_value=float(r.get("item_value", 100.0)),
        increment=float(r.get("increment", 5.0)),
        default_budget=float(r.get("default_budget", 500.0)),
        max_rounds=int(r.get("max_rounds", 60)),
        max_bid_multiple=r.get("max_bid_multiple", 5.0),
    )
