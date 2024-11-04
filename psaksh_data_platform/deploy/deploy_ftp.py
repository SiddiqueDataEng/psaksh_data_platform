"""
FTP deployment script — uploads the full PSAKSH platform to cPanel hosting.

Target server:
  IP:      144.76.202.252
  FTP:     ftp.sattioes.com.pk  port 21
  User:    publichealth@softcomputech.com
  Remote:  /home/sattioe1/softcomputech.com/publichealth/
  URL:     https://softcomputech.com/publichealth/

cPanel Python App settings (already configured on server):
  Application root:  publichealth
  Startup file:      passenger_wsgi.py
  Entry point:       application
  Virtual env:       /home/sattioe1/virtualenv/softcomputech.com/publichealth/3.11/

Usage:
    python deploy/deploy_ftp.py            # full upload
    python deploy/deploy_ftp.py --dry-run  # preview only
    python deploy/deploy_ftp.py --quick    # only changed files (by size)
"""

from __future__ import annotations

import argparse
import ftplib
import hashlib
import sys
from pathlib import Path

# ── FTP credentials ───────────────────────────────────────────────────────────
FTP_HOST     = "ftp.sattioes.com.pk"
FTP_PORT     = 21
FTP_USER     = "publichealth@softcomputech.com"
FTP_PASSWORD = "publichealth@softcomputech"   # from ftp.txt
REMOTE_BASE  = "/home/sattioe1/softcomputech.com/publichealth"

# ── Local paths ───────────────────────────────────────────────────────────────
# deploy_ftp.py lives at:  psaksh_data_platform/deploy/deploy_ftp.py
PKG_ROOT  = Path(__file__).resolve().parents[1]   # psaksh_data_platform/
WORKSPACE = PKG_ROOT.parent                        # project root

# ── Upload map ────────────────────────────────────────────────────────────────
# (local_path, remote_path_relative_to_REMOTE_BASE)
UPLOAD_MAP = [
    # ── Server entry point ────────────────────────────────────────────────
    (WORKSPACE / "passenger_wsgi.py",           "passenger_wsgi.py"),

    # ── Production .env ───────────────────────────────────────────────────
    (PKG_ROOT  / ".env.production",             ".env"),

    # ── Server requirements (minimal, no heavy ML libs) ───────────────────
    (PKG_ROOT  / "webapp" / "requirements_web.txt", "requirements.txt"),

    # ── Setup / fix scripts (run from cPanel terminal) ────────────────────
    (PKG_ROOT  / "deploy" / "setup.sh",         "setup.sh"),
    (PKG_ROOT  / "deploy" / "quickfix.sh",      "quickfix.sh"),
    (PKG_ROOT  / "deploy" / "reinstall.py",     "reinstall.py"),
    (PKG_ROOT  / "deploy" / "fix_flask.py",     "fix_flask.py"),

    # ── Package root ──────────────────────────────────────────────────────
    (PKG_ROOT  / "__init__.py",                 "psaksh_data_platform/__init__.py"),

    # ── Sub-packages ──────────────────────────────────────────────────────
    (PKG_ROOT  / "config",                      "psaksh_data_platform/config"),
    (PKG_ROOT  / "data_generator",              "psaksh_data_platform/data_generator"),
    (PKG_ROOT  / "etl",                         "psaksh_data_platform/etl"),
    (PKG_ROOT  / "analytics",                   "psaksh_data_platform/analytics"),
    (PKG_ROOT  / "warehouse",                   "psaksh_data_platform/warehouse"),
    (PKG_ROOT  / "webapp",                      "psaksh_data_platform/webapp"),
    (PKG_ROOT  / "geospatial",                  "psaksh_data_platform/geospatial"),
    (PKG_ROOT  / "governance",                  "psaksh_data_platform/governance"),
]

