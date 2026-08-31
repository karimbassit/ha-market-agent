from __future__ import annotations

import unittest

from market_agent.planner import build_deployment_plan


POLICY = {
    "core_target_weight": 0.80,
    "minimum_new_core_weight": 0.80,
    "core_tickers": ["VUAG.L", "VWRP.L", "VALL.L"],
    "risk_targets": {"foundation": 0.80, "medium_high": 0.15, "very_high": 0.05},
    "risk_tickers": {"foundation": ["VUAG.L", "VWRP.L", "VALL.L"], "medium_high": ["ASML.AS"], "very_high": ["RKLB"]},
    "primary_core_ticker": "VUAG.L",
    "diversifier_ticker": "VWRP.L",
    "primary_split": 0.80,
}


class PlannerTests(unittest.TestCase):
    def test_15000_plan_keeps_majority_in_broad_index_core(self) -> None:
        plan = build_deployment_plan(15000, [], POLICY)
        self.assertEqual(plan["planned_core_weight_of_new_money"], .80)
        self.assertGreater(plan["allocations"][0]["amount_gbp"], 7500)
        allocated = sum(item["amount_gbp"] for item in plan["allocations"])
        self.assertAlmostEqual(allocated + plan["reserve_gbp"], 15000)
        self.assertEqual({item["ticker"] for item in plan["allocations"]}, {"VUAG.L", "VWRP.L"})
        self.assertTrue(all(item.get("why") for item in plan["allocations"]))
        self.assertTrue(all(3 <= len(item.get("why_bullets", [])) <= 10 for item in plan["allocations"]))
        self.assertEqual([item["target_weight"] for item in plan["risk_summary"]], [.80, .15, .05])
        self.assertEqual([item["amount_gbp"] for item in plan["risk_budgets"]], [2250, 750])
        self.assertEqual(plan["alternatives_considered"][0]["ticker"], "VALL.L")

    def test_existing_vall_is_used_as_the_global_foundation_fund(self) -> None:
        positions = [{"ticker": "VALL.L", "market_value": 1000}]
        plan = build_deployment_plan(15000, positions, POLICY)
        self.assertEqual({item["ticker"] for item in plan["allocations"]}, {"VUAG.L", "VALL.L"})
        self.assertEqual(plan["alternatives_considered"], [])

    def test_broad_scan_candidates_fill_only_their_risk_budget(self) -> None:
        opportunities = [
            {"ticker": "QUALITY", "name": "Quality Co", "risk_bucket": "medium_high", "bullets": ["Profitable.", "Current filing checked.", "Valuation still matters."], "sources": []},
            {"ticker": "MOON", "name": "Moonshot Co", "risk_bucket": "very_high", "bullets": ["Large upside is possible.", "Cash burn is high.", "Most of the investment could be lost."], "sources": []},
        ]
        plan = build_deployment_plan(15000, [], POLICY, opportunities=opportunities)
        medium, very_high = plan["risk_budgets"]
        self.assertEqual(medium["candidate_allocations"][0]["amount_gbp"], 2250)
        self.assertEqual(very_high["candidate_allocations"][0]["amount_gbp"], 750)
        self.assertLessEqual(sum(item["amount_gbp"] for item in medium["candidate_allocations"]), medium["amount_gbp"])

    def test_news_may_slow_dca_but_cannot_select_tickers(self) -> None:
        plan = build_deployment_plan(
            15000,
            [],
            POLICY,
            {"pace": "cautious", "summary": "Verified macro risk.", "ticker": "MEME"},
        )
        self.assertEqual(plan["pace"], "cautious")
        self.assertTrue(all(len(item["tranches"]) == 4 for item in plan["allocations"]))
        self.assertEqual({item["ticker"] for item in plan["allocations"]}, {"VUAG.L", "VWRP.L"})


if __name__ == "__main__":
    unittest.main()
