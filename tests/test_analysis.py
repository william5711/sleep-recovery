from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from recovery.analysis import MEASURES, exam_changes, exam_summary, mean_difference, night_hour, travel_days


def test_night_hour_keeps_late_nights_after_midnight():
    assert night_hour(datetime(2026, 7, 27, 23, 0)) == 23
    assert night_hour(datetime(2026, 7, 28, 1, 30)) == 25.5
    assert np.isnan(night_hour(pd.NaT))


def test_mean_difference_finds_a_known_gap():
    rng = np.random.default_rng(1)
    values = np.concatenate([rng.normal(8, 1, 100), rng.normal(7, 1, 100)])
    in_a = np.arange(200) < 100
    result = mean_difference(values, in_a, ~in_a, n_boot=2000)
    assert result.low < 1 < result.high
    assert result.low > 0
    assert (result.days_a, result.days_b) == (100, 100)


def test_mean_difference_skips_missing_days():
    values = [1.0, np.nan, 3.0, 5.0]
    result = mean_difference(values, [True, True, False, False], [False, False, True, True], n_boot=200)
    assert result.estimate == pytest.approx(1 - 4)
    assert result.days_a == 1


def test_mean_difference_is_nan_when_a_group_is_empty():
    result = mean_difference([1.0, 2.0], [True, True], [False, False], n_boot=100)
    assert np.isnan(result.estimate)


def test_blocks_widen_the_interval_for_runs_of_similar_days():
    # A slow random walk: neighbouring days are close, so the honest interval
    # is wider than the one that treats every day as independent.
    rng = np.random.default_rng(2)
    values = np.cumsum(rng.normal(0, 1, 300))
    first_half = np.arange(300) < 150
    naive = mean_difference(values, first_half, ~first_half, block=1, n_boot=1000)
    blocked = mean_difference(values, first_half, ~first_half, block=14, n_boot=1000)
    assert blocked.high - blocked.low > naive.high - naive.low


def test_travel_days_finds_flights_but_not_unknown_days():
    daily = pd.DataFrame({
        "date": pd.date_range("2026-06-10", periods=5),
        "utc_offset_min": [None, -420, -420, 480, 480],
        "location": ["unknown", "US", "US", "Taiwan", "Taiwan"],
    })
    trips = travel_days(daily)
    assert len(trips) == 1
    assert trips.loc[0, "date"] == pd.Timestamp("2026-06-13")
    assert (trips.loc[0, "from"], trips.loc[0, "to"], trips.loc[0, "shift_hours"]) == ("US", "Taiwan", 15)


def exam_daily(exams, days=120):
    """Flat measures, with resting HR 5 bpm higher on the night before each exam."""
    dates = pd.date_range("2026-03-01", periods=days)
    daily = pd.DataFrame({"date": dates, "period": None, "location": "US", "utc_offset_min": -420,
                          "heart_device": "fitbit"})
    for column in MEASURES:
        daily[column] = 10.0
    daily.loc[daily["date"].isin(pd.to_datetime(exams)), "period"] = "midterms"
    daily.loc[daily["period"] == "midterms", "resting_hr"] = 15.0
    return daily


def test_exam_changes_measure_against_each_exams_own_baseline():
    changes = exam_changes(exam_daily(["2026-04-01", "2026-05-15"]))
    night_before = changes[changes["offset"] == 0]
    assert list(night_before["resting_hr"]) == [5.0, 5.0]
    assert list(night_before["steps"]) == [0.0, 0.0]


def test_exam_baseline_ignores_trips_other_exams_and_other_devices():
    daily = exam_daily(["2026-04-01", "2026-03-24"])
    daily.loc[daily["date"].between("2026-03-19", "2026-03-20"), "period"] = "weekend trip"
    daily.loc[daily["date"].between("2026-03-19", "2026-03-20"), "resting_hr"] = 99.0
    daily.loc[daily["date"] < "2026-03-21", "heart_device"] = "apple_watch"
    daily.loc[daily["date"] < "2026-03-21", "resting_hr"] = 50.0
    changes = exam_changes(daily)
    april = changes[(changes["exam"] == "2026-04-01") & (changes["offset"] == 0)]
    # The baseline is the 7 ordinary days up to Mar 29: the Mar 24 exam, the
    # trip and the Apple Watch days are skipped, which leaves Mar 22-29 at 10.
    assert april["resting_hr"].iloc[0] == 5.0


def test_exam_summary_groups_nearby_exams():
    changes = exam_changes(exam_daily(["2026-04-01", "2026-04-03", "2026-05-20"]))
    table = exam_summary(changes, n_boot=200)
    assert table.loc["Resting HR (bpm)", "exams"] == 3
    assert table.loc["Resting HR (bpm)", "exam periods"] == 2
    assert table.loc["Resting HR (bpm)", "change"] == 5.0


def test_exam_baseline_reaches_back_past_a_trip():
    daily = exam_daily(["2026-04-20"])
    daily.loc[daily["date"].between("2026-04-08", "2026-04-15"), "period"] = "weekend trip"
    daily.loc[daily["date"].between("2026-04-08", "2026-04-15"), "resting_hr"] = 99.0
    changes = exam_changes(daily)
    assert changes.loc[changes["offset"] == 0, "resting_hr"].iloc[0] == 5.0