# Patterns to never upload
SKIP_PATTERNS = {
    "__pycache__", ".pyc", ".pyo", ".pyd",
    ".git", ".gitignore",
    "psaksh_local.db", "rads_local.db",
    ".DS_Store", "Thumbs.db",
    "data/raw/", "data/processed/", "data/bronze/", "data/silver/", "data/gold/",
    "node_modules", ".env.example",
    "requirements.txt",   # don't overwrite the web requirements with the dev one
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def should_skip(path: Path) -> bool:
    s = str(path).replace("\\", "/")
    return any(p in s for p in SKIP_PATTERNS)


def ftp_mkdirs(ftp: ftplib.FTP, remote: str) -> None:
    """
    Recursively create remote directories relative to REMOTE_BASE.
    Only creates the subdirectory parts UNDER REMOTE_BASE — never
    tries to create /home, /home/sattioe1, etc. which already exist
    and would cause a doubled path like /home/.../publichealth/home/...
    """
    remote = remote.replace("\\", "/")
    # Strip REMOTE_BASE prefix — only create what's underneath it
    if remote.startswith(REMOTE_BASE):
        rel = remote[len(REMOTE_BASE):].lstrip("/")
    else:
        rel = remote.lstrip("/")

    if not rel:
        return  # nothing to create

    parts = [p for p in rel.split("/") if p]
    cur = REMOTE_BASE
    for part in parts:
        cur = f"{cur}/{part}"
        try:
            ftp.mkd(cur)
        except ftplib.error_perm:
            pass  # already exists


def upload_file(ftp: ftplib.FTP | None, local: Path, remote: str, dry: bool) -> bool:
    if dry:
        print(f"    [DRY] {local.name}  →  {remote}")
        return True
    try:
        ftp_mkdirs(ftp, remote.rsplit("/", 1)[0])
        with open(local, "rb") as f:
            ftp.storbinary(f"STOR {remote}", f)
        print(f"    OK   {local.name}")
        return True
    except Exception as e:
        print(f"    ✗  {local.name}: {e}", file=sys.stderr)
        return False


def upload_dir(ftp: ftplib.FTP | None, local_dir: Path, remote_dir: str, dry: bool) -> tuple[int, int]:
    ok = fail = 0
    for item in sorted(local_dir.rglob("*")):
        if should_skip(item) or not item.is_file():
            continue
        rel    = item.relative_to(local_dir)
        remote = f"{remote_dir}/{str(rel).replace(chr(92), '/')}"
        if upload_file(ftp, item, remote, dry):
            ok += 1
        else:
            fail += 1
    return ok, fail


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy PSAKSH platform to cPanel via FTP")
    parser.add_argument("--dry-run", action="store_true", help="Preview without uploading")
    args = parser.parse_args()

    print("=" * 64)
    print("  PSAKSH Data Platform — cPanel FTP Deployment")
    print(f"  FTP host : {FTP_HOST}:{FTP_PORT}")
    print(f"  Remote   : {REMOTE_BASE}")
    print(f"  Dry run  : {args.dry_run}")
    print("=" * 64)

    ftp = None
    if not args.dry_run:
        print(f"\nConnecting to {FTP_HOST}:{FTP_PORT} ...")
        try:
            ftp = ftplib.FTP()
            ftp.connect(FTP_HOST, FTP_PORT, timeout=60)
            ftp.login(FTP_USER, FTP_PASSWORD)
            ftp.set_pasv(True)
            print(f"Connected as {FTP_USER}\n")
        except Exception as e:
            print(f"FTP connection failed: {e}", file=sys.stderr)
            sys.exit(1)

    total_ok = total_fail = 0

    for local, rel_remote in UPLOAD_MAP:
        remote = f"{REMOTE_BASE}/{rel_remote}"
        local  = Path(local)

        if not local.exists():
            print(f"\n  SKIP (not found locally): {local}")
            continue

        if local.is_dir():
            print(f"\n  DIR  {local.name}/  ->  {rel_remote}/")
            ok, fail = upload_dir(ftp, local, remote, args.dry_run)
            total_ok   += ok
            total_fail += fail
            print(f"       {ok} uploaded, {fail} failed")
        else:
            print(f"\n  FILE {local.name}  ->  {rel_remote}")
            if upload_file(ftp, local, remote, args.dry_run):
                total_ok += 1
            else:
                total_fail += 1

    if ftp:
        try:
            ftp.quit()
        except Exception:
            pass

    print("\n" + "=" * 64)
    print(f"  Done — {total_ok} files uploaded, {total_fail} failed")
    print("=" * 64)

    print("""
Next steps — run these in the cPanel Terminal:

  source /home/sattioe1/virtualenv/softcomputech.com/publichealth/3.11/bin/activate
  cd /home/sattioe1/softcomputech.com/publichealth

  # Install Python dependencies
  pip install --no-cache-dir -r requirements.txt

  # Generate synthetic data (first time only)
  python -m psaksh_data_platform.data_generator.run \\
      --households 500 --rounds 4 \\
      --output-dir psaksh_data_platform/data/raw --format csv

  # Run ETL pipeline
  python -m psaksh_data_platform.etl.pipeline.run \\
      --raw-dir psaksh_data_platform/data/raw \\
      --output-dir psaksh_data_platform/data

  # Then click RESTART in cPanel Python App
  # App URL: https://softcomputech.com/publichealth/
""")


if __name__ == "__main__":
    main()


