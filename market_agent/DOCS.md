# Market Agent configuration

## First start

The app can run without paid API credentials. In that mode it uses deterministic rules and best-effort public Yahoo daily market data. Add your own credentials in the app's **Configuration** page for live portfolio access and source-backed web research.

### OpenAI

Create an OpenAI API key in your own OpenAI API account and paste it into **OpenAI API key**. ChatGPT subscriptions do not include API usage. The model field is configurable; the default is the lower-cost `gpt-5.6-luna`. Web search and model usage are billed by OpenAI.

### Trading 212

Create a Trading 212 API key and secret with only account and portfolio read permissions. Do not grant order permissions. Paste both values into the masked fields, enable Trading 212, and choose the live or demo environment. The app reads open equity positions; it contains no order-placement code.

### Hargreaves Lansdown

HL does not provide a public API for ISA, SIPP, Fund & Share or other investment holdings. Its Open Banking API is limited to the cash hub in Active Savings. Choose **Hargreaves Lansdown** under **Portfolio provider**, then paste a JSON list into **Hargreaves Lansdown holdings**. Never enter your HL username, password, memorable information or security code.

Minimum example:

```json
[{"ticker":"VUAG.L","name":"Vanguard S&P 500","quantity":10,"average_price_gbp":80.25}]
```

Use Yahoo-style tickers such as `VUAG.L`, `VWRP.L`, `AAPL`, or `ASML.AS`. For London listings quoted in GBP or pence, the app refreshes the GBP market value from daily market data. For a foreign-currency listing, also supply `market_value_gbp`; update that amount after trades or when you need an exact broker valuation. The importer is manual and read-only.

### Notifications

Home Assistant notification delivery is enabled by default. Leave **Home Assistant notify service** empty to notify every discovered `mobile_app_*` service, or enter one service name such as `mobile_app_my_iphone`. A persistent notification is always created in Home Assistant.

WhatsApp delivery through Twilio or Meta is optional. Those credentials must belong to the person installing this app.

## Schedule and planning

The default schedule is 07:30 in `Europe/London`, Monday to Friday. The default new-investment amount is only a planning input and never causes an order. The policy targets:

- 80% foundation / lower-to-moderate-risk diversified funds
- 15% medium-to-high-risk investments
- 5% very-high-risk investments

Research can slow the staged-buying pace but cannot place trades. The opportunity scan ignores social-media popularity and raw price momentum.

## Credential handling

- Credential defaults in this repository are empty.
- Home Assistant renders credential settings as password fields.
- Credentials are read from `/data/options.json` at runtime and passed only to the relevant API client.
- Credentials are never returned by the dashboard or included in run-history files.
- Do not post app diagnostic files publicly without reviewing them first.

Home Assistant stores app configuration on the user's own Home Assistant system. Anyone with administrator or host-level access to that system should be treated as able to access its app configuration.

## Data limitations

Daily candles currently come from Yahoo's unofficial chart endpoint. The app retries requests and refuses to issue a signal when data is missing or stale, but the source has no uptime guarantee. OpenAI research is optional and cannot change deterministic sell actions. Always verify current price, fund documentation, news, tax treatment, and suitability before investing.
