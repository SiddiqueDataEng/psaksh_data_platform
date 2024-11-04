"""
Nutrition analytics — prevalence rates, trends, and disaggregations.

All functions accept DataFrames from the fact tables and return
analysis-ready DataFrames or dicts suitable for dashboards.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats


# ---------------------------------------------------------------------------
# Prevalence calculations
# ---------------------------------------------------------------------------

NUTRITION_INDICATORS = {
    "stunting_rate":    "stunted",
    "wasting_rate":     "wasted",
    "underweight_rate": "underweight",
    "severe_stunting":  "severe_stunted",
    "severe_wasting":   "severe_wasted",
    "anemia_rate":      "anemia",
    "diarrhea_rate":    "diarrhea_2w",
    "ari_rate":         "ari_2w",
    "fever_rate":       "fever_2w",
}


def prevalence_by_group(
    df: pd.DataFrame,
    group_cols: list[str],
    indicators: Optional[dict[str, str]] = None,
    min_n: int = 10,
) -> pd.DataFrame:
    """
    Calculate prevalence rates for nutrition indicators by grouping variables.

    Args:
        df:         Child nutrition fact table.
        group_cols: Columns to group by (e.g. ['district', 'visit_round']).
        indicators: Dict mapping output column name → source column name.
        min_n:      Minimum sample size to report a rate (else NaN).

    Returns:
        DataFrame with group columns + n + rate columns.
    """
    indicators = indicators or NUTRITION_INDICATORS

    agg: dict = {"visit_id": "count"}
    for rate_col, src_col in indicators.items():
        if src_col in df.columns:
            agg[src_col] = "mean"

    result = df.groupby(group_cols).agg(agg).reset_index()
    result = result.rename(columns={"visit_id": "n"})

    # Rename mean columns to rate names
    for rate_col, src_col in indicators.items():
        if src_col in result.columns:
            result = result.rename(columns={src_col: rate_col})

    # Suppress rates with small samples
    rate_cols = [c for c in result.columns if c.endswith("_rate") or c in indicators]
    for col in rate_cols:
        if col in result.columns:
            result.loc[result["n"] < min_n, col] = np.nan

    result[rate_cols] = result[rate_cols].round(3)
    return result


def national_prevalence(df: pd.DataFrame) -> dict[str, float]:
    """Return overall national prevalence for all indicators."""
    out: dict[str, float] = {"n": len(df)}
    for rate_col, src_col in NUTRITION_INDICATORS.items():
        if src_col in df.columns:
            out[rate_col] = round(float(df[src_col].mean(skipna=True)), 3)
    return out


# ---------------------------------------------------------------------------
# Trend analysis
# ---------------------------------------------------------------------------

def prevalence_trend(
    df: pd.DataFrame,
    indicator: str,
    group_col: str = "district",
) -> pd.DataFrame:
    """
    Calculate indicator prevalence by visit round, optionally disaggregated.

    Returns a DataFrame with columns: [group_col, visit_round, rate, n, ci_lower, ci_upper]
    """
    src_col = NUTRITION_INDICATORS.get(indicator, indicator)
    if src_col not in df.columns:
        raise ValueError(f"Column '{src_col}' not found in DataFrame")

    groups = [group_col, "visit_round"] if group_col else ["visit_round"]
    result_rows = []

    for keys, grp in df.groupby(groups):
        if not isinstance(keys, tuple):
            keys = (keys,)
        n = grp[src_col].notna().sum()
        if n < 10:
            continue
        rate = grp[src_col].mean(skipna=True)
        # Wilson confidence interval
        ci = _wilson_ci(int(grp[src_col].sum(skipna=True)), n)
        row = dict(zip(groups, keys))
        row.update({"n": n, "rate": round(rate, 3), "ci_lower": ci[0], "ci_upper": ci[1]})
        result_rows.append(row)

    return pd.DataFrame(result_rows)


def _wilson_ci(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson score confidence interval for a proportion."""
    if n == 0:
        return (0.0, 0.0)
    z = stats.norm.ppf(1 - alpha / 2)
    p = k / n
    denom = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    margin = (z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))) / denom
    return (round(max(0, centre - margin), 3), round(min(1, centre + margin), 3))


# ---------------------------------------------------------------------------
# Disaggregation helpers
# ---------------------------------------------------------------------------

def disaggregate_by_ses(df: pd.DataFrame, indicator: str) -> pd.DataFrame:
    """Prevalence by SES tier for a given indicator."""
    return prevalence_by_group(df, ["ses_tier", "visit_round"], {indicator: NUTRITION_INDICATORS.get(indicator, indicator)})


def disaggregate_by_age_sex(df: pd.DataFrame, indicator: str) -> pd.DataFrame:
    """Prevalence by child age group and sex."""
    return prevalence_by_group(
        df,
        ["child_age_group", "child_sex"],
        {indicator: NUTRITION_INDICATORS.get(indicator, indicator)},
    )


def double_burden_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """
    Identify households with co-occurrence of stunting and wasting
    (double burden of malnutrition).
    """
    if "stunted" not in df.columns or "wasted" not in df.columns:
        raise ValueError("Columns 'stunted' and 'wasted' required")

    df = df.copy()
    df["double_burden"] = (df["stunted"] == 1) & (df["wasted"] == 1)

    return (
        df.groupby(["district", "visit_round"])
        .agg(
            n=("visit_id", "count"),
            stunting_rate=("stunted", "mean"),
            wasting_rate=("wasted", "mean"),
            double_burden_rate=("double_burden", "mean"),
        )
        .round(3)
        .reset_index()
    )


# ---------------------------------------------------------------------------
# Data quality metrics
# ---------------------------------------------------------------------------

def anthropometry_completeness(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate completeness rates for key anthropometry fields."""
    child_df = df[df["record_type"] == "child"] if "record_type" in df.columns else df
    cols = ["height_cm", "weight_kg", "muac_mm", "haz_score", "waz_score", "whz_score"]
    available = [c for c in cols if c in child_df.columns]

    completeness = (child_df[available].notna().mean() * 100).round(1)
    return pd.DataFrame({"field": completeness.index, "completeness_pct": completeness.values})
