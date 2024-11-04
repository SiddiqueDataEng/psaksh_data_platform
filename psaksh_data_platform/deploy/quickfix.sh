#!/bin/bash
# PSAKSH Quick Fix -- regenerate data and run ETL only
# Run from ANYWHERE:
#   bash /home/sattioe1/softcomputech.com/publichealth/quickfix.sh

VENV="/home/sattioe1/virtualenv/softcomputech.com/publichealth/3.11"
APP="/home/sattioe1/softcomputech.com/publichealth"
PKG="$APP/psaksh_data_platform"
PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

echo "============================================================"
echo "  PSAKSH Quick Fix -- Data + ETL"
echo "  App : $APP"
echo "  Venv: $VENV"
echo "============================================================"

# Always cd to app root so relative imports work
cd "$APP" || { echo "ERROR: Cannot cd to $APP"; exit 1; }
source "$VENV/bin/activate" 2>/dev/null || true
export PYTHONPATH="$APP"
export PYTHONHOME="$VENV"

mkdir -p "$PKG/data/raw/historical" "$PKG/data/raw/current" \
         "$PKG/data/bronze" "$PKG/data/silver" \
         "$PKG/data/gold"   "$PKG/data/delta_log"

echo ""
echo "[1/2] Generating 2000 households..."
"$PY" -m psaksh_data_platform.data_generator.run \
    --households 2000 --rounds 4 \
    --output-dir "$PKG/data/raw" \
    --inject-dq 1

echo ""
echo "[2/2] Running Medallion ETL..."
"$PY" -m psaksh_data_platform.etl.pipeline.run \
    --raw-dir "$PKG/data/raw" \
    --output-dir "$PKG/data"

echo ""
ls -lh "$PKG/data/gold/" 2>/dev/null || echo "(gold dir not found)"

echo ""
echo "============================================================"
echo "  Done! Click RESTART in cPanel Python App."
echo "  https://softcomputech.com/publichealth/"
echo "============================================================"
