"""
Tests for the Streamlit dashboard (offline — no browser needed).
Validates data loading, helper functions, and chart generation logic
without actually launching the Streamlit server.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import numpy as np
import pytest

# ── Path bootstrap ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
PKG  = Path(__file__).resolve().parents[1]
for p in [str(ROOT), str(PKG)]:
    if p not in sys.path:
        sys.path.insert(0, p)

DATA_DIR = PKG / "data"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sample_fct_child():
    """Generate a small child nutrition fact table for testing."""
    from psaksh_data_platform.data_generator.generators import (
        generate_households, generate_followup_visits,
    )
    from psaksh_data_platform.etl.transform import (
        transform_households, transform_followup_visits, build_fct_child_nutrition,
    )
    hh = transform_households(generate_households(n=100))
    v  = transform_followup_visits(generate_followup_visits(hh, rounds=2))
    return build_fct_child_nutrition(v, hh)


@pytest.fixture(scope="module")
def sample_fct_maternal():
    from psaksh_data_platform.data_generator.generators import (
        generate_households, generate_followup_visits,
    )
    from psaksh_data_platform.etl.transform import (
        transform_households, transform_followup_visits, build_fct_maternal_health,
    )
    hh = transform_households(generate_households(n=100))
    v  = transform_followup_visits(generate_followup_visits(hh, rounds=2))
    return build_fct_maternal_health(v, hh)


# ── Data loading tests ────────────────────────────────────────────────────────

class TestDataLoading:

    def test_data_dir_exists(self):
        """Data directory should exist."""
        assert DATA_DIR.exists(), f"Data directory not found: {DATA_DIR}"

    def test_gold_or_silver_data_present(self):
        """At least one processed data file should exist."""
        gold   = DATA_DIR / "gold"
        silver = DATA_DIR / "silver"
        has_gold   = gold.exists()   and any(gold.glob("*.parquet"))
        has_silver = silver.exists() and any(silver.glob("*.parquet"))
        assert has_gold or has_silver, (
            "No Gold or Silver data found. "
            "Run: python -m psaksh_data_platform.data_generator.run"
        )

    def test_fct_child_nutrition_loadable(self):
        """fct_child_nutrition.parquet should be readable."""
        for layer in ["gold", "silver"]:
            path = DATA_DIR / layer / "fct_child_nutrition.parquet"
            if path.exists():
                df = pd.read_parquet(path)
                assert isinstance(df, pd.DataFrame)
                assert len(df) > 0
                return
        pytest.skip("fct_child_nutrition.parquet not found in gold or silver")

    def test_fct_maternal_health_loadable(self):
        for layer in ["gold", "silver"]:
            path = DATA_DIR / layer / "fct_maternal_health.parquet"
            if path.exists():
                df = pd.read_parquet(path)
                assert isinstance(df, pd.DataFrame)
                assert len(df) > 0
                return
        pytest.skip("fct_maternal_health.parquet not found")

    def test_households_loadable(self):
        for layer in ["gold", "silver", "raw/current"]:
            path = DATA_DIR / layer / "households.parquet"
            if path.exists():
                df = pd.read_parquet(path)
                assert isinstance(df, pd.DataFrame)
                return
        pytest.skip("households.parquet not found")

    def test_delta_log_readable(self):
        import json
        path = DATA_DIR / "delta_log" / "pipeline_state.json"
        if not path.exists():
            pytest.skip("pipeline_state.json not found — run ETL first")
        state = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(state, dict)
        assert "watermarks" in state or "run_history" in state


# ── Dashboard helper function tests ──────────────────────────────────────────

class TestDashboardHelpers:

    NUMERIC_COLS = [
        "stunted", "wasted", "underweight", "anemia",
        "anc_4plus", "last_delivery_skilled",
        "haz_score", "waz_score", "whz_score",
        "hemoglobin_gdl", "child_age_months", "visit_round",
    ]

    def _coerce_numeric(self, df: pd.DataFrame) -> pd.DataFrame:
        """Mirror the dashboard's numeric coercion logic."""
        for col in self.NUMERIC_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    def _normalise_binary(self, df: pd.DataFrame) -> pd.DataFrame:
        """Mirror the dashboard's 0-100 → 0-1 normalisation."""
        BINARY = ["stunted", "wasted", "underweight", "anemia",
                  "anc_4plus", "last_delivery_skilled"]
        for col in BINARY:
            if col in df.columns and df[col].max() > 1.5:
                df[col] = df[col] / 100.0
        return df

    def test_numeric_coercion(self, sample_fct_child):
        df = self._coerce_numeric(sample_fct_child.copy())
        for col in ["stunted", "wasted", "anemia"]:
            if col in df.columns:
                # Accept any numeric dtype (int64, float64, etc.)
                assert np.issubdtype(df[col].dtype, np.number), (
                    f"{col} should be numeric after coercion, got {df[col].dtype}"
                )

    def test_binary_normalisation(self, sample_fct_child):
        df = sample_fct_child.copy()
        # Force values to 0-100 range to test normalisation
        for col in ["stunted", "wasted"]:
            if col in df.columns:
                df[col] = df[col] * 100
        df = self._normalise_binary(df)
        for col in ["stunted", "wasted"]:
            if col in df.columns:
                assert df[col].max() <= 1.0, f"{col} not normalised to 0-1"

    def test_safe_mean_returns_float(self, sample_fct_child):
        """safe_mean equivalent: mean of a column should be a float."""
        for col in ["stunted", "wasted", "anemia"]:
            if col in sample_fct_child.columns:
                val = float(pd.to_numeric(sample_fct_child[col], errors="coerce").mean())
                assert isinstance(val, float)
                assert 0.0 <= val <= 1.0 or np.isnan(val), (
                    f"safe_mean({col}) = {val} out of expected range"
                )

    def test_province_filter(self, sample_fct_child):
        """Filtering by province should return a subset."""
        if "province" not in sample_fct_child.columns:
            pytest.skip("No province column")
        provinces = sample_fct_child["province"].dropna().unique()
        if len(provinces) == 0:
            pytest.skip("No province values")
        prov = provinces[0]
        filtered = sample_fct_child[sample_fct_child["province"] == prov]
        assert len(filtered) <= len(sample_fct_child)
        assert (filtered["province"] == prov).all()

    def test_district_groupby(self, sample_fct_child):
        """Groupby district should produce one row per district."""
        if "district" not in sample_fct_child.columns or "stunted" not in sample_fct_child.columns:
            pytest.skip("Missing district or stunted column")
        grouped = sample_fct_child.groupby("district")["stunted"].mean()
        assert len(grouped) > 0
        assert (grouped >= 0).all()
        assert (grouped <= 1).all()


