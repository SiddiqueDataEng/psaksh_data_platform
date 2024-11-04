"""
PSAKSH Data Platform — Master Deploy & Test Script
===================================================
Handles:
  1. FTP upload to cPanel (softcomputech.com/publichealth)
  2. Offline tests  (pytest — no server needed)
  3. Online tests   (Flask app running locally or on server)
  4. Streamlit test (launch and smoke-test the dashboard)

Usage:
    python deploy_and_test.py --help
    python deploy_and_test.py --all
    python deploy_and_test.py --ftp
    python deploy_and_test.py --test-offline
    python deploy_and_test.py --test-online
    python deploy_and_test.py --test-streamlit
    python deploy_and_test.py --ftp --dry-run
"""

from __future__ import annotations

import argparse
import ftplib
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
WORKSPACE   = Path(__file__).resolve().parent          # project root
PKG_ROOT    = WORKSPACE / "psaksh_data_platform"       # package dir

# ── FTP credentials (from psaksh_data_platform/ftp.txt) ──────────────────────
FTP_HOST     = "ftp.sattioes.com.pk"
FTP_PORT     = 21
FTP_USER     = "publichealth@softcomputech.com"
FTP_PASSWORD = "publichealth@softcomputech"
REMOTE_BASE  = "/home/sattioe1/softcomputech.com/publichealth"

# ── URLs ──────────────────────────────────────────────────────────────────────
ONLINE_URL      = "https://softcomputech.com/publichealth"
LOCAL_FLASK_URL = "http://localhost:5000"
STREAMLIT_URL   = "http://localhost:8501"

# ── Upload map ────────────────────────────────────────────────────────────────
UPLOAD_MAP = [
    # Server entry point
    (WORKSPACE / "passenger_wsgi.py",                    "passenger_wsgi.py"),
    # Production .env
    (PKG_ROOT  / ".env.production",                      ".env"),
    # Minimal web requirements
    (PKG_ROOT  / "webapp" / "requirements_web.txt",      "requirements.txt"),
    # Setup / fix scripts
    (PKG_ROOT  / "deploy" / "setup.sh",                  "setup.sh"),
    (PKG_ROOT  / "deploy" / "quickfix.sh",               "quickfix.sh"),
    (PKG_ROOT  / "deploy" / "reinstall.py",              "reinstall.py"),
    (PKG_ROOT  / "deploy" / "fix_flask.py",              "fix_flask.py"),
    # Package root
    (PKG_ROOT  / "__init__.py",                          "psaksh_data_platform/__init__.py"),
    # Sub-packages
    (PKG_ROOT  / "config",                               "psaksh_data_platform/config"),
    (PKG_ROOT  / "data_generator",                       "psaksh_data_platform/data_generator"),
    (PKG_ROOT  / "etl",                                  "psaksh_data_platform/etl"),
    (PKG_ROOT  / "analytics",                            "psaksh_data_platform/analytics"),
    (PKG_ROOT  / "warehouse",                            "psaksh_data_platform/warehouse"),
    (PKG_ROOT  / "webapp",                               "psaksh_data_platform/webapp"),
    (PKG_ROOT  / "geospatial",                           "psaksh_data_platform/geospatial"),
    (PKG_ROOT  / "governance",                           "psaksh_data_platform/governance"),
]

