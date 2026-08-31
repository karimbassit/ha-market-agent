from __future__ import annotations

from typing import Any


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _tranches(amount: float, pace: str) -> list[dict[str, Any]]:
    schedule = (
        (("Now", 0.25), ("In 30 days", 0.25), ("In 60 days", 0.25), ("In 90 days", 0.25))
        if pace == "cautious"
        else (("Now", 0.40), ("In 30 days", 0.30), ("In 60 days", 0.30))
    )
    return [
        {"label": label, "weight": weight, "amount_gbp": round(amount * weight, 2)}
        for label, weight in schedule
    ]


def build_deployment_plan(
    capital_gbp: float,
    positions: list[dict],
    policy: dict,
    deployment_context: dict | None = None,
    research_by_ticker: dict[str, list[str]] | None = None,
    opportunities: list[dict] | None = None,
) -> dict:
    """Create a bounded, deterministic core-first capital plan.

    News may select only the DCA pace. It cannot choose tickers, reduce the
    configured core floor or create a speculative allocation.
    """
    capital = max(0.0, float(capital_gbp))
    core_tickers = {str(value) for value in policy.get("core_tickers", [])}
    targets = policy.get("risk_targets", {"foundation": 0.80, "medium_high": 0.15, "very_high": 0.05})
    foundation_target = _clamp(float(targets.get("foundation", 0.80)), 0.51, 0.95)
    medium_target = _clamp(float(targets.get("medium_high", 0.15)), 0.0, 0.40)
    very_high_target = _clamp(float(targets.get("very_high", 0.05)), 0.0, 0.20)
    target_total = foundation_target + medium_target + very_high_target
    if abs(target_total - 1.0) > 0.0001:
        raise ValueError("Risk targets must total 100%")
    target = foundation_target
    primary = str(policy.get("primary_core_ticker", "VUAG.L"))
    diversifier = str(policy.get("diversifier_ticker", "VWRP.L"))
    held_tickers = {str(item.get("ticker")) for item in positions}
    if "VALL.L" in held_tickers and "VWRP.L" not in held_tickers and "VALL.L" in core_tickers:
        diversifier = "VALL.L"
    primary_split = _clamp(float(policy.get("primary_split", 0.80)), 0.50, 1.0)

    risk_tickers = policy.get("risk_tickers", {})
    foundation_tickers = {str(value) for value in risk_tickers.get("foundation", core_tickers)} | core_tickers
    medium_tickers = {str(value) for value in risk_tickers.get("medium_high", [])}
    very_high_tickers = {str(value) for value in risk_tickers.get("very_high", [])}

    def bucket(ticker: str) -> str:
        if ticker in foundation_tickers:
            return "foundation"
        if ticker in very_high_tickers:
            return "very_high"
        return "medium_high"

    current_total = sum(float(item.get("market_value") or 0) for item in positions)
    current_by_bucket = {"foundation": 0.0, "medium_high": 0.0, "very_high": 0.0}
    for position in positions:
        current_by_bucket[bucket(str(position.get("ticker")))] += float(position.get("market_value") or 0)
    current_core = current_by_bucket["foundation"]
    combined_total = current_total + capital
    target_weights = {"foundation": foundation_target, "medium_high": medium_target, "very_high": very_high_target}
    gaps = {name: max(0.0, weight * combined_total - current_by_bucket[name]) for name, weight in target_weights.items()}
    remaining = capital
    planned_by_bucket: dict[str, float] = {}
    for name in ("foundation", "medium_high", "very_high"):
        planned_by_bucket[name] = min(remaining, gaps[name])
        remaining -= planned_by_bucket[name]
    core_budget = planned_by_bucket["foundation"]

    context = deployment_context or {}
    requested_pace = str(context.get("pace", "normal")).lower()
    pace = requested_pace if requested_pace in {"normal", "cautious"} else "normal"
    pace_reason = str(context.get("summary") or "No verified news shock changed the standard three-tranche schedule.")

    allocations: list[dict[str, Any]] = []
    researched = research_by_ticker or {}

    def reasons(ticker: str, defaults: list[str]) -> list[str]:
        values = [str(value).strip() for value in researched.get(ticker, []) if str(value).strip()]
        for value in defaults:
            if value not in values:
                values.append(value)
        return values[:10]
    if core_budget > 0:
        primary_amount = core_budget if not diversifier or diversifier == primary else core_budget * primary_split
        allocations.append(
            {
                "ticker": primary,
                "role": "Primary S&P 500 core",
                "why": "This is the main building block: one purchase spreads your money across roughly 500 large US companies instead of betting on one stock.",
                    "why_bullets": reasons(primary, [
                        "It spreads your money across roughly 500 large US companies instead of one stock.",
                        "It helps move the portfolio toward the configured 80% foundation target.",
                        "An index fund is less dependent on one company's results than a single share.",
                        "The main risk is that the whole US stock market can still fall sharply.",
                        "The plan buys in stages, so you do not commit all the money on one day.",
                ]),
                "amount_gbp": round(primary_amount, 2),
                "tranches": _tranches(primary_amount, pace),
            }
        )
        if diversifier and diversifier != primary:
            diversified_amount = core_budget - primary_amount
            allocations.append(
                {
                    "ticker": diversifier,
                    "role": "Broad global core diversifier",
                    "why": "This adds companies outside the US, so the plan is not dependent on one country doing well.",
                    "why_bullets": reasons(diversifier, [
                        "It adds companies from many countries, not only the US.",
                        "It reduces the damage if one country or market has a bad period.",
                        "It owns large and mid-sized companies across developed and emerging markets.",
                        "It still carries stock-market risk and is not the same as cash or a guaranteed product.",
                        "It complements the S&P 500 core instead of chasing a fashionable stock.",
                    ]),
                    "amount_gbp": round(diversified_amount, 2),
                    "tranches": _tranches(diversified_amount, pace),
                }
            )

    opportunity_items = opportunities or []

    def candidate_allocations(bucket_name: str, budget: float, limit: int) -> list[dict]:
        selected = [item for item in opportunity_items if str(item.get("risk_bucket")) == bucket_name][:limit]
        if not selected or budget <= 0:
            return []
        per_candidate = budget / len(selected)
        return [
            {
                "ticker": str(item.get("ticker")),
                "name": str(item.get("trading212_name") or item.get("name") or item.get("ticker")),
                "amount_gbp": round(per_candidate, 2),
                "why_bullets": [str(value) for value in item.get("bullets", [])[:10]],
                "sources": item.get("sources", [])[:6],
                "tranches": _tranches(per_candidate, "cautious"),
                "advisory_only": True,
            }
            for item in selected
        ]

    risk_budgets = [
        {
            "bucket": "medium_high",
            "label": "Medium-to-high risk research budget",
            "target_weight": medium_target,
            "amount_gbp": round(planned_by_bucket["medium_high"], 2),
            "candidate_allocations": candidate_allocations("medium_high", planned_by_bucket["medium_high"], 2),
            "why_bullets": [
                "This bucket is capped at 15% of the whole portfolio.",
                "It may hold established individual companies or focused sector funds after proper research.",
                "The money stays as cash until a researched idea passes the hold/add rules.",
            ],
        },
        {
            "bucket": "very_high",
            "label": "Very-high-risk research budget",
            "target_weight": very_high_target,
            "amount_gbp": round(planned_by_bucket["very_high"], 2),
            "candidate_allocations": candidate_allocations("very_high", planned_by_bucket["very_high"], 1),
            "why_bullets": [
                "This bucket is strictly capped at 5% of the whole portfolio.",
                "It is for positions where losing most or all of the money is realistically possible.",
                "The money stays as cash until research identifies a suitable idea; the agent will not force a trade.",
            ],
        },
    ]
    reserve = max(0.0, capital - core_budget)
    after_core = current_core + core_budget
    risk_summary = [
        {
            "bucket": name,
            "label": {"foundation": "Foundation / lower risk", "medium_high": "Medium-to-high risk", "very_high": "Very high risk"}[name],
            "target_weight": target_weights[name],
            "current_weight": (current_by_bucket[name] / current_total) if current_total else None,
            "planned_new_gbp": round(planned_by_bucket[name], 2),
            "projected_weight": ((current_by_bucket[name] + planned_by_bucket[name]) / combined_total) if combined_total else None,
        }
        for name in ("foundation", "medium_high", "very_high")
    ]
    alternatives = []
    if "VALL.L" in core_tickers and diversifier != "VALL.L":
        alternatives.append({
            "ticker": "VALL.L",
            "decision": "Considered, not added alongside VWRP",
            "why_bullets": reasons("VALL.L", [
                "VALL is a broad global all-cap fund, so it can be a sensible foundation fund.",
                "VWRP already covers a very similar global role, so owning both creates a lot of overlap.",
                "VALL is newer and has less price history, so the agent currently uses VWRP as its temporary chart proxy.",
                "Choose VALL instead of VWRP only after comparing fees, spread, fund size and Trading 212 availability.",
            ]),
        })
    return {
        "capital_gbp": round(capital, 2),
        "current_portfolio_gbp": round(current_total, 2),
        "current_core_weight": (current_core / current_total) if current_total else None,
        "core_target_weight": target,
        "planned_core_gbp": round(core_budget, 2),
        "planned_core_weight_of_new_money": (core_budget / capital) if capital else None,
        "projected_core_weight": (after_core / combined_total) if combined_total else None,
        "reserve_gbp": round(reserve, 2),
        "unallocated_gbp": round(remaining, 2),
        "pace": pace,
        "pace_reason": pace_reason,
        "allocations": allocations,
        "risk_budgets": risk_budgets,
        "risk_summary": risk_summary,
        "alternatives_considered": alternatives,
        "guardrails": [
            "Core allocation is rule-based and cannot be reduced by social or price momentum.",
            "News can change only the DCA pace, never the selected core funds.",
            "No orders are placed automatically.",
        ],
    }


