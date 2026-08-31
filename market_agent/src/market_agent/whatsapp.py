from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request

from .net import verified_ssl_context


class DeliveryError(RuntimeError):
    pass


def _post(request: urllib.request.Request) -> None:
    with urllib.request.urlopen(request, timeout=30, context=verified_ssl_context()) as response:
        if not 200 <= response.status < 300:
            raise DeliveryError(f"WhatsApp provider returned HTTP {response.status}")


def send(note: str) -> None:
    provider = os.getenv("WHATSAPP_PROVIDER", "stdout").lower()
    if provider == "stdout":
        print(note)
        return
    recipient = os.environ["WHATSAPP_TO"]
    if provider == "twilio":
        sid = os.environ["TWILIO_ACCOUNT_SID"]
        token = os.environ["TWILIO_AUTH_TOKEN"]
        sender = os.environ["TWILIO_WHATSAPP_FROM"]
        data = urllib.parse.urlencode({"From": sender, "To": f"whatsapp:{recipient}", "Body": note}).encode()
        auth = base64.b64encode(f"{sid}:{token}".encode()).decode()
        request = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data=data,
            headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        _post(request)
        return
    if provider == "meta":
        version = os.getenv("META_API_VERSION", "v23.0")
        phone_id = os.environ["META_PHONE_NUMBER_ID"]
        token = os.environ["META_ACCESS_TOKEN"]
        template = os.getenv("META_TEMPLATE_NAME")
        if template:
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "template",
                "template": {
                    "name": template,
                    "language": {"code": os.getenv("META_TEMPLATE_LANGUAGE", "en_GB")},
                    "components": [{"type": "body", "parameters": [{"type": "text", "text": note[:4000]}]}],
                },
            }
        else:
            payload = {"messaging_product": "whatsapp", "to": recipient, "type": "text", "text": {"body": note, "preview_url": False}}
        request = urllib.request.Request(
            f"https://graph.facebook.com/{version}/{phone_id}/messages",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        _post(request)
        return
    raise DeliveryError(f"Unknown WHATSAPP_PROVIDER: {provider}")
