"""Well Operations Dashboard - an interactive Streamlit app for production engineers.

Run locally:   streamlit run app.py
Data: the cleaned output of my "Production Deferment Analytics" project (30 wells, 2024-2025).
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Well Operations Dashboard", page_icon="🛢️", layout="wide")

OIL_PRICE = 70
BLUE, ORANGE, GRAY, RED = "#2a78d6", "#eb6834", "#8a8985", "#d03b3b"
CAUSE_COLORS = {"ESP trip": BLUE, "Flowline leak": "#1baf7a", "Facility constraint": "#eda100",
                "Power failure": "#6250d6", "Planned maintenance": GRAY, "Well test": "#c3c2b7",
                "Unexplained (not logged)": RED}


# ---------- data ----------
@st.cache_data
def load():
    daily = pd.read_csv("data/daily_production.csv", parse_dates=["prod_date"])
    wells = pd.read_csv("data/wells.csv")
    events = pd.read_csv("data/downtime_events.csv", parse_dates=["start_date", "end_date"])
    status = pd.read_csv("data/well_status.csv")
    wells = wells.merge(status, on="well_id", how="left")
    return daily.merge(wells[["well_id", "field", "lift_type"]], on="well_id"), wells, events


daily, wells, events = load()

# ---------- sidebar filters ----------
st.sidebar.header("Filters")
fields = st.sidebar.multiselect("Field", sorted(wells.field.unique()), default=sorted(wells.field.unique()))
lifts = st.sidebar.multiselect("Lift type", sorted(wells.lift_type.unique()), default=sorted(wells.lift_type.unique()))
dmin, dmax = daily.prod_date.min().date(), daily.prod_date.max().date()
date_range = st.sidebar.date_input("Date range", (dmin, dmax), min_value=dmin, max_value=dmax)
if len(date_range) != 2:
    st.stop()
start, end = map(pd.Timestamp, date_range)
st.sidebar.caption("Data: synthetic, modelled on real daily production reports. "
                   "Potential = latest well-test rate.")

sel_wells = wells[wells.field.isin(fields) & wells.lift_type.isin(lifts)]
d = daily[daily.well_id.isin(sel_wells.well_id) & daily.prod_date.between(start, end)]
ev = events[events.well_id.isin(sel_wells.well_id) & events.start_date.between(start, end)]

if d.empty:
    st.warning("No data for these filters. Widen the selection in the sidebar.")
    st.stop()

# ---------- header + KPI tiles ----------
st.title("🛢️ Well Operations Dashboard")
st.caption(f"{len(sel_wells)} wells · {start:%d %b %Y} to {end:%d %b %Y}")

eff = d.oil_bbl.sum() / d.potential_bopd.sum() * 100
deferred = d.deferred_bbl.sum()
unplanned = ev[ev.category != "Planned"]
unlogged = ev[ev.cause.str.startswith("Unexplained")].deferred_bbl.sum() / max(ev.deferred_bbl.sum(), 1) * 100
k1, k2, k3, k4 = st.columns(4)
k1.metric("Oil produced", f"{d.oil_bbl.sum() / 1e6:.2f} M bbl")
k2.metric("Production efficiency", f"{eff:.1f}%", help="Actual oil ÷ potential (well online 24 h at tested rate)")
k3.metric("Oil deferred", f"{deferred / 1e3:,.0f} K bbl", f"≈ ${deferred * OIL_PRICE / 1e6:.1f}M", delta_color="off")
k4.metric("Lost oil with no logged reason", f"{unlogged:.0f}%", help="Downtime found in production data but missing from the operator log")

tab1, tab2, tab3 = st.tabs(["📈 Overview", "🏭 Wells", "🔍 Well drill-down"])

# ---------- tab 1: overview ----------
with tab1:
    m = (d.set_index("prod_date").resample("MS")[["oil_bbl", "potential_bopd"]].sum().reset_index())
    fig = go.Figure()
    fig.add_scatter(x=m.prod_date, y=m.potential_bopd, name="Potential", line=dict(color=GRAY, dash="dash", width=2))
    fig.add_scatter(x=m.prod_date, y=m.oil_bbl, name="Actual", line=dict(color=BLUE, width=2.5),
                    fill="tonexty", fillcolor="rgba(208,59,59,0.12)")
    fig.update_layout(title="Monthly oil: actual vs potential (shaded gap = deferred oil)",
                      yaxis_title="bbl / month", height=360, hovermode="x unified",
                      legend=dict(orientation="h", y=1.12, x=1, xanchor="right"), margin=dict(t=70))
    st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns([3, 2])
    by_cause = ev.groupby("cause", as_index=False).deferred_bbl.sum().sort_values("deferred_bbl")
    by_cause["share"] = by_cause.deferred_bbl / by_cause.deferred_bbl.sum() * 100
    fig2 = px.bar(by_cause, x="deferred_bbl", y="cause", orientation="h", color="cause",
                  color_discrete_map=CAUSE_COLORS, text=by_cause.share.map("{:.0f}%".format),
                  title="Where the lost oil went", labels={"deferred_bbl": "bbl deferred", "cause": ""})
    fig2.update_traces(textposition="outside", cliponaxis=False)
    fig2.update_layout(showlegend=False, height=340)
    c1.plotly_chart(fig2, width="stretch")

    by_lift = (ev[ev.category != "Planned"].merge(wells[["well_id", "lift_type"]], on="well_id")
               .groupby("lift_type").agg(events=("well_id", "size"), bbl=("deferred_bbl", "sum")).reset_index())
    n_wells = sel_wells.groupby("lift_type").size().rename("wells").reset_index()
    by_lift = by_lift.merge(n_wells, on="lift_type")
    by_lift["events per well"] = (by_lift.events / by_lift.wells).round(1)
    fig3 = px.bar(by_lift, x="lift_type", y="events per well", text="events per well",
                  title="Unplanned events per well, by lift type", labels={"lift_type": ""},
                  color_discrete_sequence=[BLUE])
    fig3.update_traces(textposition="outside", cliponaxis=False)
    fig3.update_layout(height=340)
    c2.plotly_chart(fig3, width="stretch")

# ---------- tab 2: wells ----------
with tab2:
    per = (d.groupby("well_id").agg(oil_bbl=("oil_bbl", "sum"), potential=("potential_bopd", "sum"),
                                    deferred_bbl=("deferred_bbl", "sum")).reset_index())
    per["efficiency_%"] = (per.oil_bbl / per.potential * 100).round(1)
    per = per.merge(unplanned.groupby("well_id").size().rename("unplanned_events").reset_index(), how="left")
    per = per.merge(sel_wells[["well_id", "field", "lift_type", "recent_actual_vs_forecast_pct", "status"]])
    per["unplanned_events"] = per.unplanned_events.fillna(0).astype(int)
    per = per.sort_values("deferred_bbl", ascending=False)[
        ["well_id", "field", "lift_type", "oil_bbl", "deferred_bbl", "efficiency_%", "unplanned_events",
         "recent_actual_vs_forecast_pct", "status"]]

    below = per[per.status.str.startswith("Below", na=False)]
    above = per[per.status.str.startswith("Above", na=False)]
    if len(below):
        st.error(f"**Investigate: {len(below)} wells producing well below their decline forecast** "
                 "(last 3 months): " + ", ".join(f"{r.well_id} ({r.recent_actual_vs_forecast_pct:+.0f}%)"
                                                 for r in below.itertuples()))
    if len(above):
        st.success(f"**{len(above)} wells above forecast** (e.g. after treatment), so update their forecasts: "
                   + ", ".join(f"{r.well_id} ({r.recent_actual_vs_forecast_pct:+.0f}%)" for r in above.itertuples()))
    st.dataframe(
        per, hide_index=True, width="stretch", height=520,
        column_config={
            "well_id": "Well", "field": "Field", "lift_type": "Lift",
            "oil_bbl": st.column_config.NumberColumn("Oil (bbl)", format="%,.0f"),
            "deferred_bbl": st.column_config.ProgressColumn("Deferred (bbl)", format="%,.0f",
                                                            min_value=0, max_value=float(per.deferred_bbl.max())),
            "efficiency_%": st.column_config.NumberColumn("Efficiency %", format="%.1f"),
            "unplanned_events": "Unplanned events",
            "recent_actual_vs_forecast_pct": st.column_config.NumberColumn("vs forecast %", format="%+.0f"),
            "status": "Decline status",
        })
    st.download_button("⬇️ Download this table (CSV)", per.to_csv(index=False), "well_summary.csv", "text/csv")

# ---------- tab 3: drill-down ----------
with tab3:
    w = st.selectbox("Choose a well", per.well_id.tolist(), index=0,
                     help="Sorted by oil deferred: the first well is the biggest problem")
    info = wells.set_index("well_id").loc[w]
    wd = d[d.well_id == w].sort_values("prod_date")
    a, b, c, e = st.columns(4)
    a.metric("Field / lift", f"{info.field} · {info.lift_type}")
    b.metric("Efficiency", f"{wd.oil_bbl.sum() / wd.potential_bopd.sum() * 100:.1f}%")
    c.metric("Oil deferred", f"{wd.deferred_bbl.sum():,.0f} bbl")
    e.metric("Decline status", str(info.status), f"{info.recent_actual_vs_forecast_pct:+.0f}% vs forecast",
             delta_color="normal")

    fig4 = go.Figure()
    fig4.add_scatter(x=wd.prod_date, y=wd.potential_bopd, name="Potential (well test)",
                     line=dict(color=GRAY, dash="dash", shape="hv"))
    fig4.add_scatter(x=wd.prod_date, y=wd.oil_bbl, name="Daily oil", line=dict(color=BLUE, width=1.5))
    wev = ev[ev.well_id == w]
    for r in wev.itertuples():
        fig4.add_vrect(x0=r.start_date, x1=r.end_date + pd.Timedelta(days=1),
                       fillcolor=CAUSE_COLORS.get(r.cause, GRAY), opacity=0.18, line_width=0)
    fig4.update_layout(title=f"{w}: daily oil vs potential (shaded = downtime events, coloured by cause)",
                       yaxis_title="bbl/day", height=380, hovermode="x unified",
                       legend=dict(orientation="h", y=1.12, x=1, xanchor="right"), margin=dict(t=70))
    st.plotly_chart(fig4, width="stretch")
    st.markdown(" · ".join(f"<span style='color:{c}'>■</span> {k}" for k, c in CAUSE_COLORS.items()),
                unsafe_allow_html=True)

    st.subheader("Downtime events")
    st.dataframe(wev.sort_values("start_date", ascending=False)[
        ["start_date", "end_date", "days_affected", "hours_lost", "deferred_bbl", "cause", "category"]],
        hide_index=True, width="stretch",
        column_config={"start_date": st.column_config.DateColumn("Start"),
                       "end_date": st.column_config.DateColumn("End"),
                       "days_affected": "Days", "hours_lost": "Hours lost",
                       "deferred_bbl": st.column_config.NumberColumn("Deferred bbl", format="%,.0f"),
                       "cause": "Cause", "category": "Category"})
