from __future__ import annotations

import re
import unittest
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


class ReleaseSecurityTests(unittest.TestCase):
    def test_public_defaults_contain_no_personal_markers(self) -> None:
        public_files = [
            APP_ROOT / "config.yaml",
            APP_ROOT / "config" / "portfolio.json",
            APP_ROOT / ".env.example",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in public_files)
        for marker in ("Karim", "mobile_app_karim", "+44XXXXXXXXXX"):
            self.assertNotIn(marker.lower(), combined.lower())

    def test_secret_defaults_are_empty_and_masked(self) -> None:
        config = (APP_ROOT / "config.yaml").read_text(encoding="utf-8")
        secret_options = (
            "twilio_auth_token",
            "meta_access_token",
            "openai_api_key",
            "trading212_api_key",
            "trading212_api_secret",
        )
        for name in secret_options:
            self.assertRegex(config, rf"(?m)^  {re.escape(name)}: \"\"$")
            self.assertRegex(config, rf"(?m)^  {re.escape(name)}: password$")

    def test_hl_option_never_requests_login_credentials(self) -> None:
        config = (APP_ROOT / "config.yaml").read_text(encoding="utf-8").lower()
        self.assertIn("hargreaves_lansdown_holdings_json", config)
        self.assertNotIn("hargreaves_lansdown_password", config)
        self.assertNotIn("hargreaves_lansdown_username", config)

    def test_no_known_secret_shapes_are_committed(self) -> None:
        patterns = (
            re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
            re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
            re.compile(r"AC[a-fA-F0-9]{30,}"),
        )
        for path in APP_ROOT.rglob("*"):
            if not path.is_file() or path.suffix.lower() in {".png", ".pyc"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in patterns:
                self.assertIsNone(pattern.search(text), f"possible secret in {path}")


if __name__ == "__main__":
    unittest.main()
