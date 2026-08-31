from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"").strip("'"))


def load_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    weights = [item.get("target_weight") for item in data["holdings"]]
    if weights and all(value is not None for value in weights):
        total = sum(float(value) for value in weights)
        if abs(total - 1.0) > 0.0001:
            raise ValueError(f"Holding target weights must sum to 1.0; got {total:.4f}")
    tickers = [item["ticker"] for item in data["holdings"]]
    if len(tickers) != len(set(tickers)):
        raise ValueError("Duplicate holding ticker in portfolio configuration")
    strategy = str(data.get("buy_strategy", "allocation_only"))
    if strategy not in {"allocation_only", "technical_momentum"}:
        raise ValueError("buy_strategy must be allocation_only or technical_momentum")
    plan = data.get("capital_plan", {})
    if plan:
        target = float(plan.get("core_target_weight", .75))
        floor = float(plan.get("minimum_new_core_weight", .65))
        core_tickers = {str(value) for value in plan.get("core_tickers", [])}
        if not .51 <= target <= .95 or not .51 <= floor <= 1:
            raise ValueError("Capital-plan core weights must keep a majority in broad-index funds")
        if str(plan.get("primary_core_ticker")) not in core_tickers:
            raise ValueError("The primary core ticker must be listed in capital_plan.core_tickers")
        risk_targets = plan.get("risk_targets", {})
        if risk_targets and abs(sum(float(value) for value in risk_targets.values()) - 1.0) > 0.0001:
            raise ValueError("Capital-plan risk targets must sum to 1.0")
    return data
