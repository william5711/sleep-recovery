from datetime import datetime
from pathlib import Path

import pytest

from recovery import build


def test_one_row_per_day_with_gaps_filled(con):
    rows, dates, first, last = con.execute(
        "SELECT count(*), count(DISTINCT date), min(date), max(date) FROM daily"
    ).fetchone()
    assert rows == dates
    assert (str(first), str(last)) == ("2026-07-28", "2026-09-25")
    assert rows == (last - first).days + 1


def test_partial_first_and_last_days_are_left_out(con):
    dates = {str(d) for (d,) in con.execute("SELECT date FROM daily").fetchall()}
    assert "2026-07-27" not in dates
    assert "2026-09-26" not in dates


def test_sleep_times_are_local(day):
    taiwan = day("2026-07-28")
    assert taiwan["bedtime"] == datetime(2026, 7, 28, 0, 30)
    assert taiwan["wake_time"] == datetime(2026, 7, 28, 7, 30)

    los_angeles = day("2026-09-25")
    assert los_angeles["bedtime"] == datetime(2026, 9, 25, 1, 0)


def test_location_follows_the_utc_offset(day):
    assert day("2026-07-28")["location"] == "Taiwan"
    assert day("2026-09-25")["location"] == "US"


def test_duplicate_algorithm_records_count_once(day):
    taiwan = day("2026-07-28")
    assert taiwan["sleep_algorithm"] == "sleep_session_v2"
    assert taiwan["main_sleep_minutes"] == 390
    assert taiwan["nap_count"] == 1
    assert taiwan["total_sleep_minutes"] == 390 + 35


def test_overlap_is_checked_against_every_earlier_record(con):
    # Comparing each record only with the one before it would start a new
    # sleep at v1's second piece (20:10 is after the first piece ends at 20:00),
    # though the v2 record still runs to 23:30.
    merged = con.execute(
        "SELECT sleep_id FROM sleep_episodes WHERE start_utc < '2026-07-28' ORDER BY start_utc"
    ).fetchall()
    assert merged == [("1",)]


def test_missing_sleep_score_is_null(day):
    assert day("2026-07-28")["sleep_score"] == pytest.approx(81.5)
    assert day("2026-09-25")["sleep_score"] is None


def test_steps_use_one_source_per_day(day):
    taiwan = day("2026-07-28")
    assert taiwan["steps"] == 5000
    assert taiwan["steps_source"] == "Fitbit Air"


def test_steps_after_local_midnight_belong_to_the_next_day(day):
    assert day("2026-07-29")["steps"] == 700


def test_fitbit_daily_rows_keep_their_date_and_win_over_apple(day):
    taiwan = day("2026-07-28")
    assert taiwan["resting_hr"] == 52.0
    assert taiwan["heart_device"] == "fitbit"


def test_zero_hrv_is_treated_as_missing(day):
    assert day("2026-09-25")["hrv_ms"] is None


def test_active_minutes_and_readiness(day):
    taiwan = day("2026-07-28")
    assert taiwan["active_zone_minutes"] == 3
    assert taiwan["readiness_score"] == 64


def test_narrowest_calendar_period_wins(day):
    assert day("2026-07-28")["period"] == "summer"
    assert day("2026-09-25")["period"] == "midterms"


def test_no_calendar_leaves_period_empty(export, tmp_path):
    con = build(export, tmp_path / "plain.duckdb", tmp_path / "missing.csv")
    assert con.execute("SELECT count(period) FROM daily").fetchone() == (0,)


def test_rejects_a_folder_that_is_not_an_export(tmp_path):
    with pytest.raises(FileNotFoundError):
        build(Path(tmp_path), tmp_path / "x.duckdb")


def test_quality_counts_what_the_cleaning_fixed(con):
    from recovery.build import quality

    q = quality(con)
    assert (q["sleep_records"], q["sleeps_after_merge"]) == (5, 3)
    assert q["time_zones"] == 2
    assert q["step_sources"] == 2
    assert q["days_steps_not_from_watch"] == 0
    assert q["partial_days_dropped"] == 2