SKIP_PATTERNS = {
    "__pycache__", ".pyc", ".pyo", ".pyd",
    ".git", ".gitignore",
    "psaksh_local.db", "rads_local.db",
    ".DS_Store", "Thumbs.db",
    "data/raw/", "data/processed/", "data/bronze/", "data/silver/", "data/gold/",
    "node_modules", ".env.example",
    "requirements.txt",   # don't overwrite web requirements with dev requirements
}

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def _p(msg, **kw): print(msg.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8", errors="replace"), **kw)
def ok(msg):   _p(f"  {GREEN}[OK]{RESET}  {msg}")
def fail(msg): _p(f"  {RED}[FAIL]{RESET}  {msg}", file=sys.stderr)
def info(msg): _p(f"  {CYAN}-->{RESET}  {msg}")
def warn(msg): _p(f"  {YELLOW}[WARN]{RESET}  {msg}")
def header(msg):
    _p(f"\n{BOLD}{CYAN}{'='*64}{RESET}")
    _p(f"{BOLD}{CYAN}  {msg}{RESET}")
    _p(f"{BOLD}{CYAN}{'='*64}{RESET}")


# ══════════════════════════════════════════════════════════════════════════════
# FTP UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def should_skip(path: Path) -> bool:
    s = str(path).replace("\\", "/")
    return any(p in s for p in SKIP_PATTERNS)


def ftp_mkdirs(ftp: ftplib.FTP, remote: str) -> None:
    """
    Create directories under REMOTE_BASE only.
    Never recreates /home, /home/sattioe1, etc. — those already exist
    and rebuilding them from / causes the doubled-path bug:
      /home/sattioe1/.../publichealth/home/sattioe1/.../publichealth
    """
    remote = remote.replace("\\", "/")
    # Only create the portion that sits UNDER REMOTE_BASE
    if remote.startswith(REMOTE_BASE):
        rel = remote[len(REMOTE_BASE):].lstrip("/")
    else:
        rel = remote.lstrip("/")
    if not rel:
        return
    cur = REMOTE_BASE
    for part in rel.split("/"):
        if not part:
            continue
        cur = f"{cur}/{part}"
        try:
            ftp.mkd(cur)
        except ftplib.error_perm:
            pass  # already exists


def upload_file(ftp: ftplib.FTP | None, local: Path, remote: str, dry: bool) -> bool:
    if dry:
        print(f"    [DRY] {local.name}  -->  {remote}")
        return True
    try:
        ftp_mkdirs(ftp, remote.rsplit("/", 1)[0])
        with open(local, "rb") as f:
            ftp.storbinary(f"STOR {remote}", f)
        ok(local.name)
        return True
    except Exception as e:
        fail(f"{local.name}: {e}")
        return False


def upload_dir(ftp: ftplib.FTP | None, local_dir: Path, remote_dir: str, dry: bool) -> tuple[int, int]:
    ok_count = fail_count = 0
    for item in sorted(local_dir.rglob("*")):
        if should_skip(item) or not item.is_file():
            continue
        rel    = item.relative_to(local_dir)
        remote = f"{remote_dir}/{str(rel).replace(chr(92), '/')}"
        if upload_file(ftp, item, remote, dry):
            ok_count += 1
        else:
            fail_count += 1
    return ok_count, fail_count


def run_ftp(dry_run: bool = False) -> bool:
    header("FTP Upload to softcomputech.com/publichealth")
    info(f"Host   : {FTP_HOST}:{FTP_PORT}")
    info(f"User   : {FTP_USER}")
    info(f"Remote : {REMOTE_BASE}")
    info(f"Dry run: {dry_run}")

    ftp = None
    if not dry_run:
        print(f"\n  Connecting to {FTP_HOST}:{FTP_PORT} ...")
        try:
            ftp = ftplib.FTP()
            ftp.connect(FTP_HOST, FTP_PORT, timeout=60)
            ftp.login(FTP_USER, FTP_PASSWORD)
            ftp.set_pasv(True)
            ok(f"Connected as {FTP_USER}")
        except Exception as e:
            fail(f"FTP connection failed: {e}")
            return False

    total_ok = total_fail = 0

    for local, rel_remote in UPLOAD_MAP:
        remote = f"{REMOTE_BASE}/{rel_remote}"
        local  = Path(local)

        if not local.exists():
            warn(f"SKIP (not found): {local}")
            continue

        if local.is_dir():
            print(f"\n  DIR  {local.name}/  -->  {rel_remote}/")
            n_ok, n_fail = upload_dir(ftp, local, remote, dry_run)
            total_ok   += n_ok
            total_fail += n_fail
            print(f"       {n_ok} uploaded, {n_fail} failed")
        else:
            print(f"\n  FILE {local.name}  -->  {rel_remote}")
            if upload_file(ftp, local, remote, dry_run):
                total_ok += 1
            else:
                total_fail += 1

    if ftp:
        try:
            ftp.quit()
        except Exception:
            pass

    print(f"\n  {BOLD}Done -- {total_ok} files uploaded, {total_fail} failed{RESET}")

    if not dry_run:
        print(f"""
{CYAN}Next steps on the server (cPanel Terminal):{RESET}

  source /home/sattioe1/virtualenv/softcomputech.com/publichealth/3.11/bin/activate
  cd /home/sattioe1/softcomputech.com/publichealth

  pip install --no-cache-dir -r requirements.txt

  python -m psaksh_data_platform.data_generator.run \\
      --households 500 --rounds 4 \\
      --output-dir psaksh_data_platform/data/raw --format csv

  python -m psaksh_data_platform.etl.pipeline.run \\
      --raw-dir psaksh_data_platform/data/raw \\
      --output-dir psaksh_data_platform/data

  # Then click RESTART in cPanel Python App panel
  # URL: {ONLINE_URL}
""")

    return total_fail == 0


# ══════════════════════════════════════════════════════════════════════════════
# OFFLINE TESTS (pytest)
# ══════════════════════════════════════════════════════════════════════════════

def run_offline_tests() -> bool:
    header("Offline Tests (pytest)")
    info("Running unit tests — no server required")

    test_dir = PKG_ROOT / "tests"
    if not test_dir.exists():
        fail(f"Tests directory not found: {test_dir}")
        return False

    cmd = [
        sys.executable, "-m", "pytest",
        str(test_dir),
        "-v",
        "--tb=short",
        "--no-header",
        "-q",
    ]

    print()
    result = subprocess.run(cmd, cwd=str(WORKSPACE))
    success = result.returncode == 0

    if success:
        ok("All offline tests passed")
    else:
        fail("Some offline tests failed — see output above")

    return success


# ══════════════════════════════════════════════════════════════════════════════
# ONLINE TESTS (HTTP smoke tests)
# ══════════════════════════════════════════════════════════════════════════════

def _http_get(url: str, timeout: int = 15) -> tuple[int, str]:
    """Return (status_code, body_snippet). Returns (-1, error) on failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PSAKSH-Test/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, str(e)
    except Exception as e:
        return -1, str(e)


def _smoke_test_url(label: str, url: str, expect_text: str | None = None) -> bool:
    status, body = _http_get(url)
    if status == 200:
        if expect_text and expect_text.lower() not in body.lower():
            warn(f"{label}: HTTP 200 but expected text '{expect_text}' not found")
            return False
        ok(f"{label}: HTTP {status}")
        return True
    else:
        fail(f"{label}: HTTP {status} — {url}")
        return False


def run_online_tests(base_url: str | None = None) -> bool:
    """
    Smoke-test the live Flask app.
    Defaults to the production URL; pass base_url to test a local instance.
    """
    url = (base_url or ONLINE_URL).rstrip("/")
    header(f"Online Tests → {url}")
    info("Smoke-testing Flask routes")

    routes = [
        ("Home / Overview",  f"{url}/",           "Public Sector Analytics"),
        ("Nutrition page",   f"{url}/nutrition",   "Nutrition"),
        ("Maternal page",    f"{url}/maternal",    "Maternal"),
        ("Field ops page",   f"{url}/field",       "Field"),
        ("Facilities page",  f"{url}/facilities",  "Facilit"),
        ("Bootstrap log",    f"{url}/bootstrap-log", "Python"),
        ("API — households",     f"{url}/api/v1/households",     None),
        ("API — child-nutrition", f"{url}/api/v1/child-nutrition", None),
    ]

    results = []
    for label, route_url, expect in routes:
        passed = _smoke_test_url(label, route_url, expect)
        results.append(passed)

    passed_count = sum(results)
    total        = len(results)
    print(f"\n  {BOLD}{passed_count}/{total} routes OK{RESET}")

    if passed_count == total:
        ok("All online smoke tests passed")
        return True
    else:
        fail(f"{total - passed_count} route(s) failed")
        return False


def run_local_flask_tests() -> bool:
    """Start Flask locally, run smoke tests, then stop it."""
    header("Local Flask Tests (offline mode)")
    info("Starting Flask dev server on localhost:5000 ...")

    env = os.environ.copy()
    env["ENV"]      = "local"
    env["FLASK_APP"] = "psaksh_data_platform.webapp.app"

    proc = subprocess.Popen(
        [sys.executable, "-m", "flask", "run", "--port", "5000", "--no-reload"],
        cwd=str(WORKSPACE),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for Flask to start
    for _ in range(20):
        time.sleep(1)
        status, _ = _http_get(LOCAL_FLASK_URL)
        if status in (200, 302, 404):
            break
    else:
        fail("Flask did not start within 20 seconds")
        proc.terminate()
        return False

    ok("Flask started")
    result = run_online_tests(base_url=LOCAL_FLASK_URL)

    proc.terminate()
    proc.wait(timeout=5)
    info("Flask stopped")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# STREAMLIT TEST
# ══════════════════════════════════════════════════════════════════════════════

def run_streamlit_test() -> bool:
    """Launch Streamlit, verify it responds, then stop it."""
    header("Streamlit Dashboard Test")
    info("Starting Streamlit on localhost:8501 ...")

    dash_app = PKG_ROOT / "dashboards" / "app.py"
    if not dash_app.exists():
        fail(f"Streamlit app not found: {dash_app}")
        return False

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run",
            str(dash_app),
            "--server.port", "8501",
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=str(PKG_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for Streamlit to start (it takes a few seconds)
    started = False
    for i in range(30):
        time.sleep(1)
        status, body = _http_get(STREAMLIT_URL)
        if status == 200:
            started = True
            break
        if i % 5 == 0:
            info(f"  Waiting for Streamlit... ({i}s)")

    if not started:
        fail("Streamlit did not start within 30 seconds")
        proc.terminate()
        return False

    ok(f"Streamlit is running at {STREAMLIT_URL}")

    # Smoke test: check the main page loads
    status, body = _http_get(STREAMLIT_URL)
    if status == 200:
        ok("Streamlit main page: HTTP 200")
    else:
        fail(f"Streamlit main page: HTTP {status}")

    # Check health endpoint
    status2, _ = _http_get(f"{STREAMLIT_URL}/_stcore/health")
    if status2 == 200:
        ok("Streamlit health endpoint: HTTP 200")
    else:
        warn(f"Streamlit health endpoint: HTTP {status2} (non-critical)")

    proc.terminate()
    proc.wait(timeout=10)
    info("Streamlit stopped")

    print(f"""
{CYAN}To run Streamlit interactively:{RESET}
  cd psaksh_data_platform
  streamlit run dashboards/app.py

  Or double-click:  psaksh_data_platform\\run_streamlit.bat
  URL: {STREAMLIT_URL}
""")
    return status == 200


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PSAKSH — Deploy via FTP and run all tests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python deploy_and_test.py --all                  # FTP + all tests
  python deploy_and_test.py --ftp                  # upload only
  python deploy_and_test.py --ftp --dry-run        # preview upload
  python deploy_and_test.py --test-offline         # pytest only
  python deploy_and_test.py --test-online          # smoke-test live server
  python deploy_and_test.py --test-online-local    # start Flask locally + test
  python deploy_and_test.py --test-streamlit       # launch + test Streamlit
        """,
    )
    parser.add_argument("--all",               action="store_true", help="Run FTP upload + all tests")
    parser.add_argument("--ftp",               action="store_true", help="Upload via FTP to cPanel")
    parser.add_argument("--dry-run",           action="store_true", help="Preview FTP upload without uploading")
    parser.add_argument("--test-offline",      action="store_true", help="Run pytest unit tests (no server)")
    parser.add_argument("--test-online",       action="store_true", help="Smoke-test live server at softcomputech.com")
    parser.add_argument("--test-online-local", action="store_true", help="Start Flask locally and smoke-test it")
    parser.add_argument("--test-streamlit",    action="store_true", help="Launch Streamlit and smoke-test it")
    args = parser.parse_args()

    # Default: show help if no flags given
    if not any(vars(args).values()):
        parser.print_help()
        return

    results: dict[str, bool] = {}

    if args.all or args.ftp:
        results["FTP Upload"] = run_ftp(dry_run=args.dry_run)

    if args.all or args.test_offline:
        results["Offline Tests"] = run_offline_tests()

    if args.all or args.test_online:
        results["Online Tests (live)"] = run_online_tests()

    if args.test_online_local:
        results["Online Tests (local Flask)"] = run_local_flask_tests()

    if args.all or args.test_streamlit:
        results["Streamlit Test"] = run_streamlit_test()

    # ── Summary ───────────────────────────────────────────────────────────────
    if results:
        header("Summary")
        all_passed = True
        for name, passed in results.items():
            if passed:
                ok(name)
            else:
                fail(name)
                all_passed = False

        print()
        if all_passed:
            print(f"  {BOLD}{GREEN}All steps completed successfully.{RESET}")
        else:
            print(f"  {BOLD}{RED}Some steps failed — see details above.{RESET}")
            sys.exit(1)


if __name__ == "__main__":
    main()
