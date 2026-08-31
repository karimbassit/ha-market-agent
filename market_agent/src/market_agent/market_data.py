from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .net import verified_ssl_context


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class MarketDataError(RuntimeError):
    pass


class YahooChartClient:
    """Small Yahoo chart client. Yahoo is unofficial, so failures fail closed."""

    def __init__(self, opener: Callable | None = None, retries: int = 3) -> None:
        self.opener = opener or urllib.request.urlopen
        self.retries = retries
        self.ssl_context = verified_ssl_context()
        self.currencies: dict[str, str] = {}

    def history(self, ticker: str, range_: str = "2y") -> list[Bar]:
        encoded = urllib.parse.quote(ticker, safe="")
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
            f"?range={range_}&interval=1d&events=div%2Csplits"
        )
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 market-monitor/0.1", "Accept": "application/json"},
        )
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                with self.opener(request, timeout=20, context=self.ssl_context) as response:
                    payload = json.load(response)
                result = ((payload.get("chart") or {}).get("result") or [{}])[0]
                currency = (result.get("meta") or {}).get("currency")
                if currency:
                    self.currencies[ticker] = str(currency)
                return self._parse(payload, ticker)
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(0.4 * (2**attempt))
        raise MarketDataError(f"Could not retrieve {ticker}: {last_error}")

    def currency(self, ticker: str) -> str:
        return self.currencies.get(ticker, "USD")

    @staticmethod
    def _parse(payload: dict, ticker: str) -> list[Bar]:
        chart = payload.get("chart", {})
        if chart.get("error"):
            raise MarketDataError(f"{ticker}: {chart['error']}")
        result = (chart.get("result") or [None])[0]
        if not result:
            raise MarketDataError(f"{ticker}: empty response")
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        bars: list[Bar] = []
        for index, stamp in enumerate(timestamps):
            values = [quote[key][index] for key in ("open", "high", "low", "close")]
            if any(value is None for value in values):
                continue
            bars.append(
                Bar(
                    timestamp=datetime.fromtimestamp(stamp, tz=timezone.utc),
                    open=float(values[0]),
                    high=float(values[1]),
                    low=float(values[2]),
                    close=float(values[3]),
                    volume=float((quote.get("volume") or [0] * len(timestamps))[index] or 0),
                )
            )
        if len(bars) < 50:
            raise MarketDataError(f"{ticker}: only {len(bars)} usable daily bars")
        return bars
