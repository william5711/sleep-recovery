"""Predict the morning's HRV, and check whether the prediction beats simple guesses.

Two models, both ridge regression:

- The evening model only uses what's known before going to sleep: recent HRV
  and resting heart rate, yesterday's activity, and what kind of day it is.
- The morning model adds the night's sleep, to see whether sleep explains
  anything beyond recent history.

They're compared with two baselines: "same as yesterday" and "average of the
last 7 days". Every prediction is walk-forward: the model for a day is trained
only on earlier days, as it would be if used for real.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from recovery.analysis import mark_jet_lag, mean_interval

EVENING_FEATURES = [
    "last", "week_mean", "resting_hr_last", "steps_yesterday",
    "active_minutes_yesterday", "sleep_hours_last", "is_weekend", "location_us",
]
MORNING_FEATURES = EVENING_FEATURES + ["sleep_hours", "bedtime_hour", "deep_sleep_minutes"]
METHODS = {
    "yesterday": "Same as yesterday",
    "week_mean": "Average of last 7 days",
    "evening": "Evening model",
    "morning": "Morning model (adds the night's sleep)",
}


def add_features(daily: pd.DataFrame, target: str = "hrv_ms") -> pd.DataFrame:
    """Fitbit days with the features for predicting `target`, settled days only.

    `daily` must have one row per calendar day, so shifting by one row is
    shifting by one day.
    """
    frame = daily.sort_values("date").reset_index(drop=True).copy()
    frame["jet_lag"] = mark_jet_lag(frame)
    value = frame[target].where(frame["heart_device"] == "fitbit")

    # A missing day or two is bridged with the latest earlier value.
    frame["target"] = value
    frame["last"] = value.shift(1).ffill(limit=2)
    frame["week_mean"] = value.shift(1).rolling(7, min_periods=3).mean()
    frame["resting_hr_last"] = frame["resting_hr"].shift(1).ffill(limit=2)
    frame["steps_yesterday"] = frame["steps"].shift(1)
    frame["active_minutes_yesterday"] = frame["active_zone_minutes"].shift(1).fillna(0)
    frame["sleep_hours_last"] = frame["sleep_hours"].shift(1)
    frame["is_weekend"] = frame["is_weekend"].astype(float)
    frame["location_us"] = (frame["location"] == "US").astype(float)

    usable = frame["target"].notna() & frame["last"].notna() & frame["week_mean"].notna() & ~frame["jet_lag"]
    return frame[usable].reset_index(drop=True)


def _model():
    return make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        # The penalty is picked by cross-validation on the training days only.
        RidgeCV(alphas=np.logspace(-2, 3, 20)),
    )


def walk_forward(frame: pd.DataFrame, features: list[str], min_train: int = 42) -> pd.Series:
    """Predict each day from a model fit on all earlier days, after `min_train` of them."""
    predictions = pd.Series(np.nan, index=frame.index)
    # numpy 2.0 with Apple's Accelerate library raises false overflow warnings
    # inside matrix products. The results are finite and correct.
    with np.errstate(all="ignore"):
        for t in range(min_train, len(frame)):
            train = frame.iloc[:t]
            model = _model().fit(train[features], train["target"])
            predictions.iloc[t] = model.predict(frame.iloc[[t]][features])[0]
    return predictions


def evaluate(daily: pd.DataFrame, target: str = "hrv_ms", min_train: int = 42):
    """Return (predictions per day, summary table) for every method."""
    frame = add_features(daily, target)
    predictions = pd.DataFrame({
        "date": frame["date"],
        "actual": frame["target"],
        "yesterday": frame["last"],
        "week_mean": frame["week_mean"],
        "evening": walk_forward(frame, EVENING_FEATURES, min_train),
        "morning": walk_forward(frame, MORNING_FEATURES, min_train),
    }).iloc[min_train:].reset_index(drop=True)
    return predictions, summarize(predictions)


def summarize(predictions: pd.DataFrame) -> pd.DataFrame:
    """Mean absolute error per method, and how it compares with the 7-day average."""
    errors = {key: (predictions[key] - predictions["actual"]).abs() for key in METHODS}
    rows = []
    for key, name in METHODS.items():
        gap, low, high = mean_interval(errors[key] - errors["week_mean"])
        rows.append({
            "method": name,
            "mean absolute error": errors[key].mean(),
            "vs. 7-day average": gap,
            "95% interval": f"{low:.2f} to {high:.2f}",
        })
    table = pd.DataFrame(rows).set_index("method")
    table.attrs["days"] = len(predictions)
    return table
