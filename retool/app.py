"""
Healthcare Billing Anomaly Investigation & Audit Dashboard
==========================================================
Interactive Streamlit workbench for triaging billing anomalies flagged by the
SQL (Window Functions / CTEs / Temporal Joins) and Python Regex detection engines.

Run:
    python -m streamlit run retool/app.py
"""

import os
from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ─────────────────────────────────────────────────────────────────────────────
# Page configuration
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Billing Anomaly Investigation Queue",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────────────────
# Constants & display helpers
# ─────────────────────────────────────────────────────────────────────────────
TYPE_LABELS = {
    "DUPLICATE_CHARGE": "Duplicate Charge",
    "POST_MORTEM_BILLING": "Post-Mortem Billing",
    "MALFORMED_CPT_CODE": "Malformed CPT/SNOMED Code",
    "OVERPAYMENT": "Overpayment",
}
TYPE_COLORS = {
    "Duplicate Charge": "#3B82F6",
    "Post-Mortem Billing": "#EF4444",
    "Malformed CPT/SNOMED Code": "#F59E0B",
    "Overpayment": "#8B5CF6",
}
METHOD_LABELS = {
    "SQL_WINDOW_FUNCTION": "SQL Window Function",
    "SQL_TEMPORAL_JOIN": "SQL Temporal Join",
    "SQL_CTE_RECONCILIATION": "SQL CTE Reconciliation",
    "PYTHON_REGEX_VALIDATOR": "Python Regex Validator",
}
RECOMMENDED_ACTION = {
    "DUPLICATE_CHARGE": "Compare against the original charge line; void the duplicate and request a payer adjustment if already paid.",
    "POST_MORTEM_BILLING": "Verify the patient's date of death and the service date; reverse the charge and review the claim for compliance exposure.",
    "MALFORMED_CPT_CODE": "Correct the procedure code against the CPT/SNOMED/HCPCS reference and resubmit the claim line.",
    "OVERPAYMENT": "Reconcile payments against the billed amount; initiate a refund or credit-balance resolution.",
}
PRIORITY_ORDER = ["🔴 Critical", "🟠 High", "🟡 Medium", "🟢 Low"]
STATUS_OPTIONS = ["Open", "In Review", "Escalated", "Resolved"]


def pretty_type(value: str) -> str:
    return TYPE_LABELS.get(value, str(value).replace("_", " ").title())


def pretty_method(value: str) -> str:
    return METHOD_LABELS.get(value, str(value).replace("_", " ").title())


def show(obj_fn, *args, **kwargs):
    """Call a Streamlit element with full-width sizing across Streamlit versions."""
    try:
        return obj_fn(*args, width="stretch", **kwargs)
    except TypeError:
        return obj_fn(*args, use_container_width=True, **kwargs)


def money(x: float) -> str:
    return f"${x:,.2f}"


