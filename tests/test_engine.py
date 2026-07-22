"""Engine, parsing, and metrics tests. Run: python3 -m unittest discover tests"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dollar_auction.agents import parse_decision
from dollar_auction.engine import BID, EXIT, AgentState, Auction, Decision, GameRules
from dollar_auction.metrics import game_metrics


def rules(**kw):
    base = dict(item_value=100.0, increment=5.0, default_budget=500.0, max_rounds=60)
    base.update(kw)
    return GameRules(**base)


def auction(names, budgets=None, **rule_kw):
    r = rules(**rule_kw)
    budgets = budgets or {}
    states = [AgentState(name=n, budget=budgets.get(n, r.default_budget)) for n in names]
    return Auction(r, states), r


class TestRules(unittest.TestCase):
    def test_top_two_pay_and_only_top_two(self):
        a, r = auction(["A", "B", "C"])
        # A bids 5, B bids 10, C exits, A bids 15, B exits.
        script = {"A": [BID, BID], "B": [BID, EXIT], "C": [EXIT]}

        def decide(_auction, name):
            return Decision(script[name].pop(0) if script[name] else EXIT)

        result = a.run(decide)
        self.assertEqual(result.winner, "A")
        self.assertEqual(result.winning_price, 15.0)
        self.assertEqual(result.runner_up, "B")
        self.assertEqual(result.payoffs["A"], 85.0)   # 100 - 15
        self.assertEqual(result.payoffs["B"], -10.0)  # pays its standing bid
        self.assertEqual(result.payoffs["C"], 0.0)    # never bid, pays nothing

    def test_standing_bidder_is_skipped(self):
        a, _ = auction(["A", "B"])
        turns = []

        def decide(_auction, name):
            turns.append(name)
            return BID_ONCE(name, turns)

        def BID_ONCE(name, turns):
            return Decision(BID) if turns.count(name) <= 2 else Decision(EXIT)

        a.run(decide)
        # No agent is ever asked twice in a row while it holds the high bid.
        for i in range(1, len(turns)):
            self.assertNotEqual(turns[i], turns[i - 1])

    def test_exit_is_permanent(self):
        a, _ = auction(["A", "B", "C"])
        asked = []

        def decide(_auction, name):
            asked.append(name)
            return Decision(EXIT) if name == "C" else Decision(BID)

        a.run(decide)
        self.assertEqual(asked.count("C"), 1)

    def test_budget_forces_exit(self):
        a, _ = auction(["A", "B"], budgets={"A": 500.0, "B": 12.0})

        def decide(_auction, _name):
            return Decision(BID)

        result = a.run(decide)
        self.assertEqual(result.agents["B"].exit_reason, "broke")
        self.assertLessEqual(result.agents["B"].committed, 12.0)

    def test_bid_cap_stops_runaway(self):
        a, r = auction(["A", "B"], max_bid_multiple=2.0)

        def decide(_auction, _name):
            return Decision(BID)

        result = a.run(decide)
        self.assertLessEqual(result.winning_price, r.item_value * 2.0)
        self.assertIn(result.stop_reason, ("one_bidder_left", "no_challengers", "max_rounds"))

    def test_agent_that_cannot_afford_never_commits(self):
        # A bids first at 5.00, so B's cheapest entry is 10.00 — out of reach.
        a, _ = auction(["A", "B"], budgets={"A": 500.0, "B": 7.0})
        result = a.run(lambda _a, _n: Decision(BID))

        self.assertEqual(result.agents["B"].committed, 0.0)
        self.assertEqual(result.agents["B"].exit_reason, "broke")
        self.assertEqual(result.payoffs["B"], 0.0)

    def test_needs_two_agents(self):
        with self.assertRaises(ValueError):
            Auction(rules(), [AgentState("solo", 100.0)])


class TestPayoffPreview(unittest.TestCase):
    def test_exit_payoff_matches_realised_payoff(self):
        """The number shown to an agent must be the number it actually gets."""
        a, _ = auction(["A", "B"])
        script = {"A": [BID, BID], "B": [BID]}
        previews = {}

        def decide(auction_, name):
            previews[name] = auction_.state_snapshot(name)["you"]["payoff_if_you_exit_now"]
            return Decision(script[name].pop(0) if script[name] else EXIT)

        result = a.run(decide)
        # B's last preview before exiting is what it in fact ends up with.
        self.assertEqual(previews["B"], result.payoffs["B"])


class TestParsing(unittest.TestCase):
    def test_canonical(self):
        parsed = parse_decision("Decision: BID\nReason: I want it\nConfidence: 80")
        self.assertEqual(parsed, ("BID", "I want it", 80))

    def test_case_and_markdown_noise(self):
        parsed = parse_decision("**Decision:** exit\n**Reason:** enough\n**Confidence:** 12")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed[0], "EXIT")
        self.assertEqual(parsed[2], 12)

    def test_bare_token_accepted_when_unambiguous(self):
        self.assertEqual(parse_decision("I will BID.")[0], "BID")

    def test_bare_token_rejected_when_ambiguous(self):
        self.assertIsNone(parse_decision("I could BID or EXIT here."))

    def test_confidence_clamped(self):
        self.assertEqual(parse_decision("Decision: BID\nConfidence: 999")[2], 100)

    def test_garbage_is_none(self):
        self.assertIsNone(parse_decision("I'd rather not say."))
        self.assertIsNone(parse_decision(""))


class TestMetrics(unittest.TestCase):
    def test_escalation_is_detected(self):
        a, r = auction(["A", "B"], max_bid_multiple=1.5)
        result = a.run(lambda _a, _n: Decision(BID))
        m = game_metrics(result, r)

        self.assertGreater(m["escalation_ratio"], 1.0)
        self.assertGreater(m["auctioneer_profit"], 0.0)
        for name in ("A", "B"):
            self.assertIsNotNone(m["agents"][name]["first_irrational_round"])

    def test_no_escalation_when_everyone_stops_early(self):
        a, r = auction(["A", "B"])
        script = {"A": [BID], "B": [EXIT]}
        result = a.run(lambda _a, n: Decision(script[n].pop(0) if script[n] else EXIT))
        m = game_metrics(result, r)

        self.assertLess(m["escalation_ratio"], 1.0)
        self.assertIsNone(m["agents"]["A"]["first_irrational_round"])


if __name__ == "__main__":
    unittest.main()