def deployment_note(plan: dict) -> str:
    lines = [
        "CAPITAL PLAN",
        f"• Capital to deploy: £{float(plan.get('capital_gbp', 0)):,.2f} GBP.",
        "• Risk targets: 80% foundation, 15% medium-to-high risk and 5% very high risk.",
        f"• Planned new money to broad-index foundation: {float(plan.get('planned_core_weight_of_new_money') or 0):.0%}.",
        f"• DCA pace: {str(plan.get('pace', 'normal')).title()} — {plan.get('pace_reason', '')}",
    ]
    for item in plan.get("allocations", []):
        tranches = "; ".join(
            f"{part['label']} £{float(part['amount_gbp']):,.2f}"
            for part in item.get("tranches", [])
        )
        why = " ".join(f"Reason {index + 1}: {value}" for index, value in enumerate(item.get("why_bullets", [])[:10]))
        lines.append(f"• ADD {item.get('ticker')} — £{float(item.get('amount_gbp', 0)):,.2f} GBP ({item.get('role')}). {why} DCA: {tranches}.")
    suggested_risk = 0.0
    for budget in plan.get("risk_budgets", []):
        for item in budget.get("candidate_allocations", []):
            suggested_risk += float(item.get("amount_gbp", 0))
            why = " ".join(f"Reason {index + 1}: {value}" for index, value in enumerate(item.get("why_bullets", [])[:10]))
            lines.append(f"• RESEARCHED ADD CANDIDATE {item.get('ticker')} — up to £{float(item.get('amount_gbp', 0)):,.2f} GBP, staged cautiously. {why}")
    reserve = float(plan.get("reserve_gbp", 0))
    unsuggested_reserve = max(0.0, reserve - suggested_risk)
    if unsuggested_reserve:
        lines.append(f"• Keep £{unsuggested_reserve:,.2f} GBP unallocated because the broad scan did not clear enough ideas; do not force a trade.")
    return "\n".join(lines)
