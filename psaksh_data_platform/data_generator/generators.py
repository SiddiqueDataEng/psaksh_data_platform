"""
Pakistan-wide synthetic data generators for PSAKSH survey instruments.

Generates realistic, large-scale public health survey data covering
all 4 provinces, 36 districts, 180 union councils across Pakistan.

Instruments:
  1. Household Enrollment (baseline)
  2. Follow-up Visits (quarterly, child + maternal)
  3. Facility Assessments
  4. Enumerator Performance Logs
  5. Back-check / Audit Records

Parameters (all generators):
  start_date  : ISO date string — earliest enrollment/visit date (default: STUDY_START_DATE)
  end_date    : ISO date string — latest enrollment/visit date   (default: STUDY_END_DATE)
  min_records : minimum records to generate (random between min and max)
  max_records : maximum records to generate (random between min and max)
  seed        : RNG seed for reproducibility (default: 42)

Unique household IDs are guaranteed via UUID — no accidental duplicates.
Deliberate DQ issues are injected at documented rates (see DQ_RATES in config).
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

from .config import (
    DISTRICTS,
    DISTRICT_PROVINCE_MAP,
    DISTRICT_INFO_MAP,
    ENUMERATORS,
    HEALTH_FACILITIES,
    PAKISTAN_DISTRICTS,
    PREVALENCE,
    PROVINCE_PROFILES,
    SES_TIERS,
    SES_WEIGHTS,
    STUDY_END_DATE,
    STUDY_START_DATE,
    UNION_COUNCILS,
    URDU_NAMES_FEMALE,
    URDU_NAMES_MALE,
    URDU_SURNAMES,
    URDU_WATER_SOURCES,
    URDU_SES_TIERS,
    URDU_YES_NO,
    DATA_QUALITY_RATE,
    DQ_RATES,
)

RNG = np.random.default_rng(42)

# Pre-build lookup: district -> list of enumerators
_ENUM_BY_DISTRICT: dict[str, list[dict]] = {}
for _e in ENUMERATORS:
    _ENUM_BY_DISTRICT.setdefault(_e["district"], []).append(_e)

# Pre-build lookup: district -> list of facilities
_FAC_BY_DISTRICT: dict[str, list[dict]] = {}
for _f in HEALTH_FACILITIES:
    _FAC_BY_DISTRICT.setdefault(_f["district"], []).append(_f)

# Province weights for district sampling (proportional to population)
_PROVINCE_WEIGHTS = {"Punjab": 0.53, "Sindh": 0.23, "KPK": 0.15, "Balochistan": 0.09}
_PROVINCE_DISTRICTS = {p: [d["name"] for d in dlist]
                       for p, dlist in PAKISTAN_DISTRICTS.items()}


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _resolve_count(
    n: Optional[int],
    min_records: Optional[int],
    max_records: Optional[int],
    default: int,
    rng: np.random.Generator,
) -> int:
    """
    Resolve final record count from explicit n or random between min/max.
    Priority: n > random(min, max) > default
    """
    if n is not None:
        return max(1, int(n))
    if min_records is not None and max_records is not None:
        lo = max(1, int(min_records))
        hi = max(lo, int(max_records))
        return int(rng.integers(lo, hi + 1))
    if min_records is not None:
        return max(1, int(min_records))
    if max_records is not None:
        return max(1, int(max_records))
    return default


def _make_rng(seed: Optional[int]) -> np.random.Generator:
    """Create a fresh RNG — uses global RNG if no seed given."""
    return np.random.default_rng(seed) if seed is not None else RNG


def _random_date(start: str, end: str) -> datetime:
    """Return a random datetime between two ISO date strings."""
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end,   "%Y-%m-%d")
    delta = max(1, (e - s).days)
    return s + timedelta(days=int(RNG.integers(0, delta)))
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    return s + timedelta(days=int(RNG.integers(0, (e - s).days)))


def _bernoulli(p: float) -> int:
    return int(RNG.random() < p)


def _female_name() -> str:
    return f"{random.choice(URDU_NAMES_FEMALE)} {random.choice(URDU_SURNAMES)}"


def _male_name() -> str:
    return f"{random.choice(URDU_NAMES_MALE)} {random.choice(URDU_SURNAMES)}"


def _gps_jitter(lat: float, lon: float, radius_km: float = 8.0) -> tuple[float, float]:
    dlat = (RNG.random() - 0.5) * 2 * (radius_km / 111.0)
    dlon = (RNG.random() - 0.5) * 2 * (radius_km / (111.0 * np.cos(np.radians(lat))))
    return round(lat + dlat, 6), round(lon + dlon, 6)


def _province_prevalence(district: str, indicator: str) -> float:
    prov = DISTRICT_PROVINCE_MAP.get(district, "Punjab")
    return PROVINCE_PROFILES.get(prov, PREVALENCE).get(indicator, PREVALENCE[indicator])


def _sample_district() -> str:
    """Sample a district proportional to province population weights."""
    prov = random.choices(
        list(_PROVINCE_WEIGHTS.keys()),
        weights=list(_PROVINCE_WEIGHTS.values()),
    )[0]
    return random.choice(_PROVINCE_DISTRICTS[prov])


# ---------------------------------------------------------------------------
# DQ injectors — deliberate, documented, reproducible
# ---------------------------------------------------------------------------

def _dq_water(val: str) -> str:
    if RNG.random() < DQ_RATES["bilingual_field"]:
        return URDU_WATER_SOURCES.get(val, val)
    return val


def _dq_ses(val: str) -> str:
    if RNG.random() < DQ_RATES["bilingual_field"]:
        return URDU_SES_TIERS.get(val, val)
    return val


def _dq_yesno(val: int) -> Any:
    if RNG.random() < DQ_RATES["bilingual_field"]:
        return URDU_YES_NO[val]
    return val


def _dq_district(val: str) -> str:
    """Inject district name typos, case errors, or Urdu script."""
    if RNG.random() >= DQ_RATES["typo_district"]:
        return val
    typos = {
        "Lahore":           ["Lahor", "lahore", "LAHORE", "\u0644\u0627\u06c1\u0648\u0631"],
        "Karachi":          ["Karachi ", "karachi", "KARACHI", "\u06a9\u0631\u0627\u0686\u06cc"],
        "Peshawar":         ["Peshawer", "peshawar", "\u067e\u0634\u0627\u0648\u0631"],
        "Quetta":           ["Queta", "quetta", "\u06a9\u0648\u0626\u0679\u06c1"],
        "Faisalabad":       ["Faisalabad ", "faisalabad", "\u0641\u06cc\u0635\u0644 \u0622\u0628\u0627\u062f"],
        "Multan":           ["multan", "MULTAN", "\u0645\u0644\u062a\u0627\u0646"],
        "Rawalpindi":       ["Rawalpindi ", "rawalpindi", "\u0631\u0627\u0648\u0644\u067e\u0646\u0688\u06cc"],
        "Hyderabad":        ["Hydrabad", "hyderabad", "\u062d\u06cc\u062f\u0631\u0622\u0628\u0627\u062f"],
        "Sukkur":           ["Sukkar", "sukkur", "\u0633\u06a9\u06be\u0631"],
        "Swat":             ["swat", "SWAT", "\u0633\u0648\u0627\u062a"],
        "Gwadar":           ["Gawadar", "gwadar", "\u06af\u0648\u0627\u062f\u0631"],
        "Rahim Yar Khan":   ["Rahim Yar Khan ", "RYK", "rahim yar khan"],
        "Dera Ismail Khan": ["D.I. Khan", "DIKhan", "Dera Ismail Khan "],
        "Mirpur Khas":      ["Mirpurkhas", "mirpur khas", "Mirpur-Khas"],
    }
    choices = typos.get(val, [val.lower(), val.upper(), val + " "])
    return random.choice(choices)


def _dq_date(dt: datetime) -> str:
    if RNG.random() < DQ_RATES["bad_date_format"]:
        fmt = random.choice(["%d/%m/%Y", "%m-%d-%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"])
        return dt.strftime(fmt)
    return dt.strftime("%Y-%m-%d")


def _dq_missing(val: Any, p: float = 0.05) -> Any:
    return None if RNG.random() < p else val


def _dq_age(age: int) -> Any:
    if RNG.random() < DQ_RATES["outlier_age"]:
        return random.choice([0, 5, 99, 120, -1, 999])
    return age


def _dq_height(h: float) -> float:
    if RNG.random() < DQ_RATES["outlier_height"]:
        return random.choice([5.0, 200.0, 999.0, 0.5, -1.0])
    return h


def _dq_weight(w: float) -> float:
    if RNG.random() < DQ_RATES["outlier_weight"]:
        return random.choice([0.1, 50.0, 100.0, -5.0, 999.0])
    return w


def _dq_enum_id(eid: str) -> str:
    """Occasionally mangle enumerator ID format."""
    if RNG.random() < DQ_RATES["enum_id_typo"]:
        return random.choice([
            eid.lower(),
            eid.replace("E", "e"),
            eid + " ",
            eid[1:],          # drop the E prefix
            "ENU" + eid[1:],  # wrong prefix
        ])
    return eid


# ---------------------------------------------------------------------------
# 1. Household Enrollment
# ---------------------------------------------------------------------------

def generate_households(
    n: Optional[int] = 5000,
    *,
    start_date:  Optional[str] = None,
    end_date:    Optional[str] = None,
    min_records: Optional[int] = None,
    max_records: Optional[int] = None,
    seed:        Optional[int] = None,
) -> pd.DataFrame:
    """
    Generate household enrollment records covering all Pakistan districts.

    Args:
        n           : Exact number of households (overrides min/max if given).
        start_date  : Earliest enrollment date YYYY-MM-DD (default: STUDY_START_DATE).
        end_date    : Latest enrollment date YYYY-MM-DD   (default: STUDY_END_DATE).
        min_records : Minimum households when using random count.
        max_records : Maximum households when using random count.
        seed        : RNG seed for reproducibility.

    Returns:
        DataFrame with one row per household (+ ~4.5% deliberate duplicates).
    """
    rng    = _make_rng(seed)
    n      = _resolve_count(n, min_records, max_records, 5000, rng)
    _start = start_date or STUDY_START_DATE
    _end   = end_date   or STUDY_END_DATE

    # Validate / clamp dates
    try:
        _s = datetime.strptime(_start, "%Y-%m-%d")
        _e = datetime.strptime(_end,   "%Y-%m-%d")
        if _e <= _s:
            _e = _s + timedelta(days=365)
            _end = _e.strftime("%Y-%m-%d")
    except ValueError:
        _start, _end = STUDY_START_DATE, STUDY_END_DATE

    records: list[dict] = []
    seen_ids: set[str] = set()

    # Distribute households across districts proportional to province population
    district_counts: dict[str, int] = {}
    for _ in range(n):
        d = _sample_district()
        district_counts[d] = district_counts.get(d, 0) + 1

    hh_counter = 0
    for district, count in district_counts.items():
        province = DISTRICT_PROVINCE_MAP.get(district, "Punjab")
        ucs      = UNION_COUNCILS.get(district, ["UC-1"])
        enums    = _ENUM_BY_DISTRICT.get(district, ENUMERATORS[:1])
        facs     = _FAC_BY_DISTRICT.get(district, HEALTH_FACILITIES[:1])
        d_info   = DISTRICT_INFO_MAP.get(district, {"lat": 30.0, "lon": 70.0})

        for _ in range(count):
            hh_counter += 1

            # Guaranteed unique ID
            hh_id = f"HH{uuid.uuid4().hex[:10].upper()}"
            while hh_id in seen_ids:
                hh_id = f"HH{uuid.uuid4().hex[:10].upper()}"
            seen_ids.add(hh_id)

            uc       = random.choice(ucs)
            enum     = random.choice(enums)
            fac      = random.choice(facs)
            ses_tier = random.choices(SES_TIERS, weights=SES_WEIGHTS)[0]
            lat, lon = _gps_jitter(d_info["lat"], d_info["lon"])
            enroll_dt = _random_date(_start, _end)

            hh_size  = int(RNG.integers(3, 14))
            children = int(RNG.integers(0, min(hh_size, 6)))
            women    = int(RNG.integers(1, min(hh_size, 5)))
            age      = int(RNG.integers(18, 55))

            water_src = random.choices(
                ["piped", "handpump", "well", "tanker", "river", "canal"],
                weights=[0.22, 0.40, 0.18, 0.10, 0.06, 0.04],
            )[0]

            # Urban/rural adjustment
            is_urban = d_info.get("urban", False)
            toilet_p = 0.78 if is_urban else 0.52

            rec = {
                "household_id":            hh_id,
                "province":                province,
                "district":                _dq_district(district),
                "union_council":           uc,
                "enumerator_id":           _dq_enum_id(enum["id"]),
                "respondent_name":         _female_name(),
                "respondent_age":          _dq_age(age),
                "household_size":          hh_size,
                "children_under_5":        children,
                "women_15_49":             women,
                "ses_tier":                _dq_ses(ses_tier),
                "water_source":            _dq_water(water_src),
                "has_toilet":              _dq_yesno(_bernoulli(toilet_p)),
                "consent_given":           _dq_yesno(1) if RNG.random() > 0.02 else 0,
                "enrollment_date":         _dq_date(enroll_dt),
                "submission_time":         enroll_dt.strftime("%Y-%m-%d %H:%M:%S"),
                "gps_latitude":            _dq_missing(lat, p=DQ_RATES["missing_gps"]),
                "gps_longitude":           _dq_missing(lon, p=DQ_RATES["missing_gps"]),
                "nearest_facility_id":     fac["id"],
                "nearest_facility_type":   fac["type"],
                "distance_to_facility_km": round(float(RNG.uniform(0.3, 20.0)), 2),
                "urban_rural":             "urban" if is_urban else "rural",
                "notes": _dq_missing(None, p=0.90) or random.choice([
                    "\u06af\u06be\u0631 \u0645\u06cc\u06ba \u06a9\u0648\u0626\u06cc \u0646\u06c1\u06cc\u06ba \u062a\u06be\u0627\u060c \u062f\u0648\u0628\u0627\u0631\u06c1 \u0622\u0626\u06cc\u06ba",
                    "Respondent was cooperative",
                    "GPS signal weak",
                    "\u062f\u0648\u0628\u0627\u0631\u06c1 \u062f\u0648\u0631\u06c1 \u0636\u0631\u0648\u0631\u06cc \u06c1\u06d2",
                    "Household absent — revisit scheduled",
                    "Consent obtained verbally",
                    "",
                ]),
            }

            records.append(rec)

            # Deliberate duplicate submission (~4.5% of households)
            if RNG.random() < DQ_RATES["duplicate_hh"]:
                dup = rec.copy()
                dup["submission_time"] = (
                    enroll_dt + timedelta(minutes=random.randint(2, 120))
                ).strftime("%Y-%m-%d %H:%M:%S")
                # Slightly different GPS to simulate re-submission from different location
                if dup["gps_latitude"] is not None and dup["gps_longitude"] is not None:
                    dup["gps_latitude"]  = round(float(dup["gps_latitude"])  + float(RNG.normal(0, 0.001)), 6)
                    dup["gps_longitude"] = round(float(dup["gps_longitude"]) + float(RNG.normal(0, 0.001)), 6)
                records.append(dup)

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 2. Follow-up Visits (child + maternal)
# ---------------------------------------------------------------------------

def generate_followup_visits(
    households_df: pd.DataFrame,
    rounds: int = 4,
    *,
    start_date:  Optional[str] = None,
    end_date:    Optional[str] = None,
    seed:        Optional[int] = None,
) -> pd.DataFrame:
    """
    Generate quarterly follow-up visit records for each enrolled household.

    Args:
        households_df : Output of generate_households().
        rounds        : Number of follow-up rounds (default 4 = quarterly for 1 year).
        start_date    : Override earliest visit date YYYY-MM-DD.
        end_date      : Override latest visit date YYYY-MM-DD.
        seed          : RNG seed for reproducibility.
        - One child record per child under 5 per round
    - One maternal record per woman 15-49 per round
    - Province-specific prevalence rates
    - ~8% attrition per round (household not found)
    - Deliberate DQ issues injected at documented rates
    """
    records: list[dict] = []
    round_offsets = [0, 90, 180, 270]   # days from enrollment date

    for _, hh in households_df.iterrows():
        hh_id    = hh["household_id"]
        province = str(hh.get("province", "Punjab"))

        # Normalise district (strip DQ typos for logic)
        raw_dist = str(hh.get("district", "Lahore")).strip()
        district = raw_dist
        for d in DISTRICTS:
            if d.lower() in raw_dist.lower() or raw_dist.lower() in d.lower():
                district = d
                break

        uc       = hh.get("union_council", "UC-1")
        children = int(hh.get("children_under_5", 0) or 0)
        women    = int(hh.get("women_15_49", 1) or 1)
        enums    = _ENUM_BY_DISTRICT.get(district, ENUMERATORS[:1])

        # Get province-specific prevalence
        prev = PROVINCE_PROFILES.get(province, PREVALENCE)

        for rnd in range(1, rounds + 1):
            offset = round_offsets[rnd - 1]
            try:
                base_dt = datetime.strptime(str(hh["enrollment_date"])[:10], "%Y-%m-%d")
            except Exception:
                base_dt = datetime(2022, 6, 1)

            visit_dt = base_dt + timedelta(days=offset + int(RNG.integers(-10, 10)))

            # Attrition: ~8% per round, higher in Balochistan
            attrition = 0.12 if province == "Balochistan" else 0.08
            if RNG.random() < attrition:
                continue

            enum = random.choice(enums)

            # Short interview flag (potential fabrication)
            is_short_interview = RNG.random() < DQ_RATES["short_interview"]

            # ── Child records ──────────────────────────────────────────────
            n_children = max(1, children)
            for child_idx in range(n_children):
                child_age_m = int(RNG.integers(0, 60))
                child_sex   = random.choice(["male", "female"])

                # Province-adjusted z-scores
                stunt_adj = -0.3 if province == "Balochistan" else (0.1 if province == "Punjab" else 0.0)
                haz = float(RNG.normal(-1.8 + stunt_adj, 1.2))
                waz = float(RNG.normal(-1.5 + stunt_adj * 0.7, 1.1))
                whz = float(RNG.normal(-0.9 + stunt_adj * 0.5, 1.0))

                stunted        = int(haz < -2)
                wasted         = int(whz < -2)
                underweight    = int(waz < -2)
                severe_stunted = int(haz < -3)
                severe_wasted  = int(whz < -3)

                median_h = 45 + child_age_m * 0.7
                height   = round(median_h + haz * 4.5, 1)
                weight   = round((height / 100) ** 2 * (16 + waz * 1.5), 2)
                muac     = round(float(RNG.normal(135, 15)), 1)

                anemia   = _bernoulli(prev["anemia_child"])
                diarrhea = _bernoulli(prev["diarrhea_2w"])
                ari      = _bernoulli(prev["ari_2w"])
                fever    = _bernoulli(prev["fever_2w"])
                vacc     = _bernoulli(prev["vaccination_full"])
                excl_bf  = _bernoulli(prev["exclusive_bf"]) if child_age_m < 6 else 0

                # Short interview: compress duration
                duration = int(RNG.integers(5, 12)) if is_short_interview else int(RNG.integers(15, 50))

                records.append({
                    "visit_id":               f"V{uuid.uuid4().hex[:10].upper()}",
                    "household_id":           hh_id,
                    "province":               province,
                    "visit_round":            rnd,
                    "visit_date":             _dq_date(visit_dt),
                    "district":               _dq_district(district),
                    "union_council":          uc,
                    "enumerator_id":          _dq_enum_id(enum["id"]),
                    "record_type":            "child",
                    "child_age_months":       child_age_m,
                    "child_sex":              child_sex,
                    "height_cm":              _dq_height(height),
                    "weight_kg":              _dq_weight(weight),
                    "muac_mm":                _dq_missing(muac, p=DQ_RATES["missing_muac"]),
                    "haz_score":              round(haz, 3),
                    "waz_score":              round(waz, 3),
                    "whz_score":              round(whz, 3),
                    "stunted":                stunted,
                    "wasted":                 wasted,
                    "underweight":            underweight,
                    "severe_stunted":         severe_stunted,
                    "severe_wasted":          severe_wasted,
                    "anemia":                 _dq_yesno(anemia),
                    "diarrhea_2w":            _dq_yesno(diarrhea),
                    "ari_2w":                 _dq_yesno(ari),
                    "fever_2w":               _dq_yesno(fever),
                    "vaccination_full":       _dq_yesno(vacc),
                    "exclusive_bf":           excl_bf if child_age_m < 6 else None,
                    "interview_duration_min": _dq_missing(duration, p=0.03),
                    "short_interview_flag":   int(is_short_interview),
                    "maternal_age":           None,
                    "currently_pregnant":     None,
                    "anc_4plus":              None,
                    "last_delivery_skilled":  None,
                    "hemoglobin_gdl":         None,
                })

            # ── Maternal records ───────────────────────────────────────────
            n_women = max(1, women)
            for _ in range(n_women):
                mat_age     = int(RNG.integers(15, 50))
                pregnant    = _bernoulli(0.18)
                anc_4plus   = _bernoulli(prev["anc_4plus"])
                skilled_del = _bernoulli(prev["skilled_delivery"])
                anemia_m    = _bernoulli(prev["anemia_mother"])
                hb          = round(float(RNG.normal(11.2 if anemia_m else 12.8, 1.5)), 1)

                duration = int(RNG.integers(5, 10)) if is_short_interview else int(RNG.integers(12, 40))

                records.append({
                    "visit_id":               f"V{uuid.uuid4().hex[:10].upper()}",
                    "household_id":           hh_id,
                    "province":               province,
                    "visit_round":            rnd,
                    "visit_date":             _dq_date(visit_dt),
                    "district":               _dq_district(district),
                    "union_council":          uc,
                    "enumerator_id":          _dq_enum_id(enum["id"]),
                    "record_type":            "maternal",
                    "child_age_months":       None,
                    "child_sex":              None,
                    "height_cm":              None,
                    "weight_kg":              None,
                    "muac_mm":                None,
                    "haz_score":              None,
                    "waz_score":              None,
                    "whz_score":              None,
                    "stunted":                None,
                    "wasted":                 None,
                    "underweight":            None,
                    "severe_stunted":         None,
                    "severe_wasted":          None,
                    "anemia":                 _dq_yesno(anemia_m),
                    "diarrhea_2w":            None,
                    "ari_2w":                 None,
                    "fever_2w":               None,
                    "vaccination_full":       None,
                    "exclusive_bf":           None,
                    "interview_duration_min": _dq_missing(duration, p=0.03),
                    "short_interview_flag":   int(is_short_interview),
                    "maternal_age":           _dq_age(mat_age),
                    "currently_pregnant":     _dq_yesno(pregnant),
                    "anc_4plus":              _dq_yesno(anc_4plus) if not pregnant else None,
                    "last_delivery_skilled":  _dq_yesno(skilled_del),
                    "hemoglobin_gdl":         _dq_missing(hb, p=DQ_RATES["missing_hb"]),
                })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 3. Facility Assessments
# ---------------------------------------------------------------------------

def generate_facility_assessments(
    rounds: int = 4,
    *,
    start_date: Optional[str] = None,
    end_date:   Optional[str] = None,
    seed:       Optional[int] = None,
) -> pd.DataFrame:
    """
    Generate facility assessment records for all 108 facilities across Pakistan.

    Args:
        rounds     : Number of assessment rounds (default 4).
        start_date : Earliest assessment date YYYY-MM-DD.
        end_date   : Latest assessment date YYYY-MM-DD.
        seed       : RNG seed for reproducibility.
    """
    rng    = _make_rng(seed)
    _start = start_date or STUDY_START_DATE
    _end   = end_date   or STUDY_END_DATE
    records: list[dict] = []
    commodities = ["ORS", "Zinc", "Amoxicillin", "Iron_Folate", "Vitamin_A",
                   "Oxytocin", "Misoprostol", "Magnesium_Sulphate"]

    # Province-level readiness adjustments
    prov_adj = {"Punjab": 8, "Sindh": -5, "KPK": 0, "Balochistan": -15}

    for fac in HEALTH_FACILITIES:
        base = {"DHQ": 72, "RHC": 58, "BHU": 42}.get(fac["type"], 52)
        adj  = prov_adj.get(fac["province"], 0)

        for rnd in range(1, rounds + 1):
            assess_dt = _random_date(_start, _end)
            score     = float(np.clip(rng.normal(base + adj, 12), 5, 100))

            # Stock-out probability higher in Balochistan/rural
            so_p = 0.40 if fac["province"] == "Balochistan" else 0.22
            stockouts = {f"stockout_{c.lower()}": _bernoulli(so_p) for c in commodities}

            records.append({
                "assessment_id":   f"FA{fac['id']}-R{rnd}",
                "facility_id":     fac["id"],
                "facility_name":   fac["name"],
                "facility_type":   fac["type"],
                "province":        fac["province"],
                "district":        fac["district"],
                "assessment_date": _dq_date(assess_dt),
                "visit_round":     rnd,
                "readiness_score": round(score, 1),
                "overall_score":   round(score, 1),
                "staff_present":   int(RNG.integers(1, 10)),
                "staff_required":  {"DHQ": 15, "RHC": 7, "BHU": 3}.get(fac["type"], 5),
                "has_electricity": _bernoulli(0.95 if fac["province"] == "Punjab" else 0.65),
                "has_water":       _bernoulli(0.88 if fac["province"] == "Punjab" else 0.60),
                "has_toilet":      _bernoulli(0.92),
                **stockouts,
                "gps_latitude":    _dq_missing(fac["lat"], p=0.02),
                "gps_longitude":   _dq_missing(fac["lon"], p=0.02),
            })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 4. Enumerator Performance Logs
# ---------------------------------------------------------------------------

def generate_enumerator_performance(
    households_df: pd.DataFrame,
    *,
    start_date: Optional[str] = None,
    end_date:   Optional[str] = None,
    seed:       Optional[int] = None,
) -> pd.DataFrame:
    """
    Generate daily performance logs for all 108 enumerators.
    Flags enumerators with short interviews or high back-check failure rates.
    """
    rng   = _make_rng(seed)
    records: list[dict] = []
    start = datetime.strptime(start_date or STUDY_START_DATE, "%Y-%m-%d")
    end   = datetime.strptime(end_date   or STUDY_END_DATE,   "%Y-%m-%d")
    days  = max(1, (end - start).days)

    for enum in ENUMERATORS:
        # Each enumerator works ~70% of days
        for day_offset in range(days):
            if rng.random() < 0.30:
                continue
            work_date = start + timedelta(days=day_offset)
            subs      = int(rng.integers(2, 14))
            avg_dur   = float(rng.normal(22, 7))
            short_int = int(avg_dur < 15)
            flagged   = _bernoulli(0.07)

            records.append({
                "enumerator_id":         enum["id"],
                "enumerator_name":       enum["name"],
                "province":              enum["province"],
                "district":              enum["district"],
                "date":                  work_date.strftime("%Y-%m-%d"),
                "submissions":           subs,
                "avg_duration_min":      round(avg_dur, 1),
                "short_interviews":      short_int,
                "flagged_for_backcheck": flagged,
            })

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 5. Back-check Records
# ---------------------------------------------------------------------------

def generate_backcheck_records(
    visits_df: pd.DataFrame,
    sample_rate: float = 0.10,
    *,
    seed: Optional[int] = None,
) -> pd.DataFrame:
    """
    Generate back-check audit records for a random sample of child visits.

    Args:
        visits_df   : Output of generate_followup_visits().
        sample_rate : Fraction of child visits to back-check (default 10%).
        seed        : RNG seed for reproducibility.
    """
    rng = _make_rng(seed)
    if visits_df.empty or "record_type" not in visits_df.columns:
        return pd.DataFrame()

    child_visits = visits_df[visits_df["record_type"] == "child"].copy()
    if child_visits.empty:
        return pd.DataFrame()

    sample = child_visits.sample(frac=sample_rate, random_state=42)
    records: list[dict] = []

    for _, v in sample.iterrows():
        h_orig = float(v.get("height_cm") or 0)
        w_orig = float(v.get("weight_kg") or 0)

        h_recheck = round(h_orig + float(RNG.normal(0, 1.5)), 1) if h_orig > 0 else None
        w_recheck = round(w_orig + float(RNG.normal(0, 0.3)), 2) if w_orig > 0 else None

        h_disc = abs(h_recheck - h_orig) if h_recheck and h_orig else 0.0
        w_disc = abs(w_recheck - w_orig) if w_recheck and w_orig else 0.0

        morb_match = _bernoulli(0.87)
        passed     = int(h_disc <= 2.0 and w_disc <= 0.5 and morb_match)

        # Pick a different enumerator for the back-check
        district = str(v.get("district", "Lahore"))
        bc_enums = [e for e in ENUMERATORS if e["district"] != district]
        bc_enum  = random.choice(bc_enums if bc_enums else ENUMERATORS)

        records.append({
            "backcheck_id":            f"BC{uuid.uuid4().hex[:8].upper()}",
            "original_visit_id":       v["visit_id"],
            "household_id":            v["household_id"],
            "province":                v.get("province", ""),
            "district":                district,
            "backcheck_enumerator_id": bc_enum["id"],
            "backcheck_date":          v["visit_date"],
            "height_original_cm":      h_orig,
            "height_recheck_cm":       h_recheck,
            "weight_original_kg":      w_orig,
            "weight_recheck_kg":       w_recheck,
            "height_discrepancy_cm":   round(h_disc, 1),
            "weight_discrepancy_kg":   round(w_disc, 2),
            "morbidity_match":         morb_match,
            "overall_pass":            passed,
            "per_enumerator":          v.get("enumerator_id", ""),
        })

    return pd.DataFrame(records)

