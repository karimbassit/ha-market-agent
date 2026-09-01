from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from market_agent.llm import research_with_openai
from market_agent.trading212 import live_holdings, yahoo_ticker
from market_agent.hargreaves_lansdown import HargreavesLansdownError, manual_holdings, refresh_gbp_values
from market_agent.indicators import Snapshot


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

    def test_hl_manual_holdings_are_read_without_credentials(self) -> None:
        holdings, portfolio = manual_holdings(json.dumps([{
            "ticker": "VUAG.L", "name": "Vanguard S&P 500", "quantity": 10,
            "average_price_gbp": 80.25, "market_value_gbp": 900,
        }]))
        self.assertEqual(holdings[0]["bucket"], "core")
        self.assertEqual(portfolio[0]["broker"], "Hargreaves Lansdown")
        self.assertEqual(portfolio[0]["total_cost"], 802.5)

    def test_hl_gbpence_quote_refreshes_portfolio_in_gbp(self) -> None:
        _, portfolio = manual_holdings('[{"ticker":"VUAG.L","quantity":2,"average_price_gbp":80}]')
        snap = Snapshot(
            ticker="VUAG.L", source_ticker="VUAG.L", date="2026-08-31",
            timestamp="2026-08-31T16:30:00+00:00", currency="GBp", price=9000,
            change_1d=0, change_20d=0, ma20=9000, ma50=9000, ma200=9000,
            rsi14=50, macd=0, macd_signal=0, avg_volume_20d=1000,
            avg_dollar_volume_20d=9000000, below_ma200_days=0, distance_from_52w_high=0,
        )
        notes = refresh_gbp_values(portfolio, {"VUAG.L": snap})
        self.assertEqual(notes, [])
        self.assertEqual(portfolio[0]["current_price"], 90)
        self.assertEqual(portfolio[0]["market_value"], 180)

    def test_hl_import_rejects_missing_ticker(self) -> None:
        with self.assertRaises(HargreavesLansdownError):
            manual_holdings('[{"quantity":2}]')


if __name__ == "__main__":
    unittest.main()
