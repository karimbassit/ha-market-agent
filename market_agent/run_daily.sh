#!/bin/sh
set -eu
cd "$(dirname "$0")"
mkdir -p data
PYTHONPATH="$PWD/src" python3 -m market_agent.cli --json-output "data/latest-run.json" >> "data/market-agent.log" 2>&1
