from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .indicators import Snapshot
from .net import verified_ssl_context
from .signals import Signal


class YahooNewsClient:
    """Fetch a small, best-effort headline digest without an API key."""

    def search(self, ticker: str, limit: int = 2) -> list[dict]:
        query = urllib.parse.urlencode({"q": ticker, "quotesCount": 0, "newsCount": limit})
        request = urllib.request.Request(
            f"https://query1.finance.yahoo.com/v1/finance/search?{query}",
            headers={"User-Agent": "Mozilla/5.0 market-monitor/0.5", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=12, context=verified_ssl_context()) as response:
            payload = json.load(response)
        output: list[dict] = []
        for item in payload.get("news", [])[:limit]:
            stamp = item.get("providerPublishTime")
            published = datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat() if stamp else None
            output.append(
                {
                    "title": str(item.get("title") or "Untitled market update"),
                    "publisher": str(item.get("publisher") or "Unknown source"),
                    "published_at": published,
                    "url": str(item.get("link") or ""),
                }
            )
        return output


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1%}"


def build_research(
    signals: list[Signal],
    snapshots: dict[str, Snapshot],
    holdings_by_ticker: dict[str, dict],
    news_client: YahooNewsClient | None = None,
) -> list[dict]:
    client = news_client or YahooNewsClient()
    items: list[dict] = []
    for signal in signals:
        snap = snapshots[signal.ticker]
        holding = holdings_by_ticker.get(signal.ticker, {})
        trend = "unavailable"
        if snap.ma200:
            trend = f"{_percent(snap.price / snap.ma200 - 1)} versus the 200-day average"
        bullets = [
            f"Signal: {signal.action}. " + ("; ".join(signal.reasons[:3]) or "No strong deterministic trigger."),
            f"Price context only (not a buy trigger): 1 day {_percent(snap.change_1d)}; 20 days {_percent(snap.change_20d)}; RSI {snap.rsi14:.0f}.",
            f"Trend: {trend}; {_percent(snap.distance_from_52w_high)} from the 52-week high.",
        ]
        if holding.get("thesis"):
            bullets.insert(0, f"Thesis: {holding['thesis']}")
        try:
            headlines = client.search(snap.source_ticker, limit=2)
        except Exception:
            headlines = []
        items.append(
            {
                "ticker": signal.ticker,
                "source_ticker": snap.source_ticker,
                "action": signal.action,
                "currency": snap.currency,
                "price": snap.price,
                "bullets": bullets,
                "news": headlines,
            }
        )
    return items
