from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from market_agent import home_assistant


class HomeAssistantDeliveryTests(unittest.TestCase):
    def test_auto_detects_mobile_app_services(self) -> None:
        response = [
            {"domain": "light", "services": {"turn_on": {}}},
            {
                "domain": "notify",
                "services": {"persistent_notification": {}, "mobile_app_example_phone": {}},
            },
        ]
        with patch.dict(os.environ, {}, clear=True), patch.object(home_assistant, "_api_request", return_value=response):
            self.assertEqual(home_assistant._mobile_services(), ["mobile_app_example_phone"])

    def test_configured_service_does_not_need_discovery(self) -> None:
        with patch.dict(os.environ, {"HA_NOTIFY_SERVICE": "notify.mobile_app_phone"}, clear=True):
            self.assertEqual(home_assistant._mobile_services(), ["mobile_app_phone"])

    def test_send_creates_persistent_and_mobile_notifications(self) -> None:
        with patch.object(home_assistant, "_mobile_services", return_value=["mobile_app_phone"]), patch.object(
            home_assistant, "_api_request"
        ) as request:
            home_assistant.send("SELL NOW\n• None\n\nKEEP / REVIEW\n• VALL — keep")
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args[0], "/services/persistent_notification/create")
        self.assertEqual(request.call_args_list[1].args[0], "/services/notify/mobile_app_phone")


if __name__ == "__main__":
    unittest.main()
