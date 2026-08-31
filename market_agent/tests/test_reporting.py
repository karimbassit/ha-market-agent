from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone

from market_agent.indicators import Snapshot
from market_agent.report import deterministic_note
from market_agent.signals import Signal
from market_agent.web_panel import _page


def sample_snapshot() -> Snapshot:
    return Snapshot(
        ticker="ASML.AS",
        source_ticker="ASML.AS",
        date="2026-08-24",
        timestamp="2026-08-24T16:35:00+00:00",
        currency="EUR",
        price=1489.8,
        change_1d=0.01,
        change_20d=0.08,
        ma20=1400,
        ma50=1350,
        ma200=1200,
        rsi14=52,
        macd=3,
        macd_signal=2,
        avg_volume_20d=1_000_000,
        avg_dollar_volume_20d=1_489_800_000,
        below_ma200_days=0,
        distance_from_52w_high=-0.05,
    )


class ReportingTests(unittest.TestCase):
    def test_note_includes_currency_and_london_timestamps(self) -> None:
        snap = sample_snapshot()
        signal = Signal("ASML.AS", "KEEP", 5, ("above 200-day trend",), "high")
        note = deterministic_note(
            datetime(2026, 8, 24, 19, 30, tzinfo=timezone.utc),
            [signal],
            [],
            {"ASML.AS": snap},
            [],
        )
        self.assertIn("24 Aug 2026, 20:30 BST", note)
        self.assertIn("€1,489.80 EUR", note)

    def test_dashboard_has_summary_and_research_tabs(self) -> None:
        snap = sample_snapshot()
        evidence = {
            "generated_at": "2026-08-24T19:30:00+00:00",
            "latest_data_at": snap.timestamp,
            "timezone": "Europe/London",
            "base_currency": "GBP",
            "signals": [{"ticker": "ASML.AS", "action": "KEEP", "reasons": ["above trend"]}],
            "snapshots": {"ASML.AS": snap.as_dict()},
            "research": [{"ticker": "ASML.AS", "action": "KEEP", "price": snap.price, "currency": "EUR", "bullets": ["Thesis: test"], "news": []}],
            "deployment_plan": {"capital_gbp": 15000, "planned_core_weight_of_new_money": .75, "projected_core_weight": .75, "pace": "normal", "pace_reason": "No verified shock.", "reserve_gbp": 3750, "allocations": [{"ticker": "VUAG.L", "role": "Primary S&P 500 core", "amount_gbp": 9000, "tranches": [{"label": "Now", "amount_gbp": 3600}]}]},
            "errors": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "report.txt").write_text("test", encoding="utf-8")
            (root / "evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
            history = root / "history"
            history.mkdir()
            (history / "20260824T193000.json").write_text(json.dumps(evidence), encoding="utf-8")
            page = _page(root / "report.txt", root / "evidence.json", history, "research", "dark").decode()
        self.assertIn('name="tab" value="today"', page)
        self.assertIn('class="nav-item active" name="tab" value="research"', page)
        self.assertIn('name="tab" value="portfolio"', page)
        self.assertIn('name="tab" value="plan"', page)
        self.assertIn("Technical research", page)
        self.assertIn("Saved locally on Home Assistant", page)
        self.assertIn("bottom-nav", page)
        self.assertIn("nav-icon", page)
        self.assertIn('<svg viewBox="0 0 24 24"', page)
        self.assertIn('class="theme-dark"', page)
        self.assertIn('aria-label="Light mode"', page)
        self.assertIn("Total portfolio value", page)
        self.assertIn("€1,489.80 EUR", page)
        self.assertIn("How much would you like to invest next?", page)
        self.assertIn('action="./plan"', page)
        self.assertIn("Your 80 / 15 / 5 plan", page)
        self.assertIn('id="run-progress"', page)
        self.assertIn("Fresh daily research", page)
        self.assertIn("VUAG.L", page)
        self.assertIn("Why add", page)
        self.assertIn("Why hold", page)
        self.assertNotIn("Buy candidates", page)
        self.assertNotIn("Add / DCA plan", page)


if __name__ == "__main__":
    unittest.main()
