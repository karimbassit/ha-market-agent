from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_agent.ha_runner import next_run, runtime_environment


class HomeAssistantRunnerTests(unittest.TestCase):
    def test_next_weekday_run(self) -> None:
        zone = ZoneInfo("Europe/London")
        monday = datetime(2026, 8, 24, 21, 0, tzinfo=zone)
        self.assertEqual(next_run(monday, "22:15", True).isoformat(), "2026-08-24T22:15:00+01:00")

    def test_skips_weekend(self) -> None:
        zone = ZoneInfo("Europe/London")
        friday_late = datetime(2026, 8, 28, 23, 0, tzinfo=zone)
        result = next_run(friday_late, "22:15", True)
        self.assertEqual(result.weekday(), 0)
        self.assertEqual(result.day, 31)

    def test_home_assistant_is_default_delivery(self) -> None:
        self.assertEqual(runtime_environment({})["DELIVERY_PROVIDER"], "home_assistant")

    def test_private_integrations_map_to_environment(self) -> None:
        result = runtime_environment({"trading212_enabled": True, "trading212_api_key": "key", "trading212_api_secret": "secret", "next_investment_gbp": 15000})
        self.assertEqual(result["TRADING212_ENABLED"], "True")
        self.assertEqual(result["TRADING212_API_KEY"], "key")
        self.assertEqual(result["NEXT_INVESTMENT_GBP"], "15000")


if __name__ == "__main__":
    unittest.main()
