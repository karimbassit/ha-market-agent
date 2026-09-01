from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .config import load_config, load_env
from .indicators import Snapshot, snapshot
from .llm import discover_opportunities_with_openai, research_with_openai
from .market_data import Bar, MarketDataError, YahooChartClient
from .planner import build_deployment_plan, deployment_note
from .report import deterministic_note
from .research import build_research
from .signals import Signal, holding_signal, watchlist_signal
from .delivery import send
from .trading212 import Trading212Client, Trading212Error, live_holdings, yahoo_ticker
from .hargreaves_lansdown import HargreavesLansdownError, manual_holdings, refresh_gbp_values


def _progress(stage: str, detail: str, percent: int) -> None:
    path = os.getenv("MARKET_AGENT_STATUS_PATH")
    if not path:
        return
    try:
        Path(path).write_text(json.dumps({"state": "running", "stage": stage, "detail": detail, "percent": percent}), encoding="utf-8")
    except OSError:
        pass


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Create and deliver a daily portfolio note")
    result.add_argument("--config", type=Path, default=Path("config/portfolio.json"))
    result.add_argument("--env", type=Path, default=Path(".env"))
    result.add_argument("--no-ai", action="store_true", help="Skip OpenAI news/context layer")
    result.add_argument("--dry-run", action="store_true", help="Print rather than deliver")
    result.add_argument("--json-output", type=Path, help="Save machine-readable run evidence")
    result.add_argument("--note-output", type=Path, help="Save the human-readable report")
    return result


