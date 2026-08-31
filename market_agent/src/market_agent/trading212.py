from __future__ import annotations

import base64
import json
import os
import re
import urllib.request

from .net import verified_ssl_context


class Trading212Error(RuntimeError):
    pass


MARKET_SUFFIXES = {
    "GB": ".L",
    "NL": ".AS",
    "DE": ".DE",
    "FR": ".PA",
    "IT": ".MI",
    "ES": ".MC",
}


def yahoo_ticker(broker_ticker: str, overrides: dict[str, str] | None = None) -> str:
    if overrides and broker_ticker in overrides:
        return overrides[broker_ticker]
    # Trading 212 uses a lowercase trailing `l` to identify London listings,
    # for example VUAGl_EQ and VWRPl_EQ. Yahoo uses the `.L` suffix.
    london = re.fullmatch(r"(.+)l_EQ", broker_ticker)
    if london:
        return london.group(1) + ".L"
    match = re.fullmatch(r"(.+)_([A-Z]{2})_(?:EQ|ETF)", broker_ticker)
    if not match:
        return broker_ticker
    symbol, market = match.groups()
    return symbol + MARKET_SUFFIXES.get(market, "")


class Trading212Client:
    """Read-only Trading 212 portfolio client. No order endpoint is implemented."""

    def __init__(self, opener=None) -> None:
        self.opener = opener or urllib.request.urlopen

    def _get(self, path: str, label: str) -> list[dict]:
        key = os.getenv("TRADING212_API_KEY", "")
        secret = os.getenv("TRADING212_API_SECRET", "")
        if not key or not secret:
            raise Trading212Error("Trading 212 credentials are not configured")
        environment = os.getenv("TRADING212_ENVIRONMENT", "live").lower()
        host = "demo.trading212.com" if environment == "demo" else "live.trading212.com"
        token = base64.b64encode(f"{key}:{secret}".encode()).decode()
        request = urllib.request.Request(
            f"https://{host}{path}",
            headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
        )
        try:
            with self.opener(request, timeout=30, context=verified_ssl_context()) as response:
                result = json.load(response)
        except Exception as exc:
            raise Trading212Error(f"Trading 212 {label} unavailable: {exc}") from exc
        if not isinstance(result, list):
            raise Trading212Error(f"Trading 212 returned an unexpected {label} response")
        return result

    def positions(self) -> list[dict]:
        return self._get("/api/v0/equity/positions", "portfolio")

    def instruments(self) -> list[dict]:
        """Return the broker's current tradeable universe; no order endpoint exists."""
        return self._get("/api/v0/equity/metadata/instruments", "instrument list")


def live_holdings(
    positions: list[dict],
    overrides: dict[str, str] | None = None,
    base_currency: str = "GBP",
    configured_holdings: list[dict] | None = None,
    core_tickers: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    holdings: list[dict] = []
    portfolio: list[dict] = []
    configured = {str(item.get("ticker")): item for item in (configured_holdings or [])}
    core = {str(value) for value in (core_tickers or ["VUAG.L", "VWRP.L", "VALL.L"])}
    for position in positions:
        instrument = position.get("instrument") or {}
        broker_ticker = str(instrument.get("ticker") or position.get("ticker") or "").strip()
        if not broker_ticker:
            continue
        mapped = yahoo_ticker(broker_ticker, overrides)
        quantity = float(position.get("quantity") or 0)
        average = float(position.get("averagePricePaid") or 0)
        current = float(position.get("currentPrice") or 0)
        quote_currency = str(instrument.get("currencyCode") or "")
        wallet = position.get("walletImpact") or {}
        account_currency = str(wallet.get("currency") or base_currency)
        account_value = wallet.get("currentValue")
        account_cost = wallet.get("totalCost")
        account_profit = wallet.get("unrealizedProfitLoss")
        account_value = float(account_value) if account_value is not None else None
        account_cost = float(account_cost) if account_cost is not None else None
        account_profit = float(account_profit) if account_profit is not None else None
        account_current_per_share = account_value / quantity if account_value is not None and quantity else None
        account_average_per_share = account_cost / quantity if account_cost is not None and quantity else None
        personal_policy = configured.get(mapped, {})
        is_core = mapped in core or personal_policy.get("bucket") == "core"
        holdings.append(
            {
                "ticker": mapped,
                "name": instrument.get("shortName") or instrument.get("name") or mapped,
                "bucket": personal_policy.get("bucket", "core" if is_core else "satellite"),
                "cost_basis": average or None,
                "thesis": personal_policy.get(
                    "thesis",
                    "Broad-market core holding." if is_core else "Live individual position; require fundamental research before adding.",
                ),
                "sell_rules": personal_policy.get(
                    "sell_rules",
                    {"below_ma200_days": 20, "max_drawdown_from_cost": None}
                    if is_core
                    else {"below_ma200_days": 10, "max_drawdown_from_cost": 0.30},
                ),
                "broker_ticker": broker_ticker,
            }
        )
        portfolio.append(
            {
                "ticker": mapped,
                "broker_ticker": broker_ticker,
                "name": instrument.get("shortName") or instrument.get("name") or mapped,
                "quantity": quantity,
                "average_price": account_average_per_share,
                "current_price": account_current_per_share,
                "currency": account_currency,
                "market_value": account_value,
                "total_cost": account_cost,
                "unrealized": account_profit,
                "return_pct": (account_value / account_cost - 1) if account_value is not None and account_cost else None,
                "fx_impact": float(wallet.get("fxImpact")) if wallet.get("fxImpact") is not None else None,
                "quote_currency": quote_currency,
                "native_average_price": average,
                "native_current_price": current,
                "created_at": position.get("createdAt"),
            }
        )
    return holdings, portfolio
