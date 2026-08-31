from __future__ import annotations

import json
import os
import urllib.request

from .net import verified_ssl_context


INSTRUCTIONS = """You are only the research layer of a deterministic portfolio monitor.
The attached market snapshot and rule-engine actions are authoritative. Do not restate, change,
contradict or add an action. Use web search to verify current facts and material recent news. Prefer
issuer fund pages, company filings, exchange notices, regulators and strong financial reporting.
For a fund, verify its index, geographic exposure, concentration, fee and overlap with the other
foundation funds. For a company, verify what drives revenue, the latest results, balance-sheet or
cash-burn risk, valuation caveats and any material event. Separate durable facts from news. Mention
only catalysts, thesis risks, earnings, regulatory events or data-source caveats. Never use
imperative trading language, predict certainty, or claim the supplied daily candles are live/intraday.
Use direct article or primary-source links. If no material verified news exists, say so plainly.
Keep summaries concise and do not invent facts, prices, dates, quotes, sources or tickers.
For every item, return between three and ten short bullets in very simple language. Aim for six to
eight useful points. Explain what the investment owns, why it fits the 80/15/5 risk plan, what the
latest results or verified news actually change, the biggest downside, overlap with existing funds,
and why buying in stages may or may not make sense. Expand every technical term in plain English.
If there is no material fresh news, say that plainly instead of inventing a catalyst.
Each bullet must explain
why the supplied authoritative action makes sense: why add for CORE RESEARCH or ADD CANDIDATE, why hold for KEEP,
why review for REVIEW, or why sell for SELL NOW. Tie each bullet to verified research or the supplied
rule evidence, avoid jargon, and never turn a weak or missing fact into a reason to trade.
Also return a deployment_context. It may choose only a normal or cautious DCA pace from verified
market-wide or portfolio-specific news. It must not choose securities, change the configured core
allocation, use social sentiment, popularity or price momentum, or convert news into a trade action."""


RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "market_summary": {"type": "string"},
        "deployment_context": {
            "type": "object",
            "properties": {
                "pace": {"type": "string", "enum": ["normal", "cautious"]},
                "summary": {"type": "string"},
            },
            "required": ["pace", "summary"],
            "additionalProperties": False,
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "summary": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 10},
                    "sources": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "url": {"type": "string"},
                                "publisher": {"type": "string"},
                            },
                            "required": ["title", "url", "publisher"],
                            "additionalProperties": False,
                        },
                        "maxItems": 6,
                    },
                },
                "required": ["ticker", "summary", "bullets", "sources"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["market_summary", "deployment_context", "items"],
    "additionalProperties": False,
}

DISCOVERY_INSTRUCTIONS = """You discover investments for a GBP Trading 212 Stocks ISA.
Search current, credible web sources across the broad public stock and ETF market; do not use a
fixed watchlist. Look separately for durable profitable companies, reasonably valued quality,
genuine earnings or regulatory catalysts, focused funds with a durable thesis, and asymmetric
small companies. Ignore social-media popularity, meme activity, raw price momentum, rumours,
day-trading setups and cryptocurrencies. Exclude securities already owned or used as foundation
funds. Return at most twelve candidates split between medium_high and very_high risk. A very-high
risk idea must explicitly say why losing most of the investment is possible. Prefer primary sources
and strong financial reporting. Use Yahoo-style tickers such as AAPL, ASML.AS or ABC.L. Do not claim
that a candidate is available at Trading 212; the caller verifies that separately. Give 3-10 simple
reasons per candidate, including the business/fund, current evidence, valuation caveat, downside,
and why it may deserve deeper research now. This is discovery, not permission to trade."""

DISCOVERY_SCHEMA = {
    "type": "object",
    "properties": {
        "scan_summary": {"type": "string"},
        "items": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "name": {"type": "string"},
                    "risk_bucket": {"type": "string", "enum": ["medium_high", "very_high"]},
                    "summary": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 10},
                    "sources": {
                        "type": "array",
                        "maxItems": 6,
                        "items": {
                            "type": "object",
                            "properties": {"title": {"type": "string"}, "url": {"type": "string"}, "publisher": {"type": "string"}},
                            "required": ["title", "url", "publisher"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["ticker", "name", "risk_bucket", "summary", "bullets", "sources"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["scan_summary", "items"],
    "additionalProperties": False,
}


def _responses_request(instructions: str, payload: dict, schema: dict, schema_name: str, max_tool_calls: int, max_output_tokens: int) -> dict | None:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
        "instructions": instructions,
        "input": json.dumps(payload, separators=(",", ":")),
        "tools": [{"type": "web_search"}],
        "max_tool_calls": max_tool_calls,
        "max_output_tokens": max_output_tokens,
        "include": ["web_search_call.action.sources"],
        "text": {"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
        "store": False,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120, context=verified_ssl_context()) as response:
        result = json.load(response)
    output_text = result.get("output_text")
    if output_text:
        return json.loads(output_text)
    chunks = [content.get("text", "") for output in result.get("output", []) for content in output.get("content", []) if content.get("type") == "output_text"]
    combined = "\n".join(chunks).strip()
    return json.loads(combined) if combined else None


def discover_opportunities_with_openai(payload: dict) -> dict | None:
    return _responses_request(DISCOVERY_INSTRUCTIONS, payload, DISCOVERY_SCHEMA, "market_opportunity_discovery", 16, 9000)


def research_with_openai(payload: dict) -> dict | None:
    return _responses_request(INSTRUCTIONS, payload, RESEARCH_SCHEMA, "market_research", 12, 8000)
