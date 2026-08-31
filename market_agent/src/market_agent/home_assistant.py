from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class HomeAssistantDeliveryError(RuntimeError):
    pass


def _api_request(path: str, *, method: str = "GET", payload: dict | None = None):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise HomeAssistantDeliveryError("SUPERVISOR_TOKEN is unavailable")
    request = urllib.request.Request(
        f"http://supervisor/core/api{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else None
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise HomeAssistantDeliveryError(f"Home Assistant API request failed: {exc}") from exc


def _mobile_services() -> list[str]:
    configured = os.environ.get("HA_NOTIFY_SERVICE", "").strip()
    if configured:
        return [configured.removeprefix("notify.")]
    services = _api_request("/services") or []
    return [
        service
        for domain in services
        if domain.get("domain") == "notify"
        for service in domain.get("services", {})
        if str(service).startswith("mobile_app_")
    ]


def _push_summary(note: str) -> str:
    lines = [line.strip() for line in note.splitlines() if line.strip()]
    selected: list[str] = []
    for line in lines:
        if line.startswith(("SELL NOW", "KEEP / REVIEW", "BUY CANDIDATES", "•", "- ")):
            selected.append(line)
    summary = "\n".join(selected) if selected else "Your daily portfolio report is ready."
    return summary[:3500]


def send(note: str) -> None:
    # Keep the complete report in Home Assistant even if a phone is offline.
    _api_request(
        "/services/persistent_notification/create",
        method="POST",
        payload={
            "title": "Market Agent",
            "message": note,
            "notification_id": "daily_market_agent",
        },
    )

    services = _mobile_services()
    if not services:
        print("[market-agent] No mobile_app notification service found; saved report in Home Assistant", flush=True)
        return
    payload = {
        "title": "Market Agent",
        "message": _push_summary(note),
        "data": {"url": "/hassio/ingress/local_market_agent_dashboard"},
    }
    for service in services:
        _api_request(f"/services/notify/{service}", method="POST", payload=payload)
        print(f"[market-agent] Sent Home Assistant notification through notify.{service}", flush=True)
