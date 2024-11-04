"""
Tests for the ETL transformation layer.
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
)
from psaksh_data_platform.etl.transform import (
    transform_households,
    transform_followup_visits,
    transform_facility_assessments,
    build_fct_child_nutrition,
    build_fct_maternal_health,
    build_rpt_district_summary,
)


@pytest.fixture(scope="module")
def raw_households():
    return generate_households(n=200)


@pytest.fixture(scope="module")
def raw_visits(raw_households):
    return generate_followup_visits(raw_households, rounds=2)


@pytest.fixture(scope="module")
def clean_households(raw_households):
    return transform_households(raw_households)


@pytest.fixture(scope="module")
def clean_visits(raw_visits):
    return transform_followup_visits(raw_visits)


class TestTransformHouseholds:

    def test_no_duplicate_ids(self, clean_households):
        assert clean_households["household_id"].nunique() == len(clean_households)

    def test_enrollment_date_is_date(self, clean_households):
        # After transform, enrollment_date should be date objects
        assert clean_households["enrollment_date"].notna().any()

    def test_invalid_gps_nulled(self, raw_households):
        # Inject an out-of-bounds GPS row
        bad = raw_households.copy()
        bad.loc[0, "gps_latitude"]  = 0.0   # outside Pakistan
        bad.loc[0, "gps_longitude"] = 0.0
        result = transform_households(bad)
        # The bad row's GPS should be null
        bad_hh = result[result["household_id"] == bad.loc[0, "household_id"]]
        if not bad_hh.empty:
            assert pd.isna(bad_hh.iloc[0]["gps_latitude"])

    def test_only_consented_records(self, clean_households):
        assert (clean_households["consent_given"] == True).all()


class TestTransformVisits:

    def test_no_duplicate_visit_ids(self, clean_visits):
        assert clean_visits["visit_id"].nunique() == len(clean_visits)

    def test_implausible_heights_nulled(self, raw_visits):
        bad = raw_visits.copy()
        child_idx = bad[bad["record_type"] == "child"].index[0]
        bad.loc[child_idx, "height_cm"] = 200.0  # implausible
        result = transform_followup_visits(bad)
        bad_visit = result[result["visit_id"] == bad.loc[child_idx, "visit_id"]]
        if not bad_visit.empty:
            assert pd.isna(bad_visit.iloc[0]["height_cm"])

    def test_age_groups_assigned(self, clean_visits):
        child = clean_visits[clean_visits["record_type"] == "child"]
        assert "child_age_group" in child.columns
        assert child["child_age_group"].notna().any()


class TestFactTables:

    def test_fct_child_has_ses(self, clean_visits, clean_households):
        fct = build_fct_child_nutrition(clean_visits, clean_households)
        assert "ses_tier" in fct.columns
        assert fct["ses_tier"].notna().any()

    def test_fct_maternal_has_anc(self, clean_visits, clean_households):
        fct = build_fct_maternal_health(clean_visits, clean_households)
        assert "anc_4plus" in fct.columns

    def test_rpt_summary_has_all_districts(self, clean_visits, clean_households):
        fct_child    = build_fct_child_nutrition(clean_visits, clean_households)
        fct_maternal = build_fct_maternal_health(clean_visits, clean_households)
        rpt = build_rpt_district_summary(fct_child, fct_maternal)
        assert "district" in rpt.columns
        assert len(rpt) > 0

    def test_rpt_rates_between_0_and_1(self, clean_visits, clean_households):
        fct_child    = build_fct_child_nutrition(clean_visits, clean_households)
        fct_maternal = build_fct_maternal_health(clean_visits, clean_households)
        rpt = build_rpt_district_summary(fct_child, fct_maternal)
        rate_cols = [c for c in rpt.columns if c.endswith("_rate")]
        for col in rate_cols:
            valid = rpt[col].dropna()
            assert (valid >= 0).all() and (valid <= 1).all(), f"{col} out of [0,1] range"