# ─────────────────────────────────────────────────────────────────────────────
# Styling
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
        .block-container {padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1500px;}
        .hero {
            background: linear-gradient(120deg, #0F2B46 0%, #1D4E89 55%, #2A7DE1 100%);
            padding: 1.6rem 2rem; border-radius: 16px; margin-bottom: 1.2rem;
            box-shadow: 0 6px 24px rgba(15, 43, 70, 0.25);
        }
        .hero h1 {color: #FFFFFF; font-size: 1.85rem; margin: 0 0 .35rem 0; padding: 0;}
        .hero p {color: #D6E4F5; margin: 0; font-size: .98rem;}
        .chip {
            display: inline-block; padding: .18rem .65rem; margin: .7rem .4rem 0 0;
            border-radius: 999px; font-size: .74rem; font-weight: 600; letter-spacing: .02em;
            background: rgba(255,255,255,.14); color: #FFFFFF; border: 1px solid rgba(255,255,255,.25);
        }
        div[data-testid="stMetric"] {padding: .2rem .2rem;}
        div[data-testid="stMetricValue"] {font-size: 1.7rem; font-weight: 700;}
        button[data-baseweb="tab"] {font-weight: 600;}
        .section-note {opacity: .7; font-size: .85rem; margin-top: -.4rem; margin-bottom: .6rem;}
        .action-box {
            border-left: 4px solid #2A7DE1; padding: .7rem 1rem; border-radius: 6px;
            background: rgba(42,125,225,.08); margin: .4rem 0 1rem 0;
        }
        footer {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# Database connection
# ─────────────────────────────────────────────────────────────────────────────
load_dotenv()
DB_URL = os.getenv("DATABASE_URL")
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

if not DB_URL:
    st.error(
        "**DATABASE_URL is not set.** Create a `.env` file in the project root:\n\n"
        "```env\nDATABASE_URL=postgresql://user:password@host:port/postgres\n```"
    )
    st.stop()


@st.cache_resource
def get_engine():
    return create_engine(DB_URL, pool_pre_ping=True)


engine = get_engine()

# ─────────────────────────────────────────────────────────────────────────────
# Data access layer
# ─────────────────────────────────────────────────────────────────────────────
SUMMARY_SQL = """
    SELECT detected_type, detection_method,
           COUNT(*) AS total_flagged,
           ROUND(SUM(financial_impact), 2) AS total_impact
    FROM investigation.detected_anomalies
    GROUP BY detected_type, detection_method
    ORDER BY total_flagged DESC;
"""

RECALL_SQL = """
    SELECT g.anomaly_type,
           COUNT(DISTINCT g.record_id) AS injected_count,
           COUNT(DISTINCT d.transaction_id) AS caught_count,
           ROUND((COUNT(DISTINCT d.transaction_id)::NUMERIC / COUNT(DISTINCT g.record_id)) * 100, 2) AS recall_pct
    FROM investigation.injected_anomalies_log g
    LEFT JOIN investigation.detected_anomalies d
        ON g.record_id = d.transaction_id
       AND g.anomaly_type = d.detected_type
    GROUP BY g.anomaly_type
    ORDER BY g.anomaly_type;
"""

QUEUE_SQL = """
    SELECT finding_id, detected_type, transaction_id, claim_id, patient_id,
           financial_impact, detection_method, details, detected_at
    FROM investigation.detected_anomalies
    ORDER BY financial_impact DESC, finding_id ASC
    LIMIT :row_limit;
"""


@st.cache_data(ttl=60, show_spinner="Loading audit data from PostgreSQL…")
def load_data(row_limit: int):
    summary = pd.read_sql(text(SUMMARY_SQL), engine)
    recall = pd.read_sql(text(RECALL_SQL), engine)
    queue = pd.read_sql(text(QUEUE_SQL), engine, params={"row_limit": row_limit})

    summary["total_impact"] = pd.to_numeric(summary["total_impact"], errors="coerce").fillna(0.0)
    summary["total_flagged"] = pd.to_numeric(summary["total_flagged"], errors="coerce").fillna(0).astype(int)
    for col in ("injected_count", "caught_count"):
        recall[col] = pd.to_numeric(recall[col], errors="coerce").fillna(0).astype(int)
    recall["recall_pct"] = pd.to_numeric(recall["recall_pct"], errors="coerce").fillna(0.0)
    queue["financial_impact"] = pd.to_numeric(queue["financial_impact"], errors="coerce").fillna(0.0)
    queue["detected_at"] = pd.to_datetime(queue["detected_at"], errors="coerce")
    return summary, recall, queue, datetime.now()


@st.cache_data(ttl=60, show_spinner=False)
def load_case_context(transaction_id: str, claim_id: str, patient_id: str):
    """Raw ledger record + every other finding that shares the claim or patient."""
    with engine.connect() as conn:
        raw = pd.read_sql(
            text("SELECT * FROM staging.claims_transactions WHERE transaction_id = :t"),
            conn, params={"t": transaction_id},
        )
        related = pd.read_sql(
            text(
                """
                SELECT finding_id, detected_type, transaction_id, claim_id,
                       financial_impact, detection_method
                FROM investigation.detected_anomalies
                WHERE (claim_id = :c OR patient_id = :p) AND transaction_id <> :t
                ORDER BY financial_impact DESC LIMIT 25
                """
            ),
            conn, params={"c": claim_id, "p": patient_id, "t": transaction_id},
        )
    return raw, related


def assign_priority(impact: pd.Series) -> pd.Series:
    """Percentile-based triage tiers on financial impact (top 10% Critical, next 20% High, next 30% Medium)."""
    if impact.empty:
        return pd.Series(dtype="object")
    pct = impact.rank(pct=True, method="max")
    tiers = pd.cut(pct, bins=[0, 0.40, 0.70, 0.90, 1.0], labels=["🟢 Low", "🟡 Medium", "🟠 High", "🔴 Critical"],
                   include_lowest=True)
    return tiers.astype(str)


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — controls
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🏥 Audit Controls")
    st.caption("Filters apply to the Issue Queue and Case Workbench.")

    row_limit = st.select_slider(
        "Queue size (top N by financial impact)",
        options=[100, 250, 500, 1000, 2500, 5000],
        value=500,
    )
    if st.button("🔄 Refresh data", help="Clear the cache and re-query the database."):
        st.cache_data.clear()
        st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# Load data
# ─────────────────────────────────────────────────────────────────────────────
try:
    summary_df, recall_df, queue_df, loaded_at = load_data(row_limit)
except Exception as exc:  # noqa: BLE001
    st.error(f"**Database connection or query error:** {exc}")
    st.info("Check `DATABASE_URL` in `.env` and make sure the pipeline has been run "
            "(`inject_anomalies.py` → SQL detection → `regex_and_audit_validator.py`).")
    st.stop()

if summary_df.empty or queue_df.empty:
    st.warning("No findings in `investigation.detected_anomalies` yet. Run the detection pipeline first.")
    st.stop()

# Enrich the queue
queue_df = queue_df.copy()
queue_df["priority"] = assign_priority(queue_df["financial_impact"])
queue_df["type_label"] = queue_df["detected_type"].map(pretty_type)
queue_df["method_label"] = queue_df["detection_method"].map(pretty_method)
if "triage" not in st.session_state:
    st.session_state["triage"] = {}
queue_df["status"] = queue_df["finding_id"].map(st.session_state["triage"]).fillna("Open")

summary_df = summary_df.copy()
summary_df["type_label"] = summary_df["detected_type"].map(pretty_type)
summary_df["method_label"] = summary_df["detection_method"].map(pretty_method)
recall_df = recall_df.copy()
recall_df["type_label"] = recall_df["anomaly_type"].map(pretty_type)

# Sidebar filters (need data for options)
with st.sidebar:
    st.divider()
    type_options = sorted(queue_df["type_label"].unique())
    sel_types = st.multiselect("Anomaly type", type_options, default=type_options)

    method_options = sorted(queue_df["method_label"].unique())
    sel_methods = st.multiselect("Detection method", method_options, default=method_options)

    sel_priority = st.multiselect("Priority tier", PRIORITY_ORDER, default=PRIORITY_ORDER)

    imp_min, imp_max = float(queue_df["financial_impact"].min()), float(queue_df["financial_impact"].max())
    if imp_max > imp_min:
        sel_range = st.slider("Financial impact ($)", imp_min, imp_max, (imp_min, imp_max))
    else:
        sel_range = (imp_min, imp_max)

    sel_status = st.multiselect("Triage status", STATUS_OPTIONS, default=STATUS_OPTIONS)
    search = st.text_input("🔎 Search", placeholder="Claim, patient or transaction ID")

    st.divider()
    st.caption(f"Last refreshed: {loaded_at:%Y-%m-%d %H:%M:%S}")
    st.caption("Source: `investigation.detected_anomalies`")

# Apply filters
mask = (
    queue_df["type_label"].isin(sel_types)
    & queue_df["method_label"].isin(sel_methods)
    & queue_df["priority"].isin(sel_priority)
    & queue_df["status"].isin(sel_status)
    & queue_df["financial_impact"].between(sel_range[0], sel_range[1])
)
if search:
    s = search.strip()
    mask &= (
        queue_df["transaction_id"].fillna("").str.contains(s, case=False, regex=False)
        | queue_df["claim_id"].fillna("").str.contains(s, case=False, regex=False)
        | queue_df["patient_id"].fillna("").str.contains(s, case=False, regex=False)
    )
filtered = queue_df[mask].reset_index(drop=True)

# ─────────────────────────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(
    """
    <div class="hero">
        <h1>🏥 Healthcare Billing Anomaly Investigation &amp; Audit Queue</h1>
        <p>Automated Revenue Cycle Management (RCM) anomaly detection powered by PostgreSQL
        Window Functions, CTEs, Temporal Joins and Python Regex validation.</p>
        <span class="chip">PostgreSQL · Supabase</span>
        <span class="chip">SQL Window Functions &amp; CTEs</span>
        <span class="chip">Python Regex</span>
        <span class="chip">Ground-Truth Validated</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────────────────────────
# KPI row
# ─────────────────────────────────────────────────────────────────────────────
total_flagged = int(summary_df["total_flagged"].sum())
total_exposure = float(summary_df["total_impact"].sum())
injected_total = int(recall_df["injected_count"].sum())
caught_total = int(recall_df["caught_count"].sum())
overall_recall = (caught_total / injected_total * 100) if injected_total else 0.0

k1, k2, k3, k4, k5 = st.columns(5)
with k1.container(border=True):
    st.metric("Total Flagged Records", f"{total_flagged:,}")
with k2.container(border=True):
    st.metric("Total Financial Exposure", money(total_exposure))
with k3.container(border=True):
    st.metric("Injected Test Cases", f"{injected_total:,}")
with k4.container(border=True):
    st.metric("Detection Recall", f"{overall_recall:.1f}%", delta=f"{caught_total}/{injected_total} caught",
              delta_color="off")
with k5.container(border=True):
    st.metric("In Current View", f"{len(filtered):,}", delta=money(float(filtered['financial_impact'].sum())),
              delta_color="off", help="Rows and exposure after applying the sidebar filters.")

st.write("")

# ─────────────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────────────
tab_overview, tab_validation, tab_queue, tab_method = st.tabs(
    ["📈 Overview", "🎯 Ground-Truth Validation", "🔍 Issue Queue & Case Workbench", "🧠 Methodology"]
)

# ── Overview ────────────────────────────────────────────────────────────────
with tab_overview:
    by_type = (
        summary_df.groupby("type_label", as_index=False)
        .agg(total_flagged=("total_flagged", "sum"), total_impact=("total_impact", "sum"))
    )
    domain = list(TYPE_COLORS.keys())
    palette = list(TYPE_COLORS.values())
    color_scale = alt.Scale(domain=domain, range=palette)

    c1, c2 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.subheader("💰 Financial Exposure by Anomaly Type")
            chart = (
                alt.Chart(by_type)
                .mark_bar(cornerRadiusEnd=5)
                .encode(
                    y=alt.Y("type_label:N", sort="-x", title=None),
                    x=alt.X("total_impact:Q", title="Total exposure ($)", axis=alt.Axis(format="$,.0f")),
                    color=alt.Color("type_label:N", scale=color_scale, legend=None),
                    tooltip=[alt.Tooltip("type_label:N", title="Type"),
                             alt.Tooltip("total_flagged:Q", title="Findings", format=","),
                             alt.Tooltip("total_impact:Q", title="Exposure", format="$,.2f")],
                )
                .properties(height=260)
            )
            show(st.altair_chart, chart)
    with c2:
        with st.container(border=True):
            st.subheader("🧮 Findings by Anomaly Type")
            donut = (
                alt.Chart(by_type)
                .mark_arc(innerRadius=62, outerRadius=115)
                .encode(
                    theta=alt.Theta("total_flagged:Q"),
                    color=alt.Color("type_label:N", scale=color_scale, legend=alt.Legend(title=None, orient="right")),
                    tooltip=[alt.Tooltip("type_label:N", title="Type"),
                             alt.Tooltip("total_flagged:Q", title="Findings", format=",")],
                )
                .properties(height=260)
            )
            show(st.altair_chart, donut)

    c3, c4 = st.columns(2)
    with c3:
        with st.container(border=True):
            st.subheader("📊 Impact Distribution (Current Queue)")
            hist_src = queue_df[["type_label", "financial_impact"]]
            hist = (
                alt.Chart(hist_src)
                .mark_bar(opacity=0.9)
                .encode(
                    x=alt.X("financial_impact:Q", bin=alt.Bin(maxbins=30), title="Financial impact ($)",
                            axis=alt.Axis(format="$,.0f")),
                    y=alt.Y("count():Q", title="Findings"),
                    color=alt.Color("type_label:N", scale=color_scale, legend=alt.Legend(title=None, orient="bottom")),
                    tooltip=[alt.Tooltip("count():Q", title="Findings")],
                )
                .properties(height=280)
            )
            show(st.altair_chart, hist)
    with c4:
        with st.container(border=True):
            st.subheader("🔝 Top 10 Claims by Exposure")
            top_claims = (
                queue_df.groupby("claim_id", as_index=False)
                .agg(findings=("finding_id", "count"), exposure=("financial_impact", "sum"),
                     types=("type_label", lambda s: ", ".join(sorted(set(s)))))
                .sort_values("exposure", ascending=False)
                .head(10)
            )
            show(
                st.dataframe,
                top_claims,
                hide_index=True,
                column_config={
                    "claim_id": st.column_config.TextColumn("Claim ID"),
                    "findings": st.column_config.NumberColumn("Findings", format="%d"),
                    "exposure": st.column_config.NumberColumn("Exposure", format="$%.2f"),
                    "types": st.column_config.TextColumn("Anomaly types"),
                },
            )

    with st.container(border=True):
        st.subheader("📋 Detection Breakdown")
        show(
            st.dataframe,
            summary_df[["type_label", "method_label", "total_flagged", "total_impact"]],
            hide_index=True,
            column_config={
                "type_label": st.column_config.TextColumn("Anomaly type"),
                "method_label": st.column_config.TextColumn("Detection method"),
                "total_flagged": st.column_config.NumberColumn("Total flagged", format="%d"),
                "total_impact": st.column_config.NumberColumn("Total impact", format="$%.2f"),
            },
        )

# ── Validation ──────────────────────────────────────────────────────────────
with tab_validation:
    st.markdown(
        '<p class="section-note">Detected findings are reconciled against the seeded ground-truth log '
        "(<code>investigation.injected_anomalies_log</code>) to measure recall per category.</p>",
        unsafe_allow_html=True,
    )
    if recall_df.empty:
        st.info("No ground-truth log found. Run `inject_anomalies.py` first.")
    else:
        cols = st.columns(len(recall_df))
        for col, (_, r) in zip(cols, recall_df.iterrows()):
            with col.container(border=True):
                st.metric(r["type_label"], f"{r['recall_pct']:.1f}%",
                          delta=f"{int(r['caught_count'])}/{int(r['injected_count'])} caught", delta_color="off")
                st.progress(min(max(float(r["recall_pct"]) / 100, 0.0), 1.0))

        long_df = recall_df.melt(id_vars="type_label", value_vars=["injected_count", "caught_count"],
                                 var_name="series", value_name="count")
        long_df["series"] = long_df["series"].map({"injected_count": "Injected", "caught_count": "Caught"})
        with st.container(border=True):
            st.subheader("Injected vs. Caught")
            grouped = (
                alt.Chart(long_df)
                .mark_bar(cornerRadiusEnd=4)
                .encode(
                    x=alt.X("type_label:N", title=None, axis=alt.Axis(labelAngle=0)),
                    y=alt.Y("count:Q", title="Records"),
                    xOffset="series:N",
                    color=alt.Color("series:N", scale=alt.Scale(domain=["Injected", "Caught"],
                                                                range=["#94A3B8", "#10B981"]),
                                    legend=alt.Legend(title=None, orient="top")),
                    tooltip=["type_label:N", "series:N", "count:Q"],
                )
                .properties(height=300)
            )
            show(st.altair_chart, grouped)

        show(
            st.dataframe,
            recall_df[["type_label", "injected_count", "caught_count", "recall_pct"]],
            hide_index=True,
            column_config={
                "type_label": st.column_config.TextColumn("Anomaly type"),
                "injected_count": st.column_config.NumberColumn("Injected", format="%d"),
                "caught_count": st.column_config.NumberColumn("Caught", format="%d"),
                "recall_pct": st.column_config.ProgressColumn("Recall %", format="%.1f%%", min_value=0, max_value=100),
            },
        )

# ── Issue Queue & Case Workbench ────────────────────────────────────────────
with tab_queue:
    st.markdown(
        f'<p class="section-note">Showing the top <b>{row_limit:,}</b> findings by financial impact · '
        f"<b>{len(filtered):,}</b> match the current filters · Priority tiers are percentile-based on financial "
        "impact. Select a row to open the case workbench.</p>",
        unsafe_allow_html=True,
    )

    queue_cols = ["priority", "status", "type_label", "financial_impact", "transaction_id", "claim_id",
                  "patient_id", "method_label", "details", "finding_id", "detected_at"]
    display_df = filtered[queue_cols]
    max_impact = max(float(queue_df["financial_impact"].max()), 1.0)
    queue_config = {
        "priority": st.column_config.TextColumn("Priority", width="small"),
        "status": st.column_config.TextColumn("Status", width="small"),
        "type_label": st.column_config.TextColumn("Anomaly type", width="medium"),
        "financial_impact": st.column_config.ProgressColumn("Financial impact", format="$%.2f",
                                                            min_value=0, max_value=max_impact),
        "transaction_id": st.column_config.TextColumn("Transaction ID"),
        "claim_id": st.column_config.TextColumn("Claim ID"),
        "patient_id": st.column_config.TextColumn("Patient ID"),
        "method_label": st.column_config.TextColumn("Detection method"),
        "details": st.column_config.TextColumn("Details", width="large"),
        "finding_id": st.column_config.NumberColumn("Finding #", format="%d"),
        "detected_at": st.column_config.DatetimeColumn("Detected at", format="YYYY-MM-DD HH:mm"),
    }

    if filtered.empty:
        st.info("No findings match the current filters. Adjust the sidebar to widen the view.")
    else:
        selected_idx = None
        try:
            event = show(
                st.dataframe, display_df,
                hide_index=True, height=420, column_config=queue_config,
                on_select="rerun", selection_mode="single-row", key="queue_table",
            )
            rows = event.selection.rows if event is not None else []
            selected_idx = rows[0] if rows else None
        except TypeError:  # very old Streamlit without row selection
            show(st.dataframe, display_df, hide_index=True, height=420, column_config=queue_config)
            pick = st.selectbox("Open case (Finding #)", filtered["finding_id"].tolist(), index=None,
                                placeholder="Select a finding…")
            if pick is not None:
                selected_idx = int(filtered.index[filtered["finding_id"] == pick][0])

        # Export row
        e1, e2, _ = st.columns([1, 1, 3])
        with e1:
            st.download_button("📥 Export filtered queue (CSV)",
                               filtered.drop(columns=["type_label", "method_label"]).to_csv(index=False).encode("utf-8"),
                               file_name="billing_investigation_queue.csv", mime="text/csv")
        with e2:
            st.download_button("📥 Export reconciliation (CSV)",
                               recall_df.drop(columns=["type_label"]).to_csv(index=False).encode("utf-8"),
                               file_name="final_audit_reconciliation.csv", mime="text/csv")

        # Case workbench
        st.divider()
        st.subheader("🗂️ Case Workbench")
        if selected_idx is None:
            st.info("👆 Select a row in the table above to inspect the finding, the raw ledger record and related cases.")
        else:
            case = filtered.iloc[selected_idx]
            with st.container(border=True):
                h1, h2, h3, h4 = st.columns(4)
                h1.metric("Anomaly type", case["type_label"])
                h2.metric("Financial impact", money(float(case["financial_impact"])))
                h3.metric("Priority", case["priority"])
                h4.metric("Status", case["status"])

                st.markdown(
                    f'<div class="action-box"><b>Finding #{int(case["finding_id"])}</b> · {case["details"]}<br>'
                    f'<b>Recommended action:</b> {RECOMMENDED_ACTION.get(case["detected_type"], "Review the transaction manually.")}'
                    "</div>",
                    unsafe_allow_html=True,
                )

                d1, d2, d3, d4 = st.columns(4)
                d1.markdown(f"**Transaction**<br>`{case['transaction_id']}`", unsafe_allow_html=True)
                d2.markdown(f"**Claim**<br>`{case['claim_id']}`", unsafe_allow_html=True)
                d3.markdown(f"**Patient**<br>`{case['patient_id']}`", unsafe_allow_html=True)
                d4.markdown(f"**Detected by**<br>{case['method_label']}", unsafe_allow_html=True)

                st.write("")
                s1, s2 = st.columns([2, 1])
                with s1:
                    new_status = st.selectbox("Update triage status", STATUS_OPTIONS,
                                              index=STATUS_OPTIONS.index(case["status"]),
                                              key=f"status_{int(case['finding_id'])}")
                with s2:
                    st.write("")
                    st.write("")
                    if st.button("Save status", type="primary", key=f"save_{int(case['finding_id'])}"):
                        st.session_state["triage"][int(case["finding_id"])] = new_status
                        st.toast(f"Finding #{int(case['finding_id'])} marked as {new_status}", icon="✅")
                        st.rerun()
                st.caption("Triage status is kept for this browser session and is included in the CSV export.")

                try:
                    raw_df, related_df = load_case_context(str(case["transaction_id"]), str(case["claim_id"]),
                                                           str(case["patient_id"]))
                    with st.expander("🧾 Raw ledger record (staging.claims_transactions)", expanded=False):
                        if raw_df.empty:
                            st.write("No matching ledger row found.")
                        else:
                            show(st.dataframe, raw_df.T.rename(columns={0: "value"}).astype(str))
                    with st.expander(f"🔗 Related findings on the same claim or patient ({len(related_df)})",
                                     expanded=not related_df.empty):
                        if related_df.empty:
                            st.write("No other findings share this claim or patient.")
                        else:
                            related_df["detected_type"] = related_df["detected_type"].map(pretty_type)
                            related_df["detection_method"] = related_df["detection_method"].map(pretty_method)
                            show(st.dataframe, related_df, hide_index=True,
                                 column_config={"financial_impact": st.column_config.NumberColumn("Impact", format="$%.2f")})
                except Exception as exc:  # noqa: BLE001
                    st.warning(f"Could not load ledger context: {exc}")

# ── Methodology ─────────────────────────────────────────────────────────────
with tab_method:
    st.subheader("How anomalies are detected")
    method_table = pd.DataFrame(
        [
            ["Duplicate Charges", "SQL Window Function",
             "ROW_NUMBER() OVER (PARTITION BY claim_id, patient_id, procedure_code, from_date, amount)"],
            ["Post-Mortem Billing", "SQL Temporal Join",
             "Join claims_transactions with patients where service_date > deathdate"],
            ["Malformed CPT/SNOMED Codes", "Python Regex (re)", "Validate procedure code against ^(?!ERR-)[A-Z0-9]{5,18}$"],
            ["Overpayments / Negative Balance", "SQL CTE Reconciliation",
             "Isolate transactions with outstanding < 0 for ledger reconciliation"],
        ],
        columns=["Anomaly category", "Detection technique", "Technical logic"],
    )
    show(st.dataframe, method_table, hide_index=True)

    st.subheader("Pipeline")
    st.code(
        "Synthea ─▶ raw CSV ─▶ Supabase raw ─▶ staging ◀─ Anomaly Injector ─▶ Ground-Truth Log\n"
        "                                         │\n"
        "                       ┌─────────────────┴─────────────────┐\n"
        "                SQL Investigation Engine          Python Regex Validator\n"
        "                       └─────────────────┬─────────────────┘\n"
        "                                         ▼\n"
        "                          investigation.detected_anomalies\n"
        "                                         ▼\n"
        "                       Streamlit Issue Queue & CSV Reports",
        language="text",
    )

st.divider()
st.caption("Healthcare Billing Anomaly Investigation & Audit Pipeline · PostgreSQL (Supabase) · Python · Streamlit")