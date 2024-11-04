"""
Tests for the analytics layer.
"""

import pytest
import pandas as pd
import numpy as np

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from psaksh_data_platform.data_generator.generators import (
    generate_households,
    generate_followup_visits,
    generate_backcheck_records,
)
from psaksh_data_platform.etl.transform import (
    transform_households,
    transform_followup_visits,
    build_fct_child_nutrition,
    build_fct_maternal_health,
)
from psaksh_data_platform.analytics.nutrition import (
    national_prevalence,
    prevalence_by_group,
    prevalence_trend,
    double_burden_analysis,
    anthropometry_completeness,
)
from psaksh_data_platform.analytics.field_monitoring import (
    backcheck_summary,
    detect_anomalies,
    submission_timeline,
    coverage_by_uc,
)


@pytest.fixture(scope="module")
def fct_child():
    hh = transform_households(generate_households(n=300))
    v  = transform_followup_visits(generate_followup_visits(hh, rounds=3))
    return build_fct_child_nutrition(v, hh)


@pytest.fixture(scope="module")
def fct_maternal():
    hh = transform_households(generate_households(n=300))
    v  = transform_followup_visits(generate_followup_visits(hh, rounds=3))
    return build_fct_maternal_health(v, hh)


@pytest.fixture(scope="module")
def visits_raw():
    hh = generate_households(n=200)
    return generate_followup_visits(hh, rounds=2)


@pytest.fixture(scope="module")
def visits_clean():
    """Transformed visits — needed for analytics that parse dates."""
    from psaksh_data_platform.etl.transform import transform_followup_visits
    hh = transform_households(generate_households(n=200))
    return transform_followup_visits(generate_followup_visits(hh, rounds=2))


class TestNutritionAnalytics:

    def test_national_prevalence_keys(self, fct_child):
        prev = national_prevalence(fct_child)
        assert "n" in prev
        assert "stunting_rate" in prev
        assert "wasting_rate" in prev

    def test_prevalence_rates_in_range(self, fct_child):
        prev = national_prevalence(fct_child)
        for key, val in prev.items():
            if key != "n":
                assert 0 <= val <= 1, f"{key} = {val} out of range"

    def test_prevalence_by_group_returns_df(self, fct_child):
        result = prevalence_by_group(fct_child, ["district"])
        assert isinstance(result, pd.DataFrame)
        assert "n" in result.columns
        assert "stunting_rate" in result.columns

    def test_prevalence_trend_returns_df(self, fct_child):
        result = prevalence_trend(fct_child, "stunting_rate", group_col="district")
        assert isinstance(result, pd.DataFrame)
        assert "rate" in result.columns
        assert "ci_lower" in result.columns
        assert "ci_upper" in result.columns

    def test_ci_lower_le_rate_le_upper(self, fct_child):
        result = prevalence_trend(fct_child, "stunting_rate", group_col="district")
        assert (result["ci_lower"] <= result["rate"]).all()
        assert (result["rate"] <= result["ci_upper"]).all()

    def test_double_burden_analysis(self, fct_child):
        result = double_burden_analysis(fct_child)
        assert "double_burden_rate" in result.columns
        assert (result["double_burden_rate"] >= 0).all()
        assert (result["double_burden_rate"] <= 1).all()

    def test_anthropometry_completeness(self, visits_raw):
        result = anthropometry_completeness(visits_raw)
        assert "field" in result.columns
        assert "completeness_pct" in result.columns
        assert (result["completeness_pct"] >= 0).all()
        assert (result["completeness_pct"] <= 100).all()


class TestFieldMonitoring:

    def test_backcheck_summary_keys(self, visits_clean):
        bc = generate_backcheck_records(visits_clean, sample_rate=0.10)
        summary = backcheck_summary(bc)
        assert "overall_pass_rate" in summary
        assert "per_enumerator" in summary

    def test_detect_anomalies_returns_df(self, visits_raw):
        result = detect_anomalies(visits_raw)
        assert isinstance(result, pd.DataFrame)
        if not result.empty:
            assert "anomaly_type" in result.columns

    def test_submission_timeline_sorted(self, visits_clean):
        timeline = submission_timeline(visits_clean)
        assert isinstance(timeline, pd.DataFrame)
        if not timeline.empty:
            assert "cumulative" in timeline.columns

    def test_coverage_by_uc(self, visits_raw):
        hh = generate_households(n=200)
        cov = coverage_by_uc(hh, visits_raw)
        assert "coverage_pct" in cov.columns
        assert (cov["coverage_pct"] >= 0).all()

