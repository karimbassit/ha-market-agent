# Market Agent

A private daily market-research and portfolio-planning app for Home Assistant Green.

## What it does

- Reads Trading 212 equity positions through its read-only API, or accepts manually supplied Hargreaves Lansdown holdings.
- Checks daily prices and candles and rejects missing or stale data.
- Optionally uses your OpenAI API key for current, source-backed news research and broad opportunity discovery.
- Explains why each holding is marked keep, review, or sell in simple language.
- Builds an illustrative GBP deployment plan around an 80% foundation, 15% medium-to-high-risk, and 5% very-high-risk policy.
- Keeps run history inside your Home Assistant app data and sends Home Assistant notifications.
- Never places a trade.

All API credential defaults are empty and the fields are masked in Home Assistant. Every installer supplies and controls their own keys.

Read the **Documentation** tab before connecting a broker account. Use Trading 212 credentials with account/portfolio read access only and never grant order permissions.

This is an advisory research tool, not financial advice. Verify all prices, research, tax treatment, and suitability independently.
