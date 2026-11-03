"""Dashboard. Run with: streamlit run app.py

It shows data/health.duckdb when that exists, and otherwise simulates an
export from recovery/simulator.py, so it can be shared without real data.
Set SIMULATED_ONLY=1 to never read the real database, for screenshots or
public hosting.
"""

from __future__ import annotations

import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from recovery import build
from recovery.analysis import compare, load_daily, study_days
from recovery.build import DEFAULT_DB, ROOT
from recovery.model import evaluate
from recovery.simulator import simulate_export

DEMO_DB = ROOT / "data" / "demo.duckdb"
BLUE, ORANGE, MUTED, BAND = "#2a78d6", "#eb6834", "#b5b4ae", "#efeee9"
TREND = {
    "sleep_hours": "Sleep (hours)", "bedtime_hour": "Bedtime", "resting_hr": "Resting HR (bpm)",
    "hrv_ms": "HRV (ms)", "readiness_score": "Readiness", "steps": "Steps",
}


@st.cache_data
def load(use_sample: bool) -> pd.DataFrame:
    if not use_sample:
        return load_daily(DEFAULT_DB)
    if not DEMO_DB.exists():
        export = simulate_export(ROOT / "data" / "sample")
        build(export, DEMO_DB, ROOT / "calendar.example.csv").close()
    return load_daily(DEMO_DB)


@st.cache_data
def model_results(daily: pd.DataFrame):
    return evaluate(daily, "hrv_ms")


def trend_chart(days: pd.DataFrame, column: str, name: str) -> alt.Chart:
    data = days[["date", column, "location"]].rename(columns={column: "value"})
    data["7-day average"] = data["value"].rolling(7, min_periods=4, center=True).mean()
    taiwan = data[data["location"] == "Taiwan"]
    band = alt.Chart(pd.DataFrame({"start": [taiwan["date"].min()], "end": [taiwan["date"].max()]})).mark_rect(
        color=BAND
    ).encode(x="start:T", x2="end:T")
    scale, axis = alt.Scale(zero=False), alt.Axis()
    if column == "bedtime_hour":
        # 9pm to 7am, shown as clock times. Flight days fall outside and are clipped.
        scale = alt.Scale(domain=[21, 31], clamp=True)
        axis = alt.Axis(values=list(range(22, 31, 2)), labelExpr="(datum.value % 24) + ':00'")
    base = alt.Chart(data).encode(x=alt.X("date:T", title=None))
    dots = base.mark_circle(size=40, color=MUTED).encode(
        y=alt.Y("value:Q", title=name, scale=scale, axis=axis),
        tooltip=[alt.Tooltip("date:T", format="%b %d"), alt.Tooltip("value:Q", title=name, format=".1f"), "location"],
    )
    line = base.mark_line(color=BLUE, strokeWidth=2).encode(y="7-day average:Q")
    layers = [dots, line] if taiwan.empty else [band, dots, line]
    return alt.layer(*layers).properties(height=320)


st.set_page_config(page_title="Sleep and Recovery", layout="wide")
st.title("Sleep and recovery: summer vs. term")

has_real = DEFAULT_DB.exists() and os.environ.get("SIMULATED_ONLY") != "1"
use_sample = st.toggle("Use simulated data", value=not has_real, disabled=not has_real)
st.caption(
    "Simulated data that copies the shape of a real export." if use_sample
    else "My own Google Health data. One person, so it describes me and nobody else."
)

daily = load(use_sample)
days = study_days(daily)
summer, term = days["summer"], days["term"]

left, middle, right, last = st.columns(4)
for column, (field, label, unit, decimals) in zip(
    [left, middle, right, last],
    [("sleep_hours", "Sleep in term", "h", 1), ("bedtime_hour", "Bedtime in term", "h", 1),
     ("resting_hr", "Resting HR in term", "bpm", 1), ("steps", "Steps in term", "", 0)],
):
    now, before = days.loc[term, field].mean(), days.loc[summer, field].mean()
    if field == "bedtime_hour":
        shown = f"{int(now) % 24}:{int(now % 1 * 60):02d}"
    else:
        shown = f"{now:,.{decimals}f} {unit}".strip()
    column.metric(label, shown, f"{now - before:+,.{decimals}f} {unit} vs. summer".strip(), delta_color="off")

st.subheader("Trends")
choice = st.segmented_control("Measure", list(TREND), format_func=TREND.get, default="sleep_hours")
st.altair_chart(trend_chart(days, choice or "sleep_hours", TREND[choice or "sleep_hours"]), use_container_width=True)
st.caption("Grey dots are days, the line is a 7-day average, and the shaded stretch is Taiwan.")

st.subheader("Comparisons")
st.caption("95% block bootstrap intervals. Days in the first week after a long flight are left out.")
first, second = st.tabs(["Summer vs. term", "Term weekends vs. weekdays"])
with first:
    st.dataframe(compare(days, term, summer, "term (US)", "summer (Taiwan)").round(2))
with second:
    weekend = days["is_weekend"].astype(bool)
    st.dataframe(compare(days, term & weekend, term & ~weekend, "weekends", "weekdays").round(2))

st.subheader("Can tomorrow's HRV be predicted?")
predictions, results = model_results(daily)
st.caption(
    f"Walk-forward over {results.attrs['days']} days: each day is predicted by a model trained only on earlier days. "
    "Negative 'vs. 7-day average' means a smaller error than that baseline."
)
st.dataframe(results.round(2))
shown = predictions.set_index("date").asfreq("D").reset_index()
long = shown.melt("date", ["actual", "week_mean", "evening"], var_name="series", value_name="HRV")
long["series"] = long["series"].map({"actual": "Actual", "week_mean": "Average of last 7 days", "evening": "Evening model"})
colors = alt.Scale(domain=["Actual", "Average of last 7 days", "Evening model"], range=[MUTED, ORANGE, BLUE])
chart = alt.Chart(long).encode(
    x=alt.X("date:T", title=None),
    y=alt.Y("HRV:Q", title="HRV (ms)", scale=alt.Scale(zero=False)),
    color=alt.Color("series:N", scale=colors, legend=alt.Legend(orient="top", title=None)),
    tooltip=[alt.Tooltip("date:T", format="%b %d"), "series", alt.Tooltip("HRV:Q", format=".1f")],
)
st.altair_chart(
    chart.transform_filter("datum.series == 'Actual'").mark_circle(size=30)
    + chart.transform_filter("datum.series != 'Actual'").mark_line(strokeWidth=2),
    use_container_width=True,
)
