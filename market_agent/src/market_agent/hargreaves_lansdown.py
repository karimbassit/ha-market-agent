from __future__ import annotations

import json

from .indicators import Snapshot


class HargreavesLansdownError(ValueError):
    pass


def manual_holdings(
    raw: str,
    configured_holdings: list[dict] | None = None,
    core_tickers: list[str] | None = None,
    base_currency: str = "GBP",
) -> tuple[list[dict], list[dict]]:
    """Parse user-supplied HL holdings without using or storing HL login details."""
    try:
        items = json.loads(raw or "[]")
    except json.JSONDecodeError as exc:
        raise HargreavesLansdownError(f"Hargreaves Lansdown holdings JSON is invalid: {exc.msg}") from exc
    if not isinstance(items, list):
        raise HargreavesLansdownError("Hargreaves Lansdown holdings must be a JSON list")
    configured = {str(item.get("ticker", "")).upper(): item for item in (configured_holdings or [])}
    core = {str(value).upper() for value in (core_tickers or ["VUAG.L", "VWRP.L", "VALL.L"])}
    holdings: list[dict] = []
    portfolio: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise HargreavesLansdownError(f"HL holding {index} must be an object")
        ticker = str(item.get("ticker") or "").upper().strip()
        if not ticker:
            raise HargreavesLansdownError(f"HL holding {index} has no ticker")
        if ticker in seen:
            raise HargreavesLansdownError(f"HL holdings contain duplicate ticker {ticker}")
        seen.add(ticker)
        try:
            quantity = float(item.get("quantity") or 0)
            average = float(item["average_price_gbp"]) if item.get("average_price_gbp") is not None else None
            market_value = float(item["market_value_gbp"]) if item.get("market_value_gbp") is not None else None
        except (TypeError, ValueError) as exc:
            raise HargreavesLansdownError(f"HL holding {ticker} contains an invalid number") from exc
        if quantity <= 0:
            raise HargreavesLansdownError(f"HL holding {ticker} quantity must be greater than zero")
        policy = configured.get(ticker, {})
        is_core = ticker in core or str(item.get("bucket") or policy.get("bucket")) == "core"
        name = str(item.get("name") or policy.get("name") or ticker)
        total_cost = quantity * average if average is not None else None
        unrealized = market_value - total_cost if market_value is not None and total_cost is not None else None
        holdings.append({
            "ticker": ticker,
            "name": name,
            "bucket": str(item.get("bucket") or policy.get("bucket") or ("core" if is_core else "satellite")),
            "cost_basis": average,
            "thesis": str(item.get("thesis") or policy.get("thesis") or (
                "Broad-market core holding." if is_core else "HL holding; require fundamental research before adding."
            )),
            "sell_rules": policy.get("sell_rules", {"below_ma200_days": 20, "max_drawdown_from_cost": None}
                if is_core else {"below_ma200_days": 10, "max_drawdown_from_cost": 0.30}),
        })
        portfolio.append({
            "ticker": ticker,
            "name": name,
            "quantity": quantity,
            "average_price": average,
            "current_price": market_value / quantity if market_value is not None else None,
            "currency": base_currency,
            "market_value": market_value,
            "total_cost": total_cost,
            "unrealized": unrealized,
            "return_pct": (market_value / total_cost - 1) if market_value is not None and total_cost else None,
            "broker": "Hargreaves Lansdown",
        })
    if not holdings:
        raise HargreavesLansdownError("No Hargreaves Lansdown holdings were supplied")
    return holdings, portfolio


def refresh_gbp_values(positions: list[dict], snapshots: dict[str, Snapshot]) -> list[str]:
    """Refresh GBP and GBp quotes; retain supplied GBP values for foreign listings."""
    notes: list[str] = []
    for position in positions:
        ticker = str(position.get("ticker") or "")
        snap = snapshots.get(ticker)
        if snap is None:
            continue
        if snap.currency == "GBp":
            price_gbp = snap.price / 100
        elif snap.currency == "GBP":
            price_gbp = snap.price
        else:
            if position.get("market_value") is None:
                notes.append(f"{ticker}: enter market_value_gbp because the listing trades in {snap.currency}, not GBP")
            continue
        quantity = float(position.get("quantity") or 0)
        market_value = quantity * price_gbp
        total_cost = position.get("total_cost")
        position["current_price"] = price_gbp
        position["market_value"] = market_value
        position["unrealized"] = market_value - float(total_cost) if total_cost is not None else None
        position["return_pct"] = (market_value / float(total_cost) - 1) if total_cost else None
    return notes
