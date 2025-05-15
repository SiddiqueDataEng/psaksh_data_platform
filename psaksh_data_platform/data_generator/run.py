"""
PSAKSH -- Pakistan-wide Synthetic Data Generator CLI

Generates realistic public health survey data for all 4 provinces,
36 districts, 180 union councils across Pakistan.

Architecture:
  Historical data (2020-2022) = heterogeneous legacy formats
    data/raw/historical/
      2020_household_survey.csv       <- Paper surveys (bad dates, string yes/no)
      2020_child_nutrition.csv        <- Excel export (different column names)
      2021_household_survey.json      <- HMIS JSON (nested fields)
      2021_maternal_health.json       <- HMIS JSON
      2022_household_survey.parquet   <- Hadoop/Avro pipeline
      2022_facility_assessment.json   <- DHIS2 export (camelCase)
      legacy_enumerators.csv          <- Old HR system

  Current data (start_date to end_date) = clean DB exports as Parquet
    data/raw/current/
      households.parquet
      followup_visits.parquet
      facility_assessments.parquet
      enumerator_performance.parquet
      backcheck_records.parquet

Usage examples:
  # Basic — 500 households, default dates
  python -m psaksh_data_platform.data_generator.run --households 500

  # Custom date range
  python -m psaksh_data_platform.data_generator.run \\
      --start-date 2024-01-01 --end-date 2025-03-31 --households 1000

  # Random count between min and max
  python -m psaksh_data_platform.data_generator.run \\
      --min-records 200 --max-records 800 --start-date 2024-06-01

  # Reproducible with seed
  python -m psaksh_data_platform.data_generator.run \\
      --households 500 --seed 42 --inject-dq 1

  # No DQ injection (clean data)
  python -m psaksh_data_platform.data_generator.run \\
      --households 300 --inject-dq 0
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, date
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from psaksh_data_platform.data_generator.generators import (
    generate_backcheck_records,
    generate_enumerator_performance,
    generate_facility_assessments,
    generate_followup_visits,
    generate_households,
)
from psaksh_data_platform.data_generator.historical import generate_historical_data
from psaksh_data_platform.data_generator.config import STUDY_START_DATE, STUDY_END_DATE


def _validate_date(s: str) -> str:
    """Validate ISO date string YYYY-MM-DD."""
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date '{s}' — use YYYY-MM-DD format")


def _append_parquet(df, path: Path) -> None:
    """APPEND-ONLY: Add new rows to existing Parquet file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import pandas as pd
        df_clean = df.copy()
        for col in df_clean.select_dtypes(include="object").columns:
            df_clean[col] = df_clean[col].astype(str).replace("None", pd.NA).replace("nan", pd.NA)
        if path.exists():
            existing = pd.read_parquet(path)
            combined = pd.concat([existing, df_clean], ignore_index=True)
            combined.to_parquet(path, index=False, engine="pyarrow")
            logger.info(f"  Parquet {path.name}: appended {len(df):,} rows (total: {len(combined):,})")
        else:
            df_clean.to_parquet(path, index=False, engine="pyarrow")
            logger.info(f"  Parquet {path.name}: created {len(df):,} rows")
    except Exception as e:
        logger.warning(f"  Parquet failed ({e}) — appending to CSV")
        _append_csv(df, path.with_suffix(".csv"))


