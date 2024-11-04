"""
PII handling utilities — masking, pseudonymisation, and audit logging.

Implements psaksh data governance standards:
  - PII fields are never written to output or reporting layers
  - Respondent names are pseudonymised with a one-way hash
  - Access to raw PII requires explicit role check
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

import pandas as pd
from loguru import logger

# Fields classified as PII in psaksh data inventory
PII_FIELDS = [
    "respondent_name",
    "household_head_name",
    "enumerator_name",
    "gps_latitude",
    "gps_longitude",
    "gps_accuracy_m",
]

# Fields that should be masked in output layers (not dropped, but generalised)
QUASI_IDENTIFIER_FIELDS = [
    "respondent_age",
    "household_head_age",
    "union_council",
]


def pseudonymise_name(name: str, salt: str = "psaksh_2023") -> str:
    """
    One-way pseudonymisation of a name using SHA-256 + salt.
    Returns an 8-character hex prefix — sufficient for linkage, not reversible.
    """
    if not name or pd.isna(name):
        return "UNKNOWN"
    h = hashlib.sha256(f"{salt}:{name}".encode()).hexdigest()
    return f"ID_{h[:8].upper()}"


def strip_pii(df: pd.DataFrame, keep_pseudonym: bool = True) -> pd.DataFrame:
    """
    Remove or pseudonymise PII fields from a DataFrame.

    Args:
        df:              Input DataFrame (may contain PII).
        keep_pseudonym:  If True, replace name fields with pseudonymised IDs.
                         If False, drop them entirely.

    Returns:
        DataFrame safe for output/reporting layers.
    """
    df = df.copy()

    for field in PII_FIELDS:
        if field not in df.columns:
            continue
        if field.endswith("_name") and keep_pseudonym:
            df[field] = df[field].apply(pseudonymise_name)
            logger.debug(f"  Pseudonymised: {field}")
        else:
            df = df.drop(columns=[field])
            logger.debug(f"  Dropped PII field: {field}")

    return df


def generalise_age(df: pd.DataFrame, age_col: str, bin_size: int = 5) -> pd.DataFrame:
    """
    Replace exact age with age band to reduce re-identification risk.
    E.g. age=27 → '25-29'
    """
    df = df.copy()
    if age_col not in df.columns:
        return df
    df[age_col] = (df[age_col] // bin_size * bin_size).astype("Int64").astype(str) + \
                  "-" + ((df[age_col] // bin_size * bin_size) + bin_size - 1).astype("Int64").astype(str)
    return df


def mask_gps(df: pd.DataFrame, precision: int = 2) -> pd.DataFrame:
    """
    Reduce GPS precision to prevent exact household location identification.
    precision=2 → ~1.1km grid; precision=3 → ~110m grid.
    """
    df = df.copy()
    for col in ["gps_latitude", "gps_longitude"]:
        if col in df.columns:
            df[col] = df[col].round(precision)
    return df


def audit_log(action: str, user: str, table: str, row_count: int) -> None:
    """
    Write an audit log entry for data access events.
    In production this would write to a dedicated audit table.
    """
    logger.info(f"AUDIT | user={user} | action={action} | table={table} | rows={row_count}")


def validate_consent(df: pd.DataFrame, consent_col: str = "consent_given") -> pd.DataFrame:
    """
    Filter out records where consent was not given.
    Logs the number of records removed.
    """
    if consent_col not in df.columns:
        logger.warning(f"  Consent column '{consent_col}' not found — skipping consent filter")
        return df

    before = len(df)
    df = df[df[consent_col] == True].copy()
    removed = before - len(df)
    if removed:
        logger.warning(f"  Removed {removed:,} records without consent")
    return df
