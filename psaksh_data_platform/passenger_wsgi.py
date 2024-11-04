"""
Phusion Passenger WSGI entry point for cPanel Python App.

Server layout:
  App root:   /home/sattioe1/softcomputech.com/publichealth/
  Package:    /home/sattioe1/softcomputech.com/publichealth/psaksh_data_platform/
  Venv:       /home/sattioe1/virtualenv/softcomputech.com/publichealth/3.11/
  URL:        https://softcomputech.com/publichealth/

Passenger looks for a module-level name called `application`.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# ── Resolve paths ─────────────────────────────────────────────────────────────
# This file lives at:  <app_root>/passenger_wsgi.py
# The package lives at: <app_root>/psaksh_data_platform/
APP_ROOT = Path(__file__).resolve().parent

# Ensure the app root is on sys.path so `psaksh_data_platform` is importable
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# ── Load .env.production ──────────────────────────────────────────────────────
env_file = APP_ROOT / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(env_file))
    except ImportError:
        # Manual fallback — parse key=value lines
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

# ── Import Flask app ──────────────────────────────────────────────────────────
try:
    from psaksh_data_platform.webapp.app import app as application
except Exception as _import_err:
    # If the full app fails to import, serve a minimal error page so
    # Passenger shows something useful instead of a blank 500.
    import traceback
    _tb = traceback.format_exc()

    def application(environ, start_response):
        body = (
            b"<html><body><pre style='padding:20px;font-family:monospace'>"
            b"<h2>PSAKSH - Import Error</h2>\n"
            + _tb.encode("utf-8", errors="replace")
            + b"</pre></body></html>"
        )
        start_response(
            "500 Internal Server Error",
            [("Content-Type", "text/html"), ("Content-Length", str(len(body)))],
        )
        return [body]