def run(args: argparse.Namespace) -> tuple[str, dict]:
    load_env(args.env)
    config = load_config(args.config)
    _progress("Loading your portfolio", "Reading your saved rules and current holdings.", 8)
    errors: list[str] = []
    portfolio_positions: list[dict] = []
    portfolio_source = "starter configuration"
    runtime_holdings = config["holdings"]
    broker_client: Trading212Client | None = None
    provider = os.getenv("PORTFOLIO_PROVIDER", "starter").lower()
    if provider == "starter" and os.getenv("TRADING212_ENABLED", "false").lower() == "true":
        provider = "trading212"
    if provider == "trading212":
        try:
            broker_client = Trading212Client()
            runtime_holdings, portfolio_positions = live_holdings(
                broker_client.positions(),
                config.get("trading212_ticker_overrides"),
                str(config.get("base_currency", "GBP")),
                config.get("holdings"),
                config.get("capital_plan", {}).get("core_tickers"),
            )
            if not runtime_holdings:
                raise Trading212Error("Trading 212 returned no open equity positions")
            portfolio_source = "Trading 212 · read-only live portfolio"
        except Trading212Error as exc:
            errors.append(f"{exc}; using the local fallback portfolio")
            runtime_holdings = config["holdings"]
    elif provider == "hargreaves_lansdown":
        try:
            runtime_holdings, portfolio_positions = manual_holdings(
                os.getenv("HARGREAVES_LANSDOWN_HOLDINGS_JSON", "[]"),
                config.get("holdings"),
                config.get("capital_plan", {}).get("core_tickers"),
                str(config.get("base_currency", "GBP")),
            )
            portfolio_source = "Hargreaves Lansdown · manual holdings · market-priced"
        except HargreavesLansdownError as exc:
            errors.append(f"{exc}; using the local fallback portfolio")
            runtime_holdings = config["holdings"]
    holdings_by_ticker = {item["ticker"]: item for item in runtime_holdings}
    planning_tickers = list(dict.fromkeys(str(value) for value in config.get("capital_plan", {}).get("core_tickers", ["VUAG.L", "VWRP.L", "VALL.L"])))
    discovered: list[dict] = []
    discovery_summary = "Market-wide discovery did not run."
    if not args.no_ai and broker_client is not None:
        try:
            _progress("Scanning the market", "Searching broadly for new opportunities, without using social-media hype.", 14)
            instruments = broker_client.instruments()
            available: dict[str, dict] = {}
            for instrument in instruments:
                if str(instrument.get("type")) not in {"STOCK", "ETF"}:
                    continue
                broker_ticker = str(instrument.get("ticker") or "")
                mapped = yahoo_ticker(broker_ticker, config.get("trading212_ticker_overrides"))
                if mapped:
                    available.setdefault(mapped.upper(), {**instrument, "yahoo_ticker": mapped, "broker_ticker": broker_ticker})
            result = discover_opportunities_with_openai({
                "date": datetime.now(timezone.utc).date().isoformat(),
                "base_currency": config.get("base_currency", "GBP"),
                "owned_tickers": sorted(holdings_by_ticker),
                "foundation_tickers": planning_tickers,
                "risk_targets": config.get("capital_plan", {}).get("risk_targets", {}),
                "available_instrument_count": len(available),
            }) or {}
            discovery_summary = str(result.get("scan_summary") or "Broad discovery completed.")
            seen: set[str] = set()
            for raw in result.get("items", []):
                proposed = str(raw.get("ticker") or "").upper().strip()
                instrument = available.get(proposed)
                if not instrument or proposed in seen or instrument["yahoo_ticker"] in holdings_by_ticker or instrument["yahoo_ticker"] in planning_tickers:
                    continue
                seen.add(proposed)
                discovered.append({
                    **raw,
                    "ticker": instrument["yahoo_ticker"],
                    "broker_ticker": instrument["broker_ticker"],
                    "trading212_name": instrument.get("shortName") or instrument.get("name"),
                    "available_on_trading212": True,
                    "sources": [source for source in raw.get("sources", [])[:6] if str(source.get("url", "")).startswith("https://")],
                })
                if len(discovered) >= 8:
                    break
        except (Trading212Error, ValueError, OSError) as exc:
            errors.append(f"Broad opportunity scan unavailable: {exc}")
    elif args.no_ai:
        discovery_summary = "OpenAI is not connected, so broad opportunity discovery was skipped."
    tickers = list(dict.fromkeys([*holdings_by_ticker, *config.get("watchlist", []), *planning_tickers, *[item["ticker"] for item in discovered]]))
    client = YahooChartClient()
    snapshots: dict[str, Snapshot] = {}
    bars_by_ticker: dict[str, list[Bar]] = {}
    now = datetime.now(timezone.utc)
    _progress("Checking prices and charts", f"Checking {len(tickers)} funds and shares against daily market data.", 20)
    for index, ticker in enumerate(tickers):
        _progress("Checking prices and charts", f"Looking at {ticker} ({index + 1} of {len(tickers)}).", 20 + round(32 * (index + 1) / max(len(tickers), 1)))
        try:
            bars = client.history(ticker)
            item = snapshot(ticker, bars, client.currency(ticker))
            age = (now.date() - datetime.fromisoformat(item.date).date()).days
            if age > int(config.get("max_data_age_days", 5)):
                errors.append(f"{ticker}: stale data ({item.date}); no signal issued")
                continue
            snapshots[ticker] = item
            bars_by_ticker[ticker] = bars
        except (MarketDataError, ValueError) as exc:
            errors.append(str(exc))

    for ticker, holding in holdings_by_ticker.items():
        proxy = holding.get("signal_proxy")
        if ticker not in snapshots and proxy in snapshots:
            snapshots[ticker] = replace(snapshots[proxy], ticker=ticker)
            bars_by_ticker[ticker] = bars_by_ticker[proxy]
            errors.append(f"{ticker}: insufficient history; signals use labeled {proxy} proxy data")

    if provider == "hargreaves_lansdown" and portfolio_positions:
        errors.extend(refresh_gbp_values(portfolio_positions, snapshots))

    holding_signals = [holding_signal(item, snapshots[ticker]) for ticker, item in holdings_by_ticker.items() if ticker in snapshots]
    minimum_price = float(config["buy_filters"]["minimum_price"])
    minimum_liquidity = float(config["buy_filters"]["minimum_average_dollar_volume"])
    verified_opportunities = [
        item for item in discovered
        if item["ticker"] in snapshots
        and snapshots[item["ticker"]].price >= minimum_price
        and snapshots[item["ticker"]].avg_dollar_volume_20d >= minimum_liquidity
    ]
    opportunity_signals = [
        Signal(item["ticker"], "ADD CANDIDATE", 0, ("Found by broad daily research and verified as liquid and available on Trading 212.",), "research-screen")
        for item in verified_opportunities
    ]
    candidates = []
    if config.get("buy_strategy", "allocation_only") == "technical_momentum":
        candidates = [
            signal
            for ticker in config.get("watchlist", [])
            if ticker in snapshots
            for signal in [watchlist_signal(snapshots[ticker], config["buy_filters"])]
            if signal is not None
        ]
    candidates.sort(key=lambda item: item.score, reverse=True)
    candidates = candidates[: int(config["buy_filters"]["maximum_daily_candidates"])]
    all_signals = [*holding_signals, *candidates]
    signalled_tickers = {item.ticker for item in all_signals}
    core_research_signals = [
        Signal(
            ticker,
            "CORE RESEARCH",
            0,
            ("Policy-selected broad-index core; price momentum does not determine eligibility.",),
            "allocation-policy",
        )
        for ticker in planning_tickers
        if ticker in snapshots and ticker not in signalled_tickers
    ]
    research_signals = [*all_signals, *core_research_signals, *opportunity_signals]
    research = build_research(research_signals, snapshots, holdings_by_ticker)
    discovered_by_ticker = {str(item["ticker"]): item for item in verified_opportunities}
    for item in research:
        discovery_item = discovered_by_ticker.get(str(item.get("ticker")))
        if discovery_item:
            item["ai_summary"] = str(discovery_item.get("summary", ""))
            item["ai_bullets"] = [str(value) for value in discovery_item.get("bullets", [])[:10]]
            item["ai_sources"] = discovery_item.get("sources", [])[:6]
            item["risk_bucket"] = discovery_item.get("risk_bucket")
    latest_data_at = max((item.timestamp for item in snapshots.values()), default=None)
    evidence = {
        "generated_at": now.isoformat(),
        "latest_data_at": latest_data_at,
        "portfolio": config["portfolio_name"],
        "portfolio_source": portfolio_source,
        "portfolio_positions": portfolio_positions,
        "base_currency": config.get("base_currency", "GBP"),
        "timezone": config.get("timezone", "Europe/London"),
        "signals": [signal.__dict__ for signal in all_signals],
        "snapshots": {ticker: item.as_dict() for ticker, item in snapshots.items()},
        "candles": {
            ticker: [
                {
                    "timestamp": bar.timestamp.isoformat(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in bars_by_ticker.get(ticker, [])[-90:]
            ]
            for ticker in {signal.ticker for signal in research_signals}
        },
        "research": research,
        "opportunity_scan": {"summary": discovery_summary, "eligible_count": len(verified_opportunities), "items": verified_opportunities},
        "errors": errors,
        "guardrails": {
            "advisory_only": True,
            "automatic_trading": False,
            "sell_actions_from_rules_only": True,
            "buy_strategy": config.get("buy_strategy", "allocation_only"),
            "social_momentum_disabled": config.get("buy_strategy", "allocation_only") == "allocation_only",
        },
    }
    note = deterministic_note(
        now,
        holding_signals,
        opportunity_signals or candidates,
        snapshots,
        errors,
        str(config.get("timezone", "Europe/London")),
    )
    deployment_context = {
        "pace": "cautious" if any(item.action in {"SELL NOW", "REVIEW"} for item in holding_signals) else "normal",
        "summary": "A review or sell signal triggered the slower four-tranche schedule."
        if any(item.action in {"SELL NOW", "REVIEW"} for item in holding_signals)
        else "No deterministic portfolio warning changed the standard three-tranche schedule.",
    }
    if not args.no_ai:
        try:
            _progress("Researching recent news", "Looking for verified company, fund and market news from the last 7 days.", 58)
            research_payload = {
                "generated_at": evidence["generated_at"],
                "latest_data_at": evidence["latest_data_at"],
                "actions_are_authoritative": [signal.__dict__ for signal in research_signals],
                "capital_policy": {
                    "core_tickers": planning_tickers,
                    "risk_targets": config.get("capital_plan", {}).get("risk_targets", {"foundation": .80, "medium_high": .15, "very_high": .05}),
                    "news_may_change_only": "DCA pace",
                },
                "market_snapshots": {
                    ticker: {
                        key: value
                        for key, value in item.as_dict().items()
                        if key in {"ticker", "source_ticker", "timestamp", "currency", "price", "change_1d", "change_20d", "ma20", "ma50", "ma200", "rsi14"}
                    }
                    for ticker, item in snapshots.items()
                    if ticker in {signal.ticker for signal in research_signals}
                },
            }
            ai_research = research_with_openai(research_payload)
            if ai_research:
                allowed = {item["ticker"]: item for item in research}
                for ai_item in ai_research.get("items", []):
                    target = allowed.get(str(ai_item.get("ticker", "")))
                    if target is None:
                        continue
                    target["ai_summary"] = str(ai_item.get("summary", ""))
                    target["ai_bullets"] = [str(value) for value in ai_item.get("bullets", [])[:10]]
                    target["ai_sources"] = [
                        source for source in ai_item.get("sources", [])[:6] if str(source.get("url", "")).startswith("https://")
                    ]
                evidence["market_summary"] = str(ai_research.get("market_summary", ""))
                evidence["ai_research_status"] = "enriched with OpenAI web research"
                evidence["ai_model"] = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
                deployment_context = ai_research.get("deployment_context") or deployment_context
                summary = evidence["market_summary"].strip()
            else:
                summary = ""
            if summary:
                marker = "\nAdvisory only — verify prices and news before trading."
                note = note.replace(marker, f"\n\nNEWS RESEARCH\n{summary}{marker}")
        except Exception as exc:
            evidence["errors"].append(f"Optional news layer unavailable: {exc}")
    else:
        _progress("Reading the available research", "OpenAI is not connected, so this run is using the fixed rules and available market data only.", 65)
    research_by_ticker = {
        str(item.get("ticker")): [str(value) for value in item.get("ai_bullets", [])[:10]]
        for item in research
        if item.get("ai_bullets")
    }
    for item in verified_opportunities:
        if item["ticker"] in research_by_ticker:
            item["bullets"] = research_by_ticker[item["ticker"]]
    for signal in evidence["signals"]:
        signal["research_bullets"] = research_by_ticker.get(str(signal.get("ticker")), [])
    capital_policy = config.get("capital_plan", {})
    _progress("Building your plan", "Comparing your current 80/15/5 risk mix with the target and deciding what needs attention.", 88)
    try:
        capital = float(os.getenv("NEXT_INVESTMENT_GBP", capital_policy.get("default_amount_gbp", 1000)))
    except (TypeError, ValueError):
        capital = float(capital_policy.get("default_amount_gbp", 1000))
    evidence["deployment_plan"] = build_deployment_plan(
        capital,
        portfolio_positions,
        capital_policy,
        deployment_context,
        research_by_ticker,
        verified_opportunities,
    )
    marker = "\nAdvisory only — verify prices and news before trading."
    note = note.replace(marker, f"\n\n{deployment_note(evidence['deployment_plan'])}{marker}")
    _progress("Preparing your note", "Saving the evidence and getting the Home Assistant notification ready.", 96)
    return note, evidence


def main() -> None:
    args = parser().parse_args()
    try:
        note, evidence = run(args)
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
        if args.note_output:
            args.note_output.parent.mkdir(parents=True, exist_ok=True)
            args.note_output.write_text(note, encoding="utf-8")
        if args.dry_run:
            print(note)
        else:
            send(note)
    except Exception as exc:
        print(f"market-agent failed safely: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
