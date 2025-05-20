"""
PSAKSH Analytics Dashboard â€” Flask / Passenger WSGI
URL: https://softcomputech.com/publichealth

Enhanced with:
  - Storytelling narrative insights on every page
  - Dynamic KPI cards with trend arrows and contextual alerts
  - Bilingual data quality indicators
  - Medallion ETL status with layer-by-layer progress
  - Power BI / Tableau API endpoints
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# â”€â”€ Paths â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
APP_DIR  = Path(__file__).resolve().parent
PKG_DIR  = APP_DIR.parent
ROOT_DIR = PKG_DIR.parent

for _p in [str(ROOT_DIR), str(PKG_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# â”€â”€ Flask â€” the ONLY top-level import â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Everything else (pandas, plotly, analytics) is imported lazily inside
# functions so a broken venv package cannot prevent Flask from loading.
from flask import Flask, jsonify, render_template, request

# â”€â”€ App â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
STATIC_DIR = APP_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

app = Flask(
    __name__,
    template_folder=str(APP_DIR / "templates"),
    static_folder=str(STATIC_DIR),
    static_url_path="/publichealth/static",
)
app.config["APPLICATION_ROOT"]      = "/publichealth"
app.config["TEMPLATES_AUTO_RELOAD"] = True   # always reload templates from disk

# Register API blueprint
# Production (Passenger strips /publichealth): /api/v1/...
# Local dev (full path): /publichealth/api/v1/...
# Use different names to avoid duplicate endpoint warnings
try:
    from psaksh_data_platform.webapp.api.routes import api_bp
    app.register_blueprint(api_bp)                                    # /api/v1/...
    app.register_blueprint(api_bp,
                           url_prefix="/publichealth/api/v1",
                           name="api_v1_prefixed")                    # /publichealth/api/v1/...
except Exception as _e:
    import logging as _log
    _log.getLogger(__name__).warning(f"API blueprint not loaded: {_e}")

PROCESSED_DIR = PKG_DIR / "data" / "processed"
RAW_DIR       = PKG_DIR / "data" / "raw"


# â”€â”€ Lazy imports â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _pd():
    import pandas as pd
    return pd

def _px():
    import plotly.express as px
    return px

def _pio():
    import plotly.io as pio
    pio.templates.default = "plotly_white"
    return pio

def _analytics():
    from psaksh_data_platform.analytics.nutrition import (
        national_prevalence, prevalence_by_group,
        prevalence_trend, double_burden_analysis,
    )
    from psaksh_data_platform.analytics.field_monitoring import (
        backcheck_summary, coverage_by_uc, submission_timeline,
    )
    return dict(
        national_prevalence=national_prevalence,
        prevalence_by_group=prevalence_by_group,
        prevalence_trend=prevalence_trend,
        double_burden_analysis=double_burden_analysis,
        backcheck_summary=backcheck_summary,
        coverage_by_uc=coverage_by_uc,
        submission_timeline=submission_timeline,
    )


# â”€â”€ Data helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _load(name: str):
    """
    Load a dataset by name. Resolution order:
      1. data/gold/<name>.parquet        (ETL Gold -- most processed, numeric dtypes)
      2. data/silver/<name>.parquet      (ETL Silver -- cleaned)
      3. data/processed/<name>.parquet   (legacy)
      4. data/raw/current/<name>.parquet (DB exports)
      5. data/raw/<name>.csv             (fallback)

    After loading, coerces known indicator columns to numeric so analytics work
    even when Parquet stores them as ArrowDtype string after Silver processing.
    """
    pd = _pd()
    data_base = PKG_DIR / "data"

    search_paths = [
        data_base / "gold"           / f"{name}.parquet",
        data_base / "gold"           / f"{name}.csv",
        data_base / "silver"         / f"{name}.parquet",
        data_base / "silver"         / f"{name}.csv",
        data_base / "processed"      / f"{name}.parquet",
        data_base / "raw" / "current" / f"{name}.parquet",
        data_base / "raw"            / f"{name}.csv",
    ]

    df = pd.DataFrame()
    for path in search_paths:
        if path.exists():
            try:
                if path.suffix == ".parquet":
                    df = pd.read_parquet(str(path))
                else:
                    df = pd.read_csv(str(path), low_memory=False)
                break
            except Exception:
                continue

    if df.empty:
        return df

    # Coerce indicator columns to numeric -- they may be ArrowDtype str
    # after parquet round-trip through Silver layer string normalisation
    NUMERIC_COLS = [
        "stunted", "wasted", "underweight", "severe_stunted", "severe_wasted",
        "anemia", "diarrhea_2w", "ari_2w", "fever_2w", "vaccination_full",
        "exclusive_bf", "anc_4plus", "last_delivery_skilled",
        "haz_score", "waz_score", "whz_score",
        "hemoglobin_gdl", "child_age_months", "maternal_age",
        "readiness_score", "overall_score",
        "stunting_rate", "wasting_rate", "underweight_rate",
        "anemia_rate", "diarrhea_rate", "vaccination_rate",
        "anc_4plus_rate", "skilled_delivery_rate", "anemia_maternal_rate",
        "visit_round", "survey_year",
    ]
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Defensive: if binary indicator columns have values > 1, they are
    # percentages (0-100) not proportions (0-1) — normalise to 0-1
    BINARY_COLS = [
        "stunted", "wasted", "underweight", "severe_stunted", "severe_wasted",
        "anemia", "diarrhea_2w", "ari_2w", "fever_2w", "vaccination_full",
        "exclusive_bf", "anc_4plus", "last_delivery_skilled",
    ]
    for col in BINARY_COLS:
        if col in df.columns and df[col].max() > 1.5:
            df[col] = df[col] / 100.0

    return df

def load_all() -> dict:
    return {
        "households":   _load("households"),
        "visits":       _load("followup_visits"),
        "fct_child":    _load("fct_child_nutrition"),
        "fct_maternal": _load("fct_maternal_health"),
        "facilities":   _load("facility_assessments"),
        "backcheck":    _load("backcheck_records"),
        "enumerator_perf": _load("enumerator_performance"),
    }


def _story_headline(fct, mat) -> str:
    """Generate a dynamic narrative headline based on worst indicator."""
    try:
        pd = _pd()
        if fct.empty:
            return "ðŸ“Š PSAKSH â€” Run the ETL pipeline to load data and generate insights."
        if "district" in fct.columns and "stunted" in fct.columns:
            dist = fct.groupby("district")["stunted"].mean()
            worst = dist.idxmax()
            worst_rate = dist.max()
            nat_avg = fct["stunted"].mean()
            gap = (worst_rate - nat_avg) * 100
            return (
                f"âš ï¸ {worst} district carries the highest stunting burden at "
                f"{worst_rate:.1%} â€” {gap:.1f}pp above the programme average of {nat_avg:.1%}."
            )
    except Exception:
        pass
    return "ðŸ“Š PSAKSH â€” Public Health Analytics Dashboard | Pakistan Field Operations"


def _dq_summary(hh, visits) -> str | None:
    """Build a short data quality summary string."""
    try:
        issues = []
        if not hh.empty:
            dup = int(hh.duplicated(subset=["household_id"]).sum()) if "household_id" in hh.columns else 0
            if dup:
                issues.append(f"{dup} duplicate household records detected")
        if not visits.empty:
            for col in ["water_source", "ses_tier"]:
                if col in visits.columns:
                    urdu_vals = visits[col].astype(str).str.contains(
                        "Ù¾Ø§Ø¦Ù¾|ÛÛŒÙ†Úˆ|Ú©Ù†ÙˆØ§Úº|Ù¹ÛŒÙ†Ú©Ø±|Ú©Ù…|Ø¯Ø±Ù…ÛŒØ§Ù†Û|Ø²ÛŒØ§Ø¯Û", na=False
                    ).sum()
                    if urdu_vals:
                        issues.append(f"{urdu_vals} bilingual field values normalised")
                        break
        return " | ".join(issues) if issues else None
    except Exception:
        return None


def _build_insights(fct, indicator: str) -> dict:
    """Build insight dict for nutrition page."""
    try:
        if fct.empty:
            return {}
        src_col = indicator.replace("_rate", "")
        if src_col not in fct.columns:
            return {}
        dist = fct.groupby("district")[src_col].mean()
        worst = dist.idxmax()
        best  = dist.idxmin()
        nat   = fct[src_col].mean()
        gap   = (dist.max() - nat) * 100
        insights = {
            "worst_district": worst,
            "worst_rate":     f"{dist.max():.1%}",
            "best_district":  best,
            "best_rate":      f"{dist.min():.1%}",
            "national_avg":   f"{nat:.1%}",
            "gap":            f"{gap:.1f}",
        }
        if "ses_tier" in fct.columns:
            ses = fct.groupby("ses_tier")[src_col].mean()
            if "low" in ses.index and "high" in ses.index:
                insights["ses_gap"] = f"{(ses['low'] - ses['high']) * 100:.1f}"
        if "visit_round" in fct.columns:
            rounds = fct.groupby("visit_round")[src_col].mean()
            if len(rounds) >= 2:
                change = (rounds.iloc[-1] - rounds.iloc[0]) * 100
                insights["trend_direction"] = "Declining" if change < 0 else "Increasing"
                insights["trend_change"] = f"{abs(change):.1f}"
        return insights
    except Exception:
        return {}


def data_ready() -> bool:
    """Return True if any usable data exists across all layers."""
    data_base = PKG_DIR / "data"
    check_paths = [
        data_base / "gold"      / "fct_child_nutrition.parquet",
        data_base / "silver"    / "followup_visits.parquet",
        data_base / "processed" / "fct_child_nutrition.parquet",
        data_base / "raw"       / "followup_visits.csv",
        data_base / "raw"       / "households.csv",
    ]
    return any(p.exists() for p in check_paths)


def fig_json(fig) -> str | None:
    """
    Serialise a Plotly figure to a JSON string for use in templates.
    Templates use:  var spec = {{ charts.foo | safe }};
                    Plotly.newPlot('divId', spec.data, spec.layout, spec.config);
    Returns None on failure so templates can show empty-state placeholders.
    """
    try:
        import plotly.io as pio
        return pio.to_json(fig)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"fig_json failed: {e}")
        return None


# Keep fig_html as a thin wrapper for any legacy callers
def fig_html(fig) -> str:
    j = fig_json(fig)
    if j is None:
        return "<p style='color:#a0aec0;text-align:center;padding:40px'>Chart unavailable</p>"
    # Return a self-contained div+script block (used only in maternal/facilities legacy templates)
    import uuid as _uuid
    div_id = "fig_" + _uuid.uuid4().hex[:8]
    return (
        f'<div id="{div_id}" style="width:100%;min-height:300px"></div>'
        f'<script>(function(){{var s={j};'
        f'Plotly.newPlot("{div_id}",s.data,s.layout||{{}},{{responsive:true,displayModeBar:false}});}})();</script>'
    )


# â”€â”€ Routes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/publichealth/")
@app.route("/publichealth")
@app.route("/")
def index():
    if not data_ready():
        return render_template("setup.html")
    try:
        an   = _analytics()
        data = load_all()
        fct  = data["fct_child"]
        mat  = data["fct_maternal"]
        hh   = data["households"]
        prev = an["national_prevalence"](fct) if not fct.empty else {}
        kpis = {
            "households":       len(hh),
            "children":         prev.get("n", 0),
            "stunting":         f"{prev.get('stunting_rate', 0):.1%}",
            "wasting":          f"{prev.get('wasting_rate', 0):.1%}",
            "underweight":      f"{prev.get('underweight_rate', 0):.1%}",
            "anemia_children":  f"{prev.get('anemia_rate', 0):.1%}",
            "anc_4plus":        f"{mat['anc_4plus'].mean():.1%}"
                                if not mat.empty and "anc_4plus" in mat else "â€”",
            "skilled_delivery": f"{mat['last_delivery_skilled'].mean():.1%}"
                                if not mat.empty and "last_delivery_skilled" in mat else "â€”",
        }
        charts = {}
        try:
            px = _px()
            dist = an["prevalence_by_group"](fct, ["district"])
            if "stunting_rate" in dist.columns:
                fig = px.bar(dist, x="district", y="stunting_rate", color="district",
                             title="Stunting Rate by District",
                             labels={"stunting_rate": "Rate"},
                             color_discrete_sequence=px.colors.qualitative.Set2)
                fig.update_yaxes(tickformat=".0%")
                fig.update_layout(showlegend=False, height=300, margin=dict(t=40, b=20))
                charts["stunting"] = fig_json(fig)
        except Exception:
            pass

        story = _story_headline(fct, mat)
        dq    = _dq_summary(hh, data["visits"])
        import datetime
        last_updated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

        return render_template("index.html", kpis=kpis, charts=charts,
                               story_headline=story, dq_summary=dq,
                               last_updated=last_updated)
    except Exception as e:
        import traceback
        return f"<pre style='padding:20px'>{traceback.format_exc()}</pre>", 500



@app.route("/publichealth/nutrition")
@app.route("/nutrition")
def nutrition():
    # Indicator value -> display label map
    INDICATOR_LABELS = {
        "stunting_rate":    "Stunting Rate",
        "wasting_rate":     "Wasting Rate",
        "underweight_rate": "Underweight Rate",
        "anemia_rate":      "Anemia Rate",
        "diarrhea_rate":    "Diarrhea Rate (2wk)",
    }
    indicator = request.args.get("indicator", "stunting_rate")
    if indicator not in INDICATOR_LABELS:
        indicator = "stunting_rate"
    label    = INDICATOR_LABELS[indicator]
    charts   = {}
    insights = {}
    dq_notes = None
    try:
        an  = _analytics()
        px  = _px()
        fct = load_all()["fct_child"]
        if not fct.empty:
            import pandas as _pd3
            insights = _build_insights(fct, indicator)

            # Chart 1: by district & round (grouped bar)
            dr = an["prevalence_by_group"](fct, ["district", "visit_round"])
            if indicator in dr.columns:
                # Defensive: ensure rates are in 0-1 range (not 0-100)
                import pandas as _pd3
                dr[indicator] = _pd3.to_numeric(dr[indicator], errors="coerce")
                if dr[indicator].max() > 1.5:
                    dr[indicator] = dr[indicator] / 100.0
                dr["visit_round"] = dr["visit_round"].astype(str)
                fig = px.bar(
                    dr.sort_values("visit_round"),
                    x="district", y=indicator,
                    color="visit_round", barmode="group",
                    title=f"{label} by District & Survey Round",
                    labels={indicator: label, "district": "District", "visit_round": "Round"},
                    color_discrete_sequence=px.colors.qualitative.Set2,
                )
                fig.update_yaxes(tickformat=".0%")
                fig.update_layout(height=380, margin=dict(t=50, b=70),
                                  xaxis_tickangle=-35, legend_title="Round")
                charts["by_district_round"] = fig_json(fig)

            # Chart 2: trend over rounds by district (line)
            try:
                trend = an["prevalence_trend"](fct, indicator, group_col="district")
                if not trend.empty:
                    fig2 = px.line(
                        trend.sort_values("visit_round"),
                        x="visit_round", y="rate", color="district",
                        markers=True,
                        title=f"{label} Trend by District",
                        labels={"rate": label, "visit_round": "Survey Round", "district": "District"},
                    )
                    fig2.update_yaxes(tickformat=".0%")
                    fig2.update_layout(height=340, margin=dict(t=50, b=20))
                    charts["trend"] = fig_json(fig2)
            except Exception:
                pass

            # Chart 3: by SES tier (line)
            if "ses_tier" in fct.columns:
                ses = an["prevalence_by_group"](fct, ["ses_tier", "visit_round"])
                if indicator in ses.columns:
                    ses["visit_round"] = ses["visit_round"].astype(str)
                    fig3 = px.line(
                        ses.sort_values("visit_round"),
                        x="visit_round", y=indicator, color="ses_tier",
                        markers=True,
                        title=f"{label} by Socioeconomic Tier",
                        labels={indicator: label, "visit_round": "Survey Round", "ses_tier": "SES Tier"},
                        color_discrete_map={"low": "#e74c3c", "middle": "#f39c12", "high": "#27ae60"},
                    )
                    fig3.update_yaxes(tickformat=".0%")
                    fig3.update_layout(height=320, margin=dict(t=50, b=20))
                    charts["by_ses"] = fig_json(fig3)

            # Chart 4: province comparison (bar)
            if "province" in fct.columns:
                prov = an["prevalence_by_group"](fct, ["province"])
                if indicator in prov.columns:
                    prov = prov.sort_values(indicator, ascending=False)
                    fig4 = px.bar(
                        prov, x="province", y=indicator,
                        color=indicator,
                        color_continuous_scale=[[0, "#276749"], [0.5, "#d69e2e"], [1, "#c53030"]],
                        title=f"{label} by Province",
                        labels={indicator: label, "province": "Province"},
                    )
                    fig4.update_yaxes(tickformat=".0%")
                    fig4.update_layout(height=300, showlegend=False, margin=dict(t=50, b=20))
                    charts["by_province"] = fig_json(fig4)

            # Chart 5: double burden of malnutrition (scatter bubble)
            try:
                db = an["double_burden_analysis"](fct)
                if not db.empty and "double_burden_rate" in db.columns:
                    db["visit_round"] = db["visit_round"].astype(str)
                    db["double_burden_pct"] = (db["double_burden_rate"] * 100).round(1)
                    db["stunting_pct"]      = (db["stunting_rate"]      * 100).round(1)
                    db["wasting_pct"]       = (db["wasting_rate"]       * 100).round(1)
                    # Aggregate to district level (mean across rounds)
                    db_agg = db.groupby("district").agg(
                        double_burden_pct=("double_burden_pct", "mean"),
                        stunting_pct=("stunting_pct", "mean"),
                        wasting_pct=("wasting_pct", "mean"),
                        n=("n", "sum"),
                    ).reset_index()
                    db_agg = db_agg.sort_values("double_burden_pct", ascending=False)
                    # px.scatter requires size > 0 — floor at 0.5 so all bubbles visible
                    db_agg["bubble_size"] = db_agg["double_burden_pct"].clip(lower=0.5)
                    fig5 = px.scatter(
                        db_agg,
                        x="stunting_pct",
                        y="wasting_pct",
                        size="bubble_size",
                        color="double_burden_pct",
                        hover_name="district",
                        hover_data={"stunting_pct": ":.1f",
                                    "wasting_pct":  ":.1f",
                                    "double_burden_pct": ":.1f",
                                    "bubble_size": False},
                        color_continuous_scale=[[0, "#276749"], [0.5, "#d69e2e"], [1, "#c53030"]],
                        title="Double Burden of Malnutrition by District",
                        labels={
                            "stunting_pct":      "Stunting Rate (%)",
                            "wasting_pct":       "Wasting Rate (%)",
                            "double_burden_pct": "Double Burden (%)",
                        },
                        size_max=40,
                    )
                    fig5.update_layout(
                        height=340,
                        margin=dict(t=50, b=20),
                        coloraxis_colorbar=dict(title="Double<br>Burden %"),
                    )
                    charts["double_burden"] = fig_json(fig5)
            except Exception:
                import logging as _log5, traceback as _tb5
                _log5.getLogger(__name__).warning(
                    "double_burden chart failed: " + _tb5.format_exc()
                )

            # DQ notes
            try:
                bilingual = 0
                for col in ["water_source", "ses_tier"]:
                    if col in fct.columns:
                        bilingual += int(fct[col].astype(str).str.contains(
                            "\u067e\u0627\u0626\u067e|\u06c1\u06cc\u0646\u0688"
                            "|\u06a9\u0646\u0648\u0627\u06ba|\u06a9\u0645"
                            "|\u062f\u0631\u0645\u06cc\u0627\u0646\u06c1"
                            "|\u0632\u06cc\u0627\u062f\u06c1",
                            na=False,
                        ).sum())
                if bilingual:
                    dq_notes = {"bilingual_normalised": bilingual}
            except Exception:
                pass

    except Exception:
        import traceback, logging
        logging.getLogger(__name__).error(traceback.format_exc())

    return render_template(
        "nutrition.html",
        charts=charts,
        indicator=indicator,
        indicator_label=label,
        valid_indicators=INDICATOR_LABELS,
        insights=insights,
        dq_notes=dq_notes,
    )



@app.route("/publichealth/maternal")
@app.route("/maternal")
def maternal():
    charts = {}
    kpis   = {}
    try:
        import pandas as _pd2
        import math as _math
        px  = _px()
        mat = load_all()["fct_maternal"]

        def _pct(col):
            if not mat.empty and col in mat.columns:
                v = _pd2.to_numeric(mat[col], errors="coerce").mean()
                return f"{v:.1%}" if not _math.isnan(v) else "—"
            return "—"

        kpis = {
            "women_assessed":   len(mat) if not mat.empty else 0,
            "anc_4plus":        _pct("anc_4plus"),
            "skilled_delivery": _pct("last_delivery_skilled"),
            "anemia":           _pct("anemia"),
        }

        if not mat.empty:
            # ANC 4+ trend by district & round
            if "anc_4plus" in mat.columns and "district" in mat.columns and "visit_round" in mat.columns:
                mat["_anc"] = _pd2.to_numeric(mat["anc_4plus"], errors="coerce")
                anc = mat.groupby(["district","visit_round"])["_anc"].mean().reset_index()
                anc.columns = ["district","visit_round","rate"]
                fig = px.line(anc.sort_values("visit_round"), x="visit_round", y="rate",
                              color="district", markers=True,
                              title="ANC 4+ Coverage by District & Round",
                              labels={"rate":"ANC 4+ Rate","visit_round":"Survey Round"})
                fig.update_yaxes(tickformat=".0%")
                fig.update_layout(height=340, margin=dict(t=50,b=20))
                charts["anc"] = fig_json(fig)

            # Hemoglobin box plot with anemia threshold line
            if "hemoglobin_gdl" in mat.columns and "district" in mat.columns:
                mat["_hb"] = _pd2.to_numeric(mat["hemoglobin_gdl"], errors="coerce")
                hb_data = mat.dropna(subset=["_hb"])
                if not hb_data.empty:
                    fig2 = px.box(hb_data, x="district", y="_hb", color="district",
                                  title="Maternal Hemoglobin by District (g/dL)",
                                  labels={"_hb":"Hemoglobin (g/dL)","district":"District"})
                    fig2.add_hline(y=11.0, line_dash="dash", line_color="#c53030",
                                   annotation_text="Anemia threshold (11 g/dL)")
                    fig2.update_layout(showlegend=False, height=320, margin=dict(t=50,b=20))
                    charts["hb"] = fig_json(fig2)

            # Skilled delivery rate by district (horizontal bar)
            if "last_delivery_skilled" in mat.columns and "district" in mat.columns:
                mat["_sd"] = _pd2.to_numeric(mat["last_delivery_skilled"], errors="coerce")
                sd = mat.groupby("district")["_sd"].mean().reset_index()
                sd.columns = ["district","rate"]
                sd = sd.sort_values("rate")
                fig3 = px.bar(sd, x="rate", y="district", orientation="h",
                              color="rate",
                              color_continuous_scale=[[0,"#c53030"],[0.5,"#d69e2e"],[1,"#276749"]],
                              title="Skilled Delivery Rate by District",
                              labels={"rate":"Skilled Delivery Rate","district":"District"})
                fig3.add_vline(x=0.80, line_dash="dash", line_color="#2b6cb0",
                               annotation_text="80% target")
                fig3.update_xaxes(tickformat=".0%")
                fig3.update_layout(height=420, showlegend=False, margin=dict(t=50,b=20))
                charts["skilled"] = fig_json(fig3)

            # Maternal anemia by SES tier
            if "anemia" in mat.columns and "ses_tier" in mat.columns:
                mat["_an"] = _pd2.to_numeric(mat["anemia"], errors="coerce")
                ses_an = mat.groupby("ses_tier")["_an"].mean().reset_index()
                ses_an.columns = ["ses_tier","rate"]
                fig4 = px.bar(ses_an, x="ses_tier", y="rate", color="ses_tier",
                              color_discrete_map={"low":"#c53030","middle":"#d69e2e","high":"#276749"},
                              title="Maternal Anemia Rate by SES Tier",
                              labels={"rate":"Anemia Rate","ses_tier":"SES Tier"})
                fig4.update_yaxes(tickformat=".0%")
                fig4.update_layout(showlegend=False, height=280, margin=dict(t=50,b=20))
                charts["anemia_ses"] = fig_json(fig4)

    except Exception:
        import traceback, logging
        logging.getLogger(__name__).error(traceback.format_exc())

    return render_template("maternal.html", charts=charts, kpis=kpis)


@app.route("/publichealth/field")
@app.route("/field")
def field():
    charts          = {}
    bc_kpis         = {}
    dq_issues       = {}
    enumerator_table = []
    try:
        an     = _analytics()
        px     = _px()
        data   = load_all()
        visits = data["visits"]
        hh     = data["households"]
        bc     = data["backcheck"]
        perf   = data["enumerator_perf"]

        if not visits.empty:
            tl = an["submission_timeline"](visits)
            if not tl.empty:
                fig = px.area(tl, x="visit_date", y="cumulative", color="district",
                              title="Cumulative Submissions by District")
                fig.update_layout(height=340, margin=dict(t=50,b=20))
                charts["timeline"] = fig_json(fig)
            if not hh.empty:
                cov = an["coverage_by_uc"](hh, visits)
                if not cov.empty:
                    fig2 = px.bar(cov.sort_values("coverage_pct"),
                                  x="coverage_pct", y="union_council",
                                  color="district", orientation="h",
                                  title="Visit Coverage by Union Council (%)")
                    fig2.update_layout(height=400, margin=dict(t=50,b=20))
                    charts["coverage"] = fig_json(fig2)

        if not bc.empty:
            bc_kpis = an["backcheck_summary"](bc)

        # Build enumerator table from backcheck + perf data
        if not bc.empty and "per_enumerator" in bc.columns:
            try:
                enum_bc = bc.groupby("per_enumerator").agg(
                    submissions=("original_visit_id", "count"),
                    pass_rate=("overall_pass", "mean"),
                    height_disc=("height_discrepancy_cm", "mean"),
                    weight_disc=("weight_discrepancy_kg", "mean"),
                ).reset_index()
                for _, row in enum_bc.iterrows():
                    pr = float(row.get("pass_rate", 0) or 0)
                    enumerator_table.append({
                        "enumerator_id": row["per_enumerator"],
                        "district":      "â€”",
                        "submissions":   int(row.get("submissions", 0)),
                        "pass_rate":     pr,
                        "height_disc":   float(row.get("height_disc", 0) or 0),
                        "weight_disc":   float(row.get("weight_disc", 0) or 0),
                        "quality_flag":  "FAIL" if pr < 0.70 else ("WARN" if pr < 0.85 else "PASS"),
                    })
            except Exception:
                pass

        # DQ issues summary
        try:
            bilingual = 0
            dupes     = 0
            outliers  = 0
            gps_bad   = 0
            if not hh.empty:
                dupes = int(hh.duplicated(subset=["household_id"]).sum()) if "household_id" in hh.columns else 0
                if "gps_latitude" in hh.columns:
                    gps_bad = int((~hh["gps_latitude"].between(23.5, 37.5) & hh["gps_latitude"].notna()).sum())
            if not visits.empty:
                for col in ["water_source", "ses_tier"]:
                    if col in visits.columns:
                        bilingual += int(visits[col].astype(str).str.contains(
                            "Ù¾Ø§Ø¦Ù¾|ÛÛŒÙ†Úˆ|Ú©Ù†ÙˆØ§Úº|Ù¹ÛŒÙ†Ú©Ø±|Ú©Ù…|Ø¯Ø±Ù…ÛŒØ§Ù†Û|Ø²ÛŒØ§Ø¯Û", na=False
                        ).sum())
                if "height_cm" in visits.columns:
                    outliers = int(((visits["height_cm"] < 40) | (visits["height_cm"] > 130)).sum())
            dq_issues = {
                "bilingual_values": bilingual,
                "duplicates":       dupes,
                "out_of_range":     outliers,
                "gps_issues":       gps_bad,
            }
        except Exception:
            pass

    except Exception:
        pass
    return render_template("field.html", charts=charts, bc_kpis=bc_kpis,
                           dq_issues=dq_issues, enumerator_table=enumerator_table)


@app.route("/publichealth/facilities")
@app.route("/facilities")
def facilities():
    charts = {}
    try:
        px  = _px()
        fac = load_all()["facilities"]
        if not fac.empty:
            # Normalise round column name â€” generator uses visit_round, older data uses assessment_round
            round_col = "visit_round" if "visit_round" in fac.columns else \
                        "assessment_round" if "assessment_round" in fac.columns else None

            score_col = "readiness_score" if "readiness_score" in fac.columns else \
                        "overall_score" if "overall_score" in fac.columns else None

            if score_col and "district" in fac.columns:
                group_cols = ["district", round_col] if round_col else ["district"]
                avg_r = fac.groupby(group_cols)[score_col].mean().reset_index()
                if round_col:
                    fig = px.bar(avg_r, x="district", y=score_col,
                                 color=round_col, barmode="group",
                                 title="Facility Readiness Score by District & Round",
                                 color_continuous_scale="Teal",
                                 labels={score_col: "Readiness Score (%)"})
                else:
                    fig = px.bar(avg_r, x="district", y=score_col,
                                 color="district",
                                 title="Facility Readiness Score by District",
                                 labels={score_col: "Readiness Score (%)"})
                fig.update_layout(height=340, margin=dict(t=50, b=20))
                charts["readiness"] = fig_json(fig)

            # Stock-out rates
            sc = [c for c in fac.columns if c.startswith("stockout_")]
            if sc:
                rates = fac[sc].mean().reset_index()
                rates.columns = ["commodity", "rate"]
                rates["commodity"] = (
                    rates["commodity"]
                    .str.replace("stockout_", "", regex=False)
                    .str.replace("_", " ")
                    .str.title()
                )
                fig2 = px.bar(
                    rates.sort_values("rate"),
                    x="rate", y="commodity", orientation="h",
                    title="Stock-out Rate by Commodity",
                    color="rate", color_continuous_scale="Reds",
                    labels={"rate": "Stock-out Rate"},
                )
                fig2.update_xaxes(tickformat=".0%")
                fig2.update_layout(height=320, showlegend=False, margin=dict(t=50, b=20))
                charts["stockout"] = fig_json(fig2)

            # Facility type breakdown
            if "facility_type" in fac.columns and score_col:
                type_avg = fac.groupby("facility_type")[score_col].mean().reset_index()
                fig3 = px.bar(
                    type_avg.sort_values(score_col),
                    x=score_col, y="facility_type", orientation="h",
                    title="Average Readiness by Facility Type (DHQ / RHC / BHU)",
                    color=score_col, color_continuous_scale="Blues",
                    labels={score_col: "Readiness Score (%)"},
                )
                fig3.update_layout(height=260, showlegend=False, margin=dict(t=50, b=20))
                charts["by_type"] = fig_json(fig3)

            # Province-level readiness
            if "province" in fac.columns and score_col:
                prov_avg = fac.groupby("province")[score_col].mean().reset_index()
                prov_avg = prov_avg.sort_values(score_col)
                fig4 = px.bar(
                    prov_avg, x=score_col, y="province", orientation="h",
                    color=score_col,
                    color_continuous_scale=[[0, "#c53030"], [0.6, "#d69e2e"], [1, "#276749"]],
                    title="Average Readiness Score by Province",
                    labels={score_col: "Readiness Score (%)", "province": "Province"},
                )
                fig4.add_vline(x=60, line_dash="dash", line_color="#718096",
                               annotation_text="60% threshold")
                fig4.update_layout(height=260, showlegend=False, margin=dict(t=50, b=20))
                charts["by_province"] = fig_json(fig4)

    except Exception:
        pass
    return render_template("facilities.html", charts=charts)


@app.route("/publichealth/api/summary")
@app.route("/api/summary")
def api_summary():
    try:
        fct = load_all()["fct_child"]
        if fct.empty:
            return jsonify({"error": "No data"}), 404
        return jsonify(_analytics()["national_prevalence"](fct))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/publichealth/api/submit-survey", methods=["POST"])
@app.route("/api/submit-survey", methods=["POST"])
def submit_survey():
    """
    Receive survey form submission.

    Storage strategy (correct data engineering approach):
      1. PRIMARY: Save to MySQL database (raw_household_submissions table)
                  This is the authoritative store for fresh current data.
                  The ETL pipeline exports this table as Parquet for the data lake.
      2. BACKUP:  Append to data/raw/current/households.csv
                  Fallback if DB is unavailable.
      3. FEEDBACK: Return detailed summary of what was stored and where.
    """
    import uuid as _uuid
    import datetime as _dt

    try:
        data = request.get_json(force=True) or {}

        # Generate unique household ID
        hh_id = "HH" + _uuid.uuid4().hex[:10].upper()
        now   = _dt.datetime.utcnow().isoformat()

        # Normalise bilingual yes/no fields
        for field in ["consent", "has_toilet"]:
            raw = str(data.get(field, "1")).lower().strip()
            data[field] = 1 if raw in ("1", "yes", "y", "true", "\u06c1\u0627\u06ba") else 0

        # Build the record
        pd = _pd()
        row = {
            "household_id":    hh_id,
            "province":        data.get("province", ""),
            "district":        data.get("district", ""),
            "union_council":   data.get("union_council", ""),
            "respondent_name": data.get("respondent_name", ""),
            "respondent_age":  data.get("age") or data.get("respondent_age"),
            "household_size":  data.get("household_size"),
            "children_under_5": data.get("children_u5") or data.get("children_under_5"),
            "water_source":    data.get("water_source", ""),
            "ses_tier":        data.get("ses_tier", ""),
            "has_toilet":      data.get("has_toilet", 0),
            "consent_given":   data.get("consent", 1),
            "gps_raw":         data.get("gps", ""),
            "submission_time": now,
            "data_source":     "web_survey_form",
            "form_version":    "v2.0",
        }

        # Parse GPS
        gps_raw = str(data.get("gps", "")).strip()
        if "," in gps_raw:
            try:
                parts = gps_raw.split(",")
                row["gps_latitude"]  = float(parts[0].strip())
                row["gps_longitude"] = float(parts[1].strip())
            except Exception:
                row["gps_latitude"]  = None
                row["gps_longitude"] = None

        new_row = pd.DataFrame([row])
        storage_log = []

        # ── 1. PRIMARY: MySQL database ────────────────────────────────────
        db_saved = False
        try:
            for mod_path in ["psaksh_data_platform.etl.load", "etl.load"]:
                try:
                    import importlib
                    load_mod = importlib.import_module(mod_path)
                    engine = load_mod.get_engine(use_sqlite=(os.environ.get("ENV","production") == "local"))
                    # Create table if it doesn't exist (auto-schema from DataFrame)
                    new_row.to_sql(
                        "raw_household_submissions",
                        engine,
                        if_exists="append",   # append creates table on first run
                        index=False,
                    )
                    db_saved = True
                    storage_log.append("MySQL/SQLite: raw_household_submissions table")
                    break
                except ImportError:
                    continue
        except Exception as db_err:
            storage_log.append(f"DB save failed: {str(db_err)[:80]}")

        # ── 2. BACKUP: CSV file ───────────────────────────────────────────
        current_dir = PKG_DIR / "data" / "raw" / "current"
        current_dir.mkdir(parents=True, exist_ok=True)
        csv_path = current_dir / "households.csv"
        try:
            if csv_path.exists():
                existing = pd.read_csv(str(csv_path), low_memory=False)
                pd.concat([existing, new_row], ignore_index=True).to_csv(str(csv_path), index=False)
            else:
                new_row.to_csv(str(csv_path), index=False)
            storage_log.append(f"CSV backup: data/raw/current/households.csv")
        except Exception as csv_err:
            storage_log.append(f"CSV backup failed: {str(csv_err)[:60]}")

        # ── 3. Build feedback summary ─────────────────────────────────────
        # Count total submissions
        total_submissions = 1
        try:
            if csv_path.exists():
                total_submissions = len(pd.read_csv(str(csv_path), low_memory=False))
        except Exception:
            pass

        return jsonify({
            "status":       "ok",
            "household_id": hh_id,
            "stored_in":    storage_log,
            "db_saved":     db_saved,
            "summary": {
                "household_id":    hh_id,
                "district":        row["district"],
                "union_council":   row["union_council"],
                "household_size":  row["household_size"],
                "children_under_5": row["children_under_5"],
                "water_source":    row["water_source"],
                "ses_tier":        row["ses_tier"],
                "submitted_at":    now,
                "total_submissions_today": total_submissions,
                "next_step": "Run ETL pipeline to process this record into Silver/Gold layers",
            },
        })

    except Exception:
        import traceback
        return jsonify({"status": "error",
                        "message": traceback.format_exc()[-600:]}), 500


@app.route("/publichealth/data-pipeline")
@app.route("/data-pipeline")
def data_pipeline():
    """Pipeline status page -- Medallion layer stats + run history from delta log."""
    import json as _json
    layers_info = {}
    data_base = PKG_DIR / "data"

    # ── Scan each layer for files + row counts ────────────────────────────────
    for layer in ["raw", "bronze", "silver", "gold"]:
        layer_dir = data_base / layer
        if layer_dir.exists():
            files = [f for f in layer_dir.rglob("*")
                     if f.suffix in (".csv", ".parquet", ".json", ".avro") and f.is_file()]
            # Per-dataset row counts (Bronze and Silver only — Gold uses rpt table)
            dataset_stats = []
            if layer in ("bronze", "silver", "raw"):
                for f in sorted(files):
                    try:
                        pd = _pd()
                        if f.suffix == ".parquet":
                            df_tmp = pd.read_parquet(str(f))
                        elif f.suffix == ".csv":
                            df_tmp = pd.read_csv(str(f), low_memory=False)
                        elif f.suffix == ".json":
                            df_tmp = pd.read_json(str(f), lines=True)
                        else:
                            df_tmp = pd.DataFrame()
                        dataset_stats.append({
                            "name":    f.stem,
                            "file":    f.name,
                            "rows":    len(df_tmp),
                            "cols":    len(df_tmp.columns),
                            "size_kb": f.stat().st_size // 1024,
                            "era":     "current" if "current" in str(f) else
                                       "historical" if "historical" in str(f) else "bronze",
                        })
                    except Exception:
                        dataset_stats.append({
                            "name": f.stem, "file": f.name,
                            "rows": "?", "cols": "?",
                            "size_kb": f.stat().st_size // 1024,
                            "era": "unknown",
                        })
            layers_info[layer] = {
                "files":         len(files),
                "names":         [f.name for f in sorted(files)[:20]],
                "size_kb":       sum(f.stat().st_size for f in files) // 1024,
                "status":        "ok" if files else "empty",
                "dataset_stats": dataset_stats,
                "path":          str(layer_dir),   # show actual path for debugging
            }
        else:
            layers_info[layer] = {
                "files": 0, "names": [], "size_kb": 0,
                "status": "empty", "dataset_stats": [],
                "path": str(data_base / layer),
            }

    # ── Load delta log ────────────────────────────────────────────────────────
    run_history = []
    dq_journey  = {"raw": 0, "bronze": 0, "silver": 0, "gold": 0}
    try:
        delta_log = data_base / "delta_log" / "pipeline_state.json"
        if delta_log.exists():
            state = _json.loads(delta_log.read_text(encoding="utf-8"))
            for run in reversed(state.get("run_history", [])[-20:]):
                run_history.append({
                    "run_id":      run.get("run_id", "--"),
                    "timestamp":   run.get("timestamp", "--")[:19].replace("T", " "),
                    "stage":       run.get("load_mode", "--"),
                    "records_in":  run.get("bronze_datasets", "--"),
                    "records_out": run.get("gold_datasets", "--"),
                    "duration":    f"{run.get('elapsed_s', 0):.1f}s",
                    "status":      run.get("status", "--"),
                })
            last = state.get("run_history", [{}])[-1]
            gold_rows = last.get("gold_rows", {})
            dq_journey = {
                "raw":          layers_info["raw"]["files"],
                "bronze":       last.get("bronze_datasets", 0),
                "silver":       last.get("silver_datasets", 0),
                "gold":         last.get("gold_datasets", 0),
                "gold_rows":    gold_rows,
                "last_run_id":  last.get("run_id", "--"),
                "last_run_ts":  last.get("timestamp", "--")[:19].replace("T", " "),
                "last_elapsed": f"{last.get('elapsed_s', 0):.1f}s",
            }
    except Exception:
        pass

    # ── Gold status table ─────────────────────────────────────────────────────
    status_table = None
    try:
        for path in [data_base / "gold" / "rpt_pipeline_status.parquet",
                     data_base / "gold" / "rpt_pipeline_status.csv"]:
            if path.exists():
                df = _pd().read_parquet(str(path)) if path.suffix == ".parquet" \
                     else _pd().read_csv(str(path))
                df = df.drop(columns=[c for c in ["_layer"] if c in df.columns], errors="ignore")
                status_table = df.to_html(classes="table", index=False, border=0)
                break
    except Exception:
        pass

    # ── Path info for debugging ───────────────────────────────────────────────
    path_info = {
        "app_root":  str(ROOT_DIR),
        "pkg_dir":   str(PKG_DIR),
        "data_base": str(data_base),
    }

    return render_template("pipeline.html",
                           layers=layers_info,
                           status_table=status_table,
                           dq_journey=dq_journey,
                           run_history=run_history,
                           path_info=path_info)


@app.route("/publichealth/survey")
@app.route("/survey")
def survey():
    """Survey collection page -- reads recent submissions from DB first, CSV fallback."""
    recent_submissions = []
    db_stats = {}
    try:
        pd = _pd()
        # Try DB first
        try:
            for mod_path in ["psaksh_data_platform.etl.load", "etl.load"]:
                try:
                    import importlib
                    load_mod = importlib.import_module(mod_path)
                    engine = load_mod.get_engine(use_sqlite=(os.environ.get("ENV","production") == "local"))
                    from sqlalchemy import text as _text
                    with engine.connect() as conn:
                        result = conn.execute(_text(
                            "SELECT household_id, district, union_council, "
                            "respondent_name, submission_time "
                            "FROM raw_household_submissions "
                            "ORDER BY submission_time DESC LIMIT 10"
                        ))
                        rows = result.fetchall()
                        if rows:
                            recent_submissions = [dict(r._mapping) for r in rows]
                            total = conn.execute(_text(
                                "SELECT COUNT(*) FROM raw_household_submissions"
                            )).scalar()
                            db_stats = {"source": "MySQL/SQLite DB", "total_records": total}
                    break
                except ImportError:
                    continue
        except Exception:
            pass
        # Parquet + CSV fallback
        if not recent_submissions:
            # Search order: parquet first (more complete), then CSV
            fallback_paths = [
                PKG_DIR / "data" / "raw" / "current" / "households.parquet",
                PKG_DIR / "data" / "raw" / "current" / "households.csv",
                PKG_DIR / "data" / "raw" / "households.parquet",
                PKG_DIR / "data" / "raw" / "households.csv",
                PKG_DIR / "data" / "silver" / "households.parquet",
                PKG_DIR / "data" / "gold"   / "dim_district.parquet",  # fallback for districts
            ]
            for fpath in fallback_paths:
                if not fpath.exists():
                    continue
                try:
                    if fpath.suffix == ".parquet":
                        df = pd.read_parquet(str(fpath))
                    else:
                        df = pd.read_csv(str(fpath), low_memory=False)

                    keep = [c for c in [
                        "household_id", "district", "union_council",
                        "respondent_name", "submission_time", "enrollment_date",
                    ] if c in df.columns]
                    if not keep or "district" not in df.columns:
                        continue

                    df_sub = df[keep].copy()
                    # Normalise time column
                    time_col = "submission_time" if "submission_time" in df_sub.columns else \
                               "enrollment_date"  if "enrollment_date"  in df_sub.columns else None
                    if time_col:
                        df_sub[time_col] = pd.to_datetime(df_sub[time_col], errors="coerce")
                        df_sub = df_sub.sort_values(time_col, ascending=False)
                        df_sub["submission_time"] = df_sub[time_col].dt.strftime(
                            "%Y-%m-%d %H:%M"
                        ).fillna("--")
                    else:
                        df_sub["submission_time"] = "--"

                    recent_submissions = df_sub.head(10).fillna("--").to_dict("records")
                    db_stats = {"source": fpath.name, "total_records": len(df)}
                    break
                except Exception:
                    continue
    except Exception:
        pass
    return render_template("survey.html", recent_submissions=recent_submissions, db_stats=db_stats)


def _run_cmd(cmd: list) -> tuple[bool, str]:
    """
    Run a Python module command in a subprocess.
    Works on both Linux (production) and Windows (local dev / WAMP).
    """
    # Linux production venv
    LINUX_VENV_PY = Path("/home/sattioe1/virtualenv/softcomputech.com/publichealth/3.11/bin/python")

    if LINUX_VENV_PY.exists():
        python = str(LINUX_VENV_PY)
        env = os.environ.copy()
        venv_root = str(LINUX_VENV_PY.parent.parent)
        env["PYTHONHOME"]  = venv_root
        env["VIRTUAL_ENV"] = venv_root
        env["PATH"]        = str(LINUX_VENV_PY.parent) + ":" + env.get("PATH", "")
    else:
        # Windows / local â€” use the same Python that's running Flask
        python = sys.executable
        env = os.environ.copy()

    try:
        r = subprocess.run(
            [python] + cmd,
            capture_output=True, text=True,
            timeout=300, cwd=str(ROOT_DIR),
            env=env,
        )
        output = (r.stdout + r.stderr)[-3000:]
        return r.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "Timed out after 300s"
    except Exception as e:
        return False, str(e)


# ── Pipeline job log — FILE-BASED so SSE works across Passenger workers ─────
import collections as _collections
import tempfile as _tempfile

_JOB_LOG_DIR = Path("/tmp/psaksh_job_logs")
try:
    _JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    _JOB_LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "job_logs"
    _JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)

def _job_log_path(job_id: str) -> Path:
    return _JOB_LOG_DIR / f"{job_id}.log"

def _job_log(job_id: str, msg: str) -> None:
    """Append a log line to the job's log file (works across processes)."""
    try:
        with open(_job_log_path(job_id), "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

def _job_log_read(job_id: str) -> list:
    """Read all log lines for a job."""
    p = _job_log_path(job_id)
    if not p.exists():
        return []
    try:
        return p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []

def _job_log_done(job_id: str) -> bool:
    lines = _job_log_read(job_id)
    return bool(lines and any(
        l.startswith("DONE") or "Pipeline complete" in l or "complete" in l.lower()
        for l in lines[-3:]
    ))


# ── SSE: stream job log to browser ───────────────────────────────────────────
@app.route("/publichealth/pipeline-stream/<job_id>")
@app.route("/pipeline-stream/<job_id>")
def pipeline_stream(job_id: str):
    """
    Server-Sent Events — streams live log lines from the job log file.
    Works across Passenger worker processes (file-based, not in-memory).
    """
    import time as _time

    def _generate():
        sent = 0
        for _ in range(600):   # max 5 minutes
            logs = _job_log_read(job_id)
            while sent < len(logs):
                line = logs[sent].replace("\n", " ").replace("\r", "")
                yield f"data: {line}\n\n"
                sent += 1
            if _job_log_done(job_id) and sent > 0:
                yield "data: __DONE__\n\n"
                return
            _time.sleep(0.5)
        yield "data: __TIMEOUT__\n\n"

    from flask import Response
    return Response(
        _generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache, no-store",
            "X-Accel-Buffering":"no",
            "Connection":       "keep-alive",
        },
    )

