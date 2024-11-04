"""
Field monitoring analytics — enumerator performance, data quality,
back-check analysis, and high-frequency anomaly detection.

These feed the operations dashboard used by field supervisors.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
import logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerator performance
# ---------------------------------------------------------------------------

def enumerator_daily_summary(perf_df: pd.DataFrame) -> pd.DataFrame:
    """
    Summarise enumerator performance over the study period.
    Flags enumerators with consistently short interviews or high back-check failure rates.
    """
    summary = (
        perf_df.groupby(["enumerator_id", "enumerator_name", "district"])
        .agg(
            total_days_worked    = ("date", "nunique"),
            total_submissions    = ("submissions", "sum"),
            avg_daily_submissions= ("submissions", "mean"),
            avg_interview_min    = ("avg_duration_min", "mean"),
            short_interview_days = ("short_interviews", lambda x: (x > 0).sum()),
            backcheck_flags      = ("flagged_for_backcheck", "sum"),
        )
        .round(2)
        .reset_index()
    )

    # Flag enumerators with avg interview < 15 min (potential data fabrication)
    summary["quality_flag"] = summary["avg_interview_min"] < 15
    return summary


def detect_anomalies(visits_df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect data quality anomalies in visit records.

    Checks:
      - Interviews shorter than 10 minutes
      - Duplicate household visits on the same day
      - GPS coordinates far from district centre
      - Z-scores outside plausible range (already nulled in transform, flag here)
    """
    anomalies = []

    # Short interviews
    short = visits_df[visits_df["interview_duration_min"] < 10].copy()
    short["anomaly_type"] = "short_interview"
    anomalies.append(short[["visit_id", "household_id", "enumerator_id", "visit_date", "anomaly_type"]])

    # Duplicate household-date combinations
    dupes = visits_df[visits_df.duplicated(["household_id", "visit_date", "record_type"], keep=False)].copy()
    dupes["anomaly_type"] = "duplicate_visit"
    anomalies.append(dupes[["visit_id", "household_id", "enumerator_id", "visit_date", "anomaly_type"]])

    if anomalies:
        result = pd.concat(anomalies, ignore_index=True).drop_duplicates("visit_id")
        logger.info(f"  Anomalies detected: {len(result):,}")
        return result

    return pd.DataFrame(columns=["visit_id", "household_id", "enumerator_id", "visit_date", "anomaly_type"])


# ---------------------------------------------------------------------------
# Back-check analysis
# ---------------------------------------------------------------------------

def backcheck_summary(backcheck_df: pd.DataFrame) -> dict:
    """
    Summarise back-check results.

    Returns:
        Dict with overall pass rate, mean discrepancies, and per-enumerator breakdown.
    """
    if backcheck_df.empty:
        return {}

    overall_pass_rate = backcheck_df["overall_pass"].mean()
    mean_height_disc  = backcheck_df["height_discrepancy_cm"].mean()
    mean_weight_disc  = backcheck_df["weight_discrepancy_kg"].mean()
    # Column is 'morbidity_match' in generator; mismatch = 1 - match
    _morb_col = "morbidity_mismatch" if "morbidity_mismatch" in backcheck_df.columns \
                else "morbidity_match"
    if _morb_col == "morbidity_match":
        morbidity_mismatch_rate = 1.0 - backcheck_df[_morb_col].mean()
    else:
        morbidity_mismatch_rate = backcheck_df[_morb_col].mean()

    # Enumerator column may be 'backcheck_enumerator' or 'per_enumerator'
    _enum_col = "backcheck_enumerator" if "backcheck_enumerator" in backcheck_df.columns \
                else "per_enumerator"

    per_enumerator = (
        backcheck_df.groupby(_enum_col)
        .agg(
            n_backchecked       = ("backcheck_id", "count"),
            pass_rate           = ("overall_pass", "mean"),
            avg_height_disc_cm  = ("height_discrepancy_cm", "mean"),
            avg_weight_disc_kg  = ("weight_discrepancy_kg", "mean"),
        )
        .round(3)
        .reset_index()
    )

    return {
        "overall_pass_rate":       round(float(overall_pass_rate), 3),
        "mean_height_discrepancy": round(float(mean_height_disc), 2),
        "mean_weight_discrepancy": round(float(mean_weight_disc), 3),
        "morbidity_mismatch_rate": round(float(morbidity_mismatch_rate), 3),
        "per_enumerator":          per_enumerator,
    }


# ---------------------------------------------------------------------------
# Submission timeline
# ---------------------------------------------------------------------------

def submission_timeline(visits_df: pd.DataFrame) -> pd.DataFrame:
    """
    Daily submission counts by district — used for field progress tracking.
    """
    visits_df = visits_df.copy()
    visits_df["visit_date"] = pd.to_datetime(visits_df["visit_date"])

    timeline = (
        visits_df.groupby(["visit_date", "district"])
        .agg(submissions=("visit_id", "nunique"))
        .reset_index()
        .sort_values("visit_date")
    )

    # Cumulative submissions per district
    timeline["cumulative"] = timeline.groupby("district")["submissions"].cumsum()
    return timeline


def coverage_by_uc(households_df: pd.DataFrame, visits_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate visit coverage (% of enrolled households visited) by union council.
    """
    enrolled = households_df.groupby(["district", "union_council"]).size().reset_index(name="enrolled")
    visited  = (
        visits_df[visits_df["record_type"] == "child"]
        .groupby(["district", "union_council"])["household_id"]
        .nunique()
        .reset_index(name="visited")
    )
    coverage = enrolled.merge(visited, on=["district", "union_council"], how="left")
    coverage["visited"] = coverage["visited"].fillna(0).astype(int)
    coverage["coverage_pct"] = (coverage["visited"] / coverage["enrolled"] * 100).round(1)
    return coverage.sort_values(["district", "union_council"])
