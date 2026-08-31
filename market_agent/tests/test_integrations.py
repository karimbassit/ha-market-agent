from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from market_agent.llm import research_with_openai
from market_agent.trading212 import live_holdings, yahoo_ticker


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return json.dumps(self.payload).encode()


class IntegrationTests(unittest.TestCase):
    def test_trading212_ticker_mapping_and_override(self) -> None:
        self.assertEqual(yahoo_ticker("VWRP_GB_EQ"), "VWRP.L")
        self.assertEqual(yahoo_ticker("VUAGl_EQ"), "VUAG.L")
        self.assertEqual(yahoo_ticker("VWRPl_EQ"), "VWRP.L")
        self.assertEqual(yahoo_ticker("ASML_NL_EQ"), "ASML.AS")
        self.assertEqual(yahoo_ticker("ODD", {"ODD": "GOOD.L"}), "GOOD.L")

    def test_live_individual_stocks_are_not_misclassified_as_core(self) -> None:
        holdings, portfolio = live_holdings(
            [{"instrument": {"ticker": "AAPL_US_EQ", "shortName": "Apple", "currencyCode": "USD"}, "quantity": 2, "averagePricePaid": 100, "currentPrice": 125, "walletImpact": {"currency": "GBP", "currentValue": 190, "totalCost": 160, "unrealizedProfitLoss": 30, "fxImpact": -2}}]
        )
        self.assertEqual(holdings[0]["ticker"], "AAPL")
        self.assertEqual(holdings[0]["bucket"], "satellite")
        self.assertEqual(portfolio[0]["currency"], "GBP")
        self.assertEqual(portfolio[0]["current_price"], 95)
        self.assertAlmostEqual(portfolio[0]["return_pct"], .1875)

    def test_live_broad_index_fund_is_core(self) -> None:
        holdings, _ = live_holdings(
            [{"instrument": {"ticker": "VUAGl_EQ", "shortName": "Vanguard S&P 500", "currencyCode": "GBP"}, "quantity": 1, "averagePricePaid": 100, "currentPrice": 110}],
            core_tickers=["VUAG.L", "VWRP.L"],
        )
        self.assertEqual(holdings[0]["ticker"], "VUAG.L")
        self.assertEqual(holdings[0]["bucket"], "core")

    def test_openai_structured_research_is_parsed(self) -> None:
        expected = {"market_summary": "Quiet day.", "deployment_context": {"pace": "normal", "summary": "No verified shock."}, "items": []}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "hidden"}, clear=True), patch(
            "market_agent.llm.urllib.request.urlopen", return_value=_Response({"output_text": json.dumps(expected)})
        ):
            self.assertEqual(research_with_openai({"signals": []}), expected)

    def test_instruments_uses_read_only_metadata_endpoint(self) -> None:
        calls = []
        def opener(request, **_kwargs):
            calls.append(request.full_url)
            return _Response([{"ticker": "AAPL_US_EQ", "type": "STOCK"}])
        with patch.dict(os.environ, {"TRADING212_API_KEY": "key", "TRADING212_API_SECRET": "secret"}, clear=True):
            from market_agent.trading212 import Trading212Client
            result = Trading212Client(opener=opener).instruments()
        self.assertEqual(result[0]["ticker"], "AAPL_US_EQ")
        self.assertTrue(calls[0].endswith("/api/v0/equity/metadata/instruments"))


if __name__ == "__main__":
    unittest.main()
