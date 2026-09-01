from __future__ import annotations

import html
import json
import re
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo


def _currency(price: float, currency: str) -> str:
    symbols = {"GBP": "£", "USD": "$", "EUR": "€", "GBp": ""}
    suffix = "p" if currency == "GBp" else ""
    return f"{symbols.get(currency, '')}{price:,.2f}{suffix} {currency}".strip()


def _money(value: object, currency: str) -> str:
    return "Unavailable" if value is None else _currency(float(value), currency)


def _when(value: str | None, timezone: str) -> str:
    if not value:
        return "Not available"
    try:
        return datetime.fromisoformat(value).astimezone(ZoneInfo(timezone)).strftime("%d %b %Y · %H:%M %Z")
    except (ValueError, TypeError):
        return str(value)


def _edition_date(value: str | None, timezone: str) -> str | None:
    """The masthead date — taken from the run itself, never the server clock."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(ZoneInfo(timezone)).strftime("%A %d %B")
    except (ValueError, TypeError):
        return None


def _hero_value(total: object, currency: str) -> str:
    """Display treatment for the live portfolio total. Never hard-coded."""
    if total is None:
        return '<strong class="big-value">Unavailable</strong>'
    symbols = {"GBP": "£", "USD": "$", "EUR": "€"}
    amount = f"{symbols.get(currency, '')}{float(total):,.2f}"
    return f'<strong class="big-value">{html.escape(amount)}<em>{html.escape(currency)}</em></strong>'


# ---------------------------------------------------------------------------
# The Spectrum: each holding is assigned a colour by portfolio order and wears
# it everywhere — the allocation bar, its legend chip, its ledger row.
# ---------------------------------------------------------------------------
_SPECTRUM = ["#e0a90f", "#3f8fd9", "#9a6fe0", "#18a875", "#e8764f", "#3bb8c9", "#d465a4", "#8fa03c"]

_ACTION_TONE = {"SELL NOW": "tone-down", "KEEP": "tone-up", "REVIEW": "tone-gold", "BUY CANDIDATE": "tone-blue"}


def _uid(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text) or "x"


def _allocation_bar(positions: list[dict], total: float | None) -> str:
    """iPhone-storage-style stacked allocation bar, from live Trading 212 values."""
    valued = [(p, float(p["market_value"])) for p in positions if p.get("market_value") is not None]
    if not valued or not total:
        return '<p class="empty">Allocation appears once Trading 212 positions are connected.</p>'
    segments, legend = [], []
    for index, (position, value) in enumerate(valued):
        colour = _SPECTRUM[index % len(_SPECTRUM)]
        ticker = html.escape(str(position.get("ticker", "?")))
        share = value / total
        segments.append(f'<span class="alloc-seg" style="width:{share * 100:.2f}%;background:{colour}" title="{ticker} · {share:.1%}"></span>')
        legend.append(f'<span class="lg-chip"><i style="background:{colour}"></i>{ticker}<b>{share:.1%}</b></span>')
    return f'<div class="alloc" role="img" aria-label="Live allocation across {len(valued)} holdings"><div class="alloc-bar">{"".join(segments)}</div><div class="alloc-legend">{"".join(legend)}</div></div>'


def _tape(positions: list[dict]) -> str:
    """A quiet market tape of the actual holdings — price and live return."""
    chips = []
    for position in positions:
        ticker = html.escape(str(position.get("ticker", "?")))
        currency = str(position.get("currency") or "")
        price = position.get("current_price")
        price_text = html.escape(_money(price, currency)) if price is not None else "—"
        ret = position.get("return_pct")
        if ret is None:
            ret_html = '<b class="flat">–</b>'
        else:
            klass = "up" if float(ret) >= 0 else "down"
            ret_html = f'<b class="{klass}">{float(ret):+.1%}</b>'
        chips.append(f'<div class="tape-chip"><span>{ticker}</span><strong>{price_text}</strong>{ret_html}</div>')
    if not chips:
        return ""
    return f'<div class="tape" aria-label="Holdings tape">{"".join(chips)}</div>'


def _chart(candles: list[dict], currency: str, uid: str = "c") -> str:
    data = candles[-60:]
    if len(data) < 2:
        return '<p class="empty">Candle history is not available for this run.</p>'
    width, height, top, bottom = 720, 270, 18, 32
    high = max(float(item["high"]) for item in data)
    low = min(float(item["low"]) for item in data)
    spread = max(high - low, 0.0001)
    plot_height = height - top - bottom
    step = width / len(data)

    def y(value: float) -> float:
        return top + (high - value) / spread * plot_height

    rows = []
    for index, item in enumerate(data):
        x = index * step + step / 2
        opening, closing = float(item["open"]), float(item["close"])
        colour = "var(--up)" if closing >= opening else "var(--down)"
        body_y = min(y(opening), y(closing))
        body_height = max(abs(y(opening) - y(closing)), 1.5)
        rows.append(
            f'<line x1="{x:.1f}" y1="{y(float(item["high"])):.1f}" x2="{x:.1f}" y2="{y(float(item["low"])):.1f}" stroke="{colour}" stroke-width="1.2"/>'
            f'<rect x="{x - step * .29:.1f}" y="{body_y:.1f}" width="{max(step * .58, 2):.1f}" height="{body_height:.1f}" rx="1" fill="{colour}"/>'
        )
    closes = [float(item["close"]) for item in data]
    points = " ".join(f"{i * step + step / 2:.1f},{y(v):.1f}" for i, v in enumerate(closes))
    trend = "var(--up)" if closes[-1] >= closes[0] else "var(--down)"
    gid = f"aura-{_uid(uid)}"
    area = (f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{trend}" stop-opacity=".16"/><stop offset="1" stop-color="{trend}" stop-opacity="0"/></linearGradient></defs>'
            f'<polygon points="{step / 2:.1f},{height - bottom} {points} {width - step / 2:.1f},{height - bottom}" fill="url(#{gid})"/>'
            f'<polyline points="{points}" fill="none" stroke="{trend}" stroke-opacity=".45" stroke-width="1.4" stroke-linejoin="round"/>')
    last_y = y(closes[-1])
    last_tag = (f'<line x1="0" y1="{last_y:.1f}" x2="{width}" y2="{last_y:.1f}" stroke="{trend}" stroke-opacity=".5" stroke-width="1" stroke-dasharray="3 4"/>'
                f'<text x="{width - 6}" y="{last_y - 5:.1f}" text-anchor="end" class="last-close" fill="{trend}">{html.escape(_currency(closes[-1], currency))}</text>')
    labels = "".join(
        f'<text x="8" y="{top + plot_height * fraction + 4:.1f}">{html.escape(_currency(high - spread * fraction, currency))}</text>'
        f'<line x1="0" y1="{top + plot_height * fraction:.1f}" x2="{width}" y2="{top + plot_height * fraction:.1f}" class="grid-line"/>'
        for fraction in (0, .5, 1)
    )
    first = datetime.fromisoformat(str(data[0]["timestamp"])).strftime("%d %b")
    last = datetime.fromisoformat(str(data[-1]["timestamp"])).strftime("%d %b")
    return f'''<figure class="chart-wrap"><svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Daily candlestick chart">{labels}{area}{''.join(rows)}{last_tag}<text x="8" y="264">{first}</text><text x="712" y="264" text-anchor="end">{last}</text></svg><figcaption>Daily candles · last {len(data)} sessions · not intraday</figcaption></figure>'''


def _chev() -> str:
    return f'<span class="chev" aria-hidden="true">{_icon("chevron")}</span>'


def _signal_row(signal: dict, snapshots: dict, candles: dict, display_prices: dict) -> str:
    ticker = str(signal.get("ticker", "Unknown"))
    action = str(signal.get("action", "REVIEW"))
    snap = snapshots.get(ticker, {})
    currency = str(snap.get("currency", "USD"))
    display = display_prices.get(ticker) or {}
    display_currency = str(display.get("currency") or currency)
    display_price = display.get("current_price")
    if display_price is None:
        display_price = snap.get("price", 0)
    source = snap.get("source_ticker")
    proxy = f'<span class="muted">via {html.escape(str(source))}</span>' if source and source != ticker else ""
    why_values = [_plain_research_point(str(value)) for value in signal.get("research_bullets", []) if str(value).strip()]
    for reason in signal.get("reasons", []):
        plain = _plain_reason(str(reason))
        if plain not in why_values:
            why_values.append(plain)
    fallback = {
        "SELL NOW": ["A sell rule you chose has been triggered.", "The warning has lasted long enough that it should not be ignored.", "Selling would reduce the risk of this one position causing more damage."],
        "KEEP": ["No sell rule has been triggered.", "The original reason for owning it has not clearly broken.", "Doing nothing avoids trading just because of normal daily noise."],
        "REVIEW": ["There is a warning, but not enough evidence for an automatic sell.", "Check the latest company or fund news before deciding.", "Keep the position under closer watch until the warning improves or worsens."],
    }.get(action, ["The rule evidence supports this action."])
    for value in fallback:
        if value not in why_values:
            why_values.append(value)
    reasons = "".join(f"<li>{html.escape(value)}</li>" for value in why_values[:10])
    tone = _ACTION_TONE.get(action, "tone-gold")
    why_label = {"SELL NOW": "Why sell", "KEEP": "Why hold", "REVIEW": "Why review"}.get(action, "Why")
    return f'''<details class="row signal {action.lower().replace(' ', '-')}"><summary><span class="tone-dot {tone}" aria-hidden="true"></span><div class="row-main"><span class="ticker">{html.escape(ticker)}</span>{proxy}</div><div class="row-end"><strong class="row-value">{html.escape(_currency(float(display_price), display_currency))}</strong><span class="row-caption {tone}">{html.escape(action)}</span></div>{_chev()}</summary><div class="row-body"><section class="evidence ai"><h3>{_icon("sparkle")}{why_label} · {len(why_values[:10])} simple reasons</h3><ul>{reasons}</ul></section>{_chart(candles.get(ticker, []), currency, ticker)}</div></details>'''


def _plain_reason(reason: str) -> str:
    replacements = {
        "above 200-day trend": "The price is above its average closing price from roughly the last 200 trading days—about ten months. That says the longer trend has generally been rising, but it does not guarantee the price will keep going up.",
        "below 200-day trend": "The price is below its average closing price from roughly the last 200 trading days—about ten months. That can mean the longer trend is weakening, but it is a warning to investigate rather than proof that you must sell.",
        "price and 20-day average above 50-day average": "Recent prices are stronger than the medium-term trend.",
        "short-term downtrend": "The price has been moving down recently.",
        "MACD positive": "Recent price movement is improving.",
        "MACD negative": "Recent price movement is weakening.",
        "persistent 200-day trend break": "The price has stayed below its long-term average for long enough to trigger your sell rule.",
        "configured loss limit breached": "The position has fallen past the maximum loss you configured.",
        "core trend break; verify thesis before acting": "This is a core holding, so do not panic-sell; check whether the fund still fits the long-term plan.",
    }
    if reason in replacements:
        return replacements[reason]
    if reason.startswith("constructive RSI"):
        return "Buying and selling pressure looks balanced—not unusually hot or weak."
    if reason.startswith("overbought RSI"):
        return "The price has risen very quickly, so it may be temporarily expensive."
    if reason.startswith("oversold RSI"):
        return "The price has fallen very quickly; this is a warning to investigate, not an automatic buy signal."
    return reason.replace(";", ".")


def _plain_research_point(value: str) -> str:
    text = str(value).strip()
    lower = text.lower()
    if "200-day" in lower and "above" in lower:
        return "The price is above its average closing price from roughly the last 200 trading days—about ten months. This means the longer trend has generally been rising, but it does not promise future gains."
    if "200-day" in lower and "below" in lower:
        return "The price is below its average closing price from roughly the last 200 trading days—about ten months. This is a warning that the longer trend may be weakening, not an automatic sell instruction."
    if "rsi" in lower:
        return "RSI is a 0-to-100 speed meter for recent price moves. A reading near the middle means the price is neither rising nor falling unusually fast; RSI alone is never a reason to buy."
    return text


def _research_row(index: int, item: dict, timezone: str, candles: dict) -> str:
    ticker = str(item.get("ticker", "Unknown"))
    deterministic = "".join(f"<li>{html.escape(str(text))}</li>" for text in item.get("bullets", []))
    ai_bullets = "".join(f"<li>{html.escape(str(text))}</li>" for text in item.get("ai_bullets", []))
    sources = []
    for source in item.get("ai_sources", []):
        url = html.escape(str(source.get("url", "")), quote=True)
        if url:
            sources.append(f'<li><a href="{url}" target="_blank" rel="noopener">{html.escape(str(source.get("title", "Source")))}</a><small>{html.escape(str(source.get("publisher", "")))}</small></li>')
    if not sources:
        for story in item.get("news", []):
            url = html.escape(str(story.get("url", "")), quote=True)
            title = html.escape(str(story.get("title", "Market update")))
            link = f'<a href="{url}" target="_blank" rel="noopener">{title}</a>' if url else title
            sources.append(f'<li>{link}<small>{html.escape(str(story.get("publisher", "Unknown source")))} · {html.escape(_when(story.get("published_at"), timezone))}</small></li>')
    currency = str(item.get("currency", "USD"))
    ai_block = f'<section class="evidence ai"><h3>{_icon("sparkle")}AI web research</h3><ul>{ai_bullets}</ul></section>' if ai_bullets else ''
    action = str(item.get('action', 'RESEARCH'))
    tone = _ACTION_TONE.get(action, "tone-blue")
    return f'''<details class="row dossier"><summary><span class="dossier-index" aria-hidden="true">{index:02d}</span><div class="row-main"><span class="ticker">{html.escape(ticker)}</span><span class="muted block">{html.escape(_currency(float(item.get('price', 0)), currency))}</span></div><div class="row-end"><span class="row-caption {tone}">{html.escape(action)}</span></div>{_chev()}</summary><div class="row-body"><p class="lede-text">{html.escape(str(item.get('ai_summary', 'No AI summary was available for this run.')))}</p>{ai_block}<section class="evidence"><h3>{_icon("scale")}Technical research</h3><ul>{deterministic or '<li>No deterministic evidence saved for this run.</li>'}</ul></section><section class="evidence"><h3>{_icon("link")}Sources</h3><ul class="sources">{''.join(sources) or '<li>No verified source was attached to this run.</li>'}</ul></section>{_chart(candles.get(ticker, []), currency, ticker)}</div></details>'''


def _portfolio_row(position: dict, colour: str, share: float | None) -> str:
    currency = str(position.get("currency") or "")
    ret = position.get("return_pct")
    return_text = "n/a" if ret is None else f"{float(ret):+.1%}"
    return_class = "up" if ret is not None and float(ret) >= 0 else "down"
    quantity = position.get("quantity")
    average = position.get("average_price")
    cost = float(quantity) * float(average) if quantity is not None and average is not None else None
    unrealized = position.get("unrealized")
    unreal_class = "up" if unrealized is not None and float(unrealized) >= 0 else "down"
    share_text = "n/a" if share is None else f"{share:.1%}"
    share_bar = "" if share is None else f'<i class="share-track"><i class="share-fill" style="width:{min(share, 1) * 100:.2f}%"></i></i>'
    return f'''<details class="row holding" style="--seg:{colour}"><summary><span class="seg-dot" aria-hidden="true"></span><div class="row-main"><span class="ticker">{html.escape(str(position.get('ticker', 'Unknown')))}</span><span class="muted block">{html.escape(str(position.get('name', '')))}</span></div><div class="row-end"><strong class="row-value">{html.escape(_money(position.get('market_value'), currency))}</strong><span class="row-caption {return_class}">{return_text}</span></div>{_chev()}</summary><div class="row-body"><div class="share-row"><span>Share of portfolio</span><b>{share_text}</b></div>{share_bar}<div class="metrics"><div><span>Market value</span><strong>{html.escape(_money(position.get('market_value'), currency))}</strong></div><div><span>Cost</span><strong>{html.escape(_money(cost, currency))}</strong></div><div><span>Return</span><strong class="{return_class}">{return_text}</strong></div><div><span>Unrealised P/L</span><strong class="{unreal_class}">{html.escape(_money(unrealized, currency))}</strong></div><div><span>Quantity</span><strong>{float(position.get('quantity', 0)):,.4f}</strong></div><div><span>Average per share</span><strong>{html.escape(_money(position.get('average_price'), currency))}</strong></div><div><span>Latest per share</span><strong>{html.escape(_money(position.get('current_price'), currency))}</strong></div></div></div></details>'''


def _history_node(run: dict, timezone: str) -> str:
    signals, snapshots = run.get("signals", []), run.get("snapshots", {})
    counts = {action: sum(1 for item in signals if item.get("action") == action) for action in ("SELL NOW", "KEEP", "REVIEW", "BUY CANDIDATE")}
    chips = "".join(f'<span class="chip {_ACTION_TONE[action]}">{html.escape(action.title())} {count}</span>' for action, count in counts.items() if count) or '<span class="chip">No signals</span>'
    rows = []
    for signal in signals:
        ticker = str(signal.get("ticker", "Unknown")); snap = snapshots.get(ticker, {})
        rows.append(f'<div class="history-row"><strong>{html.escape(ticker)}</strong><span>{html.escape(str(signal.get("action", "REVIEW")))}</span><b>{html.escape(_currency(float(snap.get("price", 0)), str(snap.get("currency", "USD"))))}</b></div>')
    return f'''<details class="row t-node"><summary><div class="row-main"><strong class="t-date">{html.escape(_when(run.get('generated_at'), timezone))}</strong><small class="muted block wrap">Data: {html.escape(_when(run.get('latest_data_at'), timezone))}</small><div class="t-chips">{chips}</div></div>{_chev()}</summary><div class="row-body"><p class="lede-text">{html.escape(str(run.get('market_summary', 'No web summary saved for this run.')))}</p><div class="history-rows">{''.join(rows) or '<p class="empty">No saved signals.</p>'}</div></div></details>'''


def _icon(name: str) -> str:
    paths = {
        "today": '<path d="M4 10.8 11.05 4.9a1.5 1.5 0 0 1 1.9 0L20 10.8"/><path d="M5.8 9.5v8.2A1.8 1.8 0 0 0 7.6 19.5h2.6v-4.4a1.8 1.8 0 0 1 3.6 0v4.4h2.6a1.8 1.8 0 0 0 1.8-1.8V9.5"/>',
        "portfolio": '<path d="M4.5 12.9c2.1 0 2.9-4.4 4.9-4.4s2.4 6.9 4.6 6.9 2.6-4.2 5.5-4.2"/><rect x="2.8" y="4.2" width="18.4" height="15.6" rx="4"/>',
        "plan": '<path d="M4 18.5V14l4-4 3 3 7-8"/><path d="M14.5 5H18v3.5"/><rect x="2.8" y="2.8" width="18.4" height="18.4" rx="4"/>',
        "research": '<circle cx="10.8" cy="10.8" r="6.6"/><path d="m15.7 15.7 4.5 4.5"/><path d="M8 12.1l1.8-2.1 1.7 1.3 2-2.8"/>',
        "history": '<path d="M3.6 12a8.4 8.4 0 1 0 2.5-6L3.8 8.2"/><path d="M3.7 3.8v4.4h4.4"/><path d="M12 7.6V12l3.3 2"/>',
        "refresh": '<path d="M20 12a8 8 0 0 1-14.6 4.5M4 12a8 8 0 0 1 14.6-4.5"/><path d="M18.9 3.6v4h-4M5.1 20.4v-4h4"/>',
        "sun": '<circle cx="12" cy="12" r="3.6"/><path d="M12 3v2.1M12 18.9V21M4.6 4.6l1.5 1.5m11.8 11.8 1.5 1.5M3 12h2.1M18.9 12H21M4.6 19.4l1.5-1.5M17.9 6.1l1.5-1.5"/>',
        "moon": '<path d="M20.4 14.9A8.6 8.6 0 0 1 9.1 3.6a8.7 8.7 0 1 0 11.3 11.3z"/>',
        "chevron": '<path d="m6.5 9.6 5.5 5 5.5-5"/>',
        "sparkle": '<path d="M12 4.5c.5 3.6 1.9 5 5.5 5.5-3.6.5-5 1.9-5.5 5.5-.5-3.6-1.9-5-5.5-5.5 3.6-.5 5-1.9 5.5-5.5z"/><path d="M18.8 14.6c.25 1.8.95 2.5 2.7 2.7-1.75.25-2.45.95-2.7 2.7-.25-1.75-.95-2.45-2.7-2.7 1.75-.2 2.45-.9 2.7-2.7z"/>',
        "scale": '<path d="M12 4v16M7.5 20h9"/><path d="M5.5 6.5h13"/><path d="M5.5 6.5 3 12.3a2.9 2.9 0 0 0 5 0zM18.5 6.5 16 12.3a2.9 2.9 0 0 0 5 0z"/>',
        "link": '<path d="M9.5 14.5 14.5 9.5"/><path d="M8 11 5.9 13.1a3.6 3.6 0 0 0 5 5L13 16M11 8l2.1-2.1a3.6 3.6 0 0 1 5 5L16 13"/>',
        "alert": '<circle cx="12" cy="12" r="8.6"/><path d="M12 7.8v4.9"/><path d="M12 16.1h.01"/>',
        "shield": '<path d="M12 3.4 5.2 6v5.4c0 4.2 2.8 7.3 6.8 9.2 4-1.9 6.8-5 6.8-9.2V6z"/><path d="m9.2 12 2 2 3.6-4"/>',
    }
    return f'<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">{paths[name]}</svg>'


def _nav(active: str, theme: str, mobile: bool = False) -> str:
    labels = [("today", "Today"), ("portfolio", "Portfolio"), ("plan", "Plan"), ("research", "Research"), ("history", "History")]
    items = "".join(
        f'<form method="get" action="./"><input type="hidden" name="theme" value="{theme}">'
        f'<button type="submit" class="nav-item {"active" if active == key else ""}" name="tab" value="{key}" '
        f'aria-label="{label}"{" aria-current=" + chr(34) + "page" + chr(34) if active == key else ""}>'
        f'<span class="nav-icon">{_icon(key)}</span><b class="nav-label">{label}</b></button></form>'
        for key, label in labels
    )
    return f'<nav class="{"bottom-nav" if mobile else "rail-nav"}" aria-label="{"Primary, compact" if mobile else "Primary"}">{items}</nav>'


def _theme_switch(active_tab: str, theme: str) -> str:
    return f'''<form class="theme-switch" method="get" action="./" aria-label="Colour theme">
      <input type="hidden" name="tab" value="{active_tab}">
      <button type="submit" name="theme" value="light" class="{'active' if theme == 'light' else ''}" aria-label="Light mode" title="Light mode">{_icon('sun')}</button>
      <button type="submit" name="theme" value="dark" class="{'active' if theme == 'dark' else ''}" aria-label="Dark mode" title="Dark mode">{_icon('moon')}</button>
    </form>'''


def _run_form(compact: bool = False) -> str:
    label = '<span class="run-label">Run now</span>'
    return f'<form class="run" method="post" action="./run"><button class="run-button{" compact" if compact else ""}" type="submit" title="Run now" aria-label="Run now">{_icon("refresh")}{label}</button></form>'


_STYLE = '''
/* ==== cross-document view transitions: tab changes morph, zero JavaScript ==== */
@view-transition{navigation:auto}
.toolbar{view-transition-name:vt-toolbar}
.rail{view-transition-name:vt-rail}
.bottom-nav{view-transition-name:vt-dock}
.masthead{view-transition-name:vt-masthead}
::view-transition-old(root),::view-transition-new(root){animation-duration:.22s}
@media(prefers-reduced-motion:reduce){::view-transition-group(*),::view-transition-old(*),::view-transition-new(*){animation:none!important}}

:root{
  --bg:#f5f1e8;
  --ink:#191b20; --muted:#6e6a5f; --faint:#8d887c;
  --paper-hi:rgba(255,255,255,.62); --paper-lo:rgba(255,255,255,.34);
  --specular:rgba(255,255,255,.78); --specular-soft:rgba(255,255,255,.32);
  --stroke:rgba(255,255,255,.68); --edge:rgba(56,48,32,.11); --glint:rgba(255,255,255,.95);
  --accent:#b98a00; --accent-soft:rgba(215,164,20,.14); --accent-ink:#6c5000;
  --up:#0e8f65; --up-soft:rgba(14,143,101,.12);
  --down:#cf5750; --down-soft:rgba(207,87,80,.12);
  --blue:#3a7fc2; --blue-soft:rgba(58,127,194,.12);
  --focus:#7d5f00;
  --shadow:0 22px 48px rgba(70,56,24,.12),0 2px 6px rgba(70,56,24,.05);
  --shadow-sm:0 10px 24px rgba(70,56,24,.09),0 1px 3px rgba(70,56,24,.05);
  --dock-bg:rgba(23,25,31,.68); --dock-stroke:rgba(255,255,255,.17);
  --dock-icon:rgba(236,239,246,.60); --dock-icon-active:#fff;
  --serif:ui-serif,"New York",Georgia,"Times New Roman",serif;
  --sans:-apple-system,BlinkMacSystemFont,"SF Pro Display","SF Pro Text","Segoe UI",Roboto,sans-serif;
  --r-xl:28px; --r-lg:22px; --r-md:16px;
  font-family:var(--sans);
  color-scheme:light dark;
}
.theme-dark{
  --bg:#07090f;
  --ink:#f3f3ef; --muted:#9aa0ac; --faint:#767c88;
  --paper-hi:rgba(40,45,57,.56); --paper-lo:rgba(20,23,32,.40);
  --specular:rgba(255,255,255,.14); --specular-soft:rgba(255,255,255,.07);
  --stroke:rgba(255,255,255,.135); --edge:rgba(255,255,255,.085); --glint:rgba(205,222,255,.5);
  --accent:#e6c14e; --accent-soft:rgba(230,193,78,.13); --accent-ink:#eecd6b;
  --up:#3dcb92; --up-soft:rgba(61,203,146,.13);
  --down:#ef8078; --down-soft:rgba(239,128,120,.13);
  --blue:#71ace8; --blue-soft:rgba(113,172,232,.13);
  --focus:#e6c14e;
  --shadow:0 24px 56px rgba(0,0,0,.50),0 2px 8px rgba(0,0,0,.35);
  --shadow-sm:0 12px 28px rgba(0,0,0,.38),0 1px 4px rgba(0,0,0,.28);
  --dock-bg:rgba(13,15,22,.74); --dock-stroke:rgba(255,255,255,.14);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;min-height:100vh;background:var(--bg);color:var(--ink);overflow-x:hidden;font-size:15px;line-height:1.5}
body::before{content:"";position:fixed;inset:-22%;z-index:-2;background:
  radial-gradient(46% 34% at 14% 10%,rgba(248,214,120,.30) 0%,transparent 70%),
  radial-gradient(40% 30% at 88% 4%,rgba(255,245,222,.55) 0%,transparent 72%),
  radial-gradient(52% 40% at 76% 88%,rgba(240,224,186,.36) 0%,transparent 74%),
  linear-gradient(150deg,#f9f4ea 0%,#f0ebdf 55%,#f6f0e2 100%);
  animation:drift 52s ease-in-out infinite alternate}
@keyframes drift{from{transform:translate3d(0,0,0) scale(1)}to{transform:translate3d(2.2%,-1.6%,0) scale(1.045)}}
body::after{content:"";position:fixed;inset:0;z-index:-1;opacity:.11;pointer-events:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='160'%3E%3Cfilter id='n'%3E%3CfeTurbulence baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='.18'/%3E%3C/svg%3E")}
.theme-dark body::before{background:
  radial-gradient(44% 34% at 12% 8%,rgba(58,86,168,.32) 0%,transparent 72%),
  radial-gradient(40% 32% at 88% 10%,rgba(112,64,150,.26) 0%,transparent 74%),
  radial-gradient(50% 40% at 70% 90%,rgba(158,116,26,.22) 0%,transparent 76%),
  linear-gradient(155deg,#090c14 0%,#0b0e17 55%,#07090f 100%)}
.theme-dark body::after{opacity:.07}

/* ============================== glass surfaces ============================== */
.sheet,.toolbar,.rail,.warn-sheet,.tape-chip{
  position:relative;
  background:linear-gradient(165deg,var(--paper-hi) 0%,var(--paper-lo) 100%);
  border:1px solid var(--stroke);
  box-shadow:inset 0 1px 0 var(--specular),inset 0 -1px 0 var(--specular-soft),var(--shadow-sm);
  backdrop-filter:blur(26px) saturate(180%);-webkit-backdrop-filter:blur(26px) saturate(180%);
}
.sheet::before,.warn-sheet::before{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;background:radial-gradient(120% 45% at 18% -4%,var(--specular-soft) 0%,transparent 58%)}
.sheet::after{content:"";position:absolute;inset:-1px;border-radius:inherit;padding:1px;pointer-events:none;background:conic-gradient(from 250deg at 30% -10%,transparent 0 18%,var(--glint) 26%,transparent 34% 100%);-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);mask-composite:exclude;opacity:.65}
.sheet{border-radius:var(--r-lg);overflow:hidden}
.sheet>*{position:relative;z-index:1}

/* ============================ app frame: toolbar ============================ */
.toolbar{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:10px;padding:9px 14px;border-left:0;border-right:0;border-top:0;border-radius:0;box-shadow:0 1px 0 var(--edge)}
.toolbar .brand{display:flex;align-items:center;gap:9px;flex:1;min-width:0}
.toolbar img{width:27px;height:27px;object-fit:contain;flex:none}
.toolbar b{font-size:14px;font-weight:750;letter-spacing:-.01em;white-space:nowrap}
.toolbar-controls{display:flex;align-items:center;gap:7px;flex:none}

/* ============================= app frame: rail ============================= */
.rail{display:none}
@media(min-width:960px){
  .toolbar{display:none}
  .rail{display:flex;flex-direction:column;gap:6px;position:fixed;left:0;top:0;bottom:0;width:248px;z-index:30;padding:22px 16px 20px;border-top:0;border-bottom:0;border-left:0;border-radius:0}
  .rail .brand{display:flex;align-items:center;gap:10px;padding:2px 8px 16px}
  .rail img{width:38px;height:38px;object-fit:contain;flex:none;filter:drop-shadow(0 5px 10px rgba(70,54,14,.22))}
  .rail .brand b{display:block;font-size:15px;font-weight:760;letter-spacing:-.02em}
  .rail .brand span{display:block;font-size:10.5px;color:var(--muted)}
  .rail-nav{display:flex;flex-direction:column;gap:2px}
  .rail-nav .nav-item{width:100%;justify-content:flex-start;padding:0 13px;min-height:46px;border-radius:14px}
  .rail-spacer{flex:1}
  .rail .theme-switch{align-self:stretch;justify-content:center}
  .rail .theme-switch button{flex:1}
  .rail .run{margin-top:8px}
  .rail .run-button{width:100%;justify-content:center}
  .colophon{margin-top:16px;padding:12px 8px 0;border-top:1px solid var(--edge);font-size:10.5px;line-height:1.6;color:var(--faint)}
  .colophon b{display:block;color:var(--muted);font-weight:650}
  .canvas{margin-left:248px}
  main{max-width:880px;margin:0 auto;padding:30px 34px 70px}
  .bottom-nav{display:none!important}
}
main{padding:16px 14px calc(112px + env(safe-area-inset-bottom))}
.colophon{display:none}
@media(min-width:960px){.colophon{display:block}}

/* ================================ controls ================================ */
button{font:inherit;color:inherit}
.theme-switch{display:flex;gap:2px;padding:3px;border-radius:999px;border:1px solid var(--stroke);background:linear-gradient(160deg,var(--paper-lo),transparent);box-shadow:inset 0 1px 0 var(--specular-soft)}
.theme-switch button{appearance:none;border:1px solid transparent;background:transparent;color:var(--muted);min-width:34px;height:34px;padding:7px;border-radius:999px;cursor:pointer;display:grid;place-items:center;transition:background .18s,color .18s}
.theme-switch button:hover{color:var(--ink)}
.theme-switch button.active{color:var(--ink);border-color:var(--stroke);background:radial-gradient(120% 130% at 30% 12%,var(--specular) 0%,var(--paper-lo) 60%);box-shadow:inset 0 1px 0 var(--specular),0 5px 12px rgba(0,0,0,.12)}
.theme-switch svg,.run-button svg{width:17px;height:17px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.run{margin:0}
.run-button{appearance:none;display:flex;align-items:center;gap:7px;min-height:40px;border:1px solid var(--stroke);border-radius:999px;background:linear-gradient(160deg,var(--paper-lo),transparent);color:var(--muted);padding:0 14px;font-size:13px;font-weight:700;box-shadow:inset 0 1px 0 var(--specular-soft);cursor:pointer;transition:color .18s,background .18s,transform .1s}
.run-button:hover{color:var(--ink);background:linear-gradient(160deg,var(--paper-hi),var(--paper-lo))}
.run-button:active{transform:scale(.97)}
.run-button.compact{width:40px;padding:0;justify-content:center}
.run-button.compact .run-label{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}

/* ================================== nav ================================== */
.nav-item{position:relative;appearance:none;border:1px solid transparent;background:transparent;display:flex;align-items:center;gap:11px;min-height:44px;padding:0 16px;border-radius:999px;color:var(--muted);font-size:13.5px;font-weight:650;cursor:pointer;transition:color .18s,background .18s,transform .1s}
.nav-item:hover{color:var(--ink);background:var(--specular-soft)}
.nav-item:active{transform:scale(.97)}
.nav-item.active{color:var(--ink);border-color:var(--stroke);background:radial-gradient(130% 150% at 28% 8%,var(--specular) 0%,var(--paper-lo) 55%,transparent 100%);box-shadow:inset 0 1px 0 var(--specular),0 6px 14px rgba(30,25,12,.10)}
.theme-dark .nav-item.active{box-shadow:inset 0 1px 0 rgba(255,255,255,.2),0 8px 18px rgba(0,0,0,.32)}
.nav-icon{display:grid;place-items:center;width:20px;height:20px;flex:none}
.nav-icon svg{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
@media(max-width:959.98px){.rail-nav{display:none}}
.bottom-nav{display:flex;position:fixed;z-index:40;left:50%;transform:translateX(-50%);bottom:calc(14px + env(safe-area-inset-bottom));gap:3px;padding:7px;border-radius:999px;background:var(--dock-bg);border:1px solid var(--dock-stroke);box-shadow:inset 0 1px 0 rgba(255,255,255,.20),inset 0 -1px 0 rgba(255,255,255,.05),0 18px 40px rgba(0,0,0,.38);backdrop-filter:blur(26px) saturate(165%);-webkit-backdrop-filter:blur(26px) saturate(165%)}
.bottom-nav form{margin:0}
.bottom-nav .nav-item{width:52px;height:52px;padding:0;border-radius:999px;color:var(--dock-icon);justify-content:center}
.bottom-nav .nav-item:hover{background:rgba(255,255,255,.07);color:var(--dock-icon-active)}
.bottom-nav .nav-item:active{transform:scale(.92)}
.bottom-nav .nav-label{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.bottom-nav .nav-icon,.bottom-nav .nav-icon svg{width:23px;height:23px}
.bottom-nav .nav-item.active{color:var(--dock-icon-active);border:1px solid rgba(255,255,255,.32);background:radial-gradient(125% 145% at 30% 10%,rgba(255,255,255,.30) 0%,rgba(255,255,255,.10) 52%,rgba(255,255,255,.03) 100%);box-shadow:inset 0 1px 0 rgba(255,255,255,.45),inset 0 -8px 14px rgba(255,255,255,.05),0 8px 18px rgba(0,0,0,.32)}
.bottom-nav .nav-item.active::after{content:"";position:absolute;bottom:6px;left:50%;transform:translateX(-50%);width:4px;height:4px;border-radius:999px;background:currentColor;opacity:.9}
.bottom-nav .nav-item:focus-visible{outline-color:#fff}

/* ============================ editorial masthead ============================ */
.masthead{padding:22px 6px 4px}
.eyebrow{display:block;font-size:10.5px;font-weight:750;text-transform:uppercase;letter-spacing:.17em;color:var(--accent-ink)}
.edition{font-family:var(--serif);font-size:clamp(34px,8.4vw,54px);font-weight:640;letter-spacing:-.015em;line-height:1.04;margin:8px 0 0;text-wrap:balance}
.byline{display:block;margin-top:10px;font-size:12px;color:var(--muted);line-height:1.6}
.byline svg{width:13px;height:13px;fill:none;stroke:var(--up);stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;display:inline-block;vertical-align:-2px;margin-right:4px}
.money{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;flex-wrap:wrap;margin-top:20px;padding-top:18px;border-top:1px solid var(--edge)}
.money-label{display:block;font-size:10.5px;font-weight:750;text-transform:uppercase;letter-spacing:.14em;color:var(--faint);margin-bottom:6px}
.big-value{display:block;font-size:clamp(33px,7vw,44px);font-weight:740;letter-spacing:-.045em;line-height:1;font-variant-numeric:tabular-nums}
@supports(-webkit-background-clip:text){
  .big-value{background:linear-gradient(105deg,var(--ink) 38%,color-mix(in srgb,var(--ink) 55%,var(--accent)) 50%,var(--ink) 62%);background-size:240% 100%;-webkit-background-clip:text;background-clip:text;color:transparent;animation:sheen 2.2s ease .35s 1 both}
  .big-value em{-webkit-text-fill-color:var(--muted)}
}
@keyframes sheen{from{background-position:120% 0}to{background-position:-60% 0}}
.big-value em{font-style:normal;font-size:.36em;font-weight:650;color:var(--muted);letter-spacing:.02em;margin-left:.35em;vertical-align:.3em}
.money-sub{font-size:12px;color:var(--muted);margin-top:8px;display:block}
.alloc{flex:1 1 320px;min-width:0}
.alloc-bar{display:flex;height:14px;border-radius:9px;overflow:hidden;gap:2px;box-shadow:inset 0 1px 2px rgba(0,0,0,.10)}
.alloc-seg{display:block;height:100%;min-width:5px}
.alloc-legend{display:flex;flex-wrap:wrap;gap:5px 12px;margin-top:9px}
.lg-chip{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:650;color:var(--muted)}
.lg-chip i{width:8px;height:8px;border-radius:3px;flex:none}
.lg-chip b{font-variant-numeric:tabular-nums;color:var(--ink);font-weight:700}

/* ================================= tape ================================= */
.tape{display:flex;gap:9px;overflow-x:auto;scroll-snap-type:x proximity;padding:16px 2px 6px;margin:0 -2px;scrollbar-width:none}
.tape::-webkit-scrollbar{display:none}
.tape-chip{scroll-snap-align:start;flex:none;display:grid;gap:3px;min-width:118px;padding:10px 13px;border-radius:var(--r-md)}
.tape-chip span{font-size:11px;font-weight:800;letter-spacing:.02em;color:var(--muted)}
.tape-chip strong{font-size:13.5px;font-weight:750;font-variant-numeric:tabular-nums;letter-spacing:-.01em;white-space:nowrap}
.tape-chip b{font-size:11.5px;font-weight:750;font-variant-numeric:tabular-nums}
.flat{color:var(--faint)}

/* ============================ views & ledger ============================ */
.view{display:none}.view.active{display:block}
.sheet-label{display:flex;align-items:baseline;gap:8px;margin:26px 6px 9px;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.13em;color:var(--faint)}
.sheet-label .count{font-variant-numeric:tabular-nums;font-weight:750}
.sheet-label.tone-down{color:var(--down)}.sheet-label.tone-up{color:var(--up)}.sheet-label.tone-gold{color:var(--accent-ink)}.sheet-label.tone-blue{color:var(--blue)}
.lede{padding:19px 20px}
.lede h2{font-family:var(--serif);font-size:21px;font-weight:650;letter-spacing:-.01em;margin:0 0 9px}
.lede p{margin:0;font-family:var(--serif);font-size:16px;line-height:1.62;color:var(--ink)}
.lede p::first-letter{font-size:2.9em;float:left;line-height:.83;padding:4px 8px 0 0;font-weight:640;color:var(--accent-ink)}
.empty{padding:12px 16px;color:var(--faint);font-size:13.5px;margin:0}
.sheet>.empty{padding:15px 18px}

/* rows */
summary{cursor:pointer;list-style:none}
summary::-webkit-details-marker{display:none}
.row+.row{border-top:1px solid var(--edge)}
.row>summary{display:flex;align-items:center;gap:12px;padding:14px 16px;min-height:56px;transition:background .15s}
.row>summary:hover{background:var(--specular-soft)}
.row-main{flex:1;min-width:0}
.row-end{text-align:right;flex:none;display:grid;gap:3px;justify-items:end}
.row-value{font-size:15px;font-weight:750;letter-spacing:-.015em;font-variant-numeric:tabular-nums;white-space:nowrap}
.row-caption{font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:.07em}
.row-caption.tone-down{color:var(--down)}.row-caption.tone-up{color:var(--up)}.row-caption.tone-gold{color:var(--accent-ink)}.row-caption.tone-blue{color:var(--blue)}
.row-caption.up{color:var(--up)}.row-caption.down{color:var(--down)}
.row-body{padding:2px 16px 18px;border-top:1px solid var(--edge);margin:0 0 0 0}
details[open] .row-body{transition:opacity .28s ease,transform .28s ease}
@starting-style{details[open] .row-body{opacity:0;transform:translateY(-5px)}}
.ticker{font-size:16px;font-weight:800;letter-spacing:-.02em}
.muted{color:var(--muted);font-size:12px}.ticker+.muted{margin-left:7px}
.block{display:block;margin:3px 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.block.wrap{white-space:normal}
.chev{display:grid;place-items:center;width:20px;height:20px;color:var(--faint);flex:none}
.chev svg{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;transition:transform .22s}
details[open]>summary .chev svg{transform:rotate(180deg)}
.tone-dot{width:8px;height:8px;border-radius:999px;flex:none}
.tone-dot.tone-up{background:var(--up)}.tone-dot.tone-down{background:var(--down)}.tone-dot.tone-gold{background:var(--accent)}.tone-dot.tone-blue{background:var(--blue)}
.seg-dot{width:9px;height:9px;border-radius:3px;flex:none;background:var(--seg,var(--accent));box-shadow:0 0 8px color-mix(in srgb,var(--seg,var(--accent)) 50%,transparent)}
.dossier-index{font-family:var(--serif);font-size:21px;font-weight:640;color:var(--faint);flex:none;width:30px;text-align:center;font-variant-numeric:tabular-nums}
.chip{font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:.06em;padding:4px 8px;border-radius:999px;border:1px solid var(--edge);color:var(--muted);background:var(--specular-soft);white-space:nowrap}
.chip.tone-up{background:var(--up-soft);color:var(--up);border-color:transparent}
.chip.tone-down{background:var(--down-soft);color:var(--down);border-color:transparent}
.chip.tone-gold{background:var(--accent-soft);color:var(--accent-ink);border-color:transparent}
.chip.tone-blue{background:var(--blue-soft);color:var(--blue);border-color:transparent}

ul,ol{padding-left:19px;margin:8px 0}
li{margin:7px 0;line-height:1.5;overflow-wrap:break-word}
.evidence{margin-top:16px}
.evidence h3{display:flex;align-items:center;gap:6px;font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:.1em;color:var(--faint);margin:0 0 4px}
.evidence h3 svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.evidence.ai h3{color:var(--accent-ink)}
.lede-text{font-family:var(--serif);line-height:1.62;font-size:15.5px;margin:12px 0 0;overflow-wrap:break-word}
.sources a{color:inherit;font-weight:700;text-decoration-color:var(--accent);text-underline-offset:2px;overflow-wrap:anywhere}
.sources small{display:block;color:var(--muted);margin-top:3px}
.chart-wrap{margin:16px 0 0;background:var(--specular-soft);border:1px solid var(--edge);border-radius:12px;padding:9px 9px 5px}
.chart{display:block;width:100%;height:auto}
.chart text{font-size:10px;fill:var(--muted)}
.chart .last-close{font-size:10.5px;font-weight:700;paint-order:stroke;stroke:var(--bg);stroke-width:3px;stroke-linejoin:round}
.grid-line{stroke:var(--edge);stroke-width:1}
.chart-wrap figcaption{color:var(--faint);font-size:11px;padding:4px 4px 3px}

.share-row{display:flex;justify-content:space-between;align-items:baseline;padding-top:14px}
.share-row span{color:var(--faint);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em}
.share-row b{font-size:13px;font-variant-numeric:tabular-nums;color:var(--seg,var(--ink))}
.share-track{display:block;height:6px;border-radius:999px;background:var(--specular-soft);margin-top:7px;overflow:hidden}
.share-fill{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,color-mix(in srgb,var(--seg,var(--accent)) 70%,transparent),var(--seg,var(--accent)))}
.metrics{display:grid;grid-template-columns:repeat(2,1fr);gap:14px 18px;padding-top:16px}
@media(min-width:960px){.metrics{grid-template-columns:repeat(3,1fr)}}
.metrics span{display:block;color:var(--faint);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;margin-bottom:4px}
.metrics strong{font-size:14px;font-weight:700;font-variant-numeric:tabular-nums}
.up{color:var(--up)}.down{color:var(--down)}

/* ============================ history timeline ============================ */
.timeline{position:relative;padding-left:24px;margin-top:4px}
.timeline::before{content:"";position:absolute;left:8px;top:14px;bottom:14px;width:2px;border-radius:2px;background:linear-gradient(var(--edge),var(--edge))}
.timeline .sheet{margin-bottom:12px;overflow:visible}
.timeline .sheet .row>summary{border-radius:inherit}
.timeline .sheet::marker{content:none}
.t-node>summary{align-items:flex-start;padding:15px 16px}
.t-node .row-main{position:relative}
.timeline .sheet{position:relative}
.timeline .sheet::before{border-radius:inherit}
.timeline .t-pin{content:"";position:absolute;left:-21px;top:24px;width:10px;height:10px;border-radius:999px;background:var(--accent);box-shadow:0 0 0 3px var(--bg),0 0 10px color-mix(in srgb,var(--accent) 60%,transparent)}
.t-date{font-size:14.5px;font-weight:750;letter-spacing:-.01em;white-space:nowrap}
.t-chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.history-rows{margin-top:12px}
.history-row{display:grid;grid-template-columns:1fr 1fr auto;gap:10px;padding:10px 0;border-bottom:1px solid var(--edge);align-items:baseline}
.history-row:last-child{border-bottom:0}
.history-row span{font-size:11px;color:var(--muted);text-transform:capitalize}
.history-row b{font-variant-numeric:tabular-nums;white-space:nowrap}

/* ============================ warnings & footer ============================ */
.warn-sheet{display:flex;gap:12px;border-radius:var(--r-md);padding:15px 17px;margin-top:24px;background:linear-gradient(160deg,var(--accent-soft),var(--paper-lo))}
.warn-sheet>*{position:relative;z-index:1}
.warn-sheet svg{width:19px;height:19px;flex:none;margin-top:2px;fill:none;stroke:var(--accent-ink);stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.warn-sheet strong{font-size:13px;font-weight:750}
.warn-sheet ul{margin:6px 0 0}
.warn-sheet li{font-size:13px;color:var(--muted)}
.smallprint{font-family:var(--serif);font-style:italic;font-size:12px;text-align:center;color:var(--faint);margin:30px auto 8px;max-width:480px;line-height:1.6}
.setup-copy{padding:17px 20px;line-height:1.6;color:var(--muted);font-size:14px}
.setup-copy h2{display:flex;align-items:center;gap:9px;font-size:17px;font-weight:750;letter-spacing:-.02em;margin:0 0 8px;color:var(--ink)}
.setup-copy h2 svg{width:19px;height:19px;fill:none;stroke:var(--accent-ink);stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.setup-copy p{margin:8px 0}

/* ============================ capital deployment ============================ */
.capital-form{padding:18px 20px;display:grid;gap:11px}
.capital-form label{font-size:13px;font-weight:800;letter-spacing:-.01em}
.capital-form small{color:var(--muted);line-height:1.45}
.capital-input{display:flex;align-items:center;gap:8px;max-width:520px}
.capital-input>span{font-family:var(--serif);font-size:28px;color:var(--accent-ink)}
.capital-input input{min-width:0;flex:1;border:1px solid var(--edge);background:var(--specular-soft);color:var(--ink);border-radius:12px;padding:11px 13px;font:700 18px/1 var(--sans);font-variant-numeric:tabular-nums}
.capital-input button{border:0;border-radius:999px;background:var(--accent);color:#16120a;padding:12px 16px;font-weight:850;white-space:nowrap;cursor:pointer}
.plan-head{padding:17px 20px;display:grid;grid-template-columns:repeat(3,1fr);gap:14px;border-bottom:1px solid var(--edge)}
.plan-stat span{display:block;color:var(--faint);font-size:10px;font-weight:750;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px}
.plan-stat strong{font-family:var(--serif);font-size:21px;font-variant-numeric:tabular-nums}
.plan-row{padding:16px 20px;border-bottom:1px solid var(--edge)}
.plan-row:last-child{border-bottom:0}
.plan-title{display:flex;justify-content:space-between;gap:12px;align-items:baseline}
.plan-title b{font-size:16px}.plan-title strong{font-variant-numeric:tabular-nums}
.plan-role{display:block;color:var(--muted);font-size:12px;margin-top:2px}
.tranches{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.tranche{border:1px solid var(--edge);background:var(--specular-soft);border-radius:999px;padding:6px 9px;font-size:11px;color:var(--muted)}
.tranche b{color:var(--ink);font-variant-numeric:tabular-nums}
.pace-note{padding:13px 20px;color:var(--muted);font-size:12px;line-height:1.5;background:var(--accent-soft)}
.why-list{margin:12px 0 0;padding-left:19px}.why-list li{font-family:var(--serif);font-size:15px;line-height:1.55;margin:7px 0}
.risk-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin:0 0 20px}.risk-card{padding:15px;border-radius:15px;background:var(--specular-soft);border:1px solid var(--edge)}
.risk-card span{display:block;color:var(--muted);font-size:11px;line-height:1.3}.risk-card strong{display:block;font-family:var(--serif);font-size:22px;margin:4px 0}.risk-card b{font-size:11px;color:var(--accent-ink)}
.opportunity{margin-top:14px;border:1px solid var(--edge);border-radius:15px;background:var(--specular-soft)}.opportunity summary{display:flex;align-items:center;gap:12px;padding:14px;cursor:pointer}.opportunity summary>div{display:grid;gap:3px;flex:1}.opportunity summary span{color:var(--muted);font-size:12px}.opportunity summary strong{font-size:13px;color:var(--accent-ink)}
.progress-overlay{position:fixed;inset:0;z-index:100;display:grid;place-items:center;padding:24px;background:rgba(6,8,13,.68);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px)}.progress-overlay[hidden]{display:none}
.progress-card{width:min(440px,100%);padding:28px;border-radius:28px;background:var(--bg);border:1px solid var(--stroke);box-shadow:var(--shadow)}
.spinner{display:block;width:42px;height:42px;border:4px solid var(--edge);border-top-color:var(--accent);border-radius:50%;animation:spin .85s linear infinite;margin-bottom:18px}@keyframes spin{to{transform:rotate(360deg)}}
.progress-card h2{font-family:var(--serif);font-size:25px;margin:0 0 7px}.progress-card p{color:var(--muted);margin:0 0 18px}.progress-track{height:9px;border-radius:999px;background:var(--edge);overflow:hidden}.progress-fill{display:block;height:100%;width:3%;border-radius:inherit;background:linear-gradient(90deg,var(--accent),#f1d477);transition:width .45s ease}.progress-percent{display:block;text-align:right;font-size:11px;color:var(--faint);margin-top:6px}

/* ============================ focus & motion ============================ */
button:focus-visible,summary:focus-visible,a:focus-visible{outline:2px solid var(--focus);outline-offset:2px;border-radius:6px}
.nav-item:focus-visible,.theme-switch button:focus-visible,.run-button:focus-visible{outline-offset:3px;border-radius:999px}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important}}

@media(max-width:420px){
  .masthead{padding-top:16px}
  .money{gap:14px}
  .metrics{grid-template-columns:repeat(2,1fr);gap:13px 14px}
  .capital-input{align-items:stretch;flex-wrap:wrap}.capital-input>span{align-self:center}.capital-input button{width:100%}
  .plan-head{grid-template-columns:1fr 1fr}.plan-head .plan-stat:last-child{grid-column:1/-1}
  .risk-grid{grid-template-columns:1fr}
}
'''


def _deployment_plan(plan: dict) -> str:
    if not plan:
        return '<section class="sheet"><p class="empty">Your capital plan appears after the next research run.</p></section>'
    capital = float(plan.get("capital_gbp") or 0)
    core_new = float(plan.get("planned_core_weight_of_new_money") or 0)
    projected = plan.get("projected_core_weight")
    projected_text = "n/a" if projected is None else f"{float(projected):.0%}"
    rows = []
    for item in plan.get("allocations", []):
        why_bullets = [_plain_research_point(str(value)) for value in item.get("why_bullets", []) if str(value).strip()]
        for fallback in (
            str(item.get("why", "It supports the configured broad-index core.")),
            "It supports the long-term diversified core instead of chasing a fashionable stock.",
            "Buying in stages reduces the risk of investing everything on one unlucky day.",
        ):
            if fallback not in why_bullets:
                why_bullets.append(fallback)
        tranches = "".join(
            f'<span class="tranche">{html.escape(str(part.get("label", "DCA")))} <b>£{float(part.get("amount_gbp") or 0):,.2f}</b></span>'
            for part in item.get("tranches", [])
        )
        rows.append(
            f'<div class="plan-row"><div class="plan-title"><b>{html.escape(str(item.get("ticker", "Core")))}</b>'
            f'<strong>£{float(item.get("amount_gbp") or 0):,.2f}</strong></div>'
            f'<span class="plan-role">{html.escape(str(item.get("role", "Broad-index core")))}</span>'
            f'<p class="lede-text"><b>Why add · {len(why_bullets[:10])} simple points</b></p><ul class="why-list">{"".join(f"<li>{html.escape(value)}</li>" for value in why_bullets[:10])}</ul>'
            f'<div class="tranches">{tranches}</div></div>'
        )
    for budget in plan.get("risk_budgets", []):
        bullets = [_plain_research_point(str(value)) for value in budget.get("why_bullets", [])[:10]]
        candidate_rows = []
        for candidate in budget.get("candidate_allocations", []):
            candidate_bullets = [_plain_research_point(str(value)) for value in candidate.get("why_bullets", [])[:10]]
            candidate_sources = "".join(
                f'<li><a href="{html.escape(str(source.get("url", "")), quote=True)}" target="_blank" rel="noopener">{html.escape(str(source.get("title", "Source")))}</a></li>'
                for source in candidate.get("sources", [])[:6] if str(source.get("url", "")).startswith("https://")
            )
            candidate_rows.append(
                f'<details class="opportunity"><summary><div><b>{html.escape(str(candidate.get("ticker", "?")))}</b>'
                f'<span>{html.escape(str(candidate.get("name", "New opportunity")))}</span></div><strong>Up to £{float(candidate.get("amount_gbp") or 0):,.2f}</strong>{_chev()}</summary>'
                f'<div class="row-body"><p class="lede-text"><b>Why it passed today’s broad scan · {len(candidate_bullets)} points</b></p>'
                f'<ul class="why-list">{"".join(f"<li>{html.escape(value)}</li>" for value in candidate_bullets)}</ul>'
                f'{f"<h4>Sources</h4><ul class=\"sources\">{candidate_sources}</ul>" if candidate_sources else ""}'
                '<p class="muted">Research suggestion only · check the full dossier before buying · no order is placed.</p></div></details>'
            )
        rows.append(
            f'<div class="plan-row"><div class="plan-title"><b>{html.escape(str(budget.get("label", "Research budget")))}</b>'
            f'<strong>£{float(budget.get("amount_gbp") or 0):,.2f}</strong></div>'
            f'<span class="plan-role">Target: {float(budget.get("target_weight") or 0):.0%} of the whole portfolio · only broad-scan ideas that pass availability and liquidity checks appear below</span>'
            f'<ul class="why-list">{"".join(f"<li>{html.escape(value)}</li>" for value in bullets)}</ul>{"".join(candidate_rows)}</div>'
        )
    unallocated = float(plan.get("unallocated_gbp") or 0)
    if unallocated:
        rows.append(f'<div class="plan-row"><div class="plan-title"><b>Unallocated cash</b><strong>£{unallocated:,.2f}</strong></div><span class="plan-role">Kept back because forcing a trade would break the 80/15/5 rules.</span></div>')
    risk_cards = "".join(
        f'<div class="risk-card"><span>{html.escape(str(item.get("label", "Risk bucket")))}</span>'
        f'<strong>{float(item.get("target_weight") or 0):.0%}</strong>'
        f'<b>Now {"n/a" if item.get("current_weight") is None else f"{float(item.get("current_weight")):.0%}"} · after plan {"n/a" if item.get("projected_weight") is None else f"{float(item.get("projected_weight")):.0%}"}</b></div>'
        for item in plan.get("risk_summary", [])
    )
    alternatives = "".join(
        f'<details class="row"><summary><div class="row-main"><span class="ticker">Why not {html.escape(str(item.get("ticker", "alternative")))}?</span><span class="muted block">{html.escape(str(item.get("decision", "Considered")))}</span></div>{_chev()}</summary>'
        f'<div class="row-body"><ul class="why-list">{"".join(f"<li>{html.escape(_plain_research_point(str(value)))}</li>" for value in item.get("why_bullets", [])[:10])}</ul></div></details>'
        for item in plan.get("alternatives_considered", [])
    )
    alternatives_html = (
        f'<h2 class="sheet-label">Alternatives considered</h2><section class="sheet">{alternatives}</section>'
        if alternatives else ""
    )
    return (
        '<section class="sheet lede"><p><b>What “foundation / lower risk” means here:</b> broad funds are safer '
        'than relying on one company, but they are still stock-market investments and can fall sharply. They are not cash or guaranteed.</p></section>'
        f'<div class="risk-grid">{risk_cards}</div><section class="sheet plan">'
        f'<div class="plan-head"><div class="plan-stat"><span>Deploy</span><strong>£{capital:,.0f}</strong></div>'
        f'<div class="plan-stat"><span>New money to foundation</span><strong>{core_new:.0%}</strong></div>'
        f'<div class="plan-stat"><span>Projected foundation</span><strong>{projected_text}</strong></div></div>'
        f'<div class="pace-note"><b>{html.escape(str(plan.get("pace", "normal")).title())} DCA pace.</b> {html.escape(str(plan.get("pace_reason", "")))}</div>'
        f'{"".join(rows)}</section>{alternatives_html}'
    )


def _page(report_path: Path, evidence_path: Path, history_dir: Path = Path("/data/history"), active_tab: str = "today", theme: str = "light", planner_path: Path | None = None, default_investment_gbp: float = 1000) -> bytes:
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else "No report yet."
    evidence: dict = {}
    if evidence_path.exists():
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    if active_tab not in {"today", "portfolio", "plan", "research", "history"}:
        active_tab = "today"
    if theme not in {"light", "dark"}:
        theme = "light"
    timezone = str(evidence.get("timezone", "Europe/London"))
    snapshots, candles, signals = evidence.get("snapshots", {}), evidence.get("candles", {}), evidence.get("signals", [])
    positions = evidence.get("portfolio_positions", [])
    display_prices = {str(item.get("ticker")): item for item in positions}
    portfolio_values = [float(item["market_value"]) for item in positions if item.get("market_value") is not None]
    portfolio_total = sum(portfolio_values) if portfolio_values else None
    portfolio_currency = str(next((item.get("currency") for item in positions if item.get("currency")), evidence.get("base_currency", "GBP")))
    # --- Today: grouped ledger sheets ---
    groups = []
    for title, action in (("Sell now", "SELL NOW"), ("Hold", "KEEP"), ("Review", "REVIEW")):
        items = [item for item in signals if item.get("action") == action]
        rows = "".join(_signal_row(item, snapshots, candles, display_prices) for item in items) or '<p class="empty">Nothing here today.</p>'
        groups.append(f'<h2 class="sheet-label {_ACTION_TONE[action]}">{title}<span class="count">{len(items)}</span></h2><section class="sheet">{rows}</section>')
    # --- Research: numbered dossiers ---
    research_items = evidence.get("research", [])
    research_rows = "".join(_research_row(index + 1, item, timezone, candles) for index, item in enumerate(research_items))
    empty_research = '<p class="empty">Research appears after the next run.</p>'
    scan = evidence.get("opportunity_scan", {})
    scan_count = int(scan.get("eligible_count") or 0)
    scan_html = (f'<h2 class="sheet-label">Broad market scan<span class="count">{scan_count}</span></h2><section class="sheet lede">'
                 f'<p>{html.escape(str(scan.get("summary") or "Run the agent to scan for new opportunities."))}</p>'
                 '<p class="muted">Candidates must be available on Trading 212 and pass minimum price and liquidity checks. Social hype is ignored.</p></section>')
    research_html = f'{scan_html}<h2 class="sheet-label">Dossiers<span class="count">{len(research_items)}</span></h2><section class="sheet">{research_rows or empty_research}</section>'
    # --- Portfolio: holdings ledger, each wearing its Spectrum colour ---
    valued_index = 0
    holding_rows = []
    for item in positions:
        has_value = item.get("market_value") is not None
        colour = _SPECTRUM[valued_index % len(_SPECTRUM)] if has_value else "var(--faint)"
        share = (float(item["market_value"]) / portfolio_total) if has_value and portfolio_total else None
        if has_value:
            valued_index += 1
        holding_rows.append(_portfolio_row(item, colour, share))
    plan = evidence.get("deployment_plan", {})
    investment_amount = float(plan.get("capital_gbp") or default_investment_gbp)
    if planner_path and planner_path.exists():
        try:
            investment_amount = float(json.loads(planner_path.read_text(encoding="utf-8"))["next_investment_gbp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
            pass
    capital_form = f'''<h2 class="sheet-label">Next investment</h2><section class="sheet"><form class="capital-form" method="post" action="./plan"><label for="amount">How much would you like to invest next?</label><div class="capital-input"><span>£</span><input id="amount" name="amount" type="number" min="0" max="10000000" step="100" value="{investment_amount:.0f}" inputmode="decimal" required><button type="submit">Build plan</button></div><small>This saves the amount and immediately runs fresh market and news research. No trade is placed.</small></form></section>'''
    plan_html = f'{capital_form}<h2 class="sheet-label">Your 80 / 15 / 5 plan</h2>{_deployment_plan(plan)}'
    if holding_rows:
        portfolio_html = f'<h2 class="sheet-label">Holdings<span class="count">{len(holding_rows)}</span></h2><section class="sheet">{"".join(holding_rows)}</section>'
    else:
        portfolio_html = f'''<h2 class="sheet-label">Holdings<span class="count">0</span></h2><section class="sheet"><div class="setup-copy"><h2>{_icon("shield")}Connect Trading 212</h2><p>Add your API key and one-time API secret in the app Configuration page, enable Trading 212, then restart or press Run now.</p><ol><li>Create a Trading 212 API key with portfolio/account read access only.</li><li>Do not enable order placement.</li><li>Paste both values into the masked Home Assistant fields.</li></ol><p>Your credentials stay in Home Assistant and are never shown in this dashboard.</p></div></section>'''
    warnings = "".join(f"<li>{html.escape(str(error))}</li>" for error in evidence.get("errors", [])[:10])
    # --- History: timeline of editions ---
    history_runs = []
    if history_dir.exists():
        for path in sorted(history_dir.glob("*.json"), reverse=True)[:120]:
            try:
                history_runs.append(json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass
    if history_runs:
        nodes = "".join(f'<section class="sheet"><i class="t-pin" aria-hidden="true"></i>{_history_node(run, str(run.get("timezone", timezone)))}</section>' for run in history_runs)
        history_html = f'<h2 class="sheet-label">Editions<span class="count">{len(history_runs)}</span></h2><div class="timeline">{nodes}</div>'
    else:
        history_html = '<h2 class="sheet-label">Editions<span class="count">0</span></h2><section class="sheet"><p class="empty">Daily history begins after a successful run.</p></section>'
    summary = html.escape(str(evidence.get("market_summary", "Run the agent to create a source-backed market briefing.")))
    source = html.escape(str(evidence.get("portfolio_source", "Starter configuration")))
    source_short = "Hargreaves Lansdown" if "Hargreaves Lansdown" in source else ("Trading 212" if "Trading 212" in source else "Manual setup")
    position_count = len(positions)
    position_word = "position" if position_count == 1 else "positions"
    edition = _edition_date(evidence.get("generated_at"), timezone)
    edition_html = html.escape(edition) if edition else "Awaiting the first edition"
    byline = (f'{_icon("shield")}Prepared {html.escape(_when(evidence.get("generated_at"), timezone))} · '
              f'Data to {html.escape(_when(evidence.get("latest_data_at"), timezone))} · {source}')
    brand_img = '<img src="./logo.png" alt="Market Agent logo">'
    colophon = (f'<div class="colophon"><b>Market Agent</b>Deterministic decisions · no auto-trading<br>'
                f'Prepared {html.escape(_when(evidence.get("generated_at"), timezone))}<br>'
                f'Data to {html.escape(_when(evidence.get("latest_data_at"), timezone))}<br>{source} · read-only</div>')
    progress_overlay = '''<div id="run-progress" class="progress-overlay" hidden role="status" aria-live="polite">
<div class="progress-card"><span class="spinner" aria-hidden="true"></span><span class="eyebrow">Fresh daily research</span>
<h2 id="progress-stage">Starting…</h2><p id="progress-detail">Getting everything ready.</p>
<div class="progress-track"><i id="progress-fill" class="progress-fill"></i></div><b id="progress-percent" class="progress-percent">0%</b></div></div>'''
    progress_script = '''<script>
(()=>{const overlay=document.getElementById('run-progress'),stage=document.getElementById('progress-stage'),detail=document.getElementById('progress-detail'),fill=document.getElementById('progress-fill'),pct=document.getElementById('progress-percent');
const show=(s='Starting research',d='Getting everything ready.',p=2)=>{overlay.hidden=false;stage.textContent=s;detail.textContent=d;fill.style.width=Math.max(0,Math.min(100,p))+'%';pct.textContent=Math.round(p)+'%'};
document.querySelectorAll('form.run,form.capital-form').forEach(form=>form.addEventListener('submit',()=>show()));
const params=new URLSearchParams(location.search);if(params.get('running')!=='1')return;show();let seen=false;
const poll=async()=>{try{const response=await fetch('./status',{cache:'no-store'}),data=await response.json();show(data.stage,data.detail,Number(data.percent||0));if(data.state==='queued'||data.state==='running')seen=true;if(seen&&(data.state==='complete'||data.state==='error')){params.delete('running');location.replace('./?'+params.toString());return}}catch(e){detail.textContent='Still waiting for Home Assistant…'}setTimeout(poll,900)};poll();})();
</script>'''
    document = f'''<!doctype html><html class="theme-{theme}" lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="color-scheme" content="light dark"><meta name="theme-color" content="{'#07090f' if theme == 'dark' else '#f5f1e8'}"><title>Market Agent</title><style>{_STYLE}</style></head><body>
<aside class="rail">
  <div class="brand">{brand_img}<div><b>Market Agent</b><span>Private daily briefing</span></div></div>
  {_nav(active_tab, theme)}
  <div class="rail-spacer"></div>
  {_theme_switch(active_tab, theme)}
  {_run_form()}
  {colophon}
</aside>
<div class="canvas">
<header class="toolbar"><div class="brand">{brand_img}<b>Market Agent</b></div><div class="toolbar-controls">{_theme_switch(active_tab, theme)}{_run_form(compact=True)}</div></header>
<main>
<section class="masthead">
  <span class="eyebrow">Private daily briefing · no auto-trading</span>
  <h1 class="edition">{edition_html}</h1>
  <span class="byline">{byline}</span>
  <div class="money">
    <div class="money-value"><span class="money-label">Total portfolio value</span>{_hero_value(portfolio_total, portfolio_currency)}<span class="money-sub">{position_count} {position_word} · {source_short} · read-only</span></div>
    {_allocation_bar(positions, portfolio_total)}
  </div>
</section>
<div class="view {'active' if active_tab == 'today' else ''}">{_tape(positions)}<h2 class="sheet-label">Market brief</h2><section class="sheet lede"><p>{summary}</p></section>{''.join(groups)}{f'<section class="warn-sheet">{_icon("alert")}<div><strong>Data notes</strong><ul>{warnings}</ul></div></section>' if warnings else ''}<p class="smallprint">Advisory screen only · verify prices, research and suitability before acting.</p></div>
<div class="view {'active' if active_tab == 'portfolio' else ''}">{portfolio_html}<p class="smallprint">Portfolio access is read-only. Hargreaves Lansdown holdings are entered manually because HL has no investment-portfolio API. This app contains no order endpoint.</p></div>
<div class="view {'active' if active_tab == 'plan' else ''}">{plan_html}<p class="smallprint">Research informs the reasons and DCA pace; allocation guardrails remain deterministic.</p></div>
<div class="view {'active' if active_tab == 'research' else ''}">{research_html}<p class="smallprint">OpenAI summarises web research; deterministic rules remain authoritative.</p></div>
<div class="view {'active' if active_tab == 'history' else ''}">{history_html}<p class="smallprint">Saved locally on Home Assistant · newest first · up to 120 runs.</p></div>
</main>
</div>
{_nav(active_tab, theme, True)}{progress_overlay}{progress_script}<noscript><pre>{html.escape(report)}</pre></noscript></body></html>'''
    return document.encode()


def start_panel(report_path: Path, evidence_path: Path, trigger: Event, port: int = 8099, logo_path: Path = Path("/opt/market-agent/logo.png"), history_dir: Path = Path("/data/history"), host: str = "0.0.0.0", planner_path: Path = Path("/data/planner.json"), status_path: Path = Path("/data/run-status.json"), default_investment_gbp: float = 1000) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            theme_cookie = SimpleCookie(self.headers.get("Cookie", "")).get("market_agent_theme")
            saved_theme = theme_cookie.value if theme_cookie and theme_cookie.value in {"light", "dark"} else "light"
            cookie_header = None
            if self.path.rstrip("/").endswith("/logo.png") and logo_path.exists():
                body, content_type = logo_path.read_bytes(), "image/png"
            elif self.path.rstrip("/").endswith("/health"):
                body, content_type = b'{"status":"ok"}', "application/json"
            elif self.path.rstrip("/").endswith("/status"):
                try:
                    body = status_path.read_bytes()
                except OSError:
                    body = b'{"state":"idle","stage":"Ready","detail":"Press Run now for fresh research.","percent":0}'
                content_type = "application/json"
            else:
                query = parse_qs(urlparse(self.path).query)
                requested_theme = (query.get("theme") or [saved_theme])[0]
                theme = requested_theme if requested_theme in {"light", "dark"} else saved_theme
                if requested_theme in {"light", "dark"}:
                    cookie_header = f"market_agent_theme={theme}; Path=/; Max-Age=31536000; SameSite=Lax"
                body, content_type = _page(report_path, evidence_path, history_dir, (query.get("tab") or ["today"])[0], theme, planner_path, default_investment_gbp), "text/html; charset=utf-8"
            self.send_response(200); self.send_header("Content-Type", content_type); self.send_header("Cache-Control", "no-store")
            if cookie_header:
                self.send_header("Set-Cookie", cookie_header)
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path.rstrip("/").endswith("/run"):
                status_path.write_text(json.dumps({"state": "queued", "stage": "Starting research", "detail": "Getting your portfolio and market checks ready.", "percent": 2}), encoding="utf-8")
                trigger.set(); self.send_response(303); self.send_header("Location", "./?tab=today&running=1"); self.end_headers(); return
            if self.path.rstrip("/").endswith("/plan"):
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 4096)
                    values = parse_qs(self.rfile.read(length).decode("utf-8"))
                    amount = float((values.get("amount") or [""])[0])
                    if not 0 <= amount <= 10_000_000:
                        raise ValueError("out of range")
                    planner_path.write_text(json.dumps({"next_investment_gbp": amount}), encoding="utf-8")
                except (ValueError, TypeError, OSError):
                    self.send_error(400, "Enter a valid investment amount"); return
                status_path.write_text(json.dumps({"state": "queued", "stage": "Starting your plan", "detail": "Saving the amount, then checking holdings, prices, charts and news.", "percent": 2}), encoding="utf-8")
                trigger.set(); self.send_response(303); self.send_header("Location", "./?tab=plan&running=1"); self.end_headers(); return
            self.send_error(404)

        def log_message(self, format: str, *args) -> None:
            print(f"[market-agent-panel] {format % args}", flush=True)

    server = ThreadingHTTPServer((host, port), Handler)
    Thread(target=server.serve_forever, name="market-agent-panel", daemon=True).start()
    return server