@app.route("/publichealth/api/job-log/<job_id>")
@app.route("/api/job-log/<job_id>")
def api_job_log(job_id: str):
    logs = _job_log_read(job_id)
    done = _job_log_done(job_id)
    return jsonify({"job_id": job_id, "lines": logs, "done": done})

@app.route("/publichealth/run-generator", methods=["POST"])
@app.route("/run-generator", methods=["POST"])
def run_generator():
    """
    Generate synthetic data in a background thread.
    Accepts JSON: {count, min_records, max_records, start_date, end_date,
                   rounds, seed, inject_dq}
    Returns immediately with job_id for SSE streaming.
    """
    import threading, uuid as _uuid
    body = request.get_json(silent=True) or {}

    # Resolve count
    try:
        count = int(body.get("count") or 0)
    except Exception:
        count = 0
    try:
        min_r = int(body.get("min_records") or 0) or None
        max_r = int(body.get("max_records") or 0) or None
    except Exception:
        min_r = max_r = None

    if not count and not min_r and not max_r:
        count = 500

    start_date = body.get("start_date") or None
    end_date   = body.get("end_date")   or None
    rounds     = max(1, min(int(body.get("rounds", 4)), 12))
    seed       = int(body.get("seed")) if body.get("seed") else None
    inject_dq  = bool(body.get("inject_dq_issues") or body.get("inject_dq", True))

    job_id = _uuid.uuid4().hex[:8].upper()
    _JOB_LOGS[job_id] = []

    def _log(msg):
        _job_log(job_id, msg)

    def _do_gen():
        import importlib, pandas as pd, time as _t
        t0 = _t.time()
        try:
            for _p in [str(ROOT_DIR), str(PKG_DIR)]:
                if _p not in sys.path:
                    sys.path.insert(0, _p)

            gen_mod = None
            for mod_path in ["psaksh_data_platform.data_generator.generators",
                             "data_generator.generators"]:
                try:
                    gen_mod = importlib.import_module(mod_path)
                    break
                except ImportError:
                    continue
            if gen_mod is None:
                raise ImportError("Cannot import data_generator.generators")

            import numpy as np
            rng = np.random.default_rng(seed)
            if count:
                n = max(10, min(count, 50000))
            elif min_r and max_r:
                n = int(rng.integers(min_r, max_r + 1))
            elif min_r:
                n = min_r
            elif max_r:
                n = max_r
            else:
                n = 500

            _log(f"[GEN] Starting data generation  job={job_id}")
            _log(f"[GEN] Households    : {n:,}")
            _log(f"[GEN] Date range    : {start_date or 'default'}  to  {end_date or 'default'}")
            _log(f"[GEN] Rounds        : {rounds}")
            _log(f"[GEN] Seed          : {seed or 'random'}")
            _log(f"[GEN] DQ injection  : {'ON' if inject_dq else 'OFF'}")

            raw_dir = PKG_DIR / "data" / "raw" / "current"
            raw_dir.mkdir(parents=True, exist_ok=True)

            _log("[1/5] Generating households...")
            hh = gen_mod.generate_households(
                n, start_date=start_date, end_date=end_date, seed=seed)
            _log(f"      {len(hh):,} households generated")

            _log("[2/5] Generating follow-up visits...")
            visits = gen_mod.generate_followup_visits(
                hh, rounds=rounds, start_date=start_date, end_date=end_date, seed=seed)
            child_n    = int((visits["record_type"] == "child").sum())
            maternal_n = int((visits["record_type"] == "maternal").sum())
            _log(f"      {len(visits):,} visits  ({child_n:,} child, {maternal_n:,} maternal)")

            _log("[3/5] Generating facility assessments...")
            fac = gen_mod.generate_facility_assessments(
                rounds=rounds, start_date=start_date, end_date=end_date, seed=seed)
            _log(f"      {len(fac):,} facility records")

            _log("[4/5] Generating enumerator performance logs...")
            perf = gen_mod.generate_enumerator_performance(
                visits, start_date=start_date, end_date=end_date, seed=seed)
            _log(f"      {len(perf):,} performance records")

            _log("[5/5] Generating back-check records...")
            backcheck = gen_mod.generate_backcheck_records(visits, seed=seed)
            _log(f"      {len(backcheck):,} back-check records")

            _log("[SAVE] Writing Parquet files to raw/current/...")

            def _append(df, name):
                path = raw_dir / f"{name}.parquet"
                try:
                    df_c = df.copy()
                    for col in df_c.select_dtypes(include="object").columns:
                        df_c[col] = df_c[col].astype(str).replace("None", pd.NA).replace("nan", pd.NA)
                    if path.exists():
                        existing = pd.read_parquet(path)
                        combined = pd.concat([existing, df_c], ignore_index=True)
                        combined.to_parquet(path, index=False)
                        _log(f"      {name}.parquet: appended {len(df):,} rows (total {len(combined):,})")
                    else:
                        df_c.to_parquet(path, index=False)
                        _log(f"      {name}.parquet: created {len(df):,} rows")
                except Exception as e:
                    _log(f"      {name}: parquet failed ({e}), using CSV")
                    df.to_csv(raw_dir / f"{name}.csv", index=False)

            _append(hh,        "households")
            _append(visits,    "followup_visits")
            _append(fac,       "facility_assessments")
            _append(perf,      "enumerator_performance")
            _append(backcheck, "backcheck_records")

            elapsed = _t.time() - t0
            _log(f"DONE Generation complete in {elapsed:.1f}s")
            _log(f"     {n:,} households | {len(visits):,} visits | {len(fac):,} facilities")
            _log(f"     Files saved to: {raw_dir}")
            _log("     Next: click Run ETL Pipeline to process into Bronze/Silver/Gold")

        except Exception:
            import traceback
            _log(f"ERROR {traceback.format_exc()[-500:]}")

    threading.Thread(target=_do_gen, daemon=True).start()
    return jsonify({
        "status":  "started",
        "job_id":  job_id,
        "message": f"Data generation started (job {job_id}). Stream progress at /pipeline-stream/{job_id}",
    }), 200


