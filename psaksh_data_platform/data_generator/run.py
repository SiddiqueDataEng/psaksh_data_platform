"""
PSAKSH -- Pakistan-wide Synthetic Data Generator CLI

CORRECT ARCHITECTURE:
  Historical data (2020-2022) = heterogeneous legacy formats
    data/raw/historical/
      2020_household_survey.csv       <- Paper surveys digitised (bad dates, string yes/no)
      2020_child_nutrition.csv        <- Excel export (different column names, cm not mm)
      2021_household_survey.json      <- HMIS JSON (nested fields, dot-notation columns)
      2021_maternal_health.json       <- HMIS JSON (different column names)
      2022_household_survey.parquet   <- Hadoop/Avro pipeline (closer to current schema)
      2022_facility_assessment.json   <- DHIS2 export (camelCase fields)
      legacy_enumerators.csv          <- Old HR system (ENUM001 not E001)

  Current data (2022-2024+) = clean DB exports as Parquet
    data/raw/current/
      households.parquet              <- MySQL DB export (survey forms -> DB -> Parquet)
      followup_visits.parquet         <- MySQL DB export
      facility_assessments.parquet    <- MySQL DB export
      enumerator_performance.parquet  <- MySQL DB export
      backcheck_records.parquet       <- MySQL DB export

The Medallion ETL unifies both into Bronze -> Silver -> Gold.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
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


def _append_parquet(df, path: Path) -> None:
    """
    APPEND-ONLY: Add new rows to existing Parquet file.
    Never replaces existing data — new data is always appended.
    This is the correct data engineering pattern for raw sources.
    """
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
        logger.warning(f"  Parquet failed ({e}) -- appending to CSV")
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


def _append_json(df, path: Path) -> None:
    """APPEND-ONLY: Add new records to existing JSON Lines file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if path.exists() else "w"
    df.to_json(path, orient="records", lines=True, mode=mode,
               date_format="iso", force_ascii=False)
    action = "appended" if mode == "a" else "created"
    logger.info(f"  JSON {path.name}: {action} {len(df):,} rows")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PSAKSH Pakistan-wide Synthetic Data Generator"
    )
    parser.add_argument("--households", type=int, default=5000,
                        help="Current-era households to generate (default: 5000)")
    parser.add_argument("--rounds",     type=int, default=4,
                        help="Follow-up rounds per household (default: 4)")
    parser.add_argument("--output-dir", type=str,
                        default="psaksh_data_platform/data/raw",
                        help="Root raw data directory")
    parser.add_argument("--inject-dq",  type=str, default="1",
                        help="Inject DQ issues in current data (1=on, 0=off)")
    parser.add_argument("--format", type=str, default="heterogeneous",
                        help="Ignored -- architecture determines formats")
    args = parser.parse_args()

    raw_dir   = Path(args.output_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    inject_dq = args.inject_dq != "0"

    logger.info("=" * 65)
    logger.info("  PSAKSH Pakistan-wide Synthetic Data Generator")
    logger.info(f"  Architecture  : Historical=heterogeneous, Current=DB Parquet")
    logger.info(f"  Households    : {args.households:,} (current era)")
    logger.info(f"  Rounds        : {args.rounds}")
    logger.info(f"  Output        : {raw_dir}")
    logger.info(f"  DQ Issues     : {'ON' if inject_dq else 'OFF'} (current data)")
    logger.info(f"  Coverage      : 4 provinces, 36 districts, 180 UCs")
    logger.info("=" * 65)

    t0 = time.time()

    # ── HISTORICAL (2020-2022): Heterogeneous legacy formats ──────────────
    logger.info("\n[HISTORICAL] Generating 2020-2022 legacy heterogeneous data...")
    logger.info("  2020: CSV (paper surveys digitised)")
    logger.info("  2021: JSON (HMIS system export)")
    logger.info("  2022: Parquet (Hadoop/Avro pipeline)")
    hist = generate_historical_data(raw_dir / "historical")
    for name, count in hist.items():
        logger.info(f"  {name}: {count:,} rows")

    # ── CURRENT (2022-2024+): Clean DB exports as Parquet ─────────────────
    logger.info("\n[CURRENT] Generating 2022-2024 data (simulates MySQL DB exports)...")
    current_dir = raw_dir / "current"
    current_dir.mkdir(parents=True, exist_ok=True)

    logger.info("\n[1/5] Households -> Parquet  (MySQL survey_submissions table export)...")
    households = generate_households(args.households)
    _append_parquet(households, current_dir / "households.parquet")
    dup_count = int(households.duplicated("household_id", keep=False).sum())
    logger.info(f"      {len(households):,} rows  ({dup_count:,} deliberate duplicates)")

    logger.info("\n[2/5] Follow-up visits -> Parquet  (MySQL followup_visits table export)...")
    visits = generate_followup_visits(households, rounds=args.rounds)
    _append_parquet(visits, current_dir / "followup_visits.parquet")
    child_n    = int((visits["record_type"] == "child").sum())
    maternal_n = int((visits["record_type"] == "maternal").sum())
    logger.info(f"      {len(visits):,} rows  ({child_n:,} child, {maternal_n:,} maternal)")

    logger.info("\n[3/5] Facility assessments -> Parquet  (MySQL facility_assessments export)...")
    facilities = generate_facility_assessments(rounds=args.rounds)
    _append_parquet(facilities, current_dir / "facility_assessments.parquet")
    logger.info(f"      {len(facilities):,} rows")

    logger.info("\n[4/5] Enumerator performance -> Parquet  (MySQL enumerator_logs export)...")
    perf = generate_enumerator_performance(visits)
    _append_parquet(perf, current_dir / "enumerator_performance.parquet")
    logger.info(f"      {len(perf):,} rows")

    logger.info("\n[5/5] Back-check records -> Parquet  (MySQL backcheck_records export)...")
    backcheck = generate_backcheck_records(visits)
    _append_parquet(backcheck, current_dir / "backcheck_records.parquet")
    logger.info(f"      {len(backcheck):,} rows")

    elapsed = time.time() - t0

    dq_urdu = 0
    for col in ["water_source", "ses_tier"]:
        if col in households.columns:
            dq_urdu += int(
                households[col].astype(str).str.contains(
                    "\u067e\u0627\u0626\u067e|\u06c1\u06cc\u0646\u0688"
                    "|\u06a9\u0646\u0648\u0627\u06ba|\u06a9\u0645"
                    "|\u062f\u0631\u0645\u06cc\u0627\u0646\u06c1"
                    "|\u0632\u06cc\u0627\u062f\u06c1",
                    na=False,
                ).sum()
            )
    short_flag = int(visits["short_interview_flag"].sum()
                     if "short_interview_flag" in visits.columns else 0)

    logger.info("\n" + "=" * 65)
    logger.info("  Generation complete")
    logger.info(f"  Time elapsed              : {elapsed:.1f}s")
    logger.info(f"  --- Historical (heterogeneous legacy formats) ---")
    for name, count in hist.items():
        logger.info(f"  {name:<35}: {count:,} rows")
    logger.info(f"  --- Current (MySQL DB exports as Parquet) ---")
    logger.info(f"  households.parquet        : {len(households):,} rows")
    logger.info(f"  followup_visits.parquet   : {len(visits):,} rows")
    logger.info(f"  facility_assessments.parquet: {len(facilities):,} rows")
    logger.info(f"  enumerator_performance.parquet: {len(perf):,} rows")
    logger.info(f"  backcheck_records.parquet : {len(backcheck):,} rows")
    logger.info(f"  --- DQ Issues in current data ---")
    logger.info(f"  Duplicate HH subs         : {dup_count:,}")
    logger.info(f"  Bilingual fields           : ~{dq_urdu:,}")
    logger.info(f"  Short interviews           : {short_flag:,}")
    logger.info("=" * 65)


if __name__ == "__main__":
    main()



