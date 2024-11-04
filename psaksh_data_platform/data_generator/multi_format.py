"""
PSAKSH — Multi-format data generator.
Saves raw data in CSV, Parquet, JSON, and Avro (fastavro) formats.
Also writes survey submissions directly to MySQL (Bronze layer).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Format writers ────────────────────────────────────────────────────────────

def save_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info(f"  CSV     {path.name} ({len(df):,} rows)")


def save_parquet(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(path, index=False, engine="pyarrow")
        logger.info(f"  Parquet {path.name} ({len(df):,} rows)")
    except Exception as e:
        logger.warning(f"  Parquet skipped ({e}) — CSV already saved")


def save_json(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_json(path, orient="records", lines=True, date_format="iso")
    logger.info(f"  JSON    {path.name} ({len(df):,} rows)")


def save_avro(df: pd.DataFrame, path: Path) -> None:
    """Save as Avro using fastavro. Falls back silently if not installed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fastavro

        # Build Avro schema from DataFrame dtypes
        type_map = {
            "int64": "long", "int32": "int", "float64": "double",
            "float32": "float", "bool": "boolean", "object": "string",
        }
        fields = []
        for col, dtype in df.dtypes.items():
            avro_type = type_map.get(str(dtype), "string")
            fields.append({"name": col, "type": ["null", avro_type], "default": None})

        schema = {
            "type": "record",
            "name": path.stem.replace("-", "_"),
            "fields": fields,
        }

        # Convert NaN to None for Avro compatibility
        records = df.where(df.notna(), other=None).to_dict(orient="records")

        with open(path, "wb") as f:
            fastavro.writer(f, fastavro.parse_schema(schema), records)

        logger.info(f"  Avro    {path.name} ({len(df):,} rows)")
    except ImportError:
        logger.warning("  Avro skipped — fastavro not installed")
    except Exception as e:
        logger.warning(f"  Avro skipped ({e})")


def save_all_formats(df: pd.DataFrame, raw_dir: Path, name: str) -> None:
    """Save a DataFrame in all four formats to raw_dir."""
    save_csv(df,     raw_dir / f"{name}.csv")
    save_parquet(df, raw_dir / f"{name}.parquet")
    save_json(df,    raw_dir / f"{name}.json")
    save_avro(df,    raw_dir / f"{name}.avro")


# ── Survey submission → MySQL ─────────────────────────────────────────────────

def submit_survey_to_db(form_data: dict[str, Any], engine) -> str:
    """
    Write a single survey submission directly to the MySQL bronze table.
    Returns the generated household_id.
    """
    household_id = str(uuid.uuid4())[:12].upper()
    now = datetime.now(timezone.utc).isoformat()

    record = {
        "household_id":       household_id,
        "district":           form_data.get("district", ""),
        "union_council":      form_data.get("union_council", ""),
        "respondent_name":    form_data.get("respondent_name", ""),
        "respondent_age":     _int(form_data.get("respondent_age")),
        "household_size":     _int(form_data.get("household_size")),
        "children_under_5":   _int(form_data.get("children_u5")),
        "water_source":       form_data.get("water_source", ""),
        "ses_tier":           form_data.get("ses_tier", ""),
        "gps_raw":            form_data.get("gps", ""),
        "consent_given":      int(form_data.get("consent", 1)),
        "submission_time":    now,
        "form_version":       "web_v1.0",
        "source":             "psaksh_web_form",
    }

    df = pd.DataFrame([record])
    df.to_sql(
        "bronze_survey_submissions",
        con=engine,
        if_exists="append",
        index=False,
        method="multi",
    )
    logger.info(f"Survey submitted to DB: {household_id}")
    return household_id


def _int(val) -> int | None:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None
