from __future__ import annotations

import os
import ssl
from pathlib import Path


def verified_ssl_context() -> ssl.SSLContext:
    """Use Python's trust store, falling back to the macOS system CA bundle."""
    configured = os.getenv("SSL_CERT_FILE")
    candidates = [configured, "/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return ssl.create_default_context(cafile=candidate)
    return ssl.create_default_context()

