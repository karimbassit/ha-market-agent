from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from market_agent.indicators import snapshot
from market_agent.market_data import Bar
from market_agent.signals import holding_signal, watchlist_signal


def bars(direction: float = 1.0, count: int = 260) -> list[Bar]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    output = []
    for day in range(count):
        price = 100 + direction * day * 0.2
        output.append(Bar(start + timedelta(days=day), price - 0.2, price + 0.5, price - 0.5, price, 1_000_000))
    return output


class AgentTests(unittest.TestCase):
    def test_positive_watchlist_candidate(self) -> None:
        item = snapshot("TEST", bars())
        signal = watchlist_signal(item, {"minimum_price": 2, "minimum_average_dollar_volume": 5_000_000})
        self.assertIsNotNone(signal)
        self.assertEqual(signal.action, "BUY CANDIDATE")

    def test_satellite_persistent_break_sells(self) -> None:
        item = snapshot("TEST", bars(direction=-1))
        holding = {
            "bucket": "satellite",
            "cost_basis": None,
            "sell_rules": {"below_ma200_days": 5, "max_drawdown_from_cost": None},
        }
        signal = holding_signal(holding, item)
        self.assertEqual(signal.action, "SELL NOW")

    def test_core_does_not_auto_sell(self) -> None:
        item = snapshot("CORE", bars(direction=-1))
        holding = {"bucket": "core", "cost_basis": None, "sell_rules": {"below_ma200_days": 5}}
        self.assertEqual(holding_signal(holding, item).action, "REVIEW")


if __name__ == "__main__":
    unittest.main()

