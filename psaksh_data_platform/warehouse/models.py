"""
SQLAlchemy ORM models for the psaksh data warehouse.

Layer structure:
  raw_*        — exact copies of source data, never modified
  stg_*        — cleaned, typed, validated staging tables
  dim_*        — dimension tables (slowly changing)
  fct_*        — fact tables (analytical grain)
  rpt_*        — pre-aggregated reporting tables
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Dimension tables
# ---------------------------------------------------------------------------

class DimDistrict(Base):
    __tablename__ = "dim_district"

    district_id   = Column(Integer, primary_key=True, autoincrement=True)
    district_name = Column(String(100), nullable=False, unique=True)
    province      = Column(String(100), default="Punjab")
    centre_lat    = Column(Float)
    centre_lon    = Column(Float)
    created_at    = Column(DateTime, default=datetime.utcnow)


class DimUnionCouncil(Base):
    __tablename__ = "dim_union_council"

    uc_id         = Column(Integer, primary_key=True, autoincrement=True)
    uc_name       = Column(String(150), nullable=False)
    district_id   = Column(Integer, ForeignKey("dim_district.district_id"))
    district      = relationship("DimDistrict")
    created_at    = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (UniqueConstraint("uc_name", "district_id"),)


class DimEnumerator(Base):
    __tablename__ = "dim_enumerator"

    enumerator_id   = Column(String(10), primary_key=True)
    enumerator_name = Column(String(150), nullable=False)
    district_id     = Column(Integer, ForeignKey("dim_district.district_id"))
    district        = relationship("DimDistrict")
    active          = Column(Boolean, default=True)
    hired_date      = Column(Date)
    created_at      = Column(DateTime, default=datetime.utcnow)


class DimFacility(Base):
    __tablename__ = "dim_facility"

    facility_id   = Column(String(10), primary_key=True)
    facility_name = Column(String(200), nullable=False)
    facility_type = Column(String(10))   # DHQ, RHC, BHU
    district_id   = Column(Integer, ForeignKey("dim_district.district_id"))
    district      = relationship("DimDistrict")
    gps_latitude  = Column(Float)
    gps_longitude = Column(Float)
    active        = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Staging tables (cleaned source data)
# ---------------------------------------------------------------------------

class StgHousehold(Base):
    __tablename__ = "stg_household"

    household_id            = Column(String(20), primary_key=True)
    district                = Column(String(100))
    union_council           = Column(String(150))
    enumerator_id           = Column(String(10), ForeignKey("dim_enumerator.enumerator_id"))
    respondent_name         = Column(String(200))
    respondent_age          = Column(Integer)
    respondent_relation     = Column(String(50))
    household_head_name     = Column(String(200))
    household_head_age      = Column(Integer)
    household_size          = Column(Integer)
    children_under_5        = Column(Integer)
    women_15_49             = Column(Integer)
    ses_tier                = Column(String(10))
    wall_material           = Column(String(50))
    roof_material           = Column(String(50))
    water_source            = Column(String(50))
    toilet_type             = Column(String(50))
    electricity             = Column(Boolean)
    mobile_phone            = Column(Boolean)
    smartphone              = Column(Boolean)
    nearest_facility_id     = Column(String(10), ForeignKey("dim_facility.facility_id"))
    distance_to_facility_km = Column(Numeric(6, 2))
    gps_latitude            = Column(Float)
    gps_longitude           = Column(Float)
    gps_accuracy_m          = Column(Float)
    enrollment_date         = Column(Date)
    consent_given           = Column(Boolean)
    interview_duration_min  = Column(Integer)
    form_version            = Column(String(10))
    loaded_at               = Column(DateTime, default=datetime.utcnow)


class StgFollowupVisit(Base):
    __tablename__ = "stg_followup_visit"

    visit_id                 = Column(String(20), primary_key=True)
    household_id             = Column(String(20), ForeignKey("stg_household.household_id"))
    visit_round              = Column(Integer)
    visit_date               = Column(Date)
    enumerator_id            = Column(String(10), ForeignKey("dim_enumerator.enumerator_id"))
    district                 = Column(String(100))
    union_council            = Column(String(150))
    record_type              = Column(String(10))   # child | maternal
    child_index              = Column(Integer)
    child_age_months         = Column(Integer)
    child_sex                = Column(String(10))
    height_cm                = Column(Numeric(5, 1))
    weight_kg                = Column(Numeric(5, 2))
    muac_mm                  = Column(Numeric(5, 1))
    haz_score                = Column(Numeric(6, 3))
    waz_score                = Column(Numeric(6, 3))
    whz_score                = Column(Numeric(6, 3))
    stunted                  = Column(Boolean)
    wasted                   = Column(Boolean)
    underweight              = Column(Boolean)
    severe_stunted           = Column(Boolean)
    severe_wasted            = Column(Boolean)
    diarrhea_2w              = Column(Boolean)
    ari_2w                   = Column(Boolean)
    fever_2w                 = Column(Boolean)
    breastfed                = Column(Boolean)
    exclusive_bf             = Column(Boolean)
    vaccination_full         = Column(Boolean)
    hemoglobin_gdl           = Column(Numeric(4, 1))
    anemia                   = Column(Boolean)
    maternal_age             = Column(Integer)
    currently_pregnant       = Column(Boolean)
    gestational_age_wks      = Column(Integer)
    anc_visits               = Column(Integer)
    anc_4plus                = Column(Boolean)
    last_delivery_skilled    = Column(Boolean)
    interview_duration_min   = Column(Integer)
    form_version             = Column(String(10))
    loaded_at                = Column(DateTime, default=datetime.utcnow)


class StgFacilityAssessment(Base):
    __tablename__ = "stg_facility_assessment"

    assessment_id          = Column(String(20), primary_key=True)
    facility_id            = Column(String(10), ForeignKey("dim_facility.facility_id"))
    assessment_round       = Column(Integer)
    assessment_date        = Column(Date)
    enumerator_id          = Column(String(10))
    doctors_present        = Column(Integer)
    nurses_present         = Column(Integer)
    lady_health_workers    = Column(Integer)
    electricity_available  = Column(Boolean)
    water_available        = Column(Boolean)
    functional_toilet      = Column(Boolean)
    cold_chain_functional  = Column(Boolean)
    stockout_oxytocin      = Column(Boolean)
    stockout_amoxicillin   = Column(Boolean)
    stockout_ors           = Column(Boolean)
    stockout_zinc          = Column(Boolean)
    stockout_iron_folate   = Column(Boolean)
    stockout_vaccines      = Column(Boolean)
    anc_available          = Column(Boolean)
    delivery_available     = Column(Boolean)
    vaccination_available  = Column(Boolean)
    growth_monitoring      = Column(Boolean)
    readiness_score        = Column(Numeric(5, 1))
    form_version           = Column(String(10))
    loaded_at              = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Fact tables (analytical grain)
# ---------------------------------------------------------------------------

class FctChildNutrition(Base):
    """One row per child per visit round — primary analytical fact table."""
    __tablename__ = "fct_child_nutrition"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    visit_id              = Column(String(20), ForeignKey("stg_followup_visit.visit_id"), unique=True)
    household_id          = Column(String(20), ForeignKey("stg_household.household_id"))
    visit_round           = Column(Integer)
    visit_date            = Column(Date)
    district              = Column(String(100))
    union_council         = Column(String(150))
    ses_tier              = Column(String(10))
    child_age_months      = Column(Integer)
    child_age_group       = Column(String(20))   # 0-5, 6-11, 12-23, 24-35, 36-59
    child_sex             = Column(String(10))
    haz_score             = Column(Numeric(6, 3))
    waz_score             = Column(Numeric(6, 3))
    whz_score             = Column(Numeric(6, 3))
    stunted               = Column(Boolean)
    wasted                = Column(Boolean)
    underweight           = Column(Boolean)
    severe_stunted        = Column(Boolean)
    severe_wasted         = Column(Boolean)
    anemia                = Column(Boolean)
    diarrhea_2w           = Column(Boolean)
    ari_2w                = Column(Boolean)
    fever_2w              = Column(Boolean)
    vaccination_full      = Column(Boolean)
    nearest_facility_id   = Column(String(10))
    distance_to_facility  = Column(Numeric(6, 2))
    loaded_at             = Column(DateTime, default=datetime.utcnow)


class FctMaternalHealth(Base):
    """One row per woman per visit round."""
    __tablename__ = "fct_maternal_health"

    id                      = Column(Integer, primary_key=True, autoincrement=True)
    visit_id                = Column(String(20), ForeignKey("stg_followup_visit.visit_id"), unique=True)
    household_id            = Column(String(20), ForeignKey("stg_household.household_id"))
    visit_round             = Column(Integer)
    visit_date              = Column(Date)
    district                = Column(String(100))
    union_council           = Column(String(150))
    ses_tier                = Column(String(10))
    maternal_age            = Column(Integer)
    maternal_age_group      = Column(String(20))   # 15-19, 20-24, 25-29, 30-34, 35-49
    currently_pregnant      = Column(Boolean)
    anc_4plus               = Column(Boolean)
    last_delivery_skilled   = Column(Boolean)
    anemia                  = Column(Boolean)
    hemoglobin_gdl          = Column(Numeric(4, 1))
    loaded_at               = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# Reporting tables (pre-aggregated)
# ---------------------------------------------------------------------------

class RptDistrictSummary(Base):
    """Monthly district-level summary for dashboards."""
    __tablename__ = "rpt_district_summary"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    district              = Column(String(100))
    report_month          = Column(String(7))   # YYYY-MM
    visit_round           = Column(Integer)
    children_measured     = Column(Integer)
    stunting_rate         = Column(Numeric(5, 3))
    wasting_rate          = Column(Numeric(5, 3))
    underweight_rate      = Column(Numeric(5, 3))
    anemia_children_rate  = Column(Numeric(5, 3))
    anemia_maternal_rate  = Column(Numeric(5, 3))
    anc_4plus_rate        = Column(Numeric(5, 3))
    skilled_delivery_rate = Column(Numeric(5, 3))
    vaccination_rate      = Column(Numeric(5, 3))
    diarrhea_rate         = Column(Numeric(5, 3))
    refreshed_at          = Column(DateTime, default=datetime.utcnow)
