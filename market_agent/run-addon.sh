#!/bin/sh
set -eu
export PYTHONPATH="/opt/market-agent/src"
exec python3 -m market_agent.ha_runner

