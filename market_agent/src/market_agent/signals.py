from __future__ import annotations

from dataclasses import dataclass

from .indicators import Snapshot


@dataclass(frozen=True)
class Signal:
    ticker: str
    action: str
    score: int
    reasons: tuple[str, ...]
    confidence: str


def technical_score(item: Snapshot) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if item.ma200:
        if item.price > item.ma200:
            score += 2
            reasons.append("above 200-day trend")
        else:
            score -= 2
            reasons.append("below 200-day trend")
    if item.ma20 and item.ma50:
        if item.price > item.ma20 > item.ma50:
            score += 2
            reasons.append("price and 20-day average above 50-day average")
        elif item.price < item.ma20 < item.ma50:
            score -= 2
            reasons.append("short-term downtrend")
    if item.rsi14 is not None:
        if 45 <= item.rsi14 <= 68:
            score += 1
            reasons.append(f"constructive RSI {item.rsi14:.0f}")
        elif item.rsi14 >= 75:
            score -= 1
            reasons.append(f"overbought RSI {item.rsi14:.0f}")
        elif item.rsi14 <= 30:
            score += 1
            reasons.append(f"oversold RSI {item.rsi14:.0f}")
    if item.macd is not None and item.macd_signal is not None:
        if item.macd > item.macd_signal:
            score += 1
            reasons.append("MACD positive")
        else:
            score -= 1
            reasons.append("MACD negative")
    return score, reasons


def holding_signal(holding: dict, item: Snapshot) -> Signal:
    score, reasons = technical_score(item)
    rules = holding.get("sell_rules", {})
    max_loss = rules.get("max_drawdown_from_cost")
    cost_basis = holding.get("cost_basis")
    hard_loss = bool(cost_basis and max_loss and item.price <= float(cost_basis) * (1 - float(max_loss)))
    trend_break = item.below_ma200_days >= int(rules.get("below_ma200_days", 9999))

    if holding["bucket"] == "core":
        if trend_break and score <= -4:
            return Signal(item.ticker, "REVIEW", score, tuple(reasons + ["core trend break; verify thesis before acting"]), "medium")
        return Signal(item.ticker, "KEEP", score, tuple(reasons), "high")
    if hard_loss:
        return Signal(item.ticker, "SELL NOW", score, tuple(reasons + ["configured loss limit breached"]), "high")
    if trend_break and score <= -4:
        return Signal(item.ticker, "SELL NOW", score, tuple(reasons + ["persistent 200-day trend break"]), "medium")
    if score <= -2:
        return Signal(item.ticker, "REVIEW", score, tuple(reasons), "medium")
    return Signal(item.ticker, "KEEP", score, tuple(reasons), "high" if score >= 1 else "medium")


def watchlist_signal(item: Snapshot, filters: dict) -> Signal | None:
    if item.price < float(filters["minimum_price"]):
        return None
    if item.avg_dollar_volume_20d < float(filters["minimum_average_dollar_volume"]):
        return None
    score, reasons = technical_score(item)
    if score >= 4 and item.distance_from_52w_high > -0.35:
        return Signal(item.ticker, "BUY CANDIDATE", score, tuple(reasons), "technical-screen only")
    return None

