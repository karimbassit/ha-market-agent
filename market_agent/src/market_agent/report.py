from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .indicators import Snapshot
from .signals import Signal


def _plain_reason(reason: str) -> str:
    mapping = {
        "above 200-day trend": "the price is above its average closing price over roughly 200 trading days (about ten months), which suggests the longer trend has been rising but does not guarantee future gains",
        "below 200-day trend": "the price is below its average closing price over roughly 200 trading days (about ten months), which warns that the longer trend may be weakening but is not automatic proof to sell",
        "short-term downtrend": "price has been moving down recently",
        "persistent 200-day trend break": "the price stayed below its average closing price over roughly 200 trading days for long enough to trigger your sell rule",
        "configured loss limit breached": "the position fell past your configured maximum loss",
        "core trend break; verify thesis before acting": "this is a core holding, so review it before making a decision",
    }
    if reason.startswith("constructive RSI"):
        return "buying and selling pressure looks balanced"
    if reason.startswith("overbought RSI"):
        return "the price has risen very quickly and may be temporarily expensive"
    if reason.startswith("oversold RSI"):
        return "the price has fallen very quickly; investigate rather than automatically buying"
    if reason == "MACD positive":
        return "recent price movement is improving"
    if reason == "MACD negative":
        return "recent price movement is weakening"
    return mapping.get(reason, reason)


def _line(signal: Signal, snap: Snapshot) -> str:
    evidence = "; ".join(_plain_reason(reason) for reason in signal.reasons[:3]) or "nothing important has changed enough to act"
    symbols = {"GBP": "£", "USD": "$", "EUR": "€", "GBp": ""}
    suffix = "p" if snap.currency == "GBp" else ""
    price_label = f"{symbols.get(snap.currency, '')}{snap.price:,.2f}{suffix} {snap.currency}"
    if snap.source_ticker != snap.ticker:
        price_label = f"technical proxy {snap.source_ticker} at {price_label}"
    verb = {"SELL NOW": "Why sell", "KEEP": "Why hold", "REVIEW": "Why review", "BUY CANDIDATE": "Why research"}.get(signal.action, "Why")
    return f"• {signal.ticker} — {price_label}. {verb}: {evidence}."


def deterministic_note(
    generated_at: datetime,
    holdings: list[Signal],
    candidates: list[Signal],
    snapshots: dict[str, Snapshot],
    errors: list[str],
    timezone: str = "Europe/London",
) -> str:
    data_dates = sorted({snap.date for snap in snapshots.values()})
    latest = data_dates[-1] if data_dates else "unavailable"
    zone = ZoneInfo(timezone)
    created_label = generated_at.astimezone(zone).strftime("%d %b %Y, %H:%M %Z")
    data_times = [datetime.fromisoformat(snap.timestamp) for snap in snapshots.values()]
    latest_label = max(data_times).astimezone(zone).strftime("%d %b %Y, %H:%M %Z") if data_times else latest
    lines = [f"Daily portfolio note · {created_label}", f"Latest market data · {latest_label} (daily bar)"]
    sellers = [signal for signal in holdings if signal.action == "SELL NOW"]
    lines.extend(["", "SELL NOW"])
    lines.extend(_line(signal, snapshots[signal.ticker]) for signal in sellers)
    if not sellers:
        lines.append("• None from the available configured rules; missing holdings receive no signal.")
    lines.extend(["", "KEEP / REVIEW"])
    lines.extend(
        _line(signal, snapshots[signal.ticker]).replace(" — ", f" [{signal.action}] — ", 1)
        for signal in holdings
        if signal.action != "SELL NOW"
    )
    lines.extend(["", "ADD / DCA RESEARCH"])
    lines.extend(_line(signal, snapshots[signal.ticker]) for signal in candidates)
    if not candidates:
        lines.append("• Social-momentum screens are disabled; additions come from the core-first capital plan.")
    if errors:
        lines.extend(["", "DATA WARNINGS", *[f"• {error}" for error in errors[:5]]])
    lines.extend(["", "Advisory only — verify prices and news before trading."])
    return "\n".join(lines)
