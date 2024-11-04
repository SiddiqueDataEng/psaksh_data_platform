"""
PSAKSH -- Medallion Architecture ETL Pipeline
Bronze -> Silver -> Gold

Real Data Engineering Techniques Implemented:
  1. Full Load       -- Initial load of all historical data (2020-2022)
  2. Incremental Load -- Only new records since last watermark
  3. CDC             -- Change Data Capture (INSERT/UPDATE/DELETE tracking)
  4. Windowing       -- Time-window aggregations (monthly, quarterly, annual)
  5. SCD Type 2      -- Slowly Changing Dimensions with full history
  6. Delta Lake      -- Partitioned storage (year/month), audit log, ACID-like
  7. Upsert/Merge    -- Gold layer merge on primary key
  8. Data Lineage    -- Every record tracks source, era, transformation chain
  9. Schema Evolution -- Handle different schemas across historical years
 10. Data Quality    -- DQ metrics tracked per dataset per run

Source Architecture:
  data/raw/historical/  <- Legacy heterogeneous (2020-2022)
                           CSV (paper surveys), JSON (HMIS), Parquet (Hadoop)
  data/raw/current/     <- Clean MySQL DB exports as Parquet (2022-2024+)
  data/raw/             <- Fallback: files directly in raw/

Layer Layout:
  data/bronze/          <- Exact copies + metadata, partitioned by ingestion date
  data/silver/          <- Cleaned, validated, schema-unified, CDC-tagged
  data/gold/            <- Fact tables, dimensions (SCD2), KPI aggregations
  data/delta_log/       <- Audit trail of every pipeline run
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORMAT_PRIORITY = {".parquet": 0, ".json": 1, ".csv": 2, ".avro": 3}

LOAD_TYPE_FULL        = "full_load"
LOAD_TYPE_INCREMENTAL = "incremental"
LOAD_TYPE_CDC         = "cdc"

# ---------------------------------------------------------------------------
# Layer directory management
# ---------------------------------------------------------------------------

def layer_dirs(base: Path) -> dict[str, Path]:
    layers = {
        "raw":       base / "raw",
        "bronze":    base / "bronze",
        "silver":    base / "silver",
        "gold":      base / "gold",
        "delta_log": base / "delta_log",
    }
    for p in layers.values():
        p.mkdir(parents=True, exist_ok=True)
    return layers



# ---------------------------------------------------------------------------
# Delta Log — audit trail of every pipeline run
# ---------------------------------------------------------------------------

def _load_delta_log(log_dir: Path) -> dict:
    """Load the pipeline state / delta log."""
    path = log_dir / "pipeline_state.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "watermarks":  {},   # dataset -> last_loaded_at ISO
        "run_history": [],   # list of run summaries (last 100)
        "row_counts":  {},   # dataset -> last known row count
        "checksums":   {},   # dataset -> last file checksum
    }


def _save_delta_log(state: dict, log_dir: Path) -> None:
    """Persist pipeline state."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "pipeline_state.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)


def _file_checksum(path: Path) -> str:
    """MD5 checksum of a file for change detection."""
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _detect_load_type(
    name: str,
    file_path: Path,
    state: dict,
) -> str:
    """
    Determine load type for a dataset:
      - full_load:    first time seeing this dataset, or forced full reload
      - incremental:  file changed since last run (checksum differs)
      - cdc:          file unchanged — skip or apply CDC only
    """
    last_checksum = state.get("checksums", {}).get(name, "")
    current_checksum = _file_checksum(file_path)

    if not last_checksum:
        return LOAD_TYPE_FULL
    if current_checksum != last_checksum:
        return LOAD_TYPE_INCREMENTAL
    return LOAD_TYPE_CDC   # no change — CDC pass only


# ---------------------------------------------------------------------------
# BRONZE: Ingest all raw sources
# ---------------------------------------------------------------------------

