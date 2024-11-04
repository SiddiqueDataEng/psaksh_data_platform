"""
PSAKSH REST API — Power BI / Tableau / Generic BI connector

Endpoints follow OData-compatible conventions so Power BI can connect
via the Web connector without any custom connector code.

Base URL: https://softcomputech.com/publichealth/api/v1/

Authentication: API key via ?api_key=<key> or X-API-Key header
(set PSAKSH_API_KEY env var; defaults to 'demo' for open access)

Power BI Web connector URL examples:
  https://softcomputech.com/publichealth/api/v1/child-nutrition
  https://softcomputech.com/publichealth/api/v1/maternal-health
  https://softcomputech.com/publichealth/api/v1/district-summary
  https://softcomputech.com/publichealth/api/v1/facilities
  https://softcomputech.com/publichealth/api/v1/pipeline-status

Tableau Web Data Connector:
  Use the /api/v1/tableau/<dataset> endpoints which return
  Tableau-compatible JSON schema.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from flask import Blueprint, jsonify, request, current_app

api_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

# ── Auth ──────────────────────────────────────────────────────────────────────
API_KEY = os.environ.get("PSAKSH_API_KEY", "demo")

def _auth_ok() -> bool:
    key = request.args.get("api_key") or request.headers.get("X-API-Key", "")
    return key == API_KEY or API_KEY == "demo"


# ── Data loader ───────────────────────────────────────────────────────────────
def _get_data_dir() -> Path:
    """Resolve data directory relative to this file."""
    return Path(__file__).resolve().parents[2] / "data"


def _load(name: str, layer: str = "gold") -> pd.DataFrame:
    """Load dataset from Gold -> Silver -> Raw fallback chain with numeric coercion."""
    data_dir = _get_data_dir()
    NUMERIC_COLS = [
        "stunted", "wasted", "underweight", "severe_stunted", "severe_wasted",
        "anemia", "diarrhea_2w", "ari_2w", "fever_2w", "vaccination_full",
        "exclusive_bf", "anc_4plus", "last_delivery_skilled",
        "haz_score", "waz_score", "whz_score", "hemoglobin_gdl",
        "child_age_months", "maternal_age", "readiness_score", "overall_score",
        "stunting_rate", "wasting_rate", "underweight_rate", "anemia_rate",
        "diarrhea_rate", "vaccination_rate", "anc_4plus_rate",
        "skilled_delivery_rate", "anemia_maternal_rate", "visit_round", "survey_year",
    ]
    for search_layer, suffix in [
        (layer,    ".parquet"),
        (layer,    ".csv"),
        ("silver", ".parquet"),
        ("silver", ".csv"),
        ("raw",    ".csv"),
    ]:
        path = data_dir / search_layer / f"{name}{suffix}"
        if path.exists():
            try:
                df = pd.read_parquet(str(path)) if suffix == ".parquet" \
                     else pd.read_csv(str(path), low_memory=False)
                # Coerce indicator columns to numeric
                for col in NUMERIC_COLS:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                return df
            except Exception:
                continue
    return pd.DataFrame()


def _df_to_response(df: pd.DataFrame, meta: dict | None = None) -> dict:
    """Convert DataFrame to API response with metadata."""
    # Convert datetime columns to ISO strings
    for col in df.select_dtypes(include=["datetime64[ns]", "datetime64[ns, UTC]"]).columns:
        df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%S")

    # Drop internal layer columns
    df = df.drop(columns=[c for c in ["_layer","_source_file","_ingested_at"]
                           if c in df.columns], errors="ignore")

    # Apply filters from query params
    for param, value in request.args.items():
        if param in ("api_key", "format", "limit", "offset", "fields"):
            continue
        if param in df.columns:
            df = df[df[param].astype(str).str.lower() == value.lower()]

    # Pagination
    limit  = min(int(request.args.get("limit",  10000)), 50000)
    offset = int(request.args.get("offset", 0))
    total  = len(df)
    df     = df.iloc[offset: offset + limit]

    # Field selection
    fields = request.args.get("fields")
    if fields:
        cols = [f.strip() for f in fields.split(",") if f.strip() in df.columns]
        if cols:
            df = df[cols]

    return {
        "meta": {
            "dataset":      meta.get("name", "unknown") if meta else "unknown",
            "description":  meta.get("description", "") if meta else "",
            "total_rows":   total,
            "returned":     len(df),
            "offset":       offset,
            "limit":        limit,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
            "api_version":  "v1",
            "source":       "PSAKSH — Public Sector Analytics & Knowledge Systems Hub",
        },
        "columns": list(df.columns),
        "data":    df.to_dict(orient="records"),
    }


# ── Discovery endpoint ────────────────────────────────────────────────────────

@api_bp.route("/", methods=["GET"])
@api_bp.route("", methods=["GET"])
def api_index():
    """API discovery — lists all available endpoints."""
    # Build base URL: always use /publichealth/api/v1 as the canonical prefix
    # (Passenger on cPanel strips /publichealth from PATH_INFO, but the
    #  browser-visible URL still includes it)
    host = request.host_url.rstrip("/")
    base = f"{host}/publichealth/api/v1"
    return jsonify({
        "name":        "PSAKSH REST API",
        "description": "Public Sector Analytics & Knowledge Systems Hub — Data API",
        "version":     "v1",
        "auth":        "Pass ?api_key=demo or X-API-Key: demo header",
        "endpoints": {
            "child_nutrition":  f"{base}/child-nutrition",
            "maternal_health":  f"{base}/maternal-health",
            "district_summary": f"{base}/district-summary",
            "facilities":       f"{base}/facilities",
            "households":       f"{base}/households",
            "pipeline_status":  f"{base}/pipeline-status",
            "kpis":             f"{base}/kpis",
            "tableau_schema":   f"{base}/tableau/child-nutrition",
        },
        "powerbi_tip": "In Power BI: Get Data → Web → paste any endpoint URL above",
        "tableau_tip": "In Tableau: Web Data Connector → use /tableau/<dataset> endpoints",
        "filters":     "Append ?district=Lahore&visit_round=1 to filter any endpoint",
        "pagination":  "Use ?limit=1000&offset=0 for pagination",
        "fields":      "Use ?fields=district,stunting_rate to select columns",
    })


# ── Child Nutrition ───────────────────────────────────────────────────────────

@api_bp.route("/child-nutrition", methods=["GET"])
def child_nutrition():
    if not _auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    df = _load("fct_child_nutrition")
    return jsonify(_df_to_response(df, {
        "name": "child_nutrition",
        "description": "Child anthropometry, morbidity, and nutrition indicators. "
                       "One row per child per visit round. "
                       "Key indicators: stunted, wasted, underweight, anemia, diarrhea_2w.",
    }))


# ── Maternal Health ───────────────────────────────────────────────────────────

@api_bp.route("/maternal-health", methods=["GET"])
def maternal_health():
    if not _auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    df = _load("fct_maternal_health")
    return jsonify(_df_to_response(df, {
        "name": "maternal_health",
        "description": "Maternal health indicators per visit round. "
                       "Key indicators: anc_4plus, last_delivery_skilled, anemia, hemoglobin_gdl.",
    }))


# ── District Summary (pre-aggregated KPIs) ────────────────────────────────────

@api_bp.route("/district-summary", methods=["GET"])
def district_summary():
    if not _auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    df = _load("rpt_district_summary")
    return jsonify(_df_to_response(df, {
        "name": "district_summary",
        "description": "Pre-aggregated district-level KPIs by visit round. "
                       "Ideal for Power BI/Tableau dashboards. "
                       "Includes stunting_rate, wasting_rate, anemia_rate, anc_4plus_rate.",
    }))


# ── Facilities ────────────────────────────────────────────────────────────────

@api_bp.route("/facilities", methods=["GET"])
def facilities():
    if not _auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    df = _load("facility_assessments", layer="raw")
    return jsonify(_df_to_response(df, {
        "name": "facilities",
        "description": "Health facility readiness assessments. "
                       "Includes readiness_score, stock-out rates, staffing, infrastructure.",
    }))


# ── Households ────────────────────────────────────────────────────────────────

@api_bp.route("/households", methods=["GET"])
def households():
    if not _auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    df = _load("households", layer="raw")
    # Strip PII before serving
    pii_cols = ["respondent_name", "household_head_name", "gps_latitude", "gps_longitude"]
    df = df.drop(columns=[c for c in pii_cols if c in df.columns], errors="ignore")
    return jsonify(_df_to_response(df, {
        "name": "households",
        "description": "Enrolled household characteristics (PII removed). "
                       "Includes district, SES tier, water source, household size.",
    }))


# ── KPIs (single-row summary for executive dashboards) ───────────────────────

@api_bp.route("/kpis", methods=["GET"])
def kpis():
    if not _auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    try:
        child = _load("fct_child_nutrition")
        mat   = _load("fct_maternal_health")
        hh    = _load("households", layer="raw")

        def _rate(df, col):
            if df.empty or col not in df.columns:
                return None
            v = df[col].mean(skipna=True)
            return round(float(v), 4) if v == v else None

        result = {
            "households_enrolled":   len(hh),
            "children_measured":     len(child),
            "women_assessed":        len(mat),
            "stunting_rate":         _rate(child, "stunted"),
            "wasting_rate":          _rate(child, "wasted"),
            "underweight_rate":      _rate(child, "underweight"),
            "child_anemia_rate":     _rate(child, "anemia"),
            "diarrhea_rate":         _rate(child, "diarrhea_2w"),
            "anc_4plus_rate":        _rate(mat,   "anc_4plus"),
            "skilled_delivery_rate": _rate(mat,   "last_delivery_skilled"),
            "maternal_anemia_rate":  _rate(mat,   "anemia"),
            "refreshed_at":          datetime.now(timezone.utc).isoformat(),
            "source":                "PSAKSH",
        }
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Pipeline Status ───────────────────────────────────────────────────────────

@api_bp.route("/pipeline-status", methods=["GET"])
def pipeline_status():
    if not _auth_ok():
        return jsonify({"error": "Unauthorized"}), 401
    df = _load("rpt_pipeline_status", layer="gold")
    if df.empty:
        # Build from directory scan
        data_dir = _get_data_dir()
        rows = []
        for layer in ["raw", "bronze", "silver", "gold"]:
            d = data_dir / layer
            if d.exists():
                for f in d.glob("*"):
                    if f.suffix in (".csv", ".parquet", ".json", ".avro"):
                        rows.append({
                            "layer": layer, "file": f.name,
                            "size_kb": f.stat().st_size // 1024,
                            "format": f.suffix.lstrip("."),
                        })
        df = pd.DataFrame(rows)
    return jsonify(_df_to_response(df, {
        "name": "pipeline_status",
        "description": "Medallion pipeline layer statistics.",
    }))


# ── Tableau WDC schema endpoint ───────────────────────────────────────────────

@api_bp.route("/tableau/<dataset>", methods=["GET"])
def tableau_endpoint(dataset: str):
    """
    Tableau Web Data Connector compatible endpoint.
    Returns data with Tableau-friendly column type hints.
    """
    if not _auth_ok():
        return jsonify({"error": "Unauthorized"}), 401

    dataset_map = {
        "child-nutrition":  "fct_child_nutrition",
        "maternal-health":  "fct_maternal_health",
        "district-summary": "rpt_district_summary",
        "facilities":       "facility_assessments",
        "households":       "households",
        "kpis":             "rpt_district_summary",
    }
    name = dataset_map.get(dataset)
    if not name:
        return jsonify({"error": f"Unknown dataset: {dataset}",
                        "available": list(dataset_map.keys())}), 404

    df = _load(name)
    if df.empty:
        return jsonify({"error": "No data available"}), 404

    # Build Tableau column schema
    type_map = {
        "int64": "int", "int32": "int", "float64": "float", "float32": "float",
        "bool": "bool", "object": "string", "datetime64[ns]": "datetime",
    }
    columns = [
        {"id": col, "alias": col.replace("_", " ").title(),
         "dataType": type_map.get(str(df[col].dtype), "string")}
        for col in df.columns
        if col not in ["_layer", "_source_file", "_ingested_at"]
    ]

    # Convert for JSON serialisation
    for col in df.select_dtypes(include=["datetime64[ns]"]).columns:
        df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%S")
    df = df.drop(columns=[c for c in ["_layer","_source_file","_ingested_at"]
                           if c in df.columns], errors="ignore")

    return jsonify({
        "connectionName": f"PSAKSH — {dataset}",
        "columns":        columns,
        "rows":           df.to_dict(orient="records"),
        "totalRows":      len(df),
    })
