"""
PSAKSH -- ETL Pipeline Orchestrator (Medallion Architecture)
Bronze -> Silver -> Gold

This module is designed to work in two modes:
  1. As a subprocess: python -m psaksh_data_platform.etl.pipeline.run
  2. As an in-process import: from etl.pipeline.run import run_pipeline

Path resolution is robust -- works on both Linux cPanel and Windows WAMP.

Usage:
    python -m psaksh_data_platform.etl.pipeline.run
    python -m psaksh_data_platform.etl.pipeline.run --raw-dir /path/to/raw
    python -m psaksh_data_platform.etl.pipeline.run --env production
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Robust path bootstrap ─────────────────────────────────────────────────────
# This file lives at: <app_root>/psaksh_data_platform/etl/pipeline/run.py
# We need <app_root> on sys.path so both import styles work:
#   from psaksh_data_platform.etl.medallion import ...   (subprocess mode)
#   from etl.medallion import ...                       (in-process mode)

_THIS_FILE   = Path(__file__).resolve()
_PKG_DIR     = _THIS_FILE.parents[2]   # psaksh_data_platform/
_APP_ROOT    = _THIS_FILE.parents[3]   # publichealth/  (contains psaksh_data_platform/)

for _p in [str(_APP_ROOT), str(_PKG_DIR.parent)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _import_medallion():
    """Import run_medallion trying multiple import paths."""
    # Try package-qualified import first (subprocess mode)
    try:
        from psaksh_data_platform.etl.medallion import run_medallion
        return run_medallion
    except ImportError:
        pass
    # Try relative-style import (in-process mode)
    try:
        from etl.medallion import run_medallion
        return run_medallion
    except ImportError:
        pass
    # Last resort: direct file import
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "medallion", _PKG_DIR / "etl" / "medallion.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.run_medallion


def _import_settings():
    """Import get_settings trying multiple import paths."""
    try:
        from psaksh_data_platform.config.settings import get_settings
        return get_settings
    except ImportError:
        pass
    try:
        from config.settings import get_settings
        return get_settings
    except ImportError:
        pass
    return None


def run_pipeline(data_base: str | Path | None = None) -> dict:
    """
    Run the full Bronze -> Silver -> Gold pipeline.
    Returns the result dict from run_medallion.
    """
    start = datetime.now(timezone.utc)

    # Resolve data directory
    if data_base is None:
        data_base = _PKG_DIR / "data"
    data_base = Path(data_base)
    data_base.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 65)
    logger.info("  PSAKSH Medallion ETL Pipeline")
    logger.info(f"  Data base : {data_base}")
    logger.info(f"  Started   : {start.isoformat()}")
    logger.info("=" * 65)

    # Run medallion
    run_medallion = _import_medallion()
    result = run_medallion(data_base)
    gold   = result.get("gold", {})

    # Optional: load Gold tables to MySQL/SQLite warehouse
    try:
        get_settings = _import_settings()
        if get_settings:
            settings = get_settings()
            try:
                from psaksh_data_platform.etl.load import get_engine, load_to_db
            except ImportError:
                from etl.load import get_engine, load_to_db

            engine = get_engine(use_sqlite=getattr(settings, "is_local", True))
            table_map = {
                "fct_child_nutrition":  "fct_child_nutrition",
                "fct_maternal_health":  "fct_maternal_health",
                "rpt_district_summary": "rpt_district_summary",
                "rpt_pipeline_status":  "rpt_pipeline_status",
            }
            for gold_name, table_name in table_map.items():
                if gold_name in gold and not gold[gold_name].empty:
                    df = gold[gold_name].drop(columns=["_layer"], errors="ignore")
                    load_to_db(df, table_name, engine, if_exists="replace")
            logger.info("  Warehouse load complete")
    except Exception as e:
        logger.warning(f"  Warehouse load skipped: {e}")
        logger.info("  (Gold files saved to disk -- dashboards will use file fallback)")

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info("=" * 65)
    logger.info(f"  Pipeline complete in {elapsed:.1f}s")
    logger.info(f"  Gold datasets: {list(gold.keys())}")
    logger.info("=" * 65)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="PSAKSH Medallion ETL Pipeline")
    parser.add_argument("--env", default="local",
                        choices=["local", "staging", "production"])
    parser.add_argument("--raw-dir",    default=None,
                        help="Raw data directory (default: <pkg>/data/raw)")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory (legacy compat -- parent used as data_base)")
    args = parser.parse_args()

    os.environ["ENV"] = args.env

    # Invalidate settings cache if available
    get_settings = _import_settings()
    if get_settings and hasattr(get_settings, "cache_clear"):
        get_settings.cache_clear()

    # Determine data_base
    # --raw-dir  points to  <data_base>/raw   → parent is data_base  ✓
    # --output-dir points to <data_base>       → use directly         ✓
    # (old callers passed --output-dir <data_base>/data which was wrong;
    #  we now accept both and normalise)
    if args.raw_dir:
        raw = Path(args.raw_dir).resolve()
        # raw should end in "raw" — its parent is data_base
        data_base = raw.parent if raw.name == "raw" else raw
    elif args.output_dir:
        out = Path(args.output_dir).resolve()
        # If caller passed .../psaksh_data_platform/data  → use as-is
        # If caller passed .../psaksh_data_platform       → append "data"
        if (out / "raw").exists() or out.name == "data":
            data_base = out
        else:
            data_base = out / "data"
    else:
        data_base = None

    run_pipeline(data_base)


if __name__ == "__main__":
    main()


