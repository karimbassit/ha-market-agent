from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .web_panel import start_panel


OPTIONS_PATH = Path("/data/options.json")
DATA_CONFIG = Path("/data/portfolio.json")
BUNDLED_CONFIG = Path("/opt/market-agent/config/portfolio.json")
EVIDENCE_PATH = Path("/data/latest-run.json")
REPORT_PATH = Path("/data/latest-report.txt")
HISTORY_DIR = Path("/data/history")
PLANNER_PATH = Path("/data/planner.json")
STATUS_PATH = Path("/data/run-status.json")


def write_status(state: str, stage: str, detail: str, percent: int) -> None:
    STATUS_PATH.write_text(json.dumps({"state": state, "stage": stage, "detail": detail, "percent": percent}), encoding="utf-8")


def sync_policy_config() -> None:
    """Upgrade rule policy without overwriting the user's holdings or broker mappings."""
    if not DATA_CONFIG.exists():
        shutil.copyfile(BUNDLED_CONFIG, DATA_CONFIG)
        return
    try:
        current = json.loads(DATA_CONFIG.read_text(encoding="utf-8"))
        bundled = json.loads(BUNDLED_CONFIG.read_text(encoding="utf-8"))
        current["buy_strategy"] = bundled.get("buy_strategy", "allocation_only")
        current["capital_plan"] = bundled["capital_plan"]
        current["watchlist"] = bundled.get("watchlist", [])
        DATA_CONFIG.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except (KeyError, OSError, json.JSONDecodeError):
        print("[market-agent] Could not upgrade the persistent policy; keeping the existing file", flush=True)


def load_options() -> dict:
    return json.loads(OPTIONS_PATH.read_text(encoding="utf-8"))


def runtime_environment(options: dict) -> dict[str, str]:
    env = os.environ.copy()
    mapping = {
        "ha_notify_service": "HA_NOTIFY_SERVICE",
        "whatsapp_provider": "WHATSAPP_PROVIDER",
        "whatsapp_to": "WHATSAPP_TO",
        "twilio_account_sid": "TWILIO_ACCOUNT_SID",
        "twilio_auth_token": "TWILIO_AUTH_TOKEN",
        "twilio_whatsapp_from": "TWILIO_WHATSAPP_FROM",
        "meta_access_token": "META_ACCESS_TOKEN",
        "meta_phone_number_id": "META_PHONE_NUMBER_ID",
        "meta_api_version": "META_API_VERSION",
        "meta_template_name": "META_TEMPLATE_NAME",
        "meta_template_language": "META_TEMPLATE_LANGUAGE",
        "openai_api_key": "OPENAI_API_KEY",
        "openai_model": "OPENAI_MODEL",
        "trading212_api_key": "TRADING212_API_KEY",
        "trading212_api_secret": "TRADING212_API_SECRET",
        "trading212_environment": "TRADING212_ENVIRONMENT",
        "trading212_enabled": "TRADING212_ENABLED",
        "next_investment_gbp": "NEXT_INVESTMENT_GBP",
    }
    env["DELIVERY_PROVIDER"] = str(options.get("delivery_provider", "home_assistant"))
    for option, variable in mapping.items():
        value = options.get(option)
        if value not in (None, ""):
            env[variable] = str(value)
        else:
            env.pop(variable, None)
    return env


def run_report(options: dict) -> int:
    write_status("running", "Starting research", "Getting the portfolio and market checks ready.", 3)
    effective_options = dict(options)
    if PLANNER_PATH.exists():
        try:
            saved_plan = json.loads(PLANNER_PATH.read_text(encoding="utf-8"))
            effective_options["next_investment_gbp"] = float(saved_plan["next_investment_gbp"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError):
            pass
    command = [
        "python3",
        "-m",
        "market_agent.cli",
        "--config",
        str(DATA_CONFIG),
        "--json-output",
        str(EVIDENCE_PATH),
        "--note-output",
        str(REPORT_PATH),
    ]
    if not options.get("openai_api_key"):
        command.append("--no-ai")
    started = datetime.now(ZoneInfo(str(options.get("timezone", "Europe/London"))))
    print(f"[market-agent] Starting report at {started.isoformat()}", flush=True)
    environment = runtime_environment(effective_options)
    environment["MARKET_AGENT_STATUS_PATH"] = str(STATUS_PATH)
    result = subprocess.run(command, env=environment, check=False)
    print(f"[market-agent] Report finished with exit code {result.returncode}", flush=True)
    if result.returncode == 0:
        archive_latest()
        write_status("complete", "Finished", "Your new plan and research are ready.", 100)
    else:
        write_status("error", "Research stopped", "The agent hit an error. Open Data notes for the simple explanation.", 100)
    return result.returncode


def archive_latest() -> None:
    if not EVIDENCE_PATH.exists():
        return
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    try:
        evidence = json.loads(EVIDENCE_PATH.read_text(encoding="utf-8"))
        generated = datetime.fromisoformat(str(evidence["generated_at"]))
        run_id = generated.strftime("%Y%m%dT%H%M%S")
    except (KeyError, ValueError, json.JSONDecodeError, OSError):
        run_id = datetime.now().strftime("%Y%m%dT%H%M%S")
    shutil.copyfile(EVIDENCE_PATH, HISTORY_DIR / f"{run_id}.json")
    if REPORT_PATH.exists():
        shutil.copyfile(REPORT_PATH, HISTORY_DIR / f"{run_id}.txt")
    print(f"[market-agent] Archived run {run_id}", flush=True)


def next_run(now: datetime, schedule_time: str, weekdays_only: bool) -> datetime:
    hour_text, minute_text = schedule_time.split(":", 1)
    candidate = now.replace(hour=int(hour_text), minute=int(minute_text), second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    while weekdays_only and candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def main() -> None:
    sync_policy_config()

    options = load_options()
    timezone = ZoneInfo(str(options.get("timezone", "Europe/London")))
    trigger = threading.Event()
    archive_latest()
    start_panel(
        REPORT_PATH,
        EVIDENCE_PATH,
        trigger,
        history_dir=HISTORY_DIR,
        planner_path=PLANNER_PATH,
        status_path=STATUS_PATH,
        default_investment_gbp=float(options.get("next_investment_gbp", 1000)),
    )
    print("[market-agent] Dashboard ready on port 8099", flush=True)
    if options.get("run_on_start", True):
        run_report(options)

    while True:
        options = load_options()
        now = datetime.now(timezone)
        scheduled = next_run(
            now,
            str(options.get("schedule_time", "07:30")),
            bool(options.get("weekdays_only", True)),
        )
        wait_seconds = max(1.0, (scheduled - now).total_seconds())
        print(f"[market-agent] Next report: {scheduled.isoformat()}", flush=True)
        triggered = trigger.wait(wait_seconds)
        if triggered:
            trigger.clear()
            print("[market-agent] Manual dashboard run requested", flush=True)
        run_report(options)


if __name__ == "__main__":
    main()
