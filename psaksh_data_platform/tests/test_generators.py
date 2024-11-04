"""
Tests for the synthetic data generators.
Validates schema, data types, and realistic value ranges.
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
    generate_facility_assessments,
    generate_enumerator_performance,
    generate_backcheck_records,
)
from psaksh_data_platform.data_generator.config import (
    DISTRICTS, DISTRICT_PROVINCE_MAP, SES_TIERS, HEALTH_FACILITIES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def households():
    return generate_households(n=100)


@pytest.fixture(scope="module")
def visits(households):
    return generate_followup_visits(households, rounds=2)


@pytest.fixture(scope="module")
def facilities():
    return generate_facility_assessments(rounds=2)


# ---------------------------------------------------------------------------
# Household tests
# ---------------------------------------------------------------------------

class TestHouseholds:

    def test_returns_dataframe(self, households):
        assert isinstance(households, pd.DataFrame)

    def test_row_count(self, households):
        # Should be close to n=100 (some may be dropped for no consent)
        # Generator injects ~4.5% duplicates so actual count may exceed n
        assert len(households) >= 90

    def test_required_columns(self, households):
        required = [
            "household_id", "district", "union_council", "enumerator_id",
            "household_size", "children_under_5", "women_15_49",
            "ses_tier", "enrollment_date", "consent_given",
        ]
        for col in required:
            assert col in households.columns, f"Missing column: {col}"

    def test_household_ids_mostly_unique(self, households):
        # Generator injects ~4.5% duplicate household IDs as DQ issues
        unique_ratio = households["household_id"].nunique() / len(households)
        assert unique_ratio >= 0.90, f"Too many duplicate IDs: {unique_ratio:.1%}"

    def test_district_values_are_valid(self, households):
        """All district values (after DQ normalisation) should be in the 36-district list
        or be a known Urdu/typo variant injected by the DQ layer."""
        # The generator injects typos, trailing spaces, lowercase, and Urdu script
        # Normalise for comparison: strip, title-case
        valid_districts = set(DISTRICTS)
        raw_districts   = set(households["district"].dropna().astype(str).unique())
        # Normalise: strip whitespace and check
        normalised = {d.strip().title() for d in raw_districts}
        valid_count = sum(1 for d in normalised if d in valid_districts)
        # At least 70% of unique district values should normalise to valid
        assert valid_count / max(len(normalised), 1) >= 0.70, (
            f"Too many invalid district values after normalisation: "
            f"{normalised - valid_districts}"
        )

    def test_ses_tier_values_mostly_valid(self, households):
        """SES tier may contain Urdu script variants (~15% DQ injection)."""
        valid_ses = set(SES_TIERS)
        ses_vals  = households["ses_tier"].dropna().astype(str)
        valid_pct = ses_vals.isin(valid_ses).mean()
        assert valid_pct >= 0.80, f"Too many invalid SES values: {valid_pct:.1%}"

    def test_household_size_plausible(self, households):
        assert households["household_size"].between(1, 20).all()

    def test_children_under_5_non_negative(self, households):
        assert (households["children_under_5"] >= 0).all()

    def test_gps_within_pakistan(self, households):
        valid = households.dropna(subset=["gps_latitude", "gps_longitude"])
        assert valid["gps_latitude"].between(23.5, 37.5).all()
        assert valid["gps_longitude"].between(60.5, 77.5).all()

    def test_consent_column_exists(self, households):
        """consent_given column should exist; DQ injection may make it non-boolean."""
        assert "consent_given" in households.columns


# ---------------------------------------------------------------------------
# Follow-up visit tests
# ---------------------------------------------------------------------------

class TestFollowupVisits:

    def test_returns_dataframe(self, visits):
        assert isinstance(visits, pd.DataFrame)

    def test_has_child_and_maternal_records(self, visits):
        assert "child" in visits["record_type"].values
        assert "maternal" in visits["record_type"].values

    def test_unique_visit_ids(self, visits):
        assert visits["visit_id"].nunique() == len(visits)

    def test_child_anthropometry_mostly_plausible(self, visits):
        """Generator injects ~2% out-of-range heights as DQ issues per call,
        but the actual rate may be higher due to multiple DQ passes."""
        child = visits[visits["record_type"] == "child"]
        valid_height = child["height_cm"].dropna()
        pct_plausible = valid_height.between(40, 130).mean()
        # Allow up to 15% DQ-injected outliers (documented intentional DQ)
        assert pct_plausible >= 0.85, f"Too many implausible heights: {pct_plausible:.1%}"

    def test_z_scores_mostly_plausible(self, visits):
        """
        Raw generator z-scores follow a normal distribution and may rarely exceed ±6.
        The transform layer nulls implausible values; here we just check the bulk is sane.
        """
        child = visits[visits["record_type"] == "child"]
        for z_col in ["haz_score", "waz_score", "whz_score"]:
            if z_col in child.columns:
                valid = child[z_col].dropna()
                pct_plausible = (valid.abs() <= 6).mean()
                assert pct_plausible > 0.99, f"{z_col}: only {pct_plausible:.1%} within ±6"

    def test_binary_indicators_mostly_0_or_1(self, visits):
        """Generator injects ~15% bilingual yes/no values as DQ issues."""
        child = visits[visits["record_type"] == "child"]
        for col in ["stunted", "wasted", "underweight", "diarrhea_2w", "ari_2w"]:
            if col in child.columns:
                valid = child[col].dropna()
                # At least 80% should be 0 or 1 (rest are bilingual DQ injections)
                pct_binary = valid.astype(str).isin(["0", "1", "0.0", "1.0"]).mean()
                assert pct_binary >= 0.80, (
                    f"{col}: only {pct_binary:.1%} are binary (0/1)"
                )

    def test_visit_round_range(self, visits):
        assert visits["visit_round"].between(1, 10).all()

    def test_hemoglobin_plausible(self, visits):
        valid = visits["hemoglobin_gdl"].dropna()
        assert valid.between(4, 20).all()


# ---------------------------------------------------------------------------
# Facility assessment tests
# ---------------------------------------------------------------------------

class TestFacilityAssessments:

    def test_returns_dataframe(self, facilities):
        assert isinstance(facilities, pd.DataFrame)

    def test_facility_count_matches_config(self, facilities):
        # 108 facilities × 2 rounds = 216 records
        expected = len(HEALTH_FACILITIES) * 2
        assert len(facilities) == expected, (
            f"Expected {expected} records, got {len(facilities)}"
        )

    def test_readiness_score_range(self, facilities):
        assert facilities["readiness_score"].between(0, 100).all()

    def test_facility_types(self, facilities):
        valid_types = {"DHQ", "RHC", "BHU"}
        assert set(facilities["facility_type"].unique()).issubset(valid_types)


# ---------------------------------------------------------------------------
# Back-check tests
# ---------------------------------------------------------------------------

class TestBackcheckRecords:

    def test_backcheck_sample_size(self, visits):
        bc = generate_backcheck_records(visits, sample_rate=0.10)
        child_visits = visits[visits["record_type"] == "child"]
        expected = int(len(child_visits) * 0.10)
        # Allow ±5 rows due to rounding
        assert abs(len(bc) - expected) <= 5

    def test_pass_rate_reasonable(self, visits):
        bc = generate_backcheck_records(visits, sample_rate=0.10)
        pass_rate = bc["overall_pass"].mean()
        # Most back-checks should pass (simulated small discrepancies)
        assert pass_rate > 0.50, f"Back-check pass rate unexpectedly low: {pass_rate:.2%}"

    def test_discrepancies_non_negative(self, visits):
        bc = generate_backcheck_records(visits, sample_rate=0.10)
        assert (bc["height_discrepancy_cm"] >= 0).all()
        assert (bc["weight_discrepancy_kg"] >= 0).all()

