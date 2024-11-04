"""Install flask and verify all packages. Run after reinstall.py."""
import subprocess
import sys

PIP = "/home/sattioe1/virtualenv/softcomputech.com/publichealth/3.11/bin/pip"

print("Installing flask...")
r = subprocess.run(
    [PIP, "install", "--no-cache-dir",
     "flask", "werkzeug", "jinja2", "itsdangerous", "click", "blinker"],
    capture_output=True, text=True,
)
print(r.stdout[-1000:] if r.stdout else "")
print(r.stderr[-500:]  if r.stderr else "")
print("exit:", r.returncode)

print()
print("Verifying all imports...")
checks = {
    "flask":             "flask",
    "pandas":            "pandas",
    "numpy":             "numpy",
    "plotly":            "plotly",
    "pyarrow":           "pyarrow",
    "sqlalchemy":        "sqlalchemy",
    "pymysql":           "pymysql",
    "loguru":            "loguru",
    "pydantic":          "pydantic",
    "pydantic_settings": "pydantic_settings",
    "scipy":             "scipy",
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
if failed:
    print("Still failing:", failed)
else:
    print("ALL PACKAGES OK!")
    print("Go to cPanel Python App and click RESTART.")
    print("App: https://softcomputech.com/publichealth/")
