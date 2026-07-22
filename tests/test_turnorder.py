"""Turn order: determinism, coverage, and that it is a real control."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dollar_auction.runner import run_experiment
from dollar_auction.turnorder import order_for_game

NAMES = ["A", "B", "C", "D"]


class TestTurnOrder(unittest.TestCase):
    def test_fixed_never_moves(self):
        for g in range(5):
            self.assertEqual(order_for_game(NAMES, policy="fixed", game_index=g), NAMES)

    def test_rotate_advances_one_seat_per_game(self):
        self.assertEqual(order_for_game(NAMES, policy="rotate", game_index=0), ["A","B","C","D"])
        self.assertEqual(order_for_game(NAMES, policy="rotate", game_index=1), ["B","C","D","A"])
        self.assertEqual(order_for_game(NAMES, policy="rotate", game_index=3), ["D","A","B","C"])
        self.assertEqual(order_for_game(NAMES, policy="rotate", game_index=4), ["A","B","C","D"])

    def test_rotate_gives_every_agent_every_seat(self):
        seats = {n: set() for n in NAMES}
        for g in range(len(NAMES)):
            for seat, name in enumerate(order_for_game(NAMES, policy="rotate", game_index=g)):
                seats[name].add(seat)
        for name, occupied in seats.items():
            self.assertEqual(occupied, set(range(len(NAMES))), f"{name} missed a seat")

    def test_every_policy_is_a_permutation(self):
        for policy in ("fixed", "rotate", "shuffle"):
            for g in range(4):
                order = order_for_game(NAMES, policy=policy, game_index=g, seed=3)
                self.assertEqual(sorted(order), sorted(NAMES), policy)

    def test_shuffle_is_stable_across_processes(self):
        """random.Random seeded off hash() would pass in-process and fail here."""
        code = (
            "import sys; sys.path.insert(0, %r);"
            "from dollar_auction.turnorder import order_for_game;"
            "print(','.join(order_for_game(%r, policy='shuffle', game_index=2, seed=9)))"
            % (str(Path(__file__).resolve().parent.parent), NAMES)
        )
        runs = {
            subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, check=True,
                env={"PYTHONHASHSEED": str(seed)},
            ).stdout.strip()
            for seed in ("0", "1", "12345")
        }
        self.assertEqual(len(runs), 1, f"shuffle differed across processes: {runs}")

    def test_unknown_policy_is_rejected(self):
        with self.assertRaises(ValueError):
            order_for_game(NAMES, policy="random")


class TestSeatPositionMatters(unittest.TestCase):
    """If seat position had no effect, rotating seats would be pointless."""

    AGENTS = ["estp", "esfp", "esfj", "enfp", "intj", "istj"]

    def _run(self, agents, tmp, policy="fixed"):
        exp = {
            "name": "seat", "roster": "mbti", "agents": agents,
            "seed": 7, "repeats": 1, "turn_order": policy,
            "rules": {"item_value": 100.0, "increment": 5.0, "default_budget": 500.0},
            "memory": {"within_game": False, "cross_game": False},
            "overrides": {"model": {"provider": "mock"}},
        }
        d = run_experiment(exp, runs_dir=Path(tmp), quiet=True)
        return json.loads((d / "metrics.json").read_text())["games"][0]

    def test_seating_changes_the_outcome_at_a_fixed_seed(self):
        # Same agents, same seed, same everything — only the seating differs.
        rotated = self.AGENTS[2:] + self.AGENTS[:2]
        with tempfile.TemporaryDirectory() as tmp:
            a = self._run(self.AGENTS, tmp)
            b = self._run(rotated, tmp)

        self.assertNotEqual(
            (a["winner"], a["winning_price"], a["rounds"]),
            (b["winner"], b["winning_price"], b["rounds"]),
            "seat order had no effect at all — the rotate control would be pointless",
        )

    def test_a_run_is_reproducible_under_every_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            for policy in ("fixed", "rotate", "shuffle"):
                first = self._run(self.AGENTS, tmp, policy)
                again = self._run(self.AGENTS, tmp, policy)
                self.assertEqual(
                    (first["winner"], first["winning_price"]),
                    (again["winner"], again["winning_price"]),
                    f"{policy} was not reproducible",
                )


if __name__ == "__main__":
    unittest.main()
