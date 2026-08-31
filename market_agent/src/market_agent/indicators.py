from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import fmean

from .market_data import Bar


def ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    output = [values[0]]
    for value in values[1:]:
        output.append(alpha * value + (1 - alpha) * output[-1])
    return output


def rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    changes = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes[-period:]]
    losses = [max(-change, 0.0) for change in changes[-period:]]
    avg_gain, avg_loss = fmean(gains), fmean(losses)
    if avg_loss == 0:
        return 100.0
    return 100 - 100 / (1 + avg_gain / avg_loss)


@dataclass(frozen=True)
class Snapshot:
    ticker: str
    source_ticker: str
    date: str
    timestamp: str
    currency: str
    price: float
    change_1d: float
    change_20d: float | None
    ma20: float | None
    ma50: float | None
    ma200: float | None
    rsi14: float | None
    macd: float | None
    macd_signal: float | None
    avg_volume_20d: float
    avg_dollar_volume_20d: float
    below_ma200_days: int
    distance_from_52w_high: float

    def as_dict(self) -> dict:
        return asdict(self)


def snapshot(ticker: str, bars: list[Bar], currency: str = "USD") -> Snapshot:
    closes = [bar.close for bar in bars]
    volumes = [bar.volume for bar in bars]
    latest = bars[-1]

    def moving_average(period: int) -> float | None:
        return fmean(closes[-period:]) if len(closes) >= period else None

    fast, slow = ema(closes, 12), ema(closes, 26)
    macd_series = [a - b for a, b in zip(fast, slow)]
    signal = ema(macd_series, 9)
    below_days = 0
    if len(closes) >= 200:
        for index in range(len(closes) - 1, 198, -1):
            average = fmean(closes[index - 199 : index + 1])
            if closes[index] >= average:
                break
            below_days += 1
    high_52w = max(bar.high for bar in bars[-252:])
    return Snapshot(
        ticker=ticker,
        source_ticker=ticker,
        date=latest.timestamp.date().isoformat(),
        timestamp=latest.timestamp.isoformat(),
        currency=currency,
        price=latest.close,
        change_1d=latest.close / bars[-2].close - 1,
        change_20d=(latest.close / bars[-21].close - 1) if len(bars) >= 21 else None,
        ma20=moving_average(20),
        ma50=moving_average(50),
        ma200=moving_average(200),
        rsi14=rsi(closes),
        macd=macd_series[-1],
        macd_signal=signal[-1],
        avg_volume_20d=fmean(volumes[-20:]),
        avg_dollar_volume_20d=fmean(volumes[-20:]) * latest.close,
        below_ma200_days=below_days,
        distance_from_52w_high=latest.close / high_52w - 1,
    )
