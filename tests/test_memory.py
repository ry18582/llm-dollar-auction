"""Memory: independence, isolation, horizon, wipes, and visible effect."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dollar_auction.memory import (
    AgentMemory,
    GameRecall,
    MemoryConfig,
    Turn,
    build_memories,
)
from dollar_auction.runner import run_experiment


def mem(**kw) -> AgentMemory:
    return AgentMemory("A", config=MemoryConfig(**kw))


def recall(i: int, payoff: float) -> GameRecall:
    return GameRecall(game_index=i, item_value=100.0, final_price=150.0,
                      my_committed=abs(payoff), my_payoff=payoff, won=False)


def turn(r: int, bid: float, reason: str = "", bidder: str = "ESFP") -> Turn:
    return Turn(game_index=0, round=r, standing_bid=bid - 5, standing_bidder=bidder,
                action="BID", bid=bid, reason=reason)


class TestSwitchesAreIndependent(unittest.TestCase):
    def test_off_means_nothing_is_retained(self):
        m = mem(within_game=False, cross_game=False)
        m.record_turn(turn(1, 10.0))
        m.record_game(recall(0, -50.0))

        self.assertEqual(m.turns, [])
        self.assertEqual(m.history, [])
        self.assertEqual(m.prompt_block(), "")

    def test_within_game_does_not_enable_cross_game(self):
        m = mem(within_game=True, cross_game=False)
        m.record_turn(turn(1, 10.0))
        m.record_game(recall(0, -50.0))

        self.assertEqual(len(m.turns), 1)
        self.assertEqual(m.history, [])
        self.assertNotIn("previous auctions", m.prompt_block())

    def test_cross_game_does_not_enable_within_game(self):
        m = mem(within_game=False, cross_game=True)
        m.record_turn(turn(1, 10.0))
        m.record_game(recall(0, -50.0))

        self.assertEqual(m.turns, [])
        self.assertEqual(len(m.history), 1)
        self.assertIn("previous auctions", m.prompt_block())

    def test_within_game_memory_does_not_survive_the_game(self):
        m = mem(within_game=True, cross_game=True)
        m.record_turn(turn(1, 10.0))
        m.record_game(recall(0, -50.0))
        m.start_game()

        self.assertEqual(m.turns, [])        # cleared
        self.assertEqual(len(m.history), 1)  # kept

    def test_memory_is_private_to_its_owner(self):
        mems = build_memories(["A", "B"], within_game=True, cross_game=True)
        mems["A"].record_turn(turn(1, 10.0))

        self.assertEqual(len(mems["A"].turns), 1)
        self.assertEqual(mems["B"].turns, [])


class TestTranscriptContent(unittest.TestCase):
    """Session-style memory must hold the agent's own words and public facts only."""

    def test_transcript_replays_the_agents_own_reasoning(self):
        m = mem(within_game=True, mode="transcript")
        m.record_turn(turn(2, 15.0, reason="cheap enough to stay in"))
        block = m.prompt_block()

        self.assertIn("Round 2", block)
        self.assertIn("You bid $15", block)
        self.assertIn("cheap enough to stay in", block)

    def test_transcript_includes_the_public_table_but_no_rival_reasoning(self):
        m = mem(within_game=True, mode="transcript")
        m.record_turn(turn(3, 20.0, reason="my own thinking", bidder="ESFP"))
        block = m.prompt_block()

        # Public: who held the standing bid. That is visible to everyone.
        self.assertIn("ESFP", block)
        # Private: only this agent's own stated reason may appear.
        self.assertIn("my own thinking", block)
        self.assertNotIn("Reason:", block)

    def test_summary_mode_omits_reasoning(self):
        m = mem(within_game=True, mode="summary")
        m.record_turn(turn(2, 15.0, reason="secret sauce"))
        block = m.prompt_block()

        self.assertIn("Round 2", block)
        self.assertNotIn("secret sauce", block)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            MemoryConfig(mode="telepathy")


class TestHorizon(unittest.TestCase):
    def test_keep_rounds_limits_what_is_shown(self):
        m = mem(within_game=True, mode="transcript", keep_rounds=3)
        for r in range(1, 11):
            m.record_turn(turn(r, r * 5.0, reason=f"round {r} thought"))
        block = m.prompt_block()

        self.assertIn("round 10 thought", block)
        self.assertIn("round 8 thought", block)
        self.assertNotIn("round 7 thought", block)   # beyond the horizon
        self.assertIn("no longer remembered", block)  # and says so

    def test_keep_games_limits_history(self):
        m = mem(cross_game=True, keep_games=2)
        for i in range(5):
            m.record_game(recall(i, -10.0 * i))
        block = m.prompt_block()

        self.assertIn("Auction 5", block)
        self.assertNotIn("Auction 1", block)
        self.assertIn("Across 5 auction(s)", block)  # totals still reflect everything

    def test_zero_horizon_means_unlimited(self):
        m = mem(within_game=True, mode="transcript", keep_rounds=0)
        for r in range(1, 21):
            m.record_turn(turn(r, r * 5.0, reason=f"round {r} thought"))

        self.assertIn("round 1 thought", m.prompt_block())


