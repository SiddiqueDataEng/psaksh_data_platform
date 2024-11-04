"""
psaksh — Clean reinstall of all Python packages.
Run via cPanel Python App > Execute python script > reinstall.py

This script:
1. Wipes all user-installed packages from the venv site-packages
2. Reinstalls everything cleanly with --no-cache-dir
3. Verifies all imports work
4. Prints a summary
"""

import subprocess
import sys
import shutil
from pathlib import Path

VENV      = Path("/home/sattioe1/virtualenv/softcomputech.com/publichealth/3.11")
PIP       = str(VENV / "bin" / "pip")
SITE64    = VENV / "lib64" / "python3.11" / "site-packages"
SITE      = VENV / "lib"   / "python3.11" / "site-packages"

# Packages to keep (pip internals — never delete these)
KEEP = {
    "pip", "setuptools", "wheel", "pkg_resources",
    "pip-*", "setuptools-*", "wheel-*",
    "_distutils_hack", "distutils-precedence.pth",
    "easy_install.py", "__pycache__",
}

PACKAGES = [
    "flask",
    "pandas",
    "numpy",
    "plotly",
    "pyarrow",
    "sqlalchemy",
    "pymysql",
    "loguru",
    "pydantic",
    "pydantic-settings",
    "faker",
    "requests",
    "scipy",
]

print("=" * 60)
print("psaksh Clean Package Reinstall")
print(f"Python: {sys.version}")
print(f"VENV:   {VENV}")
print("=" * 60)


def run(cmd, label=""):
    print(f"\n>>> {label or ' '.join(cmd[:3])}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.strip()[-1000:])
    if r.stderr.strip():
        # Filter out noise
        for line in r.stderr.strip().splitlines():
            if "WARNING" not in line or "invalid distribution" in line:
                print("  " + line)
    return r.returncode == 0


# ── Step 1: Wipe broken packages ─────────────────────────────────────────────
print("\n[1/4] Removing all installed packages...")

# Get list of installed packages (excluding pip/setuptools)
r = subprocess.run([PIP, "list", "--format=freeze"], capture_output=True, text=True)
installed = []
for line in r.stdout.splitlines():
    pkg = line.split("==")[0].strip()
    if pkg.lower() not in {"pip", "setuptools", "wheel"}:
        installed.append(pkg)

print(f"  Found {len(installed)} packages to remove: {installed}")

if installed:
    run([PIP, "uninstall", "-y"] + installed, "pip uninstall all")

# Also manually remove any broken ~xxx folders
for site in [SITE64, SITE]:
    if not site.exists():
        continue
    for item in site.iterdir():
        name = item.name.lower()
        if name.startswith("~"):
            print(f"  Removing broken: {item}")
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except Exception as e:
                print(f"  Could not remove {item}: {e}")

print("  Done.")


# ── Step 2: Upgrade pip ───────────────────────────────────────────────────────
print("\n[2/4] Upgrading pip...")
run([PIP, "install", "--upgrade", "pip"], "pip upgrade")


# ── Step 3: Install packages cleanly ─────────────────────────────────────────
print("\n[3/4] Installing packages (--no-cache-dir)...")
ok = run(
    [PIP, "install", "--no-cache-dir"] + PACKAGES,
    "pip install all"
)
if not ok:
    print("  Batch install failed, trying one by one...")
    for pkg in PACKAGES:
        run([PIP, "install", "--no-cache-dir", pkg], f"pip install {pkg}")


# ── Step 4: Verify ────────────────────────────────────────────────────────────
print("\n[4/4] Verifying imports...")
checks = {
    "flask":            "flask",
    "pandas":           "pandas",
    "numpy":            "numpy",
    "plotly":           "plotly",
    "pyarrow":          "pyarrow",
    "sqlalchemy":       "sqlalchemy",
    "pymysql":          "pymysql",
    "loguru":           "loguru",
    "pydantic":         "pydantic",
    "pydantic_settings":"pydantic_settings",
    "faker":            "faker",
    "scipy":            "scipy",
}

failed = []
for label, mod in checks.items():
    try:
        m   = __import__(mod)
        ver = getattr(m, "__version__", "ok")
        print(f"  OK   {label}: {ver}")
    except Exception as e:
        print(f"  FAIL {label}: {e}")
        failed.append(label)

print()
print("=" * 60)
if failed:
    print(f"FAILED packages: {failed}")
    print("Please check the output above for errors.")
else:
    print("All packages installed and verified OK!")
    print()
    print("Go to cPanel Python App and click RESTART.")
    print("App: https://softcomputech.com/publichealth/")
print("=" * 60)
