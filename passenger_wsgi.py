"""
PSAKSH — Passenger WSGI entry point
Startup file:  passenger_wsgi.py
Entry point:   application

Server layout:
  App root:   /home/sattioe1/softcomputech.com/publichealth/
  Package:    /home/sattioe1/softcomputech.com/publichealth/psaksh_data_platform/
  Venv:       /home/sattioe1/virtualenv/softcomputech.com/publichealth/3.11/
  Data:       /home/sattioe1/softcomputech.com/publichealth/psaksh_data_platform/data/
  URL:        https://softcomputech.com/publichealth/

# v5 — file-based SSE job logs via /tmp/psaksh_job_logs/
"""

import sys
import site
import os
import subprocess
import traceback
from pathlib import Path

# ── CRITICAL: Fix PYTHONHOME before any imports ───────────────────────────────
_VENV = "/home/sattioe1/virtualenv/softcomputech.com/publichealth/3.11"
os.environ["PYTHONHOME"] = _VENV
os.environ["VIRTUAL_ENV"] = _VENV
for _sp in [
    _VENV + "/lib/python3.11/site-packages",
    _VENV + "/lib64/python3.11/site-packages",
]:
    if _sp not in sys.path:
        sys.path.insert(0, _sp)
    try:
        site.addsitedir(_sp)
    except Exception:
        pass

# ── Paths — single source of truth ───────────────────────────────────────────
APP_ROOT = Path(__file__).resolve().parent          # /home/sattioe1/softcomputech.com/publichealth
PKG_DIR  = APP_ROOT / "psaksh_data_platform"        # .../psaksh_data_platform
DATA_DIR = PKG_DIR  / "data"                        # .../psaksh_data_platform/data
PYTHON   = _VENV + "/bin/python"
PIP      = _VENV + "/bin/pip"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# ── Load .env ─────────────────────────────────────────────────────────────────
os.environ["ENV"] = "production"
_env = APP_ROOT / ".env"
if _env.exists():
    for _l in _env.read_text(encoding="utf-8").splitlines():
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            k, _, v = _l.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

# ── Bootstrap log ─────────────────────────────────────────────────────────────
_LOG = APP_ROOT / "bootstrap.log"

def _log(msg):
    try:
        with open(str(_LOG), "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")
    except Exception:
        pass

def _run(cmd, label, timeout=300):
    _log("\n[" + label + "] " + " ".join(str(c) for c in cmd))
    try:
        r = subprocess.run(
            [str(c) for c in cmd],
            capture_output=True, text=True,
            timeout=timeout, cwd=str(APP_ROOT),
            env={**os.environ, "PYTHONPATH": str(APP_ROOT)},
        )
        if r.stdout.strip():
            _log(r.stdout[-1000:])
        if r.stderr.strip():
            _log("STDERR: " + r.stderr[-500:])
        _log("exit=" + str(r.returncode))
        return r.returncode == 0
    except Exception as e:
        _log("EXCEPTION: " + str(e))
        return False

_log("\n" + "=" * 60)
_log("Startup  Python=" + sys.version.split()[0])
_log("APP_ROOT=" + str(APP_ROOT))
_log("PKG_DIR =" + str(PKG_DIR))
_log("DATA_DIR=" + str(DATA_DIR))

# ── Force-reload ETL modules so updated medallion.py is always used ───────────
# This runs at Passenger startup — clears any stale module cache
for _mod in list(sys.modules.keys()):
    if any(_mod.startswith(p) for p in [
        "psaksh_data_platform.etl",
        "psaksh_data_platform.analytics",
        "psaksh_data_platform.data_generator",
        "etl.", "analytics.", "data_generator.",
    ]):
        del sys.modules[_mod]
_log("ETL modules cleared from cache")

# ── Install flask if missing ──────────────────────────────────────────────────
try:
    import flask
    _log("flask OK: " + flask.__version__)
except ImportError:
    _log("flask missing — installing...")
    _run([PIP, "install", "--no-cache-dir", "flask"], "pip_flask")

# ── Ensure data directories exist ────────────────────────────────────────────
for _d in [
    DATA_DIR / "raw" / "current",
    DATA_DIR / "raw" / "historical",
    DATA_DIR / "bronze",
    DATA_DIR / "silver",
    DATA_DIR / "gold",
    DATA_DIR / "delta_log",
    DATA_DIR / "processed",
]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Generate data if raw/current is empty ────────────────────────────────────
_current = DATA_DIR / "raw" / "current"
if not any(_current.glob("*.parquet")) and not any(_current.glob("*.csv")):
    _log("No current data found — generating 500 households...")
    _run([PYTHON, "-m", "psaksh_data_platform.data_generator.run",
          "--households", "500", "--rounds", "4",
          "--output-dir", str(DATA_DIR / "raw"),
          "--inject-dq", "1"],
         "data_gen", timeout=180)

# ── Load Flask app ────────────────────────────────────────────────────────────
_import_err = None
try:
    from psaksh_data_platform.webapp.app import app as _flask_app
    _log("Flask app loaded OK")
    _log("PKG_DIR in app: " + str(_flask_app.config.get("APPLICATION_ROOT", "?")))
except Exception:
    _import_err = traceback.format_exc()
    _log("IMPORT ERROR:\n" + _import_err)

# ── Error page ────────────────────────────────────────────────────────────────
if _import_err:
    _log_txt = _LOG.read_text(errors="replace") if _LOG.exists() else ""
    _body = (
        "<html><body style='font-family:monospace;padding:20px;"
        "background:#0d1117;color:#c9d1d9'>"
        "<h2 style='color:#f85149'>PSAKSH Import Error</h2>"
        "<pre style='background:#161b22;padding:16px;border-radius:6px;"
        "overflow:auto;white-space:pre-wrap'>"
        + _import_err.replace("&", "&amp;").replace("<", "&lt;")
        + "</pre><h3 style='margin-top:20px'>Bootstrap Log</h3>"
        "<pre style='background:#161b22;padding:16px;border-radius:6px;"
        "overflow:auto;white-space:pre-wrap'>"
        + _log_txt.replace("&", "&amp;").replace("<", "&lt;")
        + "</pre></body></html>"
    ).encode("utf-8")

    def _flask_app(environ, start_response):
        start_response("500 Internal Server Error", [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(_body))),
        ])
        return [_body]


# ── WSGI application ──────────────────────────────────────────────────────────
def application(environ, start_response):
    path = environ.get("PATH_INFO", "")

    # Clear Jinja2 template cache so updated templates load immediately
    try:
        _flask_app.jinja_env.cache.clear()
    except Exception:
        pass

    # Bootstrap log diagnostic
    if path == "/bootstrap-log":
        txt  = _LOG.read_text(errors="replace") if _LOG.exists() else "No log."
        body = (
            "<html><body style='font-family:monospace;padding:20px;"
            "background:#0d1117;color:#c9d1d9'><pre>"
            + txt.replace("&", "&amp;").replace("<", "&lt;")
            + "</pre></body></html>"
        ).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ])
        return [body]

    return _flask_app(environ, start_response)
