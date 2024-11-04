#!/bin/bash
# PSAKSH Data Platform -- Complete Server Setup
# Run from ANYWHERE:
#   bash /home/sattioe1/softcomputech.com/publichealth/setup.sh

VENV="/home/sattioe1/virtualenv/softcomputech.com/publichealth/3.11"
APP="/home/sattioe1/softcomputech.com/publichealth"
PKG="$APP/psaksh_data_platform"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

echo "============================================================"
echo "  PSAKSH Data Platform -- Server Setup"
echo "  App : $APP"
echo "  Venv: $VENV"
echo "============================================================"
echo ""

# Always cd to app root
cd "$APP" || { echo "ERROR: Cannot cd to $APP"; exit 1; }
source "$VENV/bin/activate" 2>/dev/null || true
export PYTHONPATH="$APP"
export PYTHONHOME="$VENV"

echo "[1/5] Removing broken packages..."
for broken in "~andas" "~ydantic_core" "~umpy" "~yarrow" "~lask"; do
    rm -rf "$VENV/lib64/python3.11/site-packages/$broken" "$VENV/lib/python3.11/site-packages/$broken" 2>/dev/null || true
done
$PIP uninstall -y pandas pydantic pydantic-core pydantic-settings numpy pyarrow 2>/dev/null || true
echo "  Done."

echo ""
echo "[2/5] Upgrading pip..."
$PIP install --quiet --upgrade pip
echo "  Done."

echo ""
echo "[3/5] Installing packages..."
$PIP install --no-cache-dir -r "$APP/requirements.txt"
echo "  Done."

echo ""
echo "[4/5] Generating data..."
mkdir -p "$PKG/data/raw/historical" "$PKG/data/raw/current" "$PKG/data/bronze" "$PKG/data/silver" "$PKG/data/gold" "$PKG/data/delta_log"
"$PY" -m psaksh_data_platform.data_generator.run --households 2000 --rounds 4 --output-dir "$PKG/data/raw" --inject-dq 1
echo "  Done."

echo ""
echo "[5/5] Running ETL pipeline..."
"$PY" -m psaksh_data_platform.etl.pipeline.run --raw-dir "$PKG/data/raw" --output-dir "$PKG/data"
echo "  Done."

echo ""
echo "============================================================"
echo "  DONE! Click RESTART in cPanel Python App."
echo "  https://softcomputech.com/publichealth/"
echo "============================================================"