class TestWipe(unittest.TestCase):
    def test_wipe_clears_everything_by_default(self):
        m = mem(within_game=True, cross_game=True)
        m.record_turn(turn(1, 10.0))
        m.record_game(recall(0, -50.0))
        m.wipe()

        self.assertEqual(m.turns, [])
        self.assertEqual(m.history, [])
        self.assertEqual(m.prompt_block(), "")

    def test_wipe_is_recorded_with_what_it_destroyed(self):
        m = mem(within_game=True, cross_game=True)
        m.record_turn(turn(1, 10.0))
        m.record_turn(turn(2, 15.0))
        m.record_game(recall(0, -50.0))
        event = m.wipe(game_index=2, round_no=4, source="gui")

        self.assertEqual(event["type"], "memory_wipe")
        self.assertEqual(event["agent"], "A")
        self.assertEqual(event["cleared_turns"], 2)
        self.assertEqual(event["cleared_games"], 1)
        self.assertEqual(event["game_index"], 2)
        self.assertEqual(event["round"], 4)
        self.assertEqual(event["source"], "gui")
        self.assertEqual(m.wipes, [event])

    def test_scoped_wipe_leaves_the_other_channel_alone(self):
        m = mem(within_game=True, cross_game=True)
        m.record_turn(turn(1, 10.0))
        m.record_game(recall(0, -50.0))

        m.wipe(scope="within_game")
        self.assertEqual(m.turns, [])
        self.assertEqual(len(m.history), 1)

    def test_wiping_one_agent_does_not_touch_another(self):
        mems = build_memories(["A", "B"], within_game=True)
        for name in ("A", "B"):
            mems[name].record_turn(turn(1, 10.0))
        mems["A"].wipe()

        self.assertEqual(mems["A"].turns, [])
        self.assertEqual(len(mems["B"].turns), 1)


class TestMemoryChangesBehaviour(unittest.TestCase):
    """The switches must move the numbers, or the GUI toggle is a lie."""

    def _run(self, within_game: bool, cross_game: bool, tmp: str) -> dict:
        exp = {
            "name": f"t{int(within_game)}{int(cross_game)}",
            "roster": "mbti",
            "agents": ["estp", "esfp", "esfj", "intj", "istj", "enfp"],
            "seed": 7, "repeats": 5,
            "rules": {"item_value": 100.0, "increment": 5.0, "default_budget": 500.0},
            "memory": {"within_game": within_game, "cross_game": cross_game},
            "overrides": {"model": {"provider": "mock"}},
        }
        run_dir = run_experiment(exp, runs_dir=Path(tmp), quiet=True)
        return json.loads((run_dir / "metrics.json").read_text())

    def test_cross_game_memory_lowers_prices_over_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            blind = self._run(False, False, tmp)
            learning = self._run(False, True, tmp)

        blind_games = [g["winning_price"] for g in blind["games"]]
        learn_games = [g["winning_price"] for g in learning["games"]]

        self.assertEqual(blind_games[0], blind_games[-1])   # nothing trends
        self.assertLess(learn_games[-1], learn_games[0])    # burned agents bid less
        self.assertLess(
            learning["aggregate"]["mean_winning_price"],
            blind["aggregate"]["mean_winning_price"],
        )

    def test_each_switch_moves_the_result_on_its_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            conditions = {
                (w, c): self._run(w, c, tmp)["aggregate"]["mean_winning_price"]
                for w in (False, True) for c in (False, True)
            }

        baseline = conditions[(False, False)]
        self.assertLess(conditions[(True, False)], baseline, "within-game had no effect")
        self.assertLess(conditions[(False, True)], baseline, "cross-game had no effect")
        self.assertLess(conditions[(True, True)], baseline)


class TestWipeIsPersisted(unittest.TestCase):
    def test_a_wipe_reaches_the_game_log(self):
        """A run must be interpretable later, so wipes go in the log."""
        captured = {}
        exp = {
            "name": "wipe_log", "roster": "archetypes",
            "agents": ["ego_defender", "sunk_cost_escalator"],
            "seed": 7, "repeats": 1,
            "rules": {"item_value": 100.0, "increment": 25.0, "default_budget": 200.0},
            "memory": {"within_game": True, "cross_game": True},
            "overrides": {"model": {"provider": "mock"}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            def on_ready(memories):
                captured.update(memories)
                memories["Ego_Defender"].wipe(source="test")

            run_dir = run_experiment(exp, runs_dir=Path(tmp), quiet=True, on_ready=on_ready)
            lines = (run_dir / "game_000.jsonl").read_text().splitlines()

        wipes = [json.loads(x) for x in lines if '"memory_wipe"' in x]
        self.assertEqual(len(wipes), 1)
        self.assertEqual(wipes[0]["agent"], "Ego_Defender")
        self.assertEqual(wipes[0]["source"], "test")


if __name__ == "__main__":
    unittest.main()