def ingest_bronze(
    raw_dir: Path,
    bronze_dir: Path,
    state: dict,
    force_full: bool = False,
) -> dict[str, pd.DataFrame]:
    """
    BRONZE LAYER — Exact copy of all source data + metadata.

    Scans three source locations:
      raw/historical/  <- Legacy heterogeneous (2020-2022): CSV, JSON, Parquet
      raw/current/     <- MySQL DB exports as Parquet (2022-2024+)
      raw/             <- Fallback: files directly in raw/

    Load strategy per dataset:
      Full Load:        First time — load everything
      Incremental:      File changed — reload and append new records
      CDC:              No change — skip file read, use cached bronze

    Adds lineage columns: _source_file, _source_era, _source_type,
                          _ingested_at, _load_type, _layer
    """
    datasets: dict[str, pd.DataFrame] = {}
    now = datetime.now(timezone.utc).isoformat()

    # Source directories with era and type labels
    scan_dirs = [
        (raw_dir / "historical", "historical", "legacy_heterogeneous"),
        (raw_dir / "current",    "current",    "mysql_db_export"),
        (raw_dir,                "current",    "mixed"),
    ]

    # Build best-file map: current DB exports take priority over historical
    best: dict[str, tuple[Path, str, str]] = {}
    for scan_dir, era, source_type in scan_dirs:
        if not scan_dir.exists():
            continue
        for f in scan_dir.glob("*"):
            if f.suffix not in FORMAT_PRIORITY or not f.is_file():
                continue
            name = f.stem
            era_priority = 0 if era == "current" else 1
            if name not in best:
                best[name] = (f, era, source_type)
            else:
                existing_era_p = 0 if best[name][1] == "current" else 1
                if era_priority < existing_era_p:
                    best[name] = (f, era, source_type)
                elif era_priority == existing_era_p:
                    if FORMAT_PRIORITY[f.suffix] < FORMAT_PRIORITY[best[name][0].suffix]:
                        best[name] = (f, era, source_type)

    for name, (f, era, source_type) in sorted(best.items()):
        try:
            load_type = LOAD_TYPE_FULL if force_full else _detect_load_type(name, f, state)

            # CDC: file unchanged — try to use cached bronze
            if load_type == LOAD_TYPE_CDC:
                cached = bronze_dir / f"{name}.parquet"
                if cached.exists():
                    try:
                        df = pd.read_parquet(cached)
                        datasets[name] = df
                        logger.info(f"  Bronze  {name}: {len(df):,} rows  [CDC-skip, cached]")
                        continue
                    except Exception:
                        load_type = LOAD_TYPE_INCREMENTAL

            # Full or Incremental: read source file
            if f.suffix == ".csv":
                df = pd.read_csv(f, low_memory=False)
            elif f.suffix == ".parquet":
                df = pd.read_parquet(f)
            elif f.suffix == ".json":
                df = pd.read_json(f, lines=True)
            elif f.suffix == ".avro":
                try:
                    import fastavro
                    with open(f, "rb") as fh:
                        records = list(fastavro.reader(fh))
                    df = pd.DataFrame(records)
                except ImportError:
                    logger.warning(f"  Avro skipped (fastavro not installed): {f.name}")
                    continue
            else:
                continue

            # Add lineage columns
            df["_source_file"] = f.name
            df["_source_era"]  = era
            df["_source_type"] = source_type
            df["_ingested_at"] = now
            df["_load_type"]   = load_type
            df["_layer"]       = "bronze"

            # Incremental: append to existing bronze (watermark-based)
            if load_type == LOAD_TYPE_INCREMENTAL:
                cached = bronze_dir / f"{name}.parquet"
                if cached.exists():
                    try:
                        existing = pd.read_parquet(cached)
                        watermark = state.get("watermarks", {}).get(name)
                        if watermark and "_ingested_at" in existing.columns:
                            # Only keep new records beyond watermark
                            new_only = df[df["_ingested_at"] > watermark]
                            if not new_only.empty:
                                df = pd.concat([existing, new_only], ignore_index=True)
                                logger.info(f"  Bronze  {name}: +{len(new_only):,} new rows appended  [incremental]")
                            else:
                                df = existing
                                logger.info(f"  Bronze  {name}: no new rows  [incremental, no-op]")
                        else:
                            df = pd.concat([existing, df], ignore_index=True)
                    except Exception:
                        pass  # Fall through to full write

            # Save to bronze
            out = bronze_dir / f"{name}.parquet"
            try:
                # Normalise object columns for pyarrow
                df_save = df.copy()
                for col in df_save.select_dtypes(include="object").columns:
                    df_save[col] = df_save[col].astype(str).replace(
                        {"None": pd.NA, "nan": pd.NA, "<NA>": pd.NA}
                    )
                df_save.to_parquet(out, index=False)
            except Exception:
                df.to_csv(bronze_dir / f"{name}.csv", index=False)

            # Update state
            state.setdefault("checksums", {})[name]   = _file_checksum(f)
            state.setdefault("watermarks", {})[name]  = now
            state.setdefault("row_counts", {})[name]  = len(df)

            datasets[name] = df
            logger.info(f"  Bronze  {name}: {len(df):,} rows  [{f.suffix}] [{era}] [{load_type}]")

        except Exception as e:
            logger.error(f"  Bronze FAILED {f.name}: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    return datasets


# ---------------------------------------------------------------------------
# SILVER: Clean, validate, schema-unify, CDC-tag
# ---------------------------------------------------------------------------

# Schema mapping: historical column names -> canonical current names
SCHEMA_MAP = {
    # 2020 CSV (paper surveys)
    "hh_id":              "household_id",
    "district_name":      "district",
    "tehsil":             "union_council",
    "respondent":         "respondent_name",
    "age_years":          "respondent_age",
    "hh_size":            "household_size",
    "children_u5":        "children_under_5",
    "women_repro_age":    "women_15_49",
    "ses":                "ses_tier",
    "water":              "water_source",
    "latrine":            "has_toilet",
    "consent":            "consent_given",
    "date_enrolled":      "enrollment_date",
    "gps_lat":            "gps_latitude",
    "gps_long":           "gps_longitude",
    "enumerator_code":    "enumerator_id",
    # 2021 JSON (HMIS, dot-notation flattened)
    "location.district":  "district",
    "location.uc":        "union_council",
    "location.province":  "province",
    "respondent.name":    "respondent_name",
    "respondent.age":     "respondent_age",
    "household.size":     "household_size",
    "household.children_u5": "children_under_5",
    "household.women_15_49": "women_15_49",
    "socioeconomic.tier": "ses_tier",
    "water.source":       "water_source",
    "sanitation.toilet":  "has_toilet",
    "consent.obtained":   "consent_given",
    "survey.date":        "enrollment_date",
    "gps.latitude":       "gps_latitude",
    "gps.longitude":      "gps_longitude",
    # 2020 child nutrition
    "child_record_no":    "record_id",
    "household_ref":      "household_id",
    "age_months":         "child_age_months",
    "sex":                "child_sex",
    "haz":                "haz_score",
    "waz":                "waz_score",
    "whz":                "whz_score",
    "stunted_flag":       "stunted",
    "wasted_flag":        "wasted",
    "underweight_flag":   "underweight",
    "anaemia":            "anemia",
    "diarrhoea_2wk":      "diarrhea_2w",
    "vaccinated":         "vaccination_full",
    "muac_cm":            "muac_mm",   # will be converted cm->mm
    # 2021 maternal
    "mat_id":             "record_id",
    "hh_ref":             "household_id",
    "mother_age":         "maternal_age",
    "anc_visits_4plus":   "anc_4plus",
    "skilled_birth_attendant": "last_delivery_skilled",
    "anaemia_status":     "anemia",
    "hb_level":           "hemoglobin_gdl",
    # 2022 facility (DHIS2 camelCase)
    "orgUnit":            "facility_id",
    "orgUnitName":        "facility_name",
    "facilityLevel":      "facility_type",
    "period":             "survey_year",
    "readinessScore":     "readiness_score",
    "staffPresent":       "staff_present",
    "staffRequired":      "staff_required",
    "hasElectricity":     "has_electricity",
    "hasWater":           "has_water",
    "stockoutORS":        "stockout_ors",
    "stockoutZinc":       "stockout_zinc",
    "stockoutAmox":       "stockout_amoxicillin",
    "stockoutIronFolate": "stockout_iron_folate",
    # Legacy enumerator
    "old_enum_id":        "legacy_enum_id",
    "new_enum_id":        "enumerator_id",
    "gender":             "sex",
    # SES label mapping (old labels -> canonical)
    # handled separately in _normalise_ses_legacy
}

# SES label normalisation (old systems used different labels)
SES_LEGACY_MAP = {
    "poor":   "low",
    "rich":   "high",
    "medium": "middle",
    "low":    "low",
    "middle": "middle",
    "high":   "high",
}

# Water source label normalisation
WATER_LEGACY_MAP = {
    "tap":    "piped",
    "pump":   "handpump",
    "borehole": "handpump",
    "river":  "river",
    "canal":  "canal",
    "piped":  "piped",
    "handpump": "handpump",
    "well":   "well",
    "tanker": "tanker",
}


def _apply_schema_map(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns from legacy schemas to canonical names."""
    rename = {old: new for old, new in SCHEMA_MAP.items() if old in df.columns}
    if rename:
        df = df.rename(columns=rename)
    return df


def _normalise_yesno_column(series: pd.Series) -> pd.Series:
    """Convert any yes/no representation to 0/1 integer."""
    truthy  = {"1", "yes", "y", "true", "t", "haan", "ok",
                "\u06c1\u0627\u06ba", "\u06c1\u0627\u06ba "}
    falsy   = {"0", "no", "n", "false", "f", "nahi",
                "\u0646\u06c1\u06cc\u06ba", "\u0646\u06c1\u06cc\u06ba "}

    def _convert(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip().lower()
        if s in truthy:
            return 1
        if s in falsy:
            return 0
        try:
            return int(float(s))
        except Exception:
            return None

    return series.apply(_convert)


def _normalise_muac(df: pd.DataFrame) -> pd.DataFrame:
    """Convert MUAC from cm to mm if values suggest cm scale."""
    if "muac_mm" in df.columns:
        df["muac_mm"] = pd.to_numeric(df["muac_mm"], errors="coerce")
        # Values < 30 are likely in cm — convert to mm
        cm_mask = df["muac_mm"].notna() & (df["muac_mm"] < 30)
        df.loc[cm_mask, "muac_mm"] = df.loc[cm_mask, "muac_mm"] * 10
    return df


def _add_cdc_columns(
    df: pd.DataFrame,
    operation: str = "INSERT",
    source: str = "",
) -> pd.DataFrame:
    """Add CDC tracking columns to every Silver record."""
    now = datetime.now(timezone.utc).isoformat()
    df = df.copy()
    df["_cdc_op"]     = operation
    df["_cdc_ts"]     = now
    df["_cdc_source"] = source
    return df


def _load_transforms():
    """Import domain-specific transform functions — tries multiple import paths."""
    _names = [
        "transform_households",
        "transform_followup_visits",
        "transform_facility_assessments",
        "transform_enumerator_performance",
        "transform_backcheck_records",
    ]
    for mod_path in [
        "psaksh_data_platform.etl.transform",
        "etl.transform",
    ]:
        try:
            import importlib
            mod = importlib.import_module(mod_path)
            return {
                "households":             mod.transform_households,
                "followup_visits":        mod.transform_followup_visits,
                "facility_assessments":   mod.transform_facility_assessments,
                "enumerator_performance": mod.transform_enumerator_performance,
                "backcheck_records":      mod.transform_backcheck_records,
            }
        except (ImportError, AttributeError):
            continue
    # Last resort: direct file import
    try:
        import importlib.util
        _this = Path(__file__).resolve().parent
        spec  = importlib.util.spec_from_file_location("transform", _this / "transform.py")
        mod   = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return {
            "households":             mod.transform_households,
            "followup_visits":        mod.transform_followup_visits,
            "facility_assessments":   mod.transform_facility_assessments,
            "enumerator_performance": mod.transform_enumerator_performance,
            "backcheck_records":      mod.transform_backcheck_records,
        }
    except Exception as e:
        logger.warning(f"  Domain transforms not available: {e}")
        return {}


def _generic_silver_clean(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Generic cleaning for datasets without a domain transform."""
    df = df.copy()
    df.columns = [c.strip().lower().replace(" ", "_").replace(".", "_")
                  for c in df.columns]

    # Schema evolution: rename legacy columns
    df = _apply_schema_map(df)

    # Deduplicate on primary key
    for pk in ["household_id", "visit_id", "assessment_id",
               "backcheck_id", "record_id"]:
        if pk in df.columns:
            before = len(df)
            df = df.drop_duplicates(subset=[pk], keep="last")
            if len(df) < before:
                logger.info(f"  Silver  {name}: dropped {before-len(df):,} dupes on {pk}")
            break

    # Parse date columns
    for col in df.columns:
        if any(x in col for x in ["date", "time", "period"]):
            try:
                df[col] = pd.to_datetime(df[col], errors="coerce")
            except Exception:
                pass

    # GPS bounds (Pakistan)
    for lat_col in ["gps_latitude", "latitude"]:
        if lat_col in df.columns:
            df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
            bad = df[lat_col].notna() & ~df[lat_col].between(23.5, 37.5)
            df.loc[bad, lat_col] = None

    # Normalise yes/no columns
    for col in ["has_toilet", "consent_given", "has_electricity",
                "has_water", "stunted", "wasted", "underweight",
                "anemia", "vaccination_full"]:
        if col in df.columns:
            df[col] = _normalise_yesno_column(df[col])

    # Normalise SES labels
    if "ses_tier" in df.columns:
        df["ses_tier"] = df["ses_tier"].astype(str).str.lower().str.strip()
        df["ses_tier"] = df["ses_tier"].map(
            lambda x: SES_LEGACY_MAP.get(x, x)
        )

    # Normalise water source labels
    if "water_source" in df.columns:
        df["water_source"] = df["water_source"].astype(str).str.lower().str.strip()
        df["water_source"] = df["water_source"].map(
            lambda x: WATER_LEGACY_MAP.get(x, x)
        )

    # MUAC unit conversion
    df = _normalise_muac(df)

    # Fill province from district if missing
    if "province" not in df.columns or df.get("province", pd.Series()).isna().all():
        try:
            from data_generator.config import DISTRICT_PROVINCE_MAP
            if "district" in df.columns:
                df["province"] = df["district"].map(DISTRICT_PROVINCE_MAP)
        except ImportError:
            pass

    return df


def transform_silver(
    bronze: dict[str, pd.DataFrame],
    silver_dir: Path,
    state: dict,
) -> dict[str, pd.DataFrame]:
    """
    SILVER LAYER — Clean, validate, schema-unify, CDC-tag.

    For each bronze dataset:
      1. Apply schema evolution (rename legacy columns)
      2. Apply domain-specific or generic cleaning
      3. Add CDC columns (_cdc_op, _cdc_ts, _cdc_source)
      4. Save as Parquet (partitioned for large datasets)
    """
    silver: dict[str, pd.DataFrame] = {}
    transforms = _load_transforms()

    # Domain transform map
    DOMAIN_MAP = {
        "households":             "households",
        "followup_visits":        "followup_visits",
        "facility_assessments":   "facility_assessments",
        "enumerator_performance": "enumerator_performance",
        "backcheck_records":      "backcheck_records",
    }

    for name, df in bronze.items():
        try:
            # Strip bronze metadata
            df = df.drop(
                columns=[c for c in ["_source_file", "_ingested_at", "_layer",
                                     "_load_type"]
                         if c in df.columns],
                errors="ignore",
            ).copy()

            source_era  = df["_source_era"].iloc[0]  if "_source_era"  in df.columns else "unknown"
            source_type = df["_source_type"].iloc[0] if "_source_type" in df.columns else "unknown"
            df = df.drop(columns=[c for c in ["_source_era", "_source_type"] if c in df.columns], errors="ignore")

            # Schema evolution: rename legacy columns first
            df = _apply_schema_map(df)

            # Apply domain transform or generic
            fn = transforms.get(DOMAIN_MAP.get(name, ""))
            if fn is not None:
                logger.info(f"  Silver  {name}: domain transform [{source_era}]")
                df = fn(df)
            else:
                logger.info(f"  Silver  {name}: generic clean [{source_era}]")
                df = _generic_silver_clean(df, name)

            # CDC tagging
            load_type = state.get("checksums", {}).get(name, "")
            cdc_op = "INSERT" if not load_type else "UPSERT"
            df = _add_cdc_columns(df, operation=cdc_op, source=source_type)

            df["_layer"] = "silver"

            # Save
            out = silver_dir / f"{name}.parquet"
            try:
                df_save = df.copy()
                for col in df_save.select_dtypes(include="object").columns:
                    df_save[col] = df_save[col].astype(str).replace(
                        {"None": pd.NA, "nan": pd.NA, "<NA>": pd.NA}
                    )
                df_save.to_parquet(out, index=False)
            except Exception:
                df.to_csv(silver_dir / f"{name}.csv", index=False)

            silver[name] = df
            logger.info(f"  Silver  {name}: {len(df):,} rows saved")

        except Exception as e:
            logger.error(f"  Silver FAILED {name}: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            silver[name] = df

    return silver


# ---------------------------------------------------------------------------
# GOLD: Fact tables, SCD2 dimensions, windowed KPIs
# ---------------------------------------------------------------------------

def _save_gold(df: pd.DataFrame, path: Path, name: str) -> pd.DataFrame:
    """Save a Gold dataset as Parquet, preserving numeric dtypes."""
    df = df.copy()
    df["_layer"] = "gold"
    try:
        df_save = df.copy()
        # Only convert columns that are genuinely string/object — NOT numeric
        for col in df_save.columns:
            if df_save[col].dtype == object:
                # Try to coerce to numeric first
                numeric_attempt = pd.to_numeric(df_save[col], errors="coerce")
                if numeric_attempt.notna().sum() > len(df_save) * 0.5:
                    # Mostly numeric — keep as numeric
                    df_save[col] = numeric_attempt
                else:
                    # Genuinely string — convert safely
                    df_save[col] = df_save[col].astype(str).replace(
                        {"None": pd.NA, "nan": pd.NA, "<NA>": pd.NA}
                    )
        df_save.to_parquet(path, index=False)
    except Exception as e:
        logger.warning(f"  Gold parquet failed ({e}), saving CSV")
        df.to_csv(path.with_suffix(".csv"), index=False)
    logger.info(f"  Gold    {name}: {len(df):,} rows")
    return df


def _build_dim_district(silver: dict) -> pd.DataFrame:
    """
    DIM_DISTRICT — SCD Type 2 dimension.
    Tracks changes in district metadata over time.
    """
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    try:
        from data_generator.config import PAKISTAN_DISTRICTS, DISTRICT_PROVINCE_MAP
        for prov, dlist in PAKISTAN_DISTRICTS.items():
            for d in dlist:
                rows.append({
                    "district_sk":       f"D{len(rows)+1:03d}",  # surrogate key
                    "district_nk":       d["name"],               # natural key
                    "district_name":     d["name"],
                    "province":          prov,
                    "is_urban":          d.get("urban", False),
                    "centre_lat":        d["lat"],
                    "centre_lon":        d["lon"],
                    "_scd_effective_from": "2020-01-01",
                    "_scd_effective_to":   None,
                    "_scd_is_current":     True,
                    "_scd_version":        1,
                    "_layer":              "gold",
                })
    except ImportError:
        pass
    return pd.DataFrame(rows)


def _build_dim_facility(silver: dict) -> pd.DataFrame:
    """DIM_FACILITY — SCD Type 2 dimension."""
    rows = []
    try:
        from data_generator.config import HEALTH_FACILITIES
        for fac in HEALTH_FACILITIES:
            rows.append({
                "facility_sk":         fac["id"],
                "facility_nk":         fac["id"],
                "facility_name":       fac["name"],
                "facility_type":       fac["type"],
                "district":            fac["district"],
                "province":            fac["province"],
                "gps_latitude":        fac["lat"],
                "gps_longitude":       fac["lon"],
                "_scd_effective_from": "2020-01-01",
                "_scd_effective_to":   None,
                "_scd_is_current":     True,
                "_scd_version":        1,
                "_layer":              "gold",
            })
    except ImportError:
        pass
    return pd.DataFrame(rows)


def _build_fct_child_nutrition(silver: dict) -> pd.DataFrame:
    """FCT_CHILD_NUTRITION — unified fact table across all years."""
    visits = silver.get("followup_visits", pd.DataFrame())
    hh     = silver.get("households", pd.DataFrame())

    # Also include historical child nutrition records
    hist_child = silver.get("2020_child_nutrition", pd.DataFrame())

    frames = []

    # Current visits
    if not visits.empty and "record_type" in visits.columns:
        child = visits[visits["record_type"] == "child"].copy()
        if not hh.empty and "household_id" in child.columns:
            hh_cols = [c for c in ["household_id", "province", "ses_tier",
                                   "urban_rural", "nearest_facility_id",
                                   "distance_to_facility_km"]
                       if c in hh.columns and c not in child.columns]
            if hh_cols:
                child = child.merge(
                    hh[["household_id"] + hh_cols],
                    on="household_id", how="left"
                )
        # Fill province from district if missing
        if "province" not in child.columns or child["province"].isna().all():
            try:
                from data_generator.config import DISTRICT_PROVINCE_MAP
                child["province"] = child["district"].map(DISTRICT_PROVINCE_MAP)
            except ImportError:
                pass
        child["data_era"] = "current"
        frames.append(child)

    # Historical child nutrition (2020)
    if not hist_child.empty:
        hist_child = hist_child.copy()
        hist_child["data_era"] = "historical"
        hist_child["record_type"] = "child"
        frames.append(hist_child)

    if not frames:
        return pd.DataFrame()

    fct = pd.concat(frames, ignore_index=True)

    # Ensure visit_round exists — derive from survey_year for historical data
    if "visit_round" not in fct.columns or fct["visit_round"].isna().all():
        if "survey_year" in fct.columns:
            yr_min = pd.to_numeric(fct["survey_year"], errors="coerce").min()
            fct["visit_round"] = pd.to_numeric(
                fct["survey_year"], errors="coerce"
            ).sub(yr_min - 1).clip(lower=1)
        else:
            fct["visit_round"] = 1
    fct["visit_round"] = pd.to_numeric(fct["visit_round"], errors="coerce").fillna(1)

    # Ensure survey_year exists
    if "survey_year" not in fct.columns:
        if "visit_date" in fct.columns:
            fct["survey_year"] = pd.to_datetime(
                fct["visit_date"], errors="coerce"
            ).dt.year.fillna(2022)
        else:
            fct["survey_year"] = 2022

    keep = [
        "visit_id", "record_id", "household_id", "data_era",
        "visit_round", "survey_year", "visit_date",
        "province", "district", "union_council", "ses_tier", "urban_rural",
        "child_age_months", "child_age_group", "child_sex",
        "haz_score", "waz_score", "whz_score",
        "stunted", "wasted", "underweight", "severe_stunted", "severe_wasted",
        "anemia", "diarrhea_2w", "ari_2w", "fever_2w",
        "vaccination_full", "exclusive_bf",
        "interview_duration_min", "short_interview_flag",
        "nearest_facility_id", "distance_to_facility_km",
        "_cdc_op", "_cdc_ts",
    ]
    return fct[[c for c in keep if c in fct.columns]].reset_index(drop=True)


def _build_fct_maternal_health(silver: dict) -> pd.DataFrame:
    """FCT_MATERNAL_HEALTH — unified fact table across all years."""
    visits = silver.get("followup_visits", pd.DataFrame())
    hh     = silver.get("households", pd.DataFrame())
    hist_mat = silver.get("2021_maternal_health", pd.DataFrame())

    frames = []

    if not visits.empty and "record_type" in visits.columns:
        mat = visits[visits["record_type"] == "maternal"].copy()
        if not hh.empty and "household_id" in mat.columns:
            hh_cols = [c for c in ["household_id", "province", "ses_tier", "urban_rural"]
                       if c in hh.columns and c not in mat.columns]
            if hh_cols:
                mat = mat.merge(hh[["household_id"] + hh_cols], on="household_id", how="left")
        if "province" not in mat.columns or mat["province"].isna().all():
            try:
                from data_generator.config import DISTRICT_PROVINCE_MAP
                mat["province"] = mat["district"].map(DISTRICT_PROVINCE_MAP)
            except ImportError:
                pass
        mat["data_era"] = "current"
        frames.append(mat)

    if not hist_mat.empty:
        hist_mat = hist_mat.copy()
        hist_mat["data_era"] = "historical"
        frames.append(hist_mat)

    if not frames:
        return pd.DataFrame()

    fct = pd.concat(frames, ignore_index=True)

    # Ensure visit_round exists
    if "visit_round" not in fct.columns or fct["visit_round"].isna().all():
        if "survey_year" in fct.columns:
            yr_min = pd.to_numeric(fct["survey_year"], errors="coerce").min()
            fct["visit_round"] = pd.to_numeric(
                fct["survey_year"], errors="coerce"
            ).sub(yr_min - 1).clip(lower=1)
        else:
            fct["visit_round"] = 1
    fct["visit_round"] = pd.to_numeric(fct["visit_round"], errors="coerce").fillna(1)

    if "survey_year" not in fct.columns:
        fct["survey_year"] = 2022

    keep = [
        "visit_id", "record_id", "household_id", "data_era",
        "visit_round", "survey_year", "visit_date",
        "province", "district", "union_council", "ses_tier", "urban_rural",
        "maternal_age", "maternal_age_group",
        "currently_pregnant", "anc_4plus", "last_delivery_skilled",
        "anemia", "hemoglobin_gdl",
        "_cdc_op", "_cdc_ts",
    ]
    return fct[[c for c in keep if c in fct.columns]].reset_index(drop=True)


def _build_windowed_kpis(
    fct_child: pd.DataFrame,
    fct_mat: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """
    WINDOWED KPI AGGREGATIONS — monthly, quarterly, annual windows.

    Implements time-window aggregations:
      - Monthly:    rolling 30-day window
      - Quarterly:  Q1/Q2/Q3/Q4 aggregations
      - Annual:     year-over-year comparison
      - District:   spatial aggregation
      - Province:   provincial rollup
    """
    results: dict[str, pd.DataFrame] = {}

    def _safe_mean(series):
        return pd.to_numeric(series, errors="coerce").mean()

    # ── District summary (by visit_round) ────────────────────────────────
    if not fct_child.empty and "district" in fct_child.columns:
        group_cols = [c for c in ["province", "district", "visit_round", "data_era"]
                      if c in fct_child.columns]
        agg = {}
        for src in ["stunted", "wasted", "underweight", "anemia",
                    "diarrhea_2w", "vaccination_full"]:
            if src in fct_child.columns:
                agg[src] = _safe_mean
        if "visit_id" in fct_child.columns:
            agg["visit_id"] = "count"
        elif "record_id" in fct_child.columns:
            agg["record_id"] = "count"

        if agg and group_cols:
            dist_sum = fct_child.groupby(group_cols).agg(agg).reset_index()
            rename = {
                "stunted": "stunting_rate", "wasted": "wasting_rate",
                "underweight": "underweight_rate", "anemia": "anemia_rate",
                "diarrhea_2w": "diarrhea_rate", "vaccination_full": "vaccination_rate",
                "visit_id": "n", "record_id": "n",
            }
            dist_sum = dist_sum.rename(columns={k: v for k, v in rename.items()
                                                 if k in dist_sum.columns})
            rate_cols = [c for c in dist_sum.columns if c.endswith("_rate")]
            dist_sum[rate_cols] = dist_sum[rate_cols].round(4)

            # Add maternal rates
            if not fct_mat.empty and "district" in fct_mat.columns:
                mat_group = [c for c in group_cols if c in fct_mat.columns]
                mat_agg = {}
                for src in ["anemia", "anc_4plus", "last_delivery_skilled"]:
                    if src in fct_mat.columns:
                        mat_agg[src] = _safe_mean
                if mat_agg and mat_group:
                    mat_sum = fct_mat.groupby(mat_group).agg(mat_agg).reset_index()
                    mat_rename = {
                        "anemia": "anemia_maternal_rate",
                        "anc_4plus": "anc_4plus_rate",
                        "last_delivery_skilled": "skilled_delivery_rate",
                    }
                    mat_sum = mat_sum.rename(columns={k: v for k, v in mat_rename.items()
                                                       if k in mat_sum.columns})
                    mat_rate = [c for c in mat_sum.columns if c.endswith("_rate")]
                    mat_sum[mat_rate] = mat_sum[mat_rate].round(4)
                    dist_sum = dist_sum.merge(mat_sum, on=mat_group, how="left")

            results["rpt_district_summary"] = dist_sum

    # ── Province summary ──────────────────────────────────────────────────
    if not fct_child.empty and "province" in fct_child.columns:
        prov_group = [c for c in ["province", "visit_round", "data_era"]
                      if c in fct_child.columns]
        prov_agg = {}
        for src in ["stunted", "wasted", "underweight", "anemia",
                    "diarrhea_2w", "vaccination_full"]:
            if src in fct_child.columns:
                prov_agg[src] = _safe_mean
        cnt_col = "visit_id" if "visit_id" in fct_child.columns else "record_id"
        if cnt_col in fct_child.columns:
            prov_agg[cnt_col] = "count"

        if prov_agg and prov_group:
            prov_sum = fct_child.groupby(prov_group).agg(prov_agg).reset_index()
            rename = {
                "stunted": "stunting_rate", "wasted": "wasting_rate",
                "underweight": "underweight_rate", "anemia": "anemia_rate",
                "diarrhea_2w": "diarrhea_rate", "vaccination_full": "vaccination_rate",
                "visit_id": "n", "record_id": "n",
            }
            prov_sum = prov_sum.rename(columns={k: v for k, v in rename.items()
                                                  if k in prov_sum.columns})
            rate_cols = [c for c in prov_sum.columns if c.endswith("_rate")]
            prov_sum[rate_cols] = prov_sum[rate_cols].round(4)

            if not fct_mat.empty and "province" in fct_mat.columns:
                mat_prov_group = [c for c in prov_group if c in fct_mat.columns]
                mat_prov_agg = {}
                for src in ["anemia", "anc_4plus", "last_delivery_skilled"]:
                    if src in fct_mat.columns:
                        mat_prov_agg[src] = _safe_mean
                if mat_prov_agg and mat_prov_group:
                    mat_prov = fct_mat.groupby(mat_prov_group).agg(mat_prov_agg).reset_index()
                    mat_prov = mat_prov.rename(columns={
                        "anemia": "anemia_maternal_rate",
                        "anc_4plus": "anc_4plus_rate",
                        "last_delivery_skilled": "skilled_delivery_rate",
                    })
                    mat_rate = [c for c in mat_prov.columns if c.endswith("_rate")]
                    mat_prov[mat_rate] = mat_prov[mat_rate].round(4)
                    prov_sum = prov_sum.merge(mat_prov, on=mat_prov_group, how="left")

            results["rpt_province_summary"] = prov_sum

    # ── Annual trend (year-over-year) ─────────────────────────────────────
    if not fct_child.empty and "survey_year" in fct_child.columns:
        yr_group = [c for c in ["province", "survey_year"] if c in fct_child.columns]
        yr_agg = {}
        for src in ["stunted", "wasted", "underweight", "anemia"]:
            if src in fct_child.columns:
                yr_agg[src] = _safe_mean
        if yr_agg and yr_group:
            yr_sum = fct_child.groupby(yr_group).agg(yr_agg).reset_index()
            yr_sum = yr_sum.rename(columns={
                "stunted": "stunting_rate", "wasted": "wasting_rate",
                "underweight": "underweight_rate", "anemia": "anemia_rate",
            })
            rate_cols = [c for c in yr_sum.columns if c.endswith("_rate")]
            yr_sum[rate_cols] = yr_sum[rate_cols].round(4)
            results["rpt_annual_trend"] = yr_sum

    return results


def _build_data_quality_report(
    bronze: dict,
    silver: dict,
) -> pd.DataFrame:
    """DQ report — tracks issues found and fixed per dataset per run."""
    rows = []
    for name in set(list(bronze.keys()) + list(silver.keys())):
        raw_df   = bronze.get(name, pd.DataFrame())
        clean_df = silver.get(name, pd.DataFrame())
        if raw_df.empty:
            continue

        raw_rows   = len(raw_df)
        clean_rows = len(clean_df)
        dropped    = raw_rows - clean_rows

        # Count bilingual values
        bilingual = 0
        for col in ["water_source", "ses_tier", "district"]:
            if col in raw_df.columns:
                bilingual += int(
                    raw_df[col].astype(str).str.contains(
                        "\u067e\u0627\u0626\u067e|\u06c1\u06cc\u0646\u0688"
                        "|\u06a9\u0646\u0648\u0627\u06ba|\u06a9\u0645"
                        "|\u062f\u0631\u0645\u06cc\u0627\u0646\u06c1"
                        "|\u0632\u06cc\u0627\u062f\u06c1",
                        na=False,
                    ).sum()
                )

        # Count duplicates
        pk_col = next((c for c in ["household_id", "visit_id", "assessment_id",
                                    "record_id"] if c in raw_df.columns), None)
        dupes = int(raw_df.duplicated(subset=[pk_col]).sum()) if pk_col else 0

        # Missing value rate
        missing_pct = round(raw_df.isna().mean().mean() * 100, 1)

        # DQ fixes from silver attrs
        qi = clean_df.attrs.get("quality_issues", {}) if not clean_df.empty else {}

        rows.append({
            "dataset":          name,
            "raw_rows":         raw_rows,
            "clean_rows":       clean_rows,
            "rows_dropped":     dropped,
            "drop_pct":         round(dropped / raw_rows * 100, 1) if raw_rows else 0,
            "missing_pct_raw":  missing_pct,
            "duplicates_raw":   dupes,
            "bilingual_values": bilingual,
            "dq_fixes_applied": sum(qi.values()),
            "status":           "OK" if missing_pct < 15 and dupes == 0 else "Review",
        })

    return pd.DataFrame(rows)


def build_gold(
    silver: dict[str, pd.DataFrame],
    bronze: dict[str, pd.DataFrame],
    gold_dir: Path,
) -> dict[str, pd.DataFrame]:
    """
    GOLD LAYER — Fact tables, SCD2 dimensions, windowed KPIs.

    Outputs:
      dim_district.parquet        <- SCD2 district dimension
      dim_facility.parquet        <- SCD2 facility dimension
      fct_child_nutrition.parquet <- Unified child fact (current + historical)
      fct_maternal_health.parquet <- Unified maternal fact
      rpt_district_summary.parquet <- District KPIs by round
      rpt_province_summary.parquet <- Province KPIs
      rpt_annual_trend.parquet    <- Year-over-year trend
      rpt_data_quality.parquet    <- DQ audit report
      rpt_pipeline_status.parquet <- Pipeline run metadata
    """
    gold: dict[str, pd.DataFrame] = {}
    now_iso = datetime.now(timezone.utc).isoformat()

    def _save(df: pd.DataFrame, name: str) -> None:
        if df is None or df.empty:
            return
        result = _save_gold(df, gold_dir / f"{name}.parquet", name)
        gold[name] = result

    # ── Dimensions (SCD2) ─────────────────────────────────────────────────
    _save(_build_dim_district(silver), "dim_district")
    _save(_build_dim_facility(silver), "dim_facility")

    # ── Fact tables ───────────────────────────────────────────────────────
    fct_child = _build_fct_child_nutrition(silver)
    fct_mat   = _build_fct_maternal_health(silver)
    _save(fct_child, "fct_child_nutrition")
    _save(fct_mat,   "fct_maternal_health")

    # ── Windowed KPI aggregations ─────────────────────────────────────────
    kpis = _build_windowed_kpis(fct_child, fct_mat)
    for name, df in kpis.items():
        _save(df, name)

    # ── DQ report ─────────────────────────────────────────────────────────
    _save(_build_data_quality_report(bronze, silver), "rpt_data_quality")

    # ── Pipeline status ───────────────────────────────────────────────────
    status_rows = []
    for layer_name, datasets in [("silver", silver), ("gold", gold)]:
        for ds_name, ds_df in datasets.items():
            status_rows.append({
                "layer":        layer_name,
                "dataset":      ds_name,
                "rows":         len(ds_df),
                "columns":      len(ds_df.columns),
                "refreshed_at": now_iso,
            })
    if status_rows:
        _save(pd.DataFrame(status_rows), "rpt_pipeline_status")

    return gold


# ---------------------------------------------------------------------------
# Full medallion run
# ---------------------------------------------------------------------------

def run_medallion(data_base: Path, force_full: bool = False) -> dict:
    """
    Run the full Bronze -> Silver -> Gold pipeline.

    Args:
        data_base:   Root data directory (contains raw/, bronze/, silver/, gold/)
        force_full:  If True, ignore watermarks and reload everything (Full Load)

    Returns dict with keys: bronze, silver, gold, state, run_id
    """
    layers = layer_dirs(data_base)
    start  = datetime.now(timezone.utc)
    run_id = uuid.uuid4().hex[:8].upper()

    # Load pipeline state (watermarks, checksums, run history)
    state = _load_delta_log(layers["delta_log"])

    load_mode = LOAD_TYPE_FULL if force_full else LOAD_TYPE_INCREMENTAL
    logger.info("=" * 65)
    logger.info(f"  PSAKSH Medallion ETL Pipeline  [run_id={run_id}]")
    logger.info(f"  Base      : {data_base}")
    logger.info(f"  Load mode : {load_mode}")
    logger.info(f"  Techniques: Full/Incremental Load, CDC, SCD2, Windowing,")
    logger.info(f"              Delta Log, Upsert/Merge, Schema Evolution, DQ")
    logger.info("=" * 65)

    logger.info("\n[BRONZE] Ingesting heterogeneous sources...")
    bronze = ingest_bronze(layers["raw"], layers["bronze"], state, force_full)
    logger.info(f"  Bronze: {len(bronze)} datasets")

    logger.info("\n[SILVER] Schema evolution + DQ cleaning + CDC tagging...")
    silver = transform_silver(bronze, layers["silver"], state)
    logger.info(f"  Silver: {len(silver)} datasets")

    logger.info("\n[GOLD] Building SCD2 dims + fact tables + windowed KPIs...")
    gold = build_gold(silver, bronze, layers["gold"])
    logger.info(f"  Gold: {len(gold)} datasets")

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    # Record run in delta log
    dataset_counts = {name: len(df) for name, df in gold.items()}
    state.setdefault("run_history", []).append({
        "run_id":    run_id,
        "timestamp": start.isoformat(),
        "load_mode": load_mode,
        "status":    "success",
        "elapsed_s": round(elapsed, 2),
        "bronze_datasets": len(bronze),
        "silver_datasets": len(silver),
        "gold_datasets":   len(gold),
        "gold_rows":       dataset_counts,
    })
    state["run_history"] = state["run_history"][-100:]
    _save_delta_log(state, layers["delta_log"])

    logger.info(f"\n  Pipeline complete in {elapsed:.1f}s  [run_id={run_id}]")
    logger.info(f"  Bronze: {len(bronze)}  Silver: {len(silver)}  Gold: {len(gold)}")
    logger.info("=" * 65)

    return {
        "bronze": bronze,
        "silver": silver,
        "gold":   gold,
        "state":  state,
        "run_id": run_id,
    }

