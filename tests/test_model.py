import numpy as np
import pandas as pd

from recovery.model import MORNING_FEATURES, add_features, evaluate, walk_forward


def fake_daily(days=120, seed=0, sleep_effect=0.0):
    """Daily rows in the shape load_daily returns, with HRV that wanders slowly."""
    rng = np.random.default_rng(seed)
    sleep = rng.normal(7, 1, days)
    hrv = 120 + np.cumsum(rng.normal(0, 1, days)) + sleep_effect * (sleep - 7) + rng.normal(0, 3, days)
    dates = pd.date_range("2026-06-01", periods=days)
    return pd.DataFrame({
        "date": dates,
        "hrv_ms": hrv,
        "resting_hr": rng.normal(50, 1, days),
        "steps": rng.normal(9000, 2000, days),
        "active_zone_minutes": rng.integers(0, 40, days),
        "sleep_hours": sleep,
        "bedtime_hour": rng.normal(25, 0.5, days),
        "deep_sleep_minutes": rng.normal(80, 10, days),
        "is_weekend": dates.dayofweek >= 5,
        "location": "US",
        "utc_offset_min": -420,
        "heart_device": "fitbit",
    })


def test_features_only_look_backwards():
    frame = add_features(fake_daily())
    original = fake_daily().set_index("date")["hrv_ms"]
    row = frame.iloc[10]
    assert row["last"] == original[row["date"] - pd.Timedelta(days=1)]
    assert row["target"] == original[row["date"]]


def test_walk_forward_ignores_the_future():
    frame = add_features(fake_daily())
    before = walk_forward(frame, MORNING_FEATURES, min_train=30)
    changed = frame.copy()
    changed.loc[60:, "target"] += 1000
    after = walk_forward(changed, MORNING_FEATURES, min_train=30)
    pd.testing.assert_series_equal(before.iloc[:61], after.iloc[:61])


def test_morning_model_finds_a_real_sleep_effect():
    _, table = evaluate(fake_daily(days=160, sleep_effect=15), min_train=40)
    errors = table["mean absolute error"]
    assert errors["Morning model (adds the night's sleep)"] < errors["Evening model"]
    assert errors["Morning model (adds the night's sleep)"] < errors["Average of last 7 days"]


def test_apple_watch_days_are_not_targets():
    daily = fake_daily()
    daily.loc[:20, "heart_device"] = "apple_watch"
    frame = add_features(daily)
    assert frame["date"].min() > daily.loc[20, "date"]
