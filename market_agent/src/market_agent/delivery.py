from __future__ import annotations

import os

from . import home_assistant, whatsapp


def send(note: str) -> None:
    provider = os.getenv("DELIVERY_PROVIDER", "whatsapp").lower()
    if provider == "home_assistant":
        home_assistant.send(note)
        return
    whatsapp.send(note)
