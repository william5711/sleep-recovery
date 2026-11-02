"""Helpers for the analysis notebook."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import duckdb
import numpy as np
import pandas as pd

from recovery.build import DEFAULT_DB


def load_daily(db: Path = DEFAULT_DB) -> pd.DataFrame:
    """Read the daily table, with bedtime and wake time as hours of the night."""
    with duckdb.connect(str(db), read_only=True) as con:
        daily = con.table("daily").df()
    daily["date"] = pd.to_datetime(daily["date"])
    daily["bedtime_hour"] = daily["bedtime"].map(night_hour)
    daily["wake_hour"] = daily["wake_time"].map(clock_hour)
    daily["sleep_hours"] = daily["main_sleep_minutes"] / 60
    return daily


def clock_hour(ts) -> float:
    """07:30 -> 7.5"""
    if pd.isna(ts):
        return np.nan
    return ts.hour + ts.minute / 60


def night_hour(ts) -> float:
    """Bedtime on a scale that doesn't break at midnight: 23:00 -> 23, 01:30 -> 25.5.

    Times before noon count as after midnight, so a 1am bedtime averages with
    an 11pm one to midnight instead of to noon.
    """
    hour = clock_hour(ts)
    if np.isnan(hour):
        return hour
    return hour + 24 if hour < 12 else hour


class Difference(NamedTuple):
    estimate: float
    low: float
    high: float
    days_a: int
    days_b: int


def mean_difference(
    values,
    in_a,
    in_b,
    block: int = 7,
    n_boot: int = 5000,
    seed: int = 0,
) -> Difference:
    """Mean of group a minus mean of group b, with a 95% block bootstrap interval.

    `values`, `in_a` and `in_b` line up with consecutive calendar days. Days
    next to each other are alike, so treating each day as independent would
    make the interval too narrow. Instead, each group's days are taken in date
    order and resampled in runs of `block` (a circular block bootstrap within
    each group), which keeps that day-to-day dependence and each group's size.
    """
    values = np.asarray(values, dtype=float)
    present = ~np.isnan(values)
    a = values[np.asarray(in_a, dtype=bool) & present]
    b = values[np.asarray(in_b, dtype=bool) & present]
    if len(a) == 0 or len(b) == 0:
        return Difference(np.nan, np.nan, np.nan, len(a), len(b))

    rng = np.random.default_rng(seed)
    resampled = _block_means(a, block, n_boot, rng) - _block_means(b, block, n_boot, rng)
    low, high = np.percentile(resampled, [2.5, 97.5])
    return Difference(a.mean() - b.mean(), low, high, len(a), len(b))


def mean_interval(values, block: int = 7, n_boot: int = 5000, seed: int = 0) -> tuple[float, float, float]:
    """Mean of consecutive daily values, with a 95% block bootstrap interval."""
    values = np.asarray(values, dtype=float)
    values = values[~np.isnan(values)]
    means = _block_means(values, block, n_boot, np.random.default_rng(seed))
    low, high = np.percentile(means, [2.5, 97.5])
    return values.mean(), low, high


def mark_jet_lag(daily: pd.DataFrame, days: int = 7) -> pd.Series:
    """True for the first `days` days after each long flight, arrival day included."""
    jet_lag = pd.Series(False, index=daily.index)
    for arrival in travel_days(daily)["date"]:
        jet_lag |= daily["date"].between(arrival, arrival + pd.Timedelta(days=days - 1))
    return jet_lag


MEASURES = {
    "sleep_hours": "Sleep (hours)",
    "bedtime_hour": "Bedtime (hour, 25 = 1am)",
    "wake_hour": "Wake time (hour)",
    "sleep_score": "Sleep score",
    "resting_hr": "Resting HR (bpm)",
    "hrv_ms": "HRV (ms)",
    "readiness_score": "Readiness",
    "steps": "Steps",
}


def study_days(daily: pd.DataFrame, jet_lag_days: int = 7) -> pd.DataFrame:
    """Fitbit-period days, with `jet_lag`, `trip`, `summer` and `term` columns.

    Summer is time in Taiwan and term is time in the US since the last flight
    back. Both leave out the first `jet_lag_days` after a long flight and any
    calendar period whose name ends in "trip".
    """
    daily = daily.copy()
    daily["jet_lag"] = mark_jet_lag(daily, jet_lag_days)
    daily["trip"] = daily["period"].fillna("").str.endswith("trip")
    fitbit_start = daily.loc[daily["heart_device"] == "fitbit", "date"].min()
    days = daily[daily["date"] >= fitbit_start].reset_index(drop=True)
    trips = travel_days(daily)
    back_for_term = trips.loc[trips["to"] == "US", "date"].max()
    home = ~days["jet_lag"] & ~days["trip"]
    days["summer"] = (days["location"] == "Taiwan") & home
    days["term"] = (days["location"] == "US") & (days["date"] >= back_for_term) & home
    return days


EXAMS = ("midterms", "finals")


def exam_changes(
    daily: pd.DataFrame,
    offsets=range(-7, 4),
    baseline_days: int = 7,
    gap: int = 3,
    search: int = 28,
) -> pd.DataFrame:
    """Each measure around each exam, as a change from that exam's own baseline.

    A day's row holds the night before it, so offset 0 is the night before the
    exam. The baseline is the `baseline_days` most recent ordinary days that
    end `gap` days before the exam, looking back at most `search` days. An
    ordinary day was measured by the same device and isn't another exam, a
    trip, or jet lag. Comparing each exam with its own recent past keeps the
    device change and the seasons out of the result. A measure needs at least
    4 baseline values.

    Returns one row per exam and offset, with a column of changes per measure.
    """
    daily = daily.sort_values("date").copy()
    daily["device"] = daily["heart_device"].ffill()
    exams = daily.loc[daily["period"].isin(EXAMS), "date"]
    quiet = ~daily["period"].isin(EXAMS) & ~daily["period"].fillna("").str.endswith("trip") & ~mark_jet_lag(daily)
    by_date = daily.set_index("date")
    quiet.index = by_date.index

    rows = []
    for exam in exams:
        device = by_date.at[exam, "device"]
        span = by_date.loc[exam - pd.Timedelta(days=search): exam - pd.Timedelta(days=gap)]
        span = span[(span["device"] == device) & quiet.loc[span.index]].tail(baseline_days)
        for offset in offsets:
            day = exam + pd.Timedelta(days=offset)
            if day not in by_date.index or by_date.at[day, "device"] != device:
                continue
            row = {"exam": exam, "offset": offset}
            for column in MEASURES:
                base = span[column].dropna()
                row[column] = by_date.at[day, column] - base.mean() if len(base) >= 4 else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def exam_summary(changes: pd.DataFrame, min_periods: int = 4, n_boot: int = 5000, seed: int = 0) -> pd.DataFrame:
    """Average change on the night before an exam, with a 95% interval.

    Exams within a week of each other share a stretch of days, so the
    bootstrap resamples whole exam periods rather than single exams. With
    fewer than `min_periods` exam periods there are too few to resample, and
    the interval is left blank.
    """
    night_before = changes[changes["offset"] == 0].sort_values("exam").reset_index(drop=True)
    period = (night_before["exam"].diff() > pd.Timedelta(days=7)).cumsum()
    rng = np.random.default_rng(seed)
    rows = []
    for column, name in MEASURES.items():
        values = night_before[column]
        have = values.notna()
        groups = [values[have & (period == p)].to_numpy() for p in period[have].unique()]
        if len(groups) < min_periods:
            rows.append({"measure": name, "change": values.mean(), "95% interval": "",
                         "exams": int(have.sum()), "exam periods": len(groups)})
            continue
        picks = rng.integers(0, len(groups), size=(n_boot, len(groups)))
        means = [np.concatenate([groups[i] for i in pick]).mean() for pick in picks]
        low, high = np.percentile(means, [2.5, 97.5])
        rows.append({
            "measure": name,
            "change": values.mean(),
            "95% interval": f"{low:.2f} to {high:.2f}",
            "exams": int(have.sum()),
            "exam periods": len(groups),
        })
    return pd.DataFrame(rows).set_index("measure")


def compare(days: pd.DataFrame, in_a, in_b, a_name: str, b_name: str) -> pd.DataFrame:
    """Each measure's mean in two groups of days, and the difference with its interval."""
    rows = []
    for column, name in MEASURES.items():
        d = mean_difference(days[column], in_a, in_b)
        rows.append({
            "measure": name,
            a_name: days.loc[in_a, column].mean(),
            b_name: days.loc[in_b, column].mean(),
            "difference": d.estimate,
            "95% interval": f"{d.low:.2f} to {d.high:.2f}",
            "excludes 0": "yes" if d.low > 0 or d.high < 0 else "",
            "days": f"{d.days_a} / {d.days_b}",
        })
    return pd.DataFrame(rows).set_index("measure")


def _block_means(values: np.ndarray, block: int, n_boot: int, rng: np.random.Generator) -> np.ndarray:
    """Means of `n_boot` circular block resamples of `values`."""
    n = len(values)
    block = min(block, n)
    n_blocks = -(-n // block)
    starts = rng.integers(0, n, size=(n_boot, n_blocks, 1))
    index = ((starts + np.arange(block)) % n).reshape(n_boot, -1)[:, :n]
    return values[index].mean(axis=1)


def travel_days(daily: pd.DataFrame, min_shift_hours: float = 3) -> pd.DataFrame:
    """Days where the time zone moved by at least `min_shift_hours`."""
    known = daily.loc[daily["location"] != "unknown", ["date", "utc_offset_min", "location"]]
    previous = known.shift()
    shift = (known["utc_offset_min"] - previous["utc_offset_min"]) / 60
    moved = shift.abs() >= min_shift_hours
    return pd.DataFrame({
        "date": known.loc[moved, "date"],
        "from": previous.loc[moved, "location"],
        "to": known.loc[moved, "location"],
        "shift_hours": shift[moved],
    }).reset_index(drop=True)