@app.route("/publichealth/api/generate", methods=["POST"])
@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Alias for run-generator."""
    return run_generator()


# ── ETL Pipeline — full or step-by-step ──────────────────────────────────────
@app.route("/publichealth/run-pipeline", methods=["POST"])
@app.route("/run-pipeline", methods=["POST"])
def run_pipeline():
    """
    Run full Bronze->Silver->Gold pipeline in background.
    Accepts JSON: {step: "all"|"bronze"|"silver"|"gold", force_full: bool}
    Returns job_id for SSE streaming.
    """
    import threading, uuid as _uuid
    body      = request.get_json(silent=True) or {}
    step      = body.get("step", "all")          # "all", "bronze", "silver", "gold"
    force     = bool(body.get("force_full", False))
    job_id    = _uuid.uuid4().hex[:8].upper()
    _JOB_LOGS[job_id] = []

    def _log(msg):
        _job_log(job_id, msg)

    def _import_medallion():
        import importlib
        for mod_path in ["psaksh_data_platform.etl.medallion", "etl.medallion"]:
            try:
                return importlib.import_module(mod_path)
            except ImportError:
                continue
        import importlib.util
        spec = importlib.util.spec_from_file_location("medallion", PKG_DIR / "etl" / "medallion.py")
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _do_etl():
        import time as _t, json as _json
        t0 = _t.time()
        try:
            for _p in [str(ROOT_DIR), str(PKG_DIR)]:
                if _p not in sys.path:
                    sys.path.insert(0, _p)

            med   = _import_medallion()
            data_base = PKG_DIR / "data"
            layers    = med.layer_dirs(data_base)
            state     = med._load_delta_log(layers["delta_log"])

            _log(f"[ETL] Pipeline started  job={job_id}  step={step}  force={force}")
            _log(f"[ETL] Data base: {data_base}")

            bronze = silver = gold = {}

            if step in ("all", "bronze"):
                _log("")
                _log("[BRONZE] Ingesting raw sources...")
                _log("         Scanning: raw/historical/ + raw/current/ + raw/")
                bronze = med.ingest_bronze(layers["raw"], layers["bronze"], state, force)
                for name, df in bronze.items():
                    era = df["_source_era"].iloc[0] if "_source_era" in df.columns else "?"
                    _log(f"         {name:35s}: {len(df):>7,} rows  [{era}]")
                _log(f"[BRONZE] Complete — {len(bronze)} datasets ingested")

            if step in ("all", "silver"):
                if not bronze:
                    _log("[SILVER] Loading bronze from disk...")
                    import pandas as pd
                    for f in sorted(layers["bronze"].glob("*.parquet")):
                        try:
                            bronze[f.stem] = pd.read_parquet(f)
                        except Exception:
                            pass
                _log("")
                _log("[SILVER] Applying schema evolution + DQ cleaning + CDC tagging...")
                silver = med.transform_silver(bronze, layers["silver"], state)
                for name, df in silver.items():
                    cdc = df["_cdc_op"].value_counts().to_dict() if "_cdc_op" in df.columns else {}
                    _log(f"         {name:35s}: {len(df):>7,} rows  CDC={cdc}")
                _log(f"[SILVER] Complete — {len(silver)} datasets cleaned")

            if step in ("all", "gold"):
                if not silver:
                    _log("[GOLD] Loading silver from disk...")
                    import pandas as pd
                    for f in sorted(layers["silver"].glob("*.parquet")):
                        try:
                            silver[f.stem] = pd.read_parquet(f)
                        except Exception:
                            pass
                if not bronze:
                    import pandas as pd
                    for f in sorted(layers["bronze"].glob("*.parquet")):
                        try:
                            bronze[f.stem] = pd.read_parquet(f)
                        except Exception:
                            pass
                _log("")
                _log("[GOLD] Building SCD2 dims + fact tables + windowed KPIs...")
                gold = med.build_gold(silver, bronze, layers["gold"])
                for name, df in gold.items():
                    _log(f"         {name:35s}: {len(df):>7,} rows")
                _log(f"[GOLD] Complete — {len(gold)} datasets built")

            # Update delta log
            elapsed = _t.time() - t0
            import uuid as _uuid2
            run_id = _uuid2.uuid4().hex[:8].upper()
            state.setdefault("run_history", []).append({
                "run_id":          run_id,
                "timestamp":       __import__("datetime").datetime.utcnow().isoformat(),
                "load_mode":       "full_load" if force else "incremental",
                "status":          "success",
                "elapsed_s":       round(elapsed, 2),
                "bronze_datasets": len(bronze),
                "silver_datasets": len(silver),
                "gold_datasets":   len(gold),
                "gold_rows":       {n: len(d) for n, d in gold.items()},
                "step":            step,
            })
            state["run_history"] = state["run_history"][-100:]
            med._save_delta_log(state, layers["delta_log"])

            _log("")
            _log(f"Pipeline complete in {elapsed:.1f}s  [run_id={run_id}]")
            _log(f"Bronze: {len(bronze)}  Silver: {len(silver)}  Gold: {len(gold)}")
            _log("DONE Refresh the page to see updated data.")

        except Exception:
            import traceback
            _log(f"ERROR {traceback.format_exc()[-800:]}")

    threading.Thread(target=_do_etl, daemon=True).start()
    return jsonify({
        "status":  "started",
        "job_id":  job_id,
        "step":    step,
        "message": f"ETL pipeline started (job {job_id}, step={step}). Stream at /pipeline-stream/{job_id}",
    }), 200

@app.route("/publichealth/api/kpis")
@app.route("/api/kpis")
def api_kpis():
    """Single-row national KPI summary â€” Power BI / Tableau compatible."""
    try:
        data = load_all()
        fct  = data["fct_child"]
        mat  = data["fct_maternal"]
        hh   = data["households"]

        an   = _analytics()
        prev = an["national_prevalence"](fct) if not fct.empty else {}

        kpis = {
            "households_enrolled":  len(hh),
            "children_measured":    prev.get("n", 0),
            "stunting_rate":        round(prev.get("stunting_rate", 0), 4),
            "wasting_rate":         round(prev.get("wasting_rate", 0), 4),
            "underweight_rate":     round(prev.get("underweight_rate", 0), 4),
            "anemia_children_rate": round(prev.get("anemia_rate", 0), 4),
            "anc_4plus_rate":       round(float(mat["anc_4plus"].mean()), 4)
                                    if not mat.empty and "anc_4plus" in mat else None,
            "skilled_delivery_rate": round(float(mat["last_delivery_skilled"].mean()), 4)
                                     if not mat.empty and "last_delivery_skilled" in mat else None,
            "generated_at":         __import__("datetime").datetime.utcnow().isoformat(),
        }
        return jsonify(kpis)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/publichealth/api/charts/<chart_name>")
@app.route("/api/charts/<chart_name>")
def api_chart(chart_name: str):
    """
    Return a Plotly chart as JSON for embedding in external tools.
    Supported: stunting, wasting, anc, facilities, timeline
    """
    try:
        px  = _px()
        fct = load_all()["fct_child"]
        mat = load_all()["fct_maternal"]
        fac = load_all()["facilities"]
        an  = _analytics()

        fig = None

        if chart_name == "stunting" and not fct.empty:
            dist = an["prevalence_by_group"](fct, ["district"])
            if "stunting_rate" in dist.columns:
                fig = px.bar(dist, x="district", y="stunting_rate", color="district",
                             title="Stunting Rate by District",
                             labels={"stunting_rate": "Stunting Rate"})
                fig.update_yaxes(tickformat=".0%")

        elif chart_name == "wasting" and not fct.empty:
            dist = an["prevalence_by_group"](fct, ["district"])
            if "wasting_rate" in dist.columns:
                fig = px.bar(dist, x="district", y="wasting_rate", color="district",
                             title="Wasting Rate by District",
                             labels={"wasting_rate": "Wasting Rate"})
                fig.update_yaxes(tickformat=".0%")

        elif chart_name == "anc" and not mat.empty and "anc_4plus" in mat.columns:
            anc = mat.groupby("district")["anc_4plus"].mean().reset_index()
            fig = px.bar(anc, x="district", y="anc_4plus", color="district",
                         title="ANC 4+ Coverage by District",
                         labels={"anc_4plus": "ANC 4+ Rate"})
            fig.update_yaxes(tickformat=".0%")

        elif chart_name == "facilities" and not fac.empty:
            score_col = "readiness_score" if "readiness_score" in fac.columns else "overall_score"
            if score_col in fac.columns:
                avg = fac.groupby("district")[score_col].mean().reset_index()
                fig = px.bar(avg, x="district", y=score_col, color="district",
                             title="Facility Readiness by District",
                             labels={score_col: "Readiness Score (%)"})

        if fig is None:
            return jsonify({"error": f"Chart '{chart_name}' not available or no data"}), 404

        import plotly.io as pio
        return jsonify(pio.to_json(fig))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/publichealth/glossary")
@app.route("/glossary")
def glossary():
    """Data dictionary and glossary page."""
    return render_template("glossary.html")


@app.route("/publichealth/debug/double-burden")
@app.route("/debug/double-burden")
def debug_double_burden():
    """Temporary debug endpoint — exposes double burden chart generation errors."""
    import traceback
    result = {"status": "unknown", "error": None, "data_shape": None, "chart_len": None}
    try:
        an  = _analytics()
        fct = load_all()["fct_child"]
        result["fct_rows"] = len(fct)
        result["fct_cols"] = list(fct.columns)[:15]
        db = an["double_burden_analysis"](fct)
        result["db_shape"] = list(db.shape)
        result["db_cols"]  = list(db.columns)
        result["db_sample"] = db.head(3).to_dict(orient="records")
        # Try building the chart
        px = _px()
        db["visit_round"] = db["visit_round"].astype(str)
        db["double_burden_pct"] = (db["double_burden_rate"] * 100).round(1)
        db["stunting_pct"]      = (db["stunting_rate"]      * 100).round(1)
        db["wasting_pct"]       = (db["wasting_rate"]       * 100).round(1)
        db_agg = db.groupby("district").agg(
            double_burden_pct=("double_burden_pct", "mean"),
            stunting_pct=("stunting_pct", "mean"),
            wasting_pct=("wasting_pct", "mean"),
            n=("n", "sum"),
        ).reset_index()
        db_agg["bubble_size"] = db_agg["double_burden_pct"].clip(lower=0.5)
        result["agg_shape"] = list(db_agg.shape)
        result["bubble_min"] = float(db_agg["bubble_size"].min())
        result["bubble_max"] = float(db_agg["bubble_size"].max())
        fig = px.scatter(
            db_agg, x="stunting_pct", y="wasting_pct",
            size="bubble_size", color="double_burden_pct",
            hover_name="district", size_max=40,
            color_continuous_scale=[[0, "#276749"], [0.5, "#d69e2e"], [1, "#c53030"]],
            title="Double Burden of Malnutrition by District",
        )
        j = fig_json(fig)
        result["chart_len"] = len(j) if j else 0
        result["status"] = "ok"
    except Exception:
        result["status"] = "error"
        result["error"]  = traceback.format_exc()
    from flask import jsonify
    return jsonify(result)


if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")