# ── Chart generation tests ────────────────────────────────────────────────────

class TestChartGeneration:

    def test_plotly_bar_chart_builds(self, sample_fct_child):
        """Verify a Plotly bar chart can be built from the data."""
        import plotly.express as px
        if "district" not in sample_fct_child.columns or "stunted" not in sample_fct_child.columns:
            pytest.skip("Missing required columns")
        dist = sample_fct_child.groupby("district")["stunted"].mean().reset_index()
        dist.columns = ["district", "stunting_rate"]
        fig = px.bar(dist, x="stunting_rate", y="district", orientation="h",
                     title="Test Chart")
        assert fig is not None
        assert len(fig.data) > 0

    def test_plotly_line_chart_builds(self, sample_fct_child):
        """Verify a trend line chart can be built."""
        import plotly.express as px
        if "visit_round" not in sample_fct_child.columns or "district" not in sample_fct_child.columns:
            pytest.skip("Missing required columns")
        trend = sample_fct_child.groupby(["district", "visit_round"])["stunted"].mean().reset_index()
        fig = px.line(trend.sort_values("visit_round"), x="visit_round", y="stunted",
                      color="district", markers=True, title="Test Trend")
        assert fig is not None

    def test_plotly_json_serialisable(self, sample_fct_child):
        """Plotly figures should serialise to JSON without error."""
        import plotly.express as px
        import plotly.io as pio
        if "district" not in sample_fct_child.columns or "stunted" not in sample_fct_child.columns:
            pytest.skip("Missing required columns")
        dist = sample_fct_child.groupby("district")["stunted"].mean().reset_index()
        fig = px.bar(dist, x="district", y="stunted")
        json_str = pio.to_json(fig)
        assert isinstance(json_str, str)
        assert len(json_str) > 10

    def test_maternal_anc_chart(self, sample_fct_maternal):
        """ANC coverage chart should build without error."""
        import plotly.express as px
        if "anc_4plus" not in sample_fct_maternal.columns:
            pytest.skip("No anc_4plus column")
        if "district" not in sample_fct_maternal.columns:
            pytest.skip("No district column")
        anc = sample_fct_maternal.groupby("district")["anc_4plus"].mean().reset_index()
        fig = px.bar(anc, x="district", y="anc_4plus", title="ANC Test")
        assert fig is not None


# ── KPI calculation tests ─────────────────────────────────────────────────────

class TestKPICalculations:

    def test_national_stunting_rate(self, sample_fct_child):
        if "stunted" not in sample_fct_child.columns:
            pytest.skip("No stunted column")
        rate = float(pd.to_numeric(sample_fct_child["stunted"], errors="coerce").mean())
        assert 0.0 <= rate <= 1.0, f"Stunting rate {rate} out of [0,1]"

    def test_national_wasting_rate(self, sample_fct_child):
        if "wasted" not in sample_fct_child.columns:
            pytest.skip("No wasted column")
        rate = float(pd.to_numeric(sample_fct_child["wasted"], errors="coerce").mean())
        assert 0.0 <= rate <= 1.0

    def test_anc_4plus_rate(self, sample_fct_maternal):
        if "anc_4plus" not in sample_fct_maternal.columns:
            pytest.skip("No anc_4plus column")
        rate = float(pd.to_numeric(sample_fct_maternal["anc_4plus"], errors="coerce").mean())
        assert 0.0 <= rate <= 1.0

    def test_skilled_delivery_rate(self, sample_fct_maternal):
        if "last_delivery_skilled" not in sample_fct_maternal.columns:
            pytest.skip("No last_delivery_skilled column")
        rate = float(pd.to_numeric(sample_fct_maternal["last_delivery_skilled"], errors="coerce").mean())
        assert 0.0 <= rate <= 1.0

    def test_worst_district_identified(self, sample_fct_child):
        if "district" not in sample_fct_child.columns or "stunted" not in sample_fct_child.columns:
            pytest.skip("Missing columns")
        dist_rates = sample_fct_child.groupby("district")["stunted"].mean()
        worst = dist_rates.idxmax()
        assert isinstance(worst, str)
        assert len(worst) > 0

    def test_ses_gap_calculation(self, sample_fct_child):
        if "ses_tier" not in sample_fct_child.columns or "stunted" not in sample_fct_child.columns:
            pytest.skip("Missing ses_tier or stunted column")
        ses = sample_fct_child.groupby("ses_tier")["stunted"].mean()
        if "low" in ses.index and "high" in ses.index:
            gap = (ses["low"] - ses["high"]) * 100
            assert isinstance(gap, float)
            # Low SES should generally have higher stunting
            # (not always true in synthetic data, so just check it's a number)
            assert not np.isnan(gap)