def _append_csv(df, path: Path) -> None:
    """APPEND-ONLY: Add new rows to existing CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    if path.exists():
        existing = pd.read_csv(path, low_memory=False)
        combined = pd.concat([existing, df], ignore_index=True)
        combined.to_csv(path, index=False)
        logger.info(f"  CSV {path.name}: appended {len(df):,} rows (total: {len(combined):,})")
    else:
        df.to_csv(path, index=False)
        logger.info(f"  CSV {path.name}: created {len(df):,} rows")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PSAKSH Pakistan-wide Synthetic Data Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m psaksh_data_platform.data_generator.run --households 500
  python -m psaksh_data_platform.data_generator.run --start-date 2024-01-01 --end-date 2025-03-31 --households 1000
  python -m psaksh_data_platform.data_generator.run --min-records 200 --max-records 800
  python -m psaksh_data_platform.data_generator.run --households 300 --seed 42 --inject-dq 0
        """,
    )

    # ── Record count (explicit or random range) ───────────────────────────
    count_group = parser.add_mutually_exclusive_group()
    count_group.add_argument(
        "--households", type=int, default=None,
        help="Exact number of households to generate (default: 500)",
    )
    count_group.add_argument(
        "--min-records", type=int, default=None,
        help="Minimum households when using random count (use with --max-records)",
    )
    parser.add_argument(
        "--max-records", type=int, default=None,
        help="Maximum households when using random count (use with --min-records)",
    )

    # ── Date range ────────────────────────────────────────────────────────
    parser.add_argument(
        "--start-date", type=_validate_date, default=None,
        metavar="YYYY-MM-DD",
        help=f"Earliest enrollment/visit date (default: {STUDY_START_DATE})",
    )
    parser.add_argument(
        "--end-date", type=_validate_date, default=None,
        metavar="YYYY-MM-DD",
        help=f"Latest enrollment/visit date (default: {STUDY_END_DATE})",
    )

    # ── Other options ─────────────────────────────────────────────────────
    parser.add_argument(
        "--rounds", type=int, default=4,
        help="Follow-up rounds per household (default: 4)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="RNG seed for reproducible output (default: random)",
    )
    parser.add_argument(
        "--inject-dq", type=str, default="1",
        choices=["0", "1"],
        help="Inject deliberate DQ issues: 1=on (default), 0=off (clean data)",
    )
    parser.add_argument(
        "--output-dir", type=str,
        default="psaksh_data_platform/data/raw",
        help="Root raw data directory (default: psaksh_data_platform/data/raw)",
    )
    parser.add_argument(
        "--skip-historical", action="store_true",
        help="Skip historical data generation (current era only)",
    )
    parser.add_argument(
        "--format", type=str, default="heterogeneous",
        help="Ignored — architecture determines formats (kept for compatibility)",
    )

    args = parser.parse_args()

    # ── Resolve count ─────────────────────────────────────────────────────
    import numpy as np
    rng = np.random.default_rng(args.seed)
    if args.households is not None:
        n_households = max(10, args.households)
    elif args.min_records is not None or args.max_records is not None:
        lo = max(10, args.min_records or 10)
        hi = max(lo, args.max_records or lo * 2)
        n_households = int(rng.integers(lo, hi + 1))
        logger.info(f"  Random count: {n_households:,} (between {lo:,} and {hi:,})")
    else:
        n_households = 500

    start_date = args.start_date or STUDY_START_DATE
    end_date   = args.end_date   or STUDY_END_DATE
    inject_dq  = args.inject_dq != "0"
    raw_dir    = Path(args.output_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 65)
    logger.info("  PSAKSH Pakistan-wide Synthetic Data Generator")
    logger.info(f"  Households    : {n_households:,}")
    logger.info(f"  Date range    : {start_date}  to  {end_date}")
    logger.info(f"  Rounds        : {args.rounds}")
    logger.info(f"  Seed          : {args.seed or 'random'}")
    logger.info(f"  DQ injection  : {'ON' if inject_dq else 'OFF'}")
    logger.info(f"  Output        : {raw_dir.resolve()}")
    logger.info(f"  Coverage      : 4 provinces, 36 districts, 180 UCs")
    logger.info("=" * 65)

    t0 = time.time()

    # ── HISTORICAL (2020-2022): Heterogeneous legacy formats ──────────────
    if not args.skip_historical:
        logger.info("\n[HISTORICAL] Generating 2020-2022 legacy heterogeneous data...")
        logger.info("  2020: CSV (paper surveys digitised)")
        logger.info("  2021: JSON (HMIS system export)")
        logger.info("  2022: Parquet (Hadoop/Avro pipeline)")
        hist = generate_historical_data(raw_dir / "historical")
        for name, count in hist.items():
            logger.info(f"  {name}: {count:,} rows")
    else:
        logger.info("\n[HISTORICAL] Skipped (--skip-historical)")

    # ── CURRENT: Clean DB exports as Parquet ──────────────────────────────
    logger.info(f"\n[CURRENT] Generating {n_households:,} households ({start_date} to {end_date})...")
    current_dir = raw_dir / "current"
    current_dir.mkdir(parents=True, exist_ok=True)

    logger.info("\n[1/5] Households -> Parquet  (MySQL survey_submissions export)...")
    households = generate_households(
        n_households,
        start_date=start_date,
        end_date=end_date,
        seed=args.seed,
    )
    _append_parquet(households, current_dir / "households.parquet")
    dup_count = int(households.duplicated("household_id", keep=False).sum())
    logger.info(f"      {len(households):,} rows  ({dup_count:,} deliberate duplicates)")

    logger.info("\n[2/5] Follow-up visits -> Parquet  (MySQL followup_visits export)...")
    visits = generate_followup_visits(
        households,
        rounds=args.rounds,
        start_date=start_date,
        end_date=end_date,
        seed=args.seed,
    )
    _append_parquet(visits, current_dir / "followup_visits.parquet")
    child_n    = int((visits["record_type"] == "child").sum())
    maternal_n = int((visits["record_type"] == "maternal").sum())
    logger.info(f"      {len(visits):,} rows  ({child_n:,} child, {maternal_n:,} maternal)")

    logger.info("\n[3/5] Facility assessments -> Parquet  (MySQL facility_assessments export)...")
    facilities = generate_facility_assessments(
        rounds=args.rounds,
        start_date=start_date,
        end_date=end_date,
        seed=args.seed,
    )
    _append_parquet(facilities, current_dir / "facility_assessments.parquet")
    logger.info(f"      {len(facilities):,} rows")

    logger.info("\n[4/5] Enumerator performance -> Parquet  (MySQL enumerator_logs export)...")
    perf = generate_enumerator_performance(
        visits,
        start_date=start_date,
        end_date=end_date,
        seed=args.seed,
    )
    _append_parquet(perf, current_dir / "enumerator_performance.parquet")
    logger.info(f"      {len(perf):,} rows")

    logger.info("\n[5/5] Back-check records -> Parquet  (MySQL backcheck_records export)...")
    backcheck = generate_backcheck_records(visits, seed=args.seed)
    _append_parquet(backcheck, current_dir / "backcheck_records.parquet")
    logger.info(f"      {len(backcheck):,} rows")

    elapsed = time.time() - t0

    logger.info("\n" + "=" * 65)
    logger.info("  Generation complete")
    logger.info(f"  Elapsed           : {elapsed:.1f}s")
    logger.info(f"  Date range        : {start_date}  to  {end_date}")
    logger.info(f"  Households        : {len(households):,}  ({dup_count:,} deliberate duplicates)")
    logger.info(f"  Visits            : {len(visits):,}  ({child_n:,} child, {maternal_n:,} maternal)")
    logger.info(f"  Facilities        : {len(facilities):,}")
    logger.info(f"  Enumerator logs   : {len(perf):,}")
    logger.info(f"  Back-checks       : {len(backcheck):,}")
    logger.info(f"  Output            : {raw_dir.resolve()}")
    logger.info("=" * 65)
    logger.info("  Next step: run ETL pipeline")
    logger.info("  python -m psaksh_data_platform.etl.pipeline.run")
    logger.info("=" * 65)


if __name__ == "__main__":
    main()
