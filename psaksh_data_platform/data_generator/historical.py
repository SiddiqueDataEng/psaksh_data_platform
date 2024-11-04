"""
Historical data generator (2020-2022) — heterogeneous legacy formats.

CORRECT ARCHITECTURE:
  Historical data (2020-2022) = messy, heterogeneous, legacy formats
    - Old paper-based surveys digitised as CSV (inconsistent schemas)
    - Excel exports with merged cells / extra header rows
    - JSON from old DHIS2 / HMIS systems (nested, non-standard)
    - Avro from old Hadoop pipelines
    - Different column names, date formats, encodings per year
    - Missing values, duplicates, schema drift across years

  Current data (2022-2024+) = clean, structured, from MySQL DB
    - Survey forms (single + bulk) → MySQL → exported as Parquet
    - Consistent schema, validated at entry point
    - Served via API to Flask / Streamlit / Power BI

The Medallion ETL's job is to unify all historical heterogeneous sources
with the clean current DB exports into a single Gold layer.

Files generated in data/raw/historical/:
  2020_household_survey.csv       <- Old CSV, inconsistent columns
  2020_child_nutrition.xlsx.csv   <- Excel export (simulated as CSV with quirks)
  2021_household_survey.json      <- JSON from old HMIS system
  2021_maternal_health.csv        <- Different column names than 2020
  2022_household_survey.avro      <- Avro from old Hadoop pipeline
  2022_facility_assessment.json   <- DHIS2 export, nested structure flattened
  legacy_enumerators.csv          <- Old enumerator registry, different ID format
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    DISTRICTS,
    DISTRICT_PROVINCE_MAP,
    DISTRICT_INFO_MAP,
    ENUMERATORS,
    HEALTH_FACILITIES,
    PAKISTAN_DISTRICTS,
    PROVINCE_PROFILES,
    PREVALENCE,
    SES_TIERS,
    SES_WEIGHTS,
    UNION_COUNCILS,
    URDU_NAMES_FEMALE,
    URDU_NAMES_MALE,
    URDU_SURNAMES,
)

RNG = np.random.default_rng(2020)

import logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rdate(start: str, end: str) -> datetime:
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    return s + timedelta(days=int(RNG.integers(0, (e - s).days)))


def _name_f() -> str:
    return f"{random.choice(URDU_NAMES_FEMALE)} {random.choice(URDU_SURNAMES)}"


def _name_m() -> str:
    return f"{random.choice(URDU_NAMES_MALE)} {random.choice(URDU_SURNAMES)}"


def _district_sample() -> str:
    return random.choice(DISTRICTS)


def _province(district: str) -> str:
    return DISTRICT_PROVINCE_MAP.get(district, "Punjab")


def _prev(district: str) -> dict:
    return PROVINCE_PROFILES.get(_province(district), PREVALENCE)


# Legacy DQ injectors — worse than current data (older systems, less validation)
def _legacy_date(dt: datetime, year: int) -> str:
    """Old systems used many date formats."""
    if RNG.random() < 0.25:
        fmts = ["%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y",
                f"%d/%m/{year}", f"{year}/%m/%d"]
        return dt.strftime(random.choice(fmts))
    return dt.strftime("%Y-%m-%d")


def _legacy_district(district: str) -> str:
    """Old data had more typos and abbreviations."""
    if RNG.random() < 0.20:
        variants = {
            "Dera Ismail Khan": ["D.I.Khan", "DIKhan", "D I Khan", "Dera Ismail Khan "],
            "Rahim Yar Khan":   ["RYK", "R.Y.Khan", "Rahim Yar Khan "],
            "Mirpur Khas":      ["Mirpurkhas", "Mirpur-Khas", "MirpurKhas"],
            "Karachi":          ["Karachi ", "KARACHI", "karachi"],
            "Lahore":           ["Lahor", "LAHORE", "lahore"],
            "Peshawar":         ["Peshawer", "PESHAWAR", "peshawar"],
        }
        return random.choice(variants.get(district, [district.lower(), district.upper()]))
    return district


def _legacy_yesno(val: int) -> str:
    """Old systems stored yes/no as strings, not 0/1."""
    if RNG.random() < 0.40:
        yes_variants = ["Yes", "YES", "yes", "Y", "y", "1", "True",
                        "\u06c1\u0627\u06ba", "Haan", "ہاں"]
        no_variants  = ["No", "NO", "no", "N", "n", "0", "False",
                        "\u0646\u06c1\u06cc\u06ba", "Nahi", "نہیں"]
        return random.choice(yes_variants if val else no_variants)
    return str(val)


def _maybe_missing(val, p: float = 0.08):
    """Historical data had more missing values."""
    return None if RNG.random() < p else val


# ---------------------------------------------------------------------------
# 2020 data — old CSV format (inconsistent column names, bad dates)
# ---------------------------------------------------------------------------

def generate_2020_households(n: int = 600) -> pd.DataFrame:
    """
    2020 household survey — old CSV format.
    Column names differ from current schema (e.g. 'hh_id' not 'household_id').
    Date format is DD/MM/YYYY. Yes/No stored as strings.
    """
    records = []
    for i in range(n):
        district  = _district_sample()
        uc        = random.choice(UNION_COUNCILS.get(district, ["UC-1"]))
        enroll_dt = _rdate("2020-01-01", "2020-12-31")

        records.append({
            # Old column names — different from current schema
            "hh_id":           f"HH2020{i+1:04d}",
            "survey_year":     2020,
            "district_name":   _legacy_district(district),   # typos
            "tehsil":          uc,                            # called 'tehsil' not 'union_council'
            "respondent":      _name_f(),
            "age_years":       _maybe_missing(int(RNG.integers(18, 55)), 0.05),
            "hh_size":         int(RNG.integers(3, 14)),
            "children_u5":     int(RNG.integers(0, 6)),
            "women_repro_age": int(RNG.integers(1, 5)),
            "ses":             random.choices(["poor", "middle", "rich"],  # different labels
                                              weights=[0.58, 0.32, 0.10])[0],
            "water":           random.choices(["tap", "pump", "well", "tanker"],  # different labels
                                              weights=[0.22, 0.42, 0.22, 0.14])[0],
            "latrine":         _legacy_yesno(int(RNG.random() < 0.58)),
            "consent":         _legacy_yesno(1) if RNG.random() > 0.03 else "No",
            "date_enrolled":   _legacy_date(enroll_dt, 2020),  # bad date format
            "gps_lat":         _maybe_missing(
                round(float(RNG.uniform(
                    DISTRICT_INFO_MAP.get(district, {}).get("lat", 30.0) - 0.1,
                    DISTRICT_INFO_MAP.get(district, {}).get("lat", 30.0) + 0.1
                )), 5), 0.08),
            "gps_long":        _maybe_missing(
                round(float(RNG.uniform(
                    DISTRICT_INFO_MAP.get(district, {}).get("lon", 70.0) - 0.1,
                    DISTRICT_INFO_MAP.get(district, {}).get("lon", 70.0) + 0.1
                )), 5), 0.08),
            "data_source":     "2020_paper_survey_digitised",
            "enumerator_code": f"ENUM{random.randint(1, 50):03d}",  # old ID format
        })

        # ~20% duplicates in old data (paper forms entered twice)
        if RNG.random() < 0.20:
            dup = records[-1].copy()
            dup["date_enrolled"] = _legacy_date(
                enroll_dt + timedelta(days=random.randint(1, 30)), 2020
            )
            records.append(dup)

    return pd.DataFrame(records)


def generate_2020_child_nutrition(hh_df: pd.DataFrame) -> pd.DataFrame:
    """
    2020 child nutrition — Excel export (simulated).
    Has extra metadata rows, different column names, mixed units.
    """
    records = []
    for _, hh in hh_df.iterrows():
        district = str(hh.get("district_name", "Lahore"))
        # Normalise for prevalence lookup
        for d in DISTRICTS:
            if d.lower() in district.lower():
                district = d
                break
        prev = _prev(district)
        n_ch = max(1, int(hh.get("children_u5", 1) or 1))

        for _ in range(n_ch):
            age_m = int(RNG.integers(0, 60))
            haz   = float(RNG.normal(-1.9, 1.2))
            waz   = float(RNG.normal(-1.6, 1.1))
            whz   = float(RNG.normal(-1.0, 1.0))
            h     = round(45 + age_m * 0.7 + haz * 4.5, 1)
            w     = round((h / 100) ** 2 * (16 + waz * 1.5), 2)

            records.append({
                "child_record_no":  f"CN2020{uuid.uuid4().hex[:6].upper()}",
                "household_ref":    hh["hh_id"],           # old FK name
                "year":             2020,
                "district":         _legacy_district(district),
                "age_months":       age_m,
                "sex":              random.choice(["M", "F"]),  # M/F not male/female
                "height_cm":        _maybe_missing(h, 0.06),
                "weight_kg":        _maybe_missing(w, 0.06),
                "muac_cm":          _maybe_missing(round(float(RNG.normal(13.5, 1.5)), 1), 0.10),  # cm not mm!
                "haz":              round(haz, 2),
                "waz":              round(waz, 2),
                "whz":              round(whz, 2),
                "stunted_flag":     _legacy_yesno(int(haz < -2)),
                "wasted_flag":      _legacy_yesno(int(whz < -2)),
                "underweight_flag": _legacy_yesno(int(waz < -2)),
                "anaemia":          _legacy_yesno(int(RNG.random() < prev["anemia_child"])),  # 'anaemia' spelling
                "diarrhoea_2wk":    _legacy_yesno(int(RNG.random() < prev["diarrhea_2w"])),  # 'diarrhoea'
                "vaccinated":       _legacy_yesno(int(RNG.random() < prev["vaccination_full"])),
                "data_source":      "2020_excel_export",
            })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 2021 data — JSON from old HMIS system
# ---------------------------------------------------------------------------

def generate_2021_households(n: int = 700) -> pd.DataFrame:
    """
    2021 household survey — JSON from old HMIS.
    Nested fields flattened, different field names again.
    """
    records = []
    for i in range(n):
        district  = _district_sample()
        uc        = random.choice(UNION_COUNCILS.get(district, ["UC-1"]))
        enroll_dt = _rdate("2021-01-01", "2021-12-31")

        records.append({
            "id":              f"HMIS2021-{uuid.uuid4().hex[:8].upper()}",
            "survey_year":     2021,
            "location.district": _legacy_district(district),  # nested field flattened
            "location.uc":     uc,
            "location.province": _province(district),
            "respondent.name": _name_f(),
            "respondent.age":  _maybe_missing(int(RNG.integers(18, 55)), 0.06),
            "household.size":  int(RNG.integers(3, 14)),
            "household.children_u5": int(RNG.integers(0, 6)),
            "household.women_15_49": int(RNG.integers(1, 5)),
            "socioeconomic.tier": random.choices(SES_TIERS, weights=SES_WEIGHTS)[0],
            "water.source":    random.choices(
                ["piped", "handpump", "well", "tanker"],
                weights=[0.22, 0.42, 0.22, 0.14]
            )[0],
            "sanitation.toilet": _legacy_yesno(int(RNG.random() < 0.60)),
            "consent.obtained":  _legacy_yesno(1),
            "survey.date":     _legacy_date(enroll_dt, 2021),
            "gps.latitude":    _maybe_missing(
                round(float(RNG.uniform(
                    DISTRICT_INFO_MAP.get(district, {}).get("lat", 30.0) - 0.1,
                    DISTRICT_INFO_MAP.get(district, {}).get("lat", 30.0) + 0.1
                )), 5), 0.06),
            "gps.longitude":   _maybe_missing(
                round(float(RNG.uniform(
                    DISTRICT_INFO_MAP.get(district, {}).get("lon", 70.0) - 0.1,
                    DISTRICT_INFO_MAP.get(district, {}).get("lon", 70.0) + 0.1
                )), 5), 0.06),
            "data_source":     "2021_hmis_json_export",
        })
    return pd.DataFrame(records)


def generate_2021_maternal(hh_df: pd.DataFrame) -> pd.DataFrame:
    """2021 maternal health — different column names from 2020."""
    records = []
    for _, hh in hh_df.iterrows():
        district = str(hh.get("location.district", "Lahore"))
        for d in DISTRICTS:
            if d.lower() in district.lower():
                district = d
                break
        prev    = _prev(district)
        n_women = max(1, int(hh.get("household.women_15_49", 1) or 1))

        for _ in range(n_women):
            anemia = int(RNG.random() < prev["anemia_mother"])
            records.append({
                "mat_id":          f"MAT2021{uuid.uuid4().hex[:6].upper()}",
                "hh_ref":          hh["id"],
                "year":            2021,
                "district":        _legacy_district(district),
                "mother_age":      _maybe_missing(int(RNG.integers(15, 50)), 0.05),
                "anc_visits_4plus": _legacy_yesno(int(RNG.random() < prev["anc_4plus"])),
                "skilled_birth_attendant": _legacy_yesno(int(RNG.random() < prev["skilled_delivery"])),
                "anaemia_status":  _legacy_yesno(anemia),
                "hb_level":        _maybe_missing(
                    round(float(RNG.normal(11.2 if anemia else 12.8, 1.5)), 1), 0.12),
                "data_source":     "2021_hmis_json_export",
            })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 2022 data — Avro from old Hadoop pipeline (simulated as Parquet)
# ---------------------------------------------------------------------------

def generate_2022_households(n: int = 800) -> pd.DataFrame:
    """
    2022 household survey — Avro from old Hadoop pipeline.
    Saved as Parquet (Avro requires fastavro which may not be installed).
    Schema is closer to current but still has differences.
    """
    records = []
    for i in range(n):
        district  = _district_sample()
        uc        = random.choice(UNION_COUNCILS.get(district, ["UC-1"]))
        enroll_dt = _rdate("2022-01-01", "2022-06-30")  # first half only

        records.append({
            "household_id":    f"HH2022{uuid.uuid4().hex[:8].upper()}",
            "survey_year":     2022,
            "province":        _province(district),
            "district":        _legacy_district(district),
            "union_council":   uc,
            "enumerator_id":   f"E{random.randint(1, 108):03d}",
            "respondent_name": _name_f(),
            "respondent_age":  _maybe_missing(int(RNG.integers(18, 55)), 0.04),
            "household_size":  int(RNG.integers(3, 14)),
            "children_under_5": int(RNG.integers(0, 6)),
            "women_15_49":     int(RNG.integers(1, 5)),
            "ses_tier":        random.choices(SES_TIERS, weights=SES_WEIGHTS)[0],
            "water_source":    random.choices(
                ["piped", "handpump", "well", "tanker"],
                weights=[0.22, 0.42, 0.22, 0.14]
            )[0],
            "has_toilet":      int(RNG.random() < 0.62),
            "consent_given":   1,
            "enrollment_date": enroll_dt.strftime("%Y-%m-%d"),  # ISO format (closer to current)
            "gps_latitude":    _maybe_missing(
                round(float(RNG.uniform(
                    DISTRICT_INFO_MAP.get(district, {}).get("lat", 30.0) - 0.1,
                    DISTRICT_INFO_MAP.get(district, {}).get("lat", 30.0) + 0.1
                )), 5), 0.05),
            "gps_longitude":   _maybe_missing(
                round(float(RNG.uniform(
                    DISTRICT_INFO_MAP.get(district, {}).get("lon", 70.0) - 0.1,
                    DISTRICT_INFO_MAP.get(district, {}).get("lon", 70.0) + 0.1
                )), 5), 0.05),
            "data_source":     "2022_hadoop_avro_pipeline",
        })
    return pd.DataFrame(records)


def generate_2022_facility_assessment() -> pd.DataFrame:
    """2022 facility assessment — DHIS2 JSON export, different schema."""
    records = []
    for fac in HEALTH_FACILITIES:
        assess_dt = _rdate("2022-01-01", "2022-12-31")
        base = {"DHQ": 70, "RHC": 55, "BHU": 40}.get(fac["type"], 50)
        score = float(np.clip(RNG.normal(base, 12), 5, 100))

        records.append({
            "orgUnit":         fac["id"],                    # DHIS2 field name
            "orgUnitName":     fac["name"],
            "facilityLevel":   fac["type"],                  # 'facilityLevel' not 'facility_type'
            "district":        fac["district"],
            "province":        fac["province"],
            "period":          "2022",
            "readinessScore":  round(score, 1),              # camelCase
            "staffPresent":    int(RNG.integers(1, 10)),
            "staffRequired":   {"DHQ": 15, "RHC": 7, "BHU": 3}.get(fac["type"], 5),
            "hasElectricity":  _legacy_yesno(int(RNG.random() < 0.80)),
            "hasWater":        _legacy_yesno(int(RNG.random() < 0.72)),
            "stockoutORS":     _legacy_yesno(int(RNG.random() < 0.25)),
            "stockoutZinc":    _legacy_yesno(int(RNG.random() < 0.28)),
            "stockoutAmox":    _legacy_yesno(int(RNG.random() < 0.22)),
            "stockoutIronFolate": _legacy_yesno(int(RNG.random() < 0.30)),
            "data_source":     "2022_dhis2_json_export",
        })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Legacy enumerator registry
# ---------------------------------------------------------------------------

def generate_legacy_enumerators() -> pd.DataFrame:
    """
    Legacy enumerator registry — old format, different ID scheme.
    Used to link historical data to current enumerator dimension.
    """
    records = []
    for e in ENUMERATORS:
        records.append({
            "old_enum_id":   f"ENUM{int(e['id'][1:]):03d}",  # old format: ENUM001 not E001
            "new_enum_id":   e["id"],
            "name":          e["name"],
            "district":      e["district"],
            "province":      e["province"],
            "gender":        e["sex"],
            "status":        "active",
            "data_source":   "legacy_hr_system",
        })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_historical_data(
    hist_dir: Path,
    n_2020: int = 600,
    n_2021: int = 700,
    n_2022: int = 800,
) -> dict[str, int]:
    """
    Generate all historical heterogeneous data files.

    Each year uses a different format and schema to simulate real legacy systems:
      2020: CSV (paper surveys digitised, bad dates, string yes/no)
      2021: JSON (HMIS export, nested fields, different column names)
      2022: Parquet (Hadoop/Avro pipeline, closer to current schema)

    Returns dict of {filename_stem: row_count}.
    """
    hist_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    def _save_csv(df: pd.DataFrame, name: str) -> int:
        path = hist_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        logger.info(f"  CSV     {path.name} ({len(df):,} rows)  [legacy 2020 format]")
        return len(df)

    def _save_json(df: pd.DataFrame, name: str) -> int:
        path = hist_dir / f"{name}.json"
        df.to_json(path, orient="records", lines=True, force_ascii=False)
        logger.info(f"  JSON    {path.name} ({len(df):,} rows)  [HMIS 2021 format]")
        return len(df)

    def _save_parquet(df: pd.DataFrame, name: str) -> int:
        path = hist_dir / f"{name}.parquet"
        try:
            df_clean = df.copy()
            for col in df_clean.select_dtypes(include="object").columns:
                df_clean[col] = df_clean[col].where(df_clean[col].notna(), None)
            df_clean.to_parquet(path, index=False, engine="pyarrow")
            logger.info(f"  Parquet {path.name} ({len(df):,} rows)  [Hadoop 2022 format]")
        except Exception as e:
            logger.warning(f"  Parquet failed ({e}), saving as CSV")
            df.to_csv(path.with_suffix(".csv"), index=False)
        return len(df)

    # ── 2020: CSV format ──────────────────────────────────────────────────
    logger.info("  [2020] Generating CSV legacy data...")
    hh_2020 = generate_2020_households(n_2020)
    counts["2020_household_survey"]   = _save_csv(hh_2020, "2020_household_survey")
    counts["2020_child_nutrition"]    = _save_csv(
        generate_2020_child_nutrition(hh_2020), "2020_child_nutrition"
    )

    # ── 2021: JSON format ─────────────────────────────────────────────────
    logger.info("  [2021] Generating JSON HMIS data...")
    hh_2021 = generate_2021_households(n_2021)
    counts["2021_household_survey"]   = _save_json(hh_2021, "2021_household_survey")
    counts["2021_maternal_health"]    = _save_json(
        generate_2021_maternal(hh_2021), "2021_maternal_health"
    )

    # ── 2022: Parquet format (Hadoop/Avro pipeline) ───────────────────────
    logger.info("  [2022] Generating Parquet Hadoop pipeline data...")
    hh_2022 = generate_2022_households(n_2022)
    counts["2022_household_survey"]   = _save_parquet(hh_2022, "2022_household_survey")
    counts["2022_facility_assessment"] = _save_json(
        generate_2022_facility_assessment(), "2022_facility_assessment"
    )

    # ── Legacy enumerator registry (CSV) ─────────────────────────────────
    counts["legacy_enumerators"] = _save_csv(
        generate_legacy_enumerators(), "legacy_enumerators"
    )

    return counts
