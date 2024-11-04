"""
ETL Transform Layer — Pakistan-wide data quality cleaning.

Handles ALL deliberate DQ issues injected by the data generator:
  1. Bilingual English/Urdu field values  → normalised to English
  2. Inconsistent date formats            → parsed to ISO YYYY-MM-DD
  3. Duplicate household submissions      → deduplicated (keep latest)
  4. Out-of-range anthropometric values   → nulled with audit log
  5. GPS outside Pakistan bounds          → nulled with audit log
  6. Implausible ages                     → nulled with audit log
  7. Urdu yes/no strings                  → converted to 0/1 integers
  8. District name typos / Urdu script    → normalised to canonical names
  9. Enumerator ID format inconsistencies → standardised to E### format
 10. Short interview flags                → preserved as quality indicator

Each transform_* function returns a cleaned DataFrame and attaches a
quality_issues dict to df.attrs for downstream reporting.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalisation maps — covers all 36 Pakistan districts + common variants
# ---------------------------------------------------------------------------

# Full Pakistan district canonical names (from config)
CANONICAL_DISTRICTS = [
    # Punjab
    "Lahore", "Faisalabad", "Multan", "Rawalpindi", "Gujranwala",
    "Sialkot", "Bahawalpur", "Sargodha", "Rahim Yar Khan",
    # Sindh
    "Karachi", "Hyderabad", "Sukkur", "Larkana", "Mirpur Khas",
    "Nawabshah", "Jacobabad", "Dadu", "Tharparkar",
    # KPK
    "Peshawar", "Mardan", "Abbottabad", "Swat", "Kohat",
    "Bannu", "Dera Ismail Khan", "Mansehra", "Charsadda",
    # Balochistan
    "Quetta", "Turbat", "Khuzdar", "Gwadar", "Chaman",
    "Zhob", "Loralai", "Sibi", "Nushki",
]

# Build a lowercase lookup for fast matching
_DISTRICT_LOWER = {d.lower(): d for d in CANONICAL_DISTRICTS}

# Explicit overrides for known typos and Urdu script variants
DISTRICT_OVERRIDES: dict[str, str] = {
    # Lahore
    "lahor": "Lahore", "lahore ": "Lahore",
    "\u0644\u0627\u06c1\u0648\u0631": "Lahore",
    # Karachi
    "karachi ": "Karachi",
    "\u06a9\u0631\u0627\u0686\u06cc": "Karachi",
    # Faisalabad
    "faisalabad ": "Faisalabad",
    "\u0641\u06cc\u0635\u0644 \u0622\u0628\u0627\u062f": "Faisalabad",
    # Multan
    "multan ": "Multan",
    "\u0645\u0644\u062a\u0627\u0646": "Multan",
    # Rawalpindi
    "rawalpindi ": "Rawalpindi",
    "\u0631\u0627\u0648\u0644\u067e\u0646\u0688\u06cc": "Rawalpindi",
    # Peshawar
    "peshawer": "Peshawar", "peshawar ": "Peshawar",
    "\u067e\u0634\u0627\u0648\u0631": "Peshawar",
    # Quetta
    "queta": "Quetta", "quetta ": "Quetta",
    "\u06a9\u0648\u0626\u0679\u06c1": "Quetta",
    # Hyderabad
    "hydrabad": "Hyderabad", "hyderabad ": "Hyderabad",
    "\u062d\u06cc\u062f\u0631\u0622\u0628\u0627\u062f": "Hyderabad",
    # Sukkur
    "sukkar": "Sukkur", "sukkur ": "Sukkur",
    "\u0633\u06a9\u06be\u0631": "Sukkur",
    # Swat
    "swat ": "Swat",
    "\u0633\u0648\u0627\u062a": "Swat",
    # Gwadar
    "gawadar": "Gwadar", "gwadar ": "Gwadar",
    "\u06af\u0648\u0627\u062f\u0631": "Gwadar",
    # Rahim Yar Khan
    "ryk": "Rahim Yar Khan", "rahim yar khan ": "Rahim Yar Khan",
    # Dera Ismail Khan
    "d.i. khan": "Dera Ismail Khan", "dikhan": "Dera Ismail Khan",
    "di khan": "Dera Ismail Khan", "dera ismail khan ": "Dera Ismail Khan",
    "d.i.khan": "Dera Ismail Khan", "d i khan": "Dera Ismail Khan",
    # Mirpur Khas
    "mirpurkhas": "Mirpur Khas", "mirpur-khas": "Mirpur Khas",
    "mirpur khas ": "Mirpur Khas",
}

# Water source: Urdu → English
URDU_TO_ENG_WATER: dict[str, str] = {
    "\u067e\u0627\u0626\u067e":                "piped",
    "\u06c1\u06cc\u0646\u0688 \u067e\u0645\u067e": "handpump",
    "\u06a9\u0646\u0648\u0627\u06ba":           "well",
    "\u0679\u06cc\u0646\u06a9\u0631":           "tanker",
    "\u062f\u0631\u06cc\u0627":                 "river",
    "\u0646\u06c1\u0631":                       "canal",
}

# SES tier: Urdu → English
URDU_TO_ENG_SES: dict[str, str] = {
    "\u06a9\u0645":                             "low",
    "\u062f\u0631\u0645\u06cc\u0627\u0646\u06c1": "middle",
    "\u0632\u06cc\u0627\u062f\u06c1":           "high",
}

# Yes/No: all variants → 0/1
TRUTHY  = {"1", "yes", "y", "true", "t", "ok",
           "\u06c1\u0627\u06ba", "\u06c1\u0627\u06ba "}
FALSY   = {"0", "no", "n", "false", "f",
           "\u0646\u06c1\u06cc\u06ba", "\u0646\u06c1\u06cc\u06ba "}

# Date formats to try in order
DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y",
    "%d-%m-%Y", "%m-%d-%Y", "%Y/%m/%d", "%d.%m.%Y",
]

# Enumerator ID pattern: should be E followed by digits
_ENUM_ID_RE = re.compile(r"[Ee][Nn][Uu]?(\d+)|[Ee](\d+)")


# ---------------------------------------------------------------------------
# Atomic normalisation helpers
# ---------------------------------------------------------------------------

def _parse_date(val: Any) -> pd.Timestamp | None:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return None
    for fmt in DATE_FORMATS:
        try:
            return pd.Timestamp(datetime.strptime(s, fmt))
        except ValueError:
            pass
    try:
        return pd.Timestamp(s)
    except Exception:
        return None


def _yesno(val: Any) -> int | None:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    s = str(val).strip().lower()
    if s in TRUTHY:
        return 1
    if s in FALSY:
        return 0
    try:
        v = int(float(s))
        return 1 if v else 0
    except Exception:
        return None


def _normalise_district(val: Any) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return val
    s = str(val).strip()
    # 1. Exact override match (handles Urdu script and known typos)
    if s in DISTRICT_OVERRIDES:
        return DISTRICT_OVERRIDES[s]
    # 2. Case-insensitive override match
    s_lower = s.lower()
    for k, v in DISTRICT_OVERRIDES.items():
        if k.lower() == s_lower:
            return v
    # 3. Case-insensitive exact match against canonical list
    if s_lower in _DISTRICT_LOWER:
        return _DISTRICT_LOWER[s_lower]
    # 4. Trailing-space stripped
    stripped = s_lower.rstrip()
    if stripped in _DISTRICT_LOWER:
        return _DISTRICT_LOWER[stripped]
    # 5. Partial match — canonical name contains input or vice versa
    for canonical_lower, canonical in _DISTRICT_LOWER.items():
        if s_lower in canonical_lower or canonical_lower in s_lower:
            return canonical
    # 6. Title-case fallback (preserves unknown districts)
    return s.title()


def _normalise_water(val: Any) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return val
    s = str(val).strip()
    if s in URDU_TO_ENG_WATER:
        return URDU_TO_ENG_WATER[s]
    return s.lower().strip()


def _normalise_ses(val: Any) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return val
    s = str(val).strip()
    if s in URDU_TO_ENG_SES:
        return URDU_TO_ENG_SES[s]
    return s.lower().strip()


def _normalise_enum_id(val: Any) -> str:
    """Standardise enumerator ID to E### format."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return val
    s = str(val).strip()
    m = _ENUM_ID_RE.search(s)
    if m:
        num = m.group(1) or m.group(2)
        return f"E{int(num):03d}"
    return s  # unknown format — keep as-is


