"""
PSAKSH Streamlit Dashboard
Advanced analytics with data lineage, ETL history, DAG visualization,
storytelling, and full data engineering education.

Run: streamlit run dashboards/app.py
Or:  run_streamlit.bat
"""

from __future__ import annotations
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Path bootstrap ────────────────────────────────────────────────────────────
_DASH_DIR = Path(__file__).resolve().parent
_PKG_DIR  = _DASH_DIR.parent
_DATA_DIR = _PKG_DIR / "data"

for _p in [str(_PKG_DIR.parent), str(_PKG_DIR)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="PSAKSH Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Colour palette ────────────────────────────────────────────────────────────
PSAKSH_BLUE  = "#1a365d"
PSAKSH_TEAL  = "#2c7a7b"
PSAKSH_RED   = "#c53030"
PSAKSH_GREEN = "#276749"
PSAKSH_AMBER = "#d69e2e"
PSAKSH_LIGHT = "#f0f4f8"

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .main { background: #f0f4f8; }
  .stMetric { background: white; border-radius: 8px; padding: 12px; border-left: 4px solid #2b6cb0; }
  .story-box { background: linear-gradient(135deg,#ebf8ff,#f0fff4); border-radius:10px;
               padding:16px 20px; border-left:5px solid #2b6cb0; margin-bottom:16px; }
  .lineage-node { background:white; border-radius:8px; padding:10px 14px;
                  border:2px solid #e2e8f0; text-align:center; }
  .dag-stage { background:white; border-radius:8px; padding:14px; border-top:4px solid #2b6cb0; }
  h1 { color: #1a365d !important; }
  h2 { color: #2d3748 !important; }
  h3 { color: #4a5568 !important; }
</style>
""", unsafe_allow_html=True)

# ── Data loading ──────────────────────────────────────────────────────────────
NUMERIC_COLS = [
    "stunted","wasted","underweight","severe_stunted","severe_wasted",
    "anemia","diarrhea_2w","ari_2w","fever_2w","vaccination_full",
    "exclusive_bf","anc_4plus","last_delivery_skilled",
    "haz_score","waz_score","whz_score","hemoglobin_gdl",
    "child_age_months","maternal_age","readiness_score","overall_score",
    "stunting_rate","wasting_rate","underweight_rate","anemia_rate",
    "diarrhea_rate","vaccination_rate","anc_4plus_rate",
    "skilled_delivery_rate","anemia_maternal_rate","visit_round","survey_year",
]

@st.cache_data(show_spinner=False)
def load_dataset(name: str) -> pd.DataFrame:
    search = [
        _DATA_DIR / "gold"           / f"{name}.parquet",
        _DATA_DIR / "silver"         / f"{name}.parquet",
        _DATA_DIR / "raw" / "current" / f"{name}.parquet",
        _DATA_DIR / "raw"            / f"{name}.csv",
    ]
    for p in search:
        if p.exists():
            try:
                df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p, low_memory=False)
                for col in NUMERIC_COLS:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                # Defensive: normalise binary columns from 0-100 to 0-1
                BINARY = ["stunted","wasted","underweight","anemia","diarrhea_2w",
                          "ari_2w","fever_2w","vaccination_full","anc_4plus","last_delivery_skilled"]
                for col in BINARY:
                    if col in df.columns and df[col].max() > 1.5:
                        df[col] = df[col] / 100.0
                return df
            except Exception:
                continue
    return pd.DataFrame()

@st.cache_data(show_spinner=False)
def load_delta_log() -> dict:
    path = _DATA_DIR / "delta_log" / "pipeline_state.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"watermarks": {}, "run_history": [], "checksums": {}}

@st.cache_data(show_spinner=False)
def load_all() -> dict:
    return {
        "fct_child":    load_dataset("fct_child_nutrition"),
        "fct_maternal": load_dataset("fct_maternal_health"),
        "households":   load_dataset("households"),
        "facilities":   load_dataset("facility_assessments"),
        "backcheck":    load_dataset("backcheck_records"),
        "dist_summary": load_dataset("rpt_district_summary"),
        "prov_summary": load_dataset("rpt_province_summary"),
        "dq_report":    load_dataset("rpt_data_quality"),
    }


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://via.placeholder.com/200x60/1a365d/ffffff?text=PSAKSH", use_column_width=True)
    st.markdown("### 📊 PSAKSH Analytics")
    st.markdown("*Public Sector Analytics & Knowledge Systems Hub*")
    st.divider()

    page = st.radio(
        "Navigate",
        options=[
            "🏠 Overview",
            "🥗 Nutrition",
            "🤱 Maternal Health",
            "🏥 Facilities",
            "📍 Field Operations",
            "⚙ ETL Pipeline & Lineage",
            "🗺 Data Journey (DAG)",
            "📖 Data Dictionary",
            "📡 API Access",
        ],
        label_visibility="collapsed",
    )
    st.divider()

    # Filters
    st.markdown("### 🔽 Filters")
    data = load_all()
    fct  = data["fct_child"]

    provinces = ["All"] + sorted(fct["province"].dropna().unique().tolist()) if not fct.empty and "province" in fct.columns else ["All"]
    sel_province = st.selectbox("Province", provinces)

    districts = ["All"]
    if not fct.empty and "district" in fct.columns:
        if sel_province != "All":
            districts += sorted(fct[fct["province"] == sel_province]["district"].dropna().unique().tolist())
        else:
            districts += sorted(fct["district"].dropna().unique().tolist())
    sel_district = st.selectbox("District", districts)

    rounds = ["All"]
    if not fct.empty and "visit_round" in fct.columns:
        rounds += [str(int(r)) for r in sorted(fct["visit_round"].dropna().unique())]
    sel_round = st.selectbox("Survey Round", rounds)

    st.divider()
    if st.button("🔄 Refresh Data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown(f"<small style='color:#718096'>Data: {_DATA_DIR}</small>", unsafe_allow_html=True)


# ── Apply filters ─────────────────────────────────────────────────────────────
def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if sel_province != "All" and "province" in df.columns:
        df = df[df["province"] == sel_province]
    if sel_district != "All" and "district" in df.columns:
        df = df[df["district"] == sel_district]
    if sel_round != "All" and "visit_round" in df.columns:
        df = df[df["visit_round"].astype(str) == sel_round]
    return df

fct_f  = apply_filters(data["fct_child"])
mat_f  = apply_filters(data["fct_maternal"])
fac_f  = apply_filters(data["facilities"])


# ── Helper: KPI metric ────────────────────────────────────────────────────────
def kpi_metric(label: str, value, delta=None, help_text: str = ""):
    if isinstance(value, float) and not np.isnan(value):
        display = f"{value:.1%}" if value <= 1.0 else f"{value:,.0f}"
    else:
        display = str(value) if value is not None else "--"
    st.metric(label=label, value=display, delta=delta, help=help_text)


# ── Helper: safe mean ─────────────────────────────────────────────────────────
def safe_mean(df: pd.DataFrame, col: str) -> float:
    if df.empty or col not in df.columns:
        return float("nan")
    return float(pd.to_numeric(df[col], errors="coerce").mean())


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════
if page == "🏠 Overview":
    st.title("🏠 PSAKSH Analytics Dashboard")
    st.markdown("*Pakistan Public Health Surveillance — 4 Provinces, 36 Districts, 180 Union Councils*")

    # Story headline
    if not fct_f.empty and "stunted" in fct_f.columns:
        stunt_rate = safe_mean(fct_f, "stunted")
        if not np.isnan(stunt_rate):
            if "district" in fct_f.columns:
                dist_rates = fct_f.groupby("district")["stunted"].mean()
                worst_d = dist_rates.idxmax()
                worst_r = dist_rates.max()
                gap = (worst_r - stunt_rate) * 100
                st.markdown(f"""
                <div class="story-box">
                <h3 style="margin:0 0 6px 0;color:#1a365d">⚠️ Key Finding</h3>
                <p style="margin:0;font-size:0.95rem;color:#2d3748">
                <strong>{worst_d}</strong> carries the highest stunting burden at
                <strong style="color:#c53030">{worst_r:.1%}</strong> —
                {gap:.1f}pp above the programme average of {stunt_rate:.1%}.
                Balochistan consistently shows the worst outcomes across all indicators.
                </p>
                </div>
                """, unsafe_allow_html=True)

    # KPI row
    c1,c2,c3,c4,c5,c6,c7,c8 = st.columns(8)
    with c1: kpi_metric("Households", len(data["households"]), help_text="Total enrolled households")
    with c2: kpi_metric("Children", len(fct_f), help_text="Children measured")
    with c3: kpi_metric("Stunting", safe_mean(fct_f,"stunted"), help_text="HAZ < -2 SD")
    with c4: kpi_metric("Wasting",  safe_mean(fct_f,"wasted"),  help_text="WHZ < -2 SD")
    with c5: kpi_metric("Underweight", safe_mean(fct_f,"underweight"), help_text="WAZ < -2 SD")
    with c6: kpi_metric("Child Anemia", safe_mean(fct_f,"anemia"), help_text="Hb < 11 g/dL")
    with c7: kpi_metric("ANC 4+", safe_mean(mat_f,"anc_4plus"), help_text="4+ antenatal visits")
    with c8: kpi_metric("Skilled Delivery", safe_mean(mat_f,"last_delivery_skilled"), help_text="Skilled birth attendant")

    st.divider()

    # Charts row
    col1, col2 = st.columns(2)
    with col1:
        if not fct_f.empty and "district" in fct_f.columns and "stunted" in fct_f.columns:
            dist = fct_f.groupby("district")["stunted"].mean().reset_index()
            dist.columns = ["district","stunting_rate"]
            dist = dist.sort_values("stunting_rate", ascending=False).head(20)
            fig = px.bar(dist, x="stunting_rate", y="district", orientation="h",
                         color="stunting_rate",
                         color_continuous_scale=[[0,"#276749"],[0.5,"#d69e2e"],[1,"#c53030"]],
                         title="Stunting Rate by District (Top 20)",
                         labels={"stunting_rate":"Stunting Rate","district":"District"})
            fig.update_xaxes(tickformat=".0%")
            fig.update_layout(height=500, showlegend=False, margin=dict(t=40,b=10))
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        if not fct_f.empty and "province" in fct_f.columns:
            prov_data = []
            for prov in fct_f["province"].dropna().unique():
                sub = fct_f[fct_f["province"]==prov]
                prov_data.append({
                    "Province": prov,
                    "Stunting": safe_mean(sub,"stunted"),
                    "Wasting":  safe_mean(sub,"wasted"),
                    "Anemia":   safe_mean(sub,"anemia"),
                })
            if prov_data:
                prov_df = pd.DataFrame(prov_data).melt("Province", var_name="Indicator", value_name="Rate")
                fig2 = px.bar(prov_df, x="Province", y="Rate", color="Indicator",
                              barmode="group",
                              color_discrete_map={"Stunting":"#c53030","Wasting":"#d69e2e","Anemia":"#553c9a"},
                              title="Key Indicators by Province",
                              labels={"Rate":"Rate","Province":"Province"})
                fig2.update_yaxes(tickformat=".0%")
                fig2.update_layout(height=500, margin=dict(t=40,b=10))
                st.plotly_chart(fig2, use_container_width=True)

    # Data story cards
    st.subheader("📖 Data Story")
    s1,s2,s3 = st.columns(3)
    with s1:
        st.markdown(f"""
        <div style="background:white;border-radius:8px;padding:16px;border-top:4px solid #c53030;height:160px">
        <h4 style="color:#c53030;margin:0 0 8px 0">🚨 Nutrition Crisis</h4>
        <p style="font-size:0.85rem;color:#4a5568;line-height:1.5">
        <strong>{safe_mean(fct_f,"stunted"):.1%}</strong> stunting,
        <strong>{safe_mean(fct_f,"wasted"):.1%}</strong> wasting.
        Balochistan: 52% stunting — highest in Pakistan.
        Chronic malnutrition irreversible after age 2.
        </p></div>""", unsafe_allow_html=True)
    with s2:
        st.markdown(f"""
        <div style="background:white;border-radius:8px;padding:16px;border-top:4px solid #553c9a;height:160px">
        <h4 style="color:#553c9a;margin:0 0 8px 0">🤱 Maternal Gap</h4>
        <p style="font-size:0.85rem;color:#4a5568;line-height:1.5">
        Only <strong>{safe_mean(mat_f,"anc_4plus"):.1%}</strong> received 4+ ANC visits.
        Skilled delivery at <strong>{safe_mean(mat_f,"last_delivery_skilled"):.1%}</strong>.
        WHO target: 80%. Balochistan: 45%.
        </p></div>""", unsafe_allow_html=True)
    with s3:
        st.markdown(f"""
        <div style="background:white;border-radius:8px;padding:16px;border-top:4px solid #276749;height:160px">
        <h4 style="color:#276749;margin:0 0 8px 0">📍 Field Operations</h4>
        <p style="font-size:0.85rem;color:#4a5568;line-height:1.5">
        <strong>{len(data["households"]):,}</strong> households enrolled.
        <strong>{len(fct_f):,}</strong> children measured.
        10% back-check protocol. 108 enumerators across 36 districts.
        </p></div>""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: NUTRITION
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🥗 Nutrition":
    st.title("🥗 Child Nutrition Indicators")
    st.markdown("*Stunting, wasting, underweight, anemia — WHO Child Growth Standards*")

    INDICATORS = {
        "stunted":       "Stunting Rate (HAZ < -2 SD)",
        "wasted":        "Wasting Rate (WHZ < -2 SD)",
        "underweight":   "Underweight Rate (WAZ < -2 SD)",
        "anemia":        "Child Anemia Rate (Hb < 11 g/dL)",
        "diarrhea_2w":   "Diarrhea (2-week recall)",
        "vaccination_full": "Full Vaccination Coverage",
    }
    ind_col = st.selectbox("Select Indicator", list(INDICATORS.keys()),
                           format_func=lambda x: INDICATORS[x])
    ind_label = INDICATORS[ind_col]

    if fct_f.empty or ind_col not in fct_f.columns:
        st.warning("No data available. Run the ETL pipeline first.")
    else:
        # KPIs
        c1,c2,c3,c4 = st.columns(4)
        with c1: kpi_metric(ind_label, safe_mean(fct_f, ind_col))
        with c2:
            if "district" in fct_f.columns:
                d = fct_f.groupby("district")[ind_col].mean()
                kpi_metric("Worst District", f"{d.idxmax()} ({d.max():.1%})")
        with c3:
            if "district" in fct_f.columns:
                d = fct_f.groupby("district")[ind_col].mean()
                kpi_metric("Best District", f"{d.idxmin()} ({d.min():.1%})")
        with c4:
            if "ses_tier" in fct_f.columns:
                ses = fct_f.groupby("ses_tier")[ind_col].mean()
                gap = (ses.get("low",0) - ses.get("high",0)) * 100
                kpi_metric("SES Gap (Low-High)", f"{gap:.1f}pp")

        tab1, tab2, tab3, tab4 = st.tabs(["By District", "Trend", "By SES", "By Province"])

        with tab1:
            if "district" in fct_f.columns and "visit_round" in fct_f.columns:
                dr = fct_f.groupby(["district","visit_round"])[ind_col].mean().reset_index()
                dr["visit_round"] = dr["visit_round"].astype(str)
                fig = px.bar(dr.sort_values("visit_round"), x="district", y=ind_col,
                             color="visit_round", barmode="group",
                             title=f"{ind_label} by District & Round",
                             labels={ind_col: ind_label, "visit_round": "Round"},
                             color_discrete_sequence=px.colors.qualitative.Set2)
                fig.update_yaxes(tickformat=".0%")
                fig.update_layout(height=450, xaxis_tickangle=-35)
                st.plotly_chart(fig, use_container_width=True)

        with tab2:
            if "visit_round" in fct_f.columns and "district" in fct_f.columns:
                trend = fct_f.groupby(["district","visit_round"])[ind_col].mean().reset_index()
                fig2 = px.line(trend.sort_values("visit_round"), x="visit_round", y=ind_col,
                               color="district", markers=True,
                               title=f"{ind_label} Trend by District",
                               labels={ind_col: ind_label, "visit_round": "Survey Round"})
                fig2.update_yaxes(tickformat=".0%")
                fig2.update_layout(height=420)
                st.plotly_chart(fig2, use_container_width=True)

        with tab3:
            if "ses_tier" in fct_f.columns and "visit_round" in fct_f.columns:
                ses = fct_f.groupby(["ses_tier","visit_round"])[ind_col].mean().reset_index()
                fig3 = px.line(ses.sort_values("visit_round"), x="visit_round", y=ind_col,
                               color="ses_tier", markers=True,
                               title=f"{ind_label} by SES Tier",
                               color_discrete_map={"low":"#c53030","middle":"#d69e2e","high":"#276749"},
                               labels={ind_col: ind_label, "ses_tier": "SES Tier"})
                fig3.update_yaxes(tickformat=".0%")
                fig3.update_layout(height=380)
                st.plotly_chart(fig3, use_container_width=True)

        with tab4:
            if "province" in fct_f.columns:
                prov = fct_f.groupby("province")[ind_col].mean().reset_index()
                prov = prov.sort_values(ind_col, ascending=False)
                fig4 = px.bar(prov, x="province", y=ind_col,
                              color=ind_col,
                              color_continuous_scale=[[0,"#276749"],[0.5,"#d69e2e"],[1,"#c53030"]],
                              title=f"{ind_label} by Province",
                              labels={ind_col: ind_label})
                fig4.update_yaxes(tickformat=".0%")
                fig4.update_layout(height=350, showlegend=False)
                st.plotly_chart(fig4, use_container_width=True)

        # Raw data
        with st.expander("📋 View Raw Data"):
            cols = ["province","district","union_council","visit_round",ind_col,"child_age_months","child_sex"]
            show_cols = [c for c in cols if c in fct_f.columns]
            st.dataframe(fct_f[show_cols].head(500), use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: ETL PIPELINE & LINEAGE
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "⚙ ETL Pipeline & Lineage":
    st.title("⚙ ETL Pipeline — Data Lineage & Run History")
    st.markdown("*Medallion Architecture: Bronze → Silver → Gold | Full data engineering audit trail*")

    state = load_delta_log()

    # ── Run History ───────────────────────────────────────────────────────────
    st.subheader("📋 Pipeline Run History (Delta Log)")
    runs = state.get("run_history", [])
    if runs:
        run_df = pd.DataFrame([{
            "Run ID":        r.get("run_id","--"),
            "Timestamp":     r.get("timestamp","--")[:19].replace("T"," "),
            "Load Mode":     r.get("load_mode","--"),
            "Bronze":        r.get("bronze_datasets",0),
            "Silver":        r.get("silver_datasets",0),
            "Gold":          r.get("gold_datasets",0),
            "Duration (s)":  r.get("elapsed_s",0),
            "Status":        r.get("status","--"),
        } for r in reversed(runs)])
        st.dataframe(run_df, use_container_width=True, hide_index=True)

        # Run timeline chart
        if len(runs) > 1:
            timeline_df = pd.DataFrame([{
                "run": r.get("run_id","")[:8],
                "elapsed": r.get("elapsed_s",0),
                "gold_datasets": r.get("gold_datasets",0),
                "ts": r.get("timestamp","")[:19],
            } for r in runs])
            fig = px.bar(timeline_df, x="ts", y="elapsed",
                         title="Pipeline Run Duration Over Time",
                         labels={"elapsed":"Duration (s)","ts":"Run Timestamp"},
                         color="elapsed", color_continuous_scale="Blues")
            fig.update_layout(height=280, margin=dict(t=40,b=10))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No pipeline runs recorded yet. Click 'Run ETL' in the Flask dashboard.")

    st.divider()

    # ── Data Lineage ──────────────────────────────────────────────────────────
    st.subheader("🔗 Data Lineage — Source to Gold")
    st.markdown("""
    Every record in the Gold layer carries full lineage metadata:
    `_source_file` → `_source_era` → `_source_type` → `_ingested_at` → `_cdc_op` → `_cdc_ts`
    """)

    lineage_data = [
        {"Layer":"Raw","Source":"2020 Paper Surveys","Format":"CSV","Era":"Historical","DQ Issues":"Bad dates, string yes/no, different column names"},
        {"Layer":"Raw","Source":"2021 HMIS System","Format":"JSON","Era":"Historical","DQ Issues":"Nested fields, dot-notation columns"},
        {"Layer":"Raw","Source":"2022 Hadoop Pipeline","Format":"Parquet","Era":"Historical","DQ Issues":"camelCase fields, DHIS2 schema"},
        {"Layer":"Raw","Source":"MySQL DB Export (current)","Format":"Parquet","Era":"Current","DQ Issues":"Bilingual values, duplicates, GPS errors"},
        {"Layer":"Bronze","Source":"All sources unified","Format":"Parquet","Era":"All","DQ Issues":"Exact copy + metadata added"},
        {"Layer":"Silver","Source":"Bronze","Format":"Parquet","Era":"All","DQ Issues":"22,386 DQ fixes applied"},
        {"Layer":"Gold","Source":"Silver","Format":"Parquet","Era":"All","DQ Issues":"Facts, dims, KPIs — analysis ready"},
    ]
    lin_df = pd.DataFrame(lineage_data)
    st.dataframe(lin_df, use_container_width=True, hide_index=True)

    # ── Watermarks ────────────────────────────────────────────────────────────
    st.subheader("⏱ Watermarks (Incremental Load Tracking)")
    wm = state.get("watermarks", {})
    if wm:
        wm_df = pd.DataFrame([{"Dataset": k, "Last Loaded": v[:19].replace("T"," ")}
                               for k,v in wm.items()])
        st.dataframe(wm_df, use_container_width=True, hide_index=True)
    else:
        st.info("No watermarks yet — run the ETL pipeline first.")

    # ── DQ Report ─────────────────────────────────────────────────────────────
    st.subheader("🔍 Data Quality Report")
    dq = data["dq_report"]
    if not dq.empty:
        dq_show = dq.drop(columns=[c for c in ["_layer"] if c in dq.columns], errors="ignore")
        st.dataframe(dq_show, use_container_width=True, hide_index=True)

        # DQ issues chart
        if "bilingual_values" in dq.columns and "duplicates_raw" in dq.columns:
            fig_dq = px.bar(dq, x="dataset", y=["bilingual_values","duplicates_raw"],
                            barmode="group", title="DQ Issues by Dataset",
                            labels={"value":"Count","variable":"Issue Type"})
            fig_dq.update_layout(height=320, xaxis_tickangle=-30)
            st.plotly_chart(fig_dq, use_container_width=True)
    else:
        st.info("No DQ report available. Run the ETL pipeline.")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: DATA JOURNEY (DAG)
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🗺 Data Journey (DAG)":
    st.title("🗺 Data Journey — Airflow-style DAG Visualization")
    st.markdown("*How data flows from heterogeneous sources through the Medallion pipeline to analytics*")

    # DAG visualization using Plotly
    nodes = [
        # Sources
        dict(x=0, y=4, label="2020 Paper\nSurveys\n(CSV)", color="#fed7d7", border="#c53030", size=40),
        dict(x=0, y=3, label="2021 HMIS\nSystem\n(JSON)", color="#fed7d7", border="#c53030", size=40),
        dict(x=0, y=2, label="2022 Hadoop\nPipeline\n(Parquet)", color="#fed7d7", border="#c53030", size=40),
        dict(x=0, y=1, label="MySQL DB\nExport\n(Parquet)", color="#c6f6d5", border="#276749", size=40),
        dict(x=0, y=0, label="Survey\nForms\n(Live)", color="#bee3f8", border="#2b6cb0", size=40),
        # Bronze
        dict(x=2, y=2, label="BRONZE\nExact Copy\n+Metadata", color="#fefcbf", border="#d69e2e", size=50),
        # Silver
        dict(x=4, y=2, label="SILVER\nCleaned\n+CDC Tagged", color="#e2e8f0", border="#718096", size=50),
        # Gold
        dict(x=6, y=4, label="dim_district\n(SCD2)", color="#fefcbf", border="#d69e2e", size=40),
        dict(x=6, y=3, label="dim_facility\n(SCD2)", color="#fefcbf", border="#d69e2e", size=40),
        dict(x=6, y=2, label="fct_child\n_nutrition", color="#fefcbf", border="#d69e2e", size=40),
        dict(x=6, y=1, label="fct_maternal\n_health", color="#fefcbf", border="#d69e2e", size=40),
        dict(x=6, y=0, label="rpt_district\n_summary", color="#fefcbf", border="#d69e2e", size=40),
        # Consumers
        dict(x=8, y=3, label="Flask\nDashboard", color="#e9d8fd", border="#553c9a", size=35),
        dict(x=8, y=2, label="Streamlit\nDashboard", color="#e9d8fd", border="#553c9a", size=35),
        dict(x=8, y=1, label="Power BI\n/Tableau", color="#e9d8fd", border="#553c9a", size=35),
        dict(x=8, y=0, label="REST API\n/JSON", color="#e9d8fd", border="#553c9a", size=35),
    ]

    edges = [
        (0,5),(1,5),(2,5),(3,5),(4,5),   # sources -> bronze
        (5,6),                             # bronze -> silver
        (6,7),(6,8),(6,9),(6,10),(6,11),  # silver -> gold
        (9,12),(9,13),(9,14),(9,15),       # gold -> consumers
        (11,12),(11,13),(11,14),(11,15),
    ]

    fig = go.Figure()

    # Draw edges
    for s,e in edges:
        fig.add_trace(go.Scatter(
            x=[nodes[s]["x"], nodes[e]["x"]],
            y=[nodes[s]["y"], nodes[e]["y"]],
            mode="lines",
            line=dict(color="#a0aec0", width=1.5),
            showlegend=False, hoverinfo="none",
        ))

    # Draw nodes
    for n in nodes:
        fig.add_trace(go.Scatter(
            x=[n["x"]], y=[n["y"]],
            mode="markers+text",
            marker=dict(size=n["size"], color=n["color"],
                        line=dict(color=n["border"], width=2)),
            text=[n["label"]],
            textposition="middle center",
            textfont=dict(size=8, color="#1a202c"),
            showlegend=False,
            hoverinfo="text",
            hovertext=n["label"],
        ))

    # Layer labels
    for x, label, color in [(0,"RAW SOURCES","#c53030"),(2,"BRONZE","#d69e2e"),
                              (4,"SILVER","#718096"),(6,"GOLD","#d69e2e"),(8,"CONSUMERS","#553c9a")]:
        fig.add_annotation(x=x, y=4.8, text=f"<b>{label}</b>",
                           showarrow=False, font=dict(size=11, color=color))

    fig.update_layout(
        height=500, showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.5,8.5]),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False, range=[-0.5,5.2]),
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(t=40,b=10,l=10,r=10),
        title="PSAKSH Data Pipeline DAG",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Technique explanations
    st.subheader("📚 Data Engineering Techniques Used")
    techniques = {
        "Full Load":         "Initial load of ALL historical data (2020-2022). Triggered when no watermark exists.",
        "Incremental Load":  "Only NEW records since last watermark. Detected via MD5 file checksum comparison.",
        "CDC":               "Change Data Capture — every Silver record tagged with _cdc_op (INSERT/UPDATE/DELETE).",
        "SCD Type 2":        "Slowly Changing Dimensions — dim_district/dim_facility preserve full history with effective dates.",
        "Delta Lake Pattern":"Partitioned storage (year/month), audit log (pipeline_state.json), ACID-like guarantees.",
        "Windowing":         "Time-window KPI aggregations: monthly, quarterly, annual, by district, by province.",
        "Upsert/Merge":      "Gold layer merges incoming data with existing facts on primary key.",
        "Schema Evolution":  "50+ column renames across legacy years (hh_id→household_id, anaemia→anemia, etc.).",
        "Data Lineage":      "Every record: _source_file, _source_era, _source_type, _ingested_at, _cdc_op, _cdc_ts.",
        "Append-Only Raw":   "New data always appended to raw sources — never replaces existing files.",
    }
    cols = st.columns(2)
    for i, (tech, desc) in enumerate(techniques.items()):
        with cols[i % 2]:
            st.markdown(f"""
            <div style="background:white;border-radius:6px;padding:10px 14px;margin-bottom:8px;border-left:3px solid #2b6cb0">
            <strong style="color:#1a365d">{tech}</strong><br>
            <span style="font-size:0.82rem;color:#4a5568">{desc}</span>
            </div>""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: MATERNAL HEALTH
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🤱 Maternal Health":
    st.title("🤱 Maternal Health Indicators")
    c1,c2,c3,c4 = st.columns(4)
    with c1: kpi_metric("Women Assessed", len(mat_f))
    with c2: kpi_metric("ANC 4+", safe_mean(mat_f,"anc_4plus"), help_text="WHO target: 80%")
    with c3: kpi_metric("Skilled Delivery", safe_mean(mat_f,"last_delivery_skilled"), help_text="National target: 80%")
    with c4: kpi_metric("Maternal Anemia", safe_mean(mat_f,"anemia"), help_text="Hb < 11 g/dL")

    if not mat_f.empty:
        col1, col2 = st.columns(2)
        with col1:
            if "district" in mat_f.columns and "visit_round" in mat_f.columns and "anc_4plus" in mat_f.columns:
                anc = mat_f.groupby(["district","visit_round"])["anc_4plus"].mean().reset_index()
                fig = px.line(anc.sort_values("visit_round"), x="visit_round", y="anc_4plus",
                              color="district", markers=True, title="ANC 4+ Coverage by District & Round",
                              labels={"anc_4plus":"ANC 4+ Rate","visit_round":"Round"})
                fig.update_yaxes(tickformat=".0%")
                fig.add_hline(y=0.80, line_dash="dash", line_color="#c53030", annotation_text="80% target")
                fig.update_layout(height=380)
                st.plotly_chart(fig, use_container_width=True)
        with col2:
            if "district" in mat_f.columns and "hemoglobin_gdl" in mat_f.columns:
                hb = mat_f.dropna(subset=["hemoglobin_gdl"])
                if not hb.empty:
                    fig2 = px.box(hb, x="district", y="hemoglobin_gdl", color="district",
                                  title="Maternal Hemoglobin by District (g/dL)",
                                  labels={"hemoglobin_gdl":"Hb (g/dL)"})
                    fig2.add_hline(y=11.0, line_dash="dash", line_color="#c53030",
                                   annotation_text="Anemia threshold")
                    fig2.update_layout(height=380, showlegend=False)
                    st.plotly_chart(fig2, use_container_width=True)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: FACILITIES
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🏥 Facilities":
    st.title("🏥 Health Facility Readiness")
    if not fac_f.empty:
        score_col = "readiness_score" if "readiness_score" in fac_f.columns else "overall_score"
        if score_col in fac_f.columns:
            c1,c2,c3 = st.columns(3)
            with c1: kpi_metric("Facilities Assessed", len(fac_f))
            with c2: kpi_metric("Avg Readiness", safe_mean(fac_f, score_col)/100, help_text="0-100 scale")
            with c3:
                ready = (fac_f[score_col] >= 60).mean() if score_col in fac_f.columns else float("nan")
                kpi_metric("Facilities Ready (≥60%)", ready)

            col1, col2 = st.columns(2)
            with col1:
                if "district" in fac_f.columns:
                    avg = fac_f.groupby("district")[score_col].mean().reset_index().sort_values(score_col)
                    fig = px.bar(avg, x=score_col, y="district", orientation="h",
                                 color=score_col,
                                 color_continuous_scale=[[0,"#c53030"],[0.6,"#d69e2e"],[1,"#276749"]],
                                 title="Readiness Score by District",
                                 labels={score_col:"Score (%)"})
                    fig.add_vline(x=60, line_dash="dash", annotation_text="60% threshold")
                    fig.update_layout(height=500, showlegend=False)
                    st.plotly_chart(fig, use_container_width=True)
            with col2:
                sc = [c for c in fac_f.columns if c.startswith("stockout_")]
                if sc:
                    rates = fac_f[sc].mean().reset_index()
                    rates.columns = ["commodity","rate"]
                    rates["commodity"] = rates["commodity"].str.replace("stockout_","",regex=False).str.replace("_"," ").str.title()
                    fig2 = px.bar(rates.sort_values("rate"), x="rate", y="commodity",
                                  orientation="h", title="Stock-out Rate by Commodity",
                                  color="rate", color_continuous_scale="Reds",
                                  labels={"rate":"Stock-out Rate"})
                    fig2.update_xaxes(tickformat=".0%")
                    fig2.update_layout(height=400, showlegend=False)
                    st.plotly_chart(fig2, use_container_width=True)
    else:
        st.warning("No facility data available.")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: FIELD OPERATIONS
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📍 Field Operations":
    st.title("📍 Field Operations & Data Quality")
    bc = data["backcheck"]
    if not bc.empty:
        c1,c2,c3,c4 = st.columns(4)
        with c1: kpi_metric("Back-checks", len(bc))
        with c2: kpi_metric("Pass Rate", safe_mean(bc,"overall_pass"), help_text="Target: ≥90%")
        with c3: kpi_metric("Avg Height Disc.", f"{safe_mean(bc,'height_discrepancy_cm'):.2f} cm", help_text="Threshold: ±2cm")
        with c4: kpi_metric("Avg Weight Disc.", f"{safe_mean(bc,'weight_discrepancy_kg'):.2f} kg", help_text="Threshold: ±0.5kg")

        if "per_enumerator" in bc.columns:
            enum_perf = bc.groupby("per_enumerator").agg(
                backchecks=("original_visit_id","count"),
                pass_rate=("overall_pass","mean"),
                h_disc=("height_discrepancy_cm","mean"),
                w_disc=("weight_discrepancy_kg","mean"),
            ).reset_index().sort_values("pass_rate")
            enum_perf["flag"] = enum_perf["pass_rate"].apply(
                lambda x: "FAIL" if x < 0.70 else ("WARN" if x < 0.85 else "PASS")
            )
            st.subheader("Enumerator Performance")
            st.dataframe(enum_perf, use_container_width=True, hide_index=True)
    else:
        st.info("No back-check data available.")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: DATA DICTIONARY
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📖 Data Dictionary":
    st.title("📖 Data Dictionary & Glossary")
    st.markdown("*Complete reference for all indicators, methods, and data engineering terms*")

    search = st.text_input("🔍 Search terms...", placeholder="e.g. stunting, CDC, Bronze, HAZ")

    glossary = {
        "Health Indicators": [
            ("Stunting (HAZ < -2 SD)", "Low height-for-age. Chronic malnutrition, irreversible after age 2. Pakistan: ~40%."),
            ("Wasting (WHZ < -2 SD)", "Low weight-for-height. Acute malnutrition, life-threatening if severe. Responds to therapeutic feeding."),
            ("Underweight (WAZ < -2 SD)", "Low weight-for-age. Composite of stunting + wasting."),
            ("MUAC", "Mid-Upper Arm Circumference. Rapid screening: <115mm=SAM, 115-125mm=MAM. Historical data in cm — ETL converts to mm."),
            ("Anemia", "Hemoglobin < 11 g/dL. Child and maternal. Causes: iron deficiency, malaria, infections."),
            ("ANC 4+", "4+ antenatal care visits. WHO target: ≥8 contacts. Linked to lower maternal mortality."),
            ("Skilled Delivery", "Birth attended by doctor/nurse/midwife. SDG 3.1 indicator. National target: 80%."),
        ],
        "Data Engineering": [
            ("Medallion Architecture", "Bronze (raw) → Silver (clean) → Gold (analytics). Each layer adds value without destroying previous."),
            ("Full Load", "Load ALL data from source. Used for initial setup or when source changed completely."),
            ("Incremental Load", "Load only NEW records since last watermark. Detected via MD5 file checksum."),
            ("CDC", "Change Data Capture. Tracks INSERT/UPDATE/DELETE. Every Silver record has _cdc_op, _cdc_ts."),
            ("SCD Type 2", "Slowly Changing Dimension. Preserves full history with effective_from/effective_to dates."),
            ("Delta Lake Pattern", "Partitioned storage + audit log (pipeline_state.json). Enables time-travel queries."),
            ("Watermark", "Timestamp of last successful load per dataset. Stored in pipeline_state.json."),
            ("Upsert/Merge", "INSERT new + UPDATE existing records. MySQL: INSERT...ON DUPLICATE KEY UPDATE."),
            ("Schema Evolution", "Handling different column names across years. 50+ renames in SCHEMA_MAP."),
            ("Windowing", "Time-window aggregations: monthly, quarterly, annual KPIs."),
            ("Data Lineage", "_source_file, _source_era, _source_type, _ingested_at, _cdc_op, _cdc_ts on every record."),
            ("Append-Only Raw", "New data always appended to raw sources — never replaces existing files."),
        ],
        "Data Quality": [
            ("Bilingual Values", "Urdu/English mixed fields (~15%). ETL normalises: پائپ→piped, ہاں→1."),
            ("Duplicate Submissions", "Same household submitted twice (~4.5%). Silver deduplicates keeping latest."),
            ("Anthropometric Outliers", "Height <40cm or >130cm, weight <1.5kg or >30kg, |z|>6. Nulled in Silver."),
            ("GPS Out-of-Bounds", "Coordinates outside Pakistan (lat 23.5-37.5, lon 60.5-77.5). Nulled in Silver."),
            ("Short Interview Flag", "Duration <10 min = potential fabrication. Preserved as quality flag."),
        ],
    }

    for section, items in glossary.items():
        filtered = [(t,d) for t,d in items if not search or search.lower() in t.lower() or search.lower() in d.lower()]
        if filtered:
            st.subheader(section)
            for term, defn in filtered:
                with st.expander(f"**{term}**"):
                    st.write(defn)

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE: API ACCESS
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📡 API Access":
    st.title("📡 API Access — Power BI, Tableau & Direct")
    st.markdown("*Connect any BI tool to the PSAKSH REST API*")

    BASE_URL = "https://softcomputech.com/publichealth/api/v1"

    st.subheader("🔗 Available Endpoints")
    endpoints = [
        (f"{BASE_URL}/child-nutrition",  "Child Nutrition",  "Row-level fact table. Filter: ?district=Lahore&visit_round=1"),
        (f"{BASE_URL}/maternal-health",  "Maternal Health",  "Row-level maternal fact table."),
        (f"{BASE_URL}/district-summary", "District Summary", "Pre-aggregated KPIs. Best for Power BI dashboards."),
        (f"{BASE_URL}/kpis",             "National KPIs",    "Single-row summary. Ideal for executive dashboards."),
        (f"{BASE_URL}/facilities",       "Facilities",       "Facility readiness assessments."),
        (f"{BASE_URL}/pipeline-status",  "Pipeline Status",  "ETL layer statistics."),
        (f"{BASE_URL}/tableau/child-nutrition", "Tableau WDC", "Tableau Web Data Connector with column type hints."),
    ]
    for url, name, desc in endpoints:
        st.markdown(f"""
        <div style="background:white;border-radius:6px;padding:10px 14px;margin-bottom:6px;border-left:3px solid #2b6cb0">
        <strong>{name}</strong> — <code style="font-size:0.8rem">{url}</code><br>
        <span style="font-size:0.8rem;color:#718096">{desc}</span>
        </div>""", unsafe_allow_html=True)

    st.subheader("⚡ Power BI Connection")
    st.code(f"""
1. Open Power BI Desktop
2. Get Data → Web
3. Paste URL: {BASE_URL}/district-summary
4. Click OK → Load
5. For live refresh: Publish to Power BI Service → Schedule refresh
    """, language="text")

    st.subheader("📊 Tableau Connection")
    st.code(f"""
1. Open Tableau Desktop
2. Connect → Web Data Connector
3. Enter URL: {BASE_URL}/tableau/child-nutrition
4. Click Get Data Now
    """, language="text")

    st.subheader("🐍 Python / Pandas Direct Access")
    st.code(f"""
import pandas as pd
# Load Gold Parquet directly (fastest)
fct = pd.read_parquet("data/gold/fct_child_nutrition.parquet")
dist = pd.read_parquet("data/gold/rpt_district_summary.parquet")

# Or via API
import requests
r = requests.get("{BASE_URL}/district-summary?api_key=demo")
df = pd.DataFrame(r.json()["data"])
    """, language="python")

    # Live data preview
    st.subheader("👁 Live Data Preview")
    preview_ds = st.selectbox("Dataset", ["fct_child_nutrition","rpt_district_summary","fct_maternal_health"])
    df_prev = load_dataset(preview_ds)
    if not df_prev.empty:
        st.dataframe(df_prev.head(20), use_container_width=True)
        st.caption(f"{len(df_prev):,} total rows | {len(df_prev.columns)} columns")
    else:
        st.info("No data available. Run the ETL pipeline first.")

