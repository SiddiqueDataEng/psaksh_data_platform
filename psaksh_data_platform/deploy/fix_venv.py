"""
Fix venv path everywhere:
  OLD: /home/sattioe1/virtualenv/publichealth/3.11
  NEW: /home/sattioe1/virtualenv/softcomputech.com/publichealth
"""
import ftplib
import io
from pathlib import Path

FTP_HOST = "ftp.sattioes.com.pk"
FTP_USER = "publichealth@softcomputech.com"
FTP_PASS = "sattioe1_publichealth"

VENV = "/home/sattioe1/virtualenv/softcomputech.com/publichealth"

ftp = ftplib.FTP()
ftp.connect(FTP_HOST, 21, timeout=30)
ftp.login(FTP_USER, FTP_PASS)
ftp.set_pasv(True)


def up(data: bytes, remote: str) -> None:
    ftp.storbinary("STOR " + remote, io.BytesIO(data))
    print(f"  OK  {remote}  ({len(data)}b)")


# ── 1. Fix .htaccess ─────────────────────────────────────────────────────────
htaccess = (
    "# DO NOT REMOVE OR MODIFY. CLOUDLINUX ENV VARS CONFIGURATION BEGIN\n"
    "<IfModule Litespeed>\n"
    "</IfModule>\n"
    "# DO NOT REMOVE OR MODIFY. CLOUDLINUX ENV VARS CONFIGURATION END\n"
    "\n"
    "# DO NOT REMOVE. CLOUDLINUX PASSENGER CONFIGURATION BEGIN\n"
    f'PassengerAppRoot "/home/sattioe1/softcomputech.com/publichealth"\n'
    f'PassengerBaseURI "/publichealth"\n'
    f'PassengerPython "{VENV}/bin/python"\n'
    "# DO NOT REMOVE. CLOUDLINUX PASSENGER CONFIGURATION END\n"
)
up(htaccess.encode(), "/.htaccess")

# ── 2. Fix passenger_wsgi.py ─────────────────────────────────────────────────
wsgi = f'''"""
psaksh — Passenger WSGI entry point (self-bootstrapping)
Startup file:  passenger_wsgi.py
Entry point:   application
"""

import sys
import os
import subprocess
import traceback
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent
PKG_DIR  = APP_ROOT / "psaksh_data_platform"

VENV_ROOT = Path("{VENV}")
PYTHON    = str(VENV_ROOT / "bin" / "python")
PIP       = str(VENV_ROOT / "bin" / "pip")

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

os.environ["ENV"] = "production"
_env = APP_ROOT / ".env"
if _env.exists():
    for _l in _env.read_text(encoding="utf-8").splitlines():
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            k, _, v = _l.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

_LOG = APP_ROOT / "bootstrap.log"

def _log(msg):
    try:
        with open(str(_LOG), "a") as f:
            f.write(str(msg) + "\\n")
    except Exception:
        pass

def _run(cmd, label, timeout=300):
    _log("\\n>>> " + label)
    try:
        r = subprocess.run(
            [str(c) for c in cmd],
            capture_output=True, text=True,
            timeout=timeout, cwd=str(APP_ROOT),
        )
        if r.stdout: _log(r.stdout[-3000:])
        if r.stderr: _log("STDERR: " + r.stderr[-1000:])
        _log("exit=" + str(r.returncode))
        return r.returncode == 0
    except Exception as e:
        _log("EXCEPTION: " + str(e))
        return False

_log("\\n" + "="*50)
_log("Python: " + sys.version.split()[0])
_log("PYTHON: " + PYTHON)
_log("PIP:    " + PIP)
_log("APP:    " + str(APP_ROOT))

PACKAGES = [
    "flask", "pandas", "numpy", "plotly", "pyarrow",
    "sqlalchemy", "pymysql", "loguru",
    "pydantic", "pydantic-settings",
    "faker", "requests", "scipy",
]

def _ok(pkg):
    mod = {{"pydantic-settings": "pydantic_settings"}}.get(pkg, pkg.replace("-","_"))
    try:
        __import__(mod)
        return True
    except ImportError:
        return False

missing = [p for p in PACKAGES if not _ok(p)]
_log("Missing: " + str(missing))

if missing:
    _run([PIP, "install", "--ignore-installed", "-q"] + missing, "pip_batch")
    still = [p for p in missing if not _ok(p)]
    if still:
        _log("Retrying one-by-one: " + str(still))
        for pkg in still:
            _run([PIP, "install", "--ignore-installed", "-q", pkg], "pip_" + pkg)

_RAW  = PKG_DIR / "data" / "raw"
_PROC = PKG_DIR / "data" / "processed"
_RAW.mkdir(parents=True, exist_ok=True)
_PROC.mkdir(parents=True, exist_ok=True)

if not (_RAW / "households.csv").exists():
    _log("Generating data...")
    _run([PYTHON, "-m", "psaksh_data_platform.data_generator.run",
          "--households", "500", "--rounds", "4",
          "--output-dir", str(_RAW), "--format", "csv"],
         "data_gen", timeout=120)

if not (_PROC / "fct_child_nutrition.parquet").exists():
    _log("Running ETL...")
    _run([PYTHON, "-m", "psaksh_data_platform.etl.pipeline.run",
          "--env", "production",
          "--raw-dir", str(_RAW), "--output-dir", str(_PROC)],
         "etl", timeout=300)

_import_err = None
try:
    from psaksh_data_platform.webapp.app import app as application
    _log("Flask app loaded OK")
except Exception:
    _import_err = traceback.format_exc()
    _log("IMPORT ERROR:\\n" + _import_err)

if _import_err:
    _log_txt = _LOG.read_text(errors="replace") if _LOG.exists() else ""
    _body = (
        "<html><body style=\\"font-family:monospace;padding:20px;background:#111;color:#eee\\">"
        "<h2 style=\\"color:#e94560\\">psaksh Import Error</h2>"
        "<pre style=\\"background:#222;padding:16px;border-radius:8px\\">"
        + _import_err.replace("<", "&lt;") + "</pre>"
        "<h3>Bootstrap Log</h3>"
        "<pre style=\\"background:#222;padding:16px;border-radius:8px\\">"
        + _log_txt.replace("<", "&lt;") + "</pre>"
        "</body></html>"
    ).encode("utf-8")

    def application(environ, start_response):
        start_response("500 Internal Server Error", [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(_body))),
        ])
        return [_body]

_real_app = application

def application(environ, start_response):
    if environ.get("PATH_INFO", "") == "/bootstrap-log":
        txt  = _LOG.read_text(errors="replace") if _LOG.exists() else "No log."
        body = (
            "<html><body style=\\"font-family:monospace;padding:20px;"
            "background:#111;color:#eee\\"><pre>"
            + txt.replace("<", "&lt;") + "</pre></body></html>"
        ).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ])
        return [body]
    return _real_app(environ, start_response)
'''

up(wsgi.encode("utf-8"), "/passenger_wsgi.py")

# ── 3. Clear bootstrap log ────────────────────────────────────────────────────
up(b"", "/bootstrap.log")

ftp.quit()
print("\nDone. Go to cPanel -> Python App -> RESTART")
print("Then open: https://softcomputech.com/publichealth/bootstrap-log")

