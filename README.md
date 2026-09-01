# Market Agent for Home Assistant

Market Agent is a private, read-only investment research dashboard that runs on Home Assistant Green. It checks daily market data, optionally researches current news with OpenAI, reads a Trading 212 portfolio with read-only credentials or manually supplied Hargreaves Lansdown holdings, creates an 80/15/5 risk-aware deployment plan, and sends a Home Assistant notification. It never places trades.

## Install

1. In Home Assistant, open **Settings → Apps → App store**.
2. Open the repository menu, choose **Repositories**, and add this GitHub repository URL.
3. Install **Market Agent**, then open its **Configuration** tab.
4. Choose a portfolio provider. Enter your own OpenAI and read-only Trading 212 credentials, or paste manual Hargreaves Lansdown holdings. Never enter HL login details.
5. Start the app and enable **Show in sidebar**.

All credential fields are masked by Home Assistant. No keys are included in this repository, rendered in the dashboard, written to research history, or printed in normal logs.

See [the app documentation](market_agent/DOCS.md) for configuration and limitations.

## Important

This is an advisory research tool, not financial advice. Market data and news can be delayed, incomplete, or wrong. Verify information independently before acting. The app does not contain any broker order endpoint.