def _clip_numeric(series: pd.Series, lo: float, hi: float) -> tuple[pd.Series, int]:
    """Null values outside [lo, hi]. Returns (cleaned series, count nulled)."""
    mask = series.notna() & ((series < lo) | (series > hi))
    count = int(mask.sum())
    series = series.copy()
    series[mask] = np.nan
    return series, count


# ---------------------------------------------------------------------------
# 1. Households
# ---------------------------------------------------------------------------

def transform_households(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Clean household enrollment data.

    DQ issues resolved:
      - Duplicate submissions (keep latest by submission_time)
      - Urdu district names / typos → canonical English
      - Urdu water_source / ses_tier → English
      - Urdu has_toilet / consent_given → 0/1
      - Non-ISO enrollment_date formats → ISO
      - Implausible respondent_age (< 15 or > 65) → null
      - Implausible household_size (> 25) → null
      - GPS outside Pakistan bounding box → null
      - No-consent records → dropped
      - Enumerator ID format inconsistencies → E### standard
    """
    df = raw.copy()
    initial = len(df)
    issues: dict[str, int] = {}

    # ── Column names ──────────────────────────────────────────────────────
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    # ── Drop rows with no household_id ────────────────────────────────────
    before = len(df)
    df = df.dropna(subset=["household_id"])
    if len(df) < before:
        issues["missing_hh_id_dropped"] = before - len(df)

    # ── Deduplicate: keep latest submission per household_id ──────────────
    if "submission_time" in df.columns:
        df["submission_time"] = pd.to_datetime(df["submission_time"], errors="coerce")
        before = len(df)
        df = df.sort_values("submission_time", ascending=False).drop_duplicates("household_id")
        dupes = before - len(df)
        if dupes:
            issues["duplicates_removed"] = dupes
            logger.info(f"  HH: removed {dupes:,} duplicate submissions")

    # ── District normalisation ────────────────────────────────────────────
    if "district" in df.columns:
        orig = df["district"].copy()
        df["district"] = df["district"].apply(_normalise_district)
        changed = int((orig.fillna("") != df["district"].fillna("")).sum())
        if changed:
            issues["district_normalised"] = changed

    # ── Province: fill from district if missing ───────────────────────────
    if "province" not in df.columns or df["province"].isna().any():
        try:
            from data_generator.config import DISTRICT_PROVINCE_MAP
            if "province" not in df.columns:
                df["province"] = df["district"].map(DISTRICT_PROVINCE_MAP)
            else:
                mask = df["province"].isna()
                df.loc[mask, "province"] = df.loc[mask, "district"].map(DISTRICT_PROVINCE_MAP)
        except ImportError:
            pass

    # ── Water source normalisation ────────────────────────────────────────
    if "water_source" in df.columns:
        orig = df["water_source"].copy()
        df["water_source"] = df["water_source"].apply(_normalise_water)
        changed = int((orig.fillna("") != df["water_source"].fillna("")).sum())
        if changed:
            issues["water_source_normalised"] = changed

    # ── SES tier normalisation ────────────────────────────────────────────
    if "ses_tier" in df.columns:
        orig = df["ses_tier"].copy()
        df["ses_tier"] = df["ses_tier"].apply(_normalise_ses)
        changed = int((orig.fillna("") != df["ses_tier"].fillna("")).sum())
        if changed:
            issues["ses_tier_normalised"] = changed

    # ── Boolean fields ────────────────────────────────────────────────────
    for col in ["consent_given", "has_toilet"]:
        if col in df.columns:
            df[col] = df[col].apply(_yesno)

    # ── Date parsing ──────────────────────────────────────────────────────
    if "enrollment_date" in df.columns:
        df["enrollment_date"] = df["enrollment_date"].apply(_parse_date)
        bad = int(df["enrollment_date"].isna().sum())
        if bad:
            issues["bad_enrollment_dates"] = bad

    # ── Numeric coercions ─────────────────────────────────────────────────
    for col in ["household_size", "children_under_5", "women_15_49", "respondent_age"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── Plausibility: respondent age ──────────────────────────────────────
    if "respondent_age" in df.columns:
        df["respondent_age"], n = _clip_numeric(df["respondent_age"], 15, 65)
        if n:
            issues["implausible_respondent_age"] = n

    # ── Plausibility: household size ──────────────────────────────────────
    if "household_size" in df.columns:
        df["household_size"], n = _clip_numeric(df["household_size"], 1, 25)
        if n:
            issues["implausible_hh_size"] = n

    # ── GPS bounds (Pakistan: lat 23.5–37.5, lon 60.5–77.5) ──────────────
    for lat_col, lon_col in [("gps_latitude", "gps_longitude")]:
        if lat_col in df.columns and lon_col in df.columns:
            df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
            df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
            bad_mask = (
                df[lat_col].notna() & (
                    ~df[lat_col].between(23.5, 37.5) |
                    ~df[lon_col].between(60.5, 77.5)
                )
            )
            n = int(bad_mask.sum())
            if n:
                issues["gps_out_of_bounds_nulled"] = n
                df.loc[bad_mask, [lat_col, lon_col]] = np.nan

    # ── Enumerator ID standardisation ────────────────────────────────────
    if "enumerator_id" in df.columns:
        orig = df["enumerator_id"].copy()
        df["enumerator_id"] = df["enumerator_id"].apply(_normalise_enum_id)
        changed = int((orig.fillna("") != df["enumerator_id"].fillna("")).sum())
        if changed:
            issues["enum_id_standardised"] = changed

    # ── Consent filter ────────────────────────────────────────────────────
    if "consent_given" in df.columns:
        no_consent = int((df["consent_given"] != 1).sum())
        if no_consent:
            issues["no_consent_dropped"] = no_consent
        df = df[df["consent_given"] == 1]

    final = len(df)
    total_issues = sum(issues.values())
    logger.info(
        f"  Households: {initial:,} raw -> {final:,} clean "
        f"({initial - final:,} dropped, {total_issues:,} DQ fixes) | {issues}"
    )
    df.attrs["quality_issues"] = issues
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 2. Follow-up Visits
# ---------------------------------------------------------------------------

def transform_followup_visits(raw: pd.DataFrame) -> pd.DataFrame:
    """
    Clean follow-up visit records (child + maternal).

    DQ issues resolved:
      - Duplicate visit_ids → deduplicated
      - Urdu district names → canonical English
      - Urdu yes/no in boolean columns → 0/1
      - Non-ISO visit_date formats → ISO
      - Implausible child anthropometry → nulled
      - Z-scores |z| > 6 (WHO implausible flag) → nulled
      - Implausible maternal age → nulled
      - Enumerator ID format → E### standard
      - Derived columns: child_age_group, maternal_age_group
    """
    df = raw.copy()
    initial = len(df)
    issues: dict[str, int] = {}

    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    # ── Drop rows missing primary keys ────────────────────────────────────
    before = len(df)
    df = df.dropna(subset=["visit_id", "household_id"])
    if len(df) < before:
        issues["missing_pk_dropped"] = before - len(df)

    # ── Deduplicate on visit_id ───────────────────────────────────────────
    before = len(df)
    df = df.drop_duplicates("visit_id")
    if len(df) < before:
        issues["duplicate_visit_ids"] = before - len(df)

    # ── District normalisation ────────────────────────────────────────────
    if "district" in df.columns:
        orig = df["district"].copy()
        df["district"] = df["district"].apply(_normalise_district)
        changed = int((orig.fillna("") != df["district"].fillna("")).sum())
        if changed:
            issues["district_normalised"] = changed

    # ── Province: fill from district if missing ───────────────────────────
    if "province" not in df.columns or df["province"].isna().any():
        try:
            from data_generator.config import DISTRICT_PROVINCE_MAP
            if "province" not in df.columns:
                df["province"] = df["district"].map(DISTRICT_PROVINCE_MAP)
            else:
                mask = df["province"].isna()
                df.loc[mask, "province"] = df.loc[mask, "district"].map(DISTRICT_PROVINCE_MAP)
        except ImportError:
            pass

    # ── Boolean fields (Urdu yes/no → 0/1) ───────────────────────────────
    bool_cols = [
        "anemia", "diarrhea_2w", "ari_2w", "fever_2w",
        "vaccination_full", "currently_pregnant", "anc_4plus",
        "last_delivery_skilled",
    ]
    for col in bool_cols:
        if col in df.columns:
            before_nulls = int(df[col].isna().sum())
            df[col] = df[col].apply(_yesno)
            after_nulls = int(df[col].isna().sum())
            converted = max(0, before_nulls - after_nulls)
            if converted:
                issues[f"{col}_converted"] = converted

    # ── Date parsing ──────────────────────────────────────────────────────
    if "visit_date" in df.columns:
        df["visit_date"] = df["visit_date"].apply(_parse_date)
        bad = int(df["visit_date"].isna().sum())
        if bad:
            issues["bad_visit_dates"] = bad

    # ── Numeric coercions ─────────────────────────────────────────────────
    num_cols = [
        "child_age_months", "height_cm", "weight_kg", "muac_mm",
        "haz_score", "waz_score", "whz_score",
        "hemoglobin_gdl", "maternal_age", "interview_duration_min",
    ]
    for col in num_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── Child anthropometry plausibility ─────────────────────────────────
    if "record_type" in df.columns:
        child_mask = df["record_type"] == "child"
        mat_mask   = df["record_type"] == "maternal"

        for col, lo, hi in [
            ("height_cm", 40.0, 130.0),
            ("weight_kg",  1.5,  30.0),
            ("muac_mm",   80.0, 200.0),
        ]:
            if col in df.columns:
                bad_mask = child_mask & df[col].notna() & ((df[col] < lo) | (df[col] > hi))
                n = int(bad_mask.sum())
                if n:
                    issues[f"implausible_{col}"] = n
                df.loc[bad_mask, col] = np.nan

        # ── Z-score plausibility (WHO: |z| > 6 = implausible) ────────────
        for z in ["haz_score", "waz_score", "whz_score"]:
            if z in df.columns:
                bad_mask = df[z].notna() & (df[z].abs() > 6)
                n = int(bad_mask.sum())
                if n:
                    issues[f"implausible_{z}"] = n
                df.loc[bad_mask, z] = np.nan

        # ── Maternal age plausibility ─────────────────────────────────────
        if "maternal_age" in df.columns:
            bad_mask = mat_mask & df["maternal_age"].notna() & (
                (df["maternal_age"] < 10) | (df["maternal_age"] > 60)
            )
            n = int(bad_mask.sum())
            if n:
                issues["implausible_maternal_age"] = n
            df.loc[bad_mask, "maternal_age"] = np.nan

        # ── Hemoglobin plausibility ───────────────────────────────────────
        if "hemoglobin_gdl" in df.columns:
            bad_mask = df["hemoglobin_gdl"].notna() & (
                (df["hemoglobin_gdl"] < 3.0) | (df["hemoglobin_gdl"] > 20.0)
            )
            n = int(bad_mask.sum())
            if n:
                issues["implausible_hemoglobin"] = n
            df.loc[bad_mask, "hemoglobin_gdl"] = np.nan

    # ── Enumerator ID standardisation ────────────────────────────────────
    if "enumerator_id" in df.columns:
        orig = df["enumerator_id"].copy()
        df["enumerator_id"] = df["enumerator_id"].apply(_normalise_enum_id)
        changed = int((orig.fillna("") != df["enumerator_id"].fillna("")).sum())
        if changed:
            issues["enum_id_standardised"] = changed

    # ── Derived: child age group ──────────────────────────────────────────
    if "child_age_months" in df.columns:
        df["child_age_group"] = pd.cut(
            df["child_age_months"],
            bins=[-1, 5, 11, 23, 35, 59],
            labels=["0-5m", "6-11m", "12-23m", "24-35m", "36-59m"],
        )

    # ── Derived: maternal age group ───────────────────────────────────────
    if "maternal_age" in df.columns:
        df["maternal_age_group"] = pd.cut(
            df["maternal_age"],
            bins=[14, 19, 24, 29, 34, 49],
            labels=["15-19", "20-24", "25-29", "30-34", "35-49"],
        )

    final = len(df)
    total_issues = sum(issues.values())
    logger.info(
        f"  Visits: {initial:,} raw -> {final:,} clean "
        f"({initial - final:,} dropped, {total_issues:,} DQ fixes) | {issues}"
    )
    df.attrs["quality_issues"] = issues
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 3. Facility Assessments
# ---------------------------------------------------------------------------

def transform_facility_assessments(raw: pd.DataFrame) -> pd.DataFrame:
    """Clean facility assessment records."""
    df = raw.copy()
    issues: dict[str, int] = {}

    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
    before = len(df)
    df = df.dropna(subset=["assessment_id"]).drop_duplicates("assessment_id")
    if len(df) < before:
        issues["duplicates_dropped"] = before - len(df)

    if "assessment_date" in df.columns:
        df["assessment_date"] = df["assessment_date"].apply(_parse_date)

    for col in ["readiness_score", "overall_score"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").clip(0, 100)

    for col in ["has_electricity", "has_water", "has_toilet"]:
        if col in df.columns:
            df[col] = df[col].apply(_yesno)

    for col in [c for c in df.columns if c.startswith("stockout_")]:
        df[col] = df[col].apply(_yesno)

    if "district" in df.columns:
        df["district"] = df["district"].apply(_normalise_district)

    logger.info(f"  Facilities: {len(df):,} clean records | {issues}")
    df.attrs["quality_issues"] = issues
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 4. Enumerator Performance
# ---------------------------------------------------------------------------

def transform_enumerator_performance(raw: pd.DataFrame) -> pd.DataFrame:
    """Clean enumerator performance logs."""
    df = raw.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    if "date" in df.columns:
        df["date"] = df["date"].apply(_parse_date)

    if "enumerator_id" in df.columns:
        df["enumerator_id"] = df["enumerator_id"].apply(_normalise_enum_id)

    for col in ["submissions", "short_interviews", "flagged_for_backcheck"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "avg_duration_min" in df.columns:
        df["avg_duration_min"] = pd.to_numeric(df["avg_duration_min"], errors="coerce")
        df["avg_duration_min"], _ = _clip_numeric(df["avg_duration_min"], 0, 480)

    logger.info(f"  Enumerator perf: {len(df):,} records")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# 5. Back-check Records
# ---------------------------------------------------------------------------

def transform_backcheck_records(raw: pd.DataFrame) -> pd.DataFrame:
    """Clean back-check audit records."""
    df = raw.copy()
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    if "backcheck_id" in df.columns:
        df = df.drop_duplicates("backcheck_id")

    for col in ["height_original_cm", "height_recheck_cm",
                "weight_original_kg", "weight_recheck_kg",
                "height_discrepancy_cm", "weight_discrepancy_kg"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in ["morbidity_match", "overall_pass"]:
        if col in df.columns:
            df[col] = df[col].apply(_yesno)

    if "backcheck_enumerator_id" in df.columns:
        df["backcheck_enumerator_id"] = df["backcheck_enumerator_id"].apply(_normalise_enum_id)

    logger.info(f"  Back-checks: {len(df):,} records")
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Gold: Fact table builders
# ---------------------------------------------------------------------------

def build_fct_child_nutrition(
    visits: pd.DataFrame,
    households: pd.DataFrame,
) -> pd.DataFrame:
    """Build child nutrition fact table — one row per child per visit round."""
    child = visits[visits["record_type"] == "child"].copy() if "record_type" in visits.columns else visits.copy()

    # Merge household-level attributes — but only columns NOT already in visits
    # to avoid province_x / province_y conflicts
    hh_cols_wanted = [
        "household_id", "province", "ses_tier",
        "nearest_facility_id", "nearest_facility_type",
        "distance_to_facility_km", "urban_rural",
    ]
    hh_cols = [c for c in hh_cols_wanted
               if c in households.columns and (c == "household_id" or c not in child.columns)]

    if len(hh_cols) > 1 and "household_id" in child.columns:
        child = child.merge(households[hh_cols], on="household_id", how="left")

    # If province still missing, fill from district map
    if "province" not in child.columns or child["province"].isna().all():
        try:
            from data_generator.config import DISTRICT_PROVINCE_MAP
            child["province"] = child["district"].map(DISTRICT_PROVINCE_MAP)
        except ImportError:
            pass

    keep = [
        "visit_id", "household_id", "visit_round", "visit_date",
        "province", "district", "union_council", "ses_tier", "urban_rural",
        "child_age_months", "child_age_group", "child_sex",
        "haz_score", "waz_score", "whz_score",
        "stunted", "wasted", "underweight", "severe_stunted", "severe_wasted",
        "anemia", "diarrhea_2w", "ari_2w", "fever_2w",
        "vaccination_full", "exclusive_bf",
        "interview_duration_min", "short_interview_flag",
        "nearest_facility_id", "nearest_facility_type", "distance_to_facility_km",
    ]
    return child[[c for c in keep if c in child.columns]].reset_index(drop=True)


def build_fct_maternal_health(
    visits: pd.DataFrame,
    households: pd.DataFrame,
) -> pd.DataFrame:
    """Build maternal health fact table — one row per woman per visit round."""
    mat = visits[visits["record_type"] == "maternal"].copy() if "record_type" in visits.columns else visits.copy()

    hh_cols_wanted = ["household_id", "province", "ses_tier", "urban_rural"]
    hh_cols = [c for c in hh_cols_wanted
               if c in households.columns and (c == "household_id" or c not in mat.columns)]

    if len(hh_cols) > 1 and "household_id" in mat.columns:
        mat = mat.merge(households[hh_cols], on="household_id", how="left")

    if "province" not in mat.columns or mat["province"].isna().all():
        try:
            from data_generator.config import DISTRICT_PROVINCE_MAP
            mat["province"] = mat["district"].map(DISTRICT_PROVINCE_MAP)
        except ImportError:
            pass

    keep = [
        "visit_id", "household_id", "visit_round", "visit_date",
        "province", "district", "union_council", "ses_tier", "urban_rural",
        "maternal_age", "maternal_age_group",
        "currently_pregnant", "anc_4plus", "last_delivery_skilled",
        "anemia", "hemoglobin_gdl",
        "interview_duration_min", "short_interview_flag",
    ]
    return mat[[c for c in keep if c in mat.columns]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Gold: Reporting aggregations
# ---------------------------------------------------------------------------

def build_rpt_district_summary(
    fct_child: pd.DataFrame,
    fct_maternal: pd.DataFrame,
) -> pd.DataFrame:
    """Build district-level KPI summary for dashboards."""
    group_cols = [c for c in ["province", "district", "visit_round"] if c in fct_child.columns]

    child_agg = (
        fct_child.groupby(group_cols)
        .agg(
            children_measured    = ("visit_id", "count"),
            stunting_rate        = ("stunted",          lambda x: pd.to_numeric(x, errors="coerce").mean()),
            wasting_rate         = ("wasted",           lambda x: pd.to_numeric(x, errors="coerce").mean()),
            underweight_rate     = ("underweight",      lambda x: pd.to_numeric(x, errors="coerce").mean()),
            anemia_children_rate = ("anemia",           lambda x: pd.to_numeric(x, errors="coerce").mean()),
            diarrhea_rate        = ("diarrhea_2w",      lambda x: pd.to_numeric(x, errors="coerce").mean()),
            vaccination_rate     = ("vaccination_full", lambda x: pd.to_numeric(x, errors="coerce").mean()),
        )
        .reset_index()
    )

    mat_group = [c for c in group_cols if c in fct_maternal.columns]
    maternal_agg = (
        fct_maternal.groupby(mat_group)
        .agg(
            women_assessed        = ("visit_id", "count"),
            anemia_maternal_rate  = ("anemia",                lambda x: pd.to_numeric(x, errors="coerce").mean()),
            anc_4plus_rate        = ("anc_4plus",             lambda x: pd.to_numeric(x, errors="coerce").mean()),
            skilled_delivery_rate = ("last_delivery_skilled", lambda x: pd.to_numeric(x, errors="coerce").mean()),
        )
        .reset_index()
    )

    summary = child_agg.merge(maternal_agg, on=mat_group, how="outer")
    rate_cols = [c for c in summary.columns if c.endswith("_rate")]
    summary[rate_cols] = summary[rate_cols].round(4)

    logger.info(f"  District summary: {len(summary):,} rows")
    return summary


# ---------------------------------------------------------------------------
# Gold: Data quality report
# ---------------------------------------------------------------------------

def build_data_quality_report(
    raw_datasets: dict[str, pd.DataFrame],
    clean_datasets: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """
    Cross-dataset DQ summary — shows what was found and fixed per dataset.
    Consumed by the pipeline dashboard page.
    """
    rows = []
    for name, raw in raw_datasets.items():
        clean = clean_datasets.get(name, pd.DataFrame())
        if raw.empty:
            continue

        raw_rows   = len(raw)
        clean_rows = len(clean)
        dropped    = raw_rows - clean_rows

        # Count bilingual values in raw
        bilingual = 0
        for col in ["water_source", "ses_tier", "district"]:
            if col in raw.columns:
                bilingual += int(
                    raw[col].astype(str).str.contains(
                        "\u067e\u0627\u0626\u067e|\u06c1\u06cc\u0646\u0688|\u06a9\u0646\u0648\u0627\u06ba"
                        "|\u06a9\u0645|\u062f\u0631\u0645\u06cc\u0627\u0646\u06c1|\u0632\u06cc\u0627\u062f\u06c1"
                        "|\u0644\u0627\u06c1\u0648\u0631|\u06a9\u0631\u0627\u0686\u06cc",
                        na=False,
                    ).sum()
                )

        # Count duplicates in raw
        pk_col = next((c for c in ["household_id", "visit_id", "assessment_id"] if c in raw.columns), None)
        dupes = int(raw.duplicated(subset=[pk_col]).sum()) if pk_col else 0

        # Missing value rate
        missing_pct = round(raw.isna().mean().mean() * 100, 1)

        # Quality issues from attrs if available
        qi = clean.attrs.get("quality_issues", {}) if not clean.empty else {}

        rows.append({
            "dataset":            name,
            "raw_rows":           raw_rows,
            "clean_rows":         clean_rows,
            "rows_dropped":       dropped,
            "drop_pct":           round(dropped / raw_rows * 100, 1) if raw_rows else 0,
            "missing_pct_raw":    missing_pct,
            "duplicates_raw":     dupes,
            "bilingual_values":   bilingual,
            "dq_fixes_applied":   sum(qi.values()),
            "status":             "OK" if missing_pct < 15 and dupes == 0 else "Review",
        })

    return pd.DataFrame(rows)
