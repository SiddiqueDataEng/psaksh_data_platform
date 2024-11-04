"""
Data dictionary and codebook generator.

Produces machine-readable and human-readable documentation
for every dataset in the psaksh warehouse.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


# ---------------------------------------------------------------------------
# Field-level metadata definitions
# ---------------------------------------------------------------------------

HOUSEHOLD_CODEBOOK: list[dict[str, Any]] = [
    {"field": "household_id",            "type": "string",  "pii": False, "description": "Unique household identifier (UUID prefix)"},
    {"field": "district",                "type": "string",  "pii": False, "description": "Administrative district name"},
    {"field": "union_council",           "type": "string",  "pii": False, "description": "Union council within district"},
    {"field": "enumerator_id",           "type": "string",  "pii": False, "description": "Enumerator who conducted the interview"},
    {"field": "respondent_name",         "type": "string",  "pii": True,  "description": "Name of primary respondent (PII — pseudonymised in output)"},
    {"field": "respondent_age",          "type": "integer", "pii": False, "description": "Age of respondent in years"},
    {"field": "household_size",          "type": "integer", "pii": False, "description": "Total number of household members"},
    {"field": "children_under_5",        "type": "integer", "pii": False, "description": "Number of children under 5 years"},
    {"field": "women_15_49",             "type": "integer", "pii": False, "description": "Number of women aged 15–49"},
    {"field": "ses_tier",                "type": "category","pii": False, "description": "Socioeconomic status tier: low / middle / high"},
    {"field": "water_source",            "type": "category","pii": False, "description": "Primary drinking water source"},
    {"field": "toilet_type",             "type": "category","pii": False, "description": "Type of sanitation facility"},
    {"field": "electricity",             "type": "boolean", "pii": False, "description": "Household has electricity connection"},
    {"field": "gps_latitude",            "type": "float",   "pii": True,  "description": "GPS latitude (PII — masked to 2dp in output)"},
    {"field": "gps_longitude",           "type": "float",   "pii": True,  "description": "GPS longitude (PII — masked to 2dp in output)"},
    {"field": "enrollment_date",         "type": "date",    "pii": False, "description": "Date of household enrollment"},
    {"field": "consent_given",           "type": "boolean", "pii": False, "description": "Informed consent obtained from respondent"},
]

CHILD_VISIT_CODEBOOK: list[dict[str, Any]] = [
    {"field": "visit_id",          "type": "string",  "pii": False, "description": "Unique visit record identifier"},
    {"field": "household_id",      "type": "string",  "pii": False, "description": "Foreign key to household"},
    {"field": "visit_round",       "type": "integer", "pii": False, "description": "Visit round number (1–4)"},
    {"field": "child_age_months",  "type": "integer", "pii": False, "description": "Child age in completed months at time of visit"},
    {"field": "child_sex",         "type": "category","pii": False, "description": "Child sex: male / female"},
    {"field": "height_cm",         "type": "float",   "pii": False, "description": "Recumbent length or standing height in cm"},
    {"field": "weight_kg",         "type": "float",   "pii": False, "description": "Weight in kilograms"},
    {"field": "muac_mm",           "type": "float",   "pii": False, "description": "Mid-upper arm circumference in mm"},
    {"field": "haz_score",         "type": "float",   "pii": False, "description": "Height-for-age z-score (WHO 2006 standards)"},
    {"field": "waz_score",         "type": "float",   "pii": False, "description": "Weight-for-age z-score (WHO 2006 standards)"},
    {"field": "whz_score",         "type": "float",   "pii": False, "description": "Weight-for-height z-score (WHO 2006 standards)"},
    {"field": "stunted",           "type": "boolean", "pii": False, "description": "HAZ < -2 SD (stunting)"},
    {"field": "wasted",            "type": "boolean", "pii": False, "description": "WHZ < -2 SD (wasting)"},
    {"field": "underweight",       "type": "boolean", "pii": False, "description": "WAZ < -2 SD (underweight)"},
    {"field": "diarrhea_2w",       "type": "boolean", "pii": False, "description": "Diarrhea episode in last 2 weeks (caregiver recall)"},
    {"field": "ari_2w",            "type": "boolean", "pii": False, "description": "Acute respiratory infection in last 2 weeks"},
    {"field": "hemoglobin_gdl",    "type": "float",   "pii": False, "description": "Hemoglobin concentration in g/dL"},
    {"field": "anemia",            "type": "boolean", "pii": False, "description": "Hemoglobin < 11.0 g/dL (WHO threshold for children)"},
    {"field": "vaccination_full",  "type": "boolean", "pii": False, "description": "Fully vaccinated per EPI schedule (12–23 months only)"},
]


def generate_codebook(
    codebook: list[dict[str, Any]],
    dataset_name: str,
    output_path: str | Path,
) -> pd.DataFrame:
    """
    Generate a codebook CSV from a field metadata list.

    Args:
        codebook:     List of field metadata dicts.
        dataset_name: Name of the dataset (for documentation header).
        output_path:  Path to save the CSV codebook.

    Returns:
        DataFrame of the codebook.
    """
    df = pd.DataFrame(codebook)
    df["dataset"] = dataset_name
    df["pii"] = df["pii"].map({True: "YES", False: "no"})

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False)
    return df


def generate_all_codebooks(output_dir: str | Path = "docs/codebooks") -> None:
    """Generate codebooks for all psaksh datasets."""
    output_dir = Path(output_dir)
    generate_codebook(HOUSEHOLD_CODEBOOK,    "households",    output_dir / "households_codebook.csv")
    generate_codebook(CHILD_VISIT_CODEBOOK,  "child_visits",  output_dir / "child_visits_codebook.csv")
    print(f"Codebooks written to {output_dir}/")
