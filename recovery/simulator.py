"""Simulate a Google Health export, so the project runs without anyone's data.

It copies the file layout and the quirks of a real export: most nights appear
twice (sleep_session_v1 and v2), the phone and the watch both count steps, the
daily Fitbit rows are dated at midnight UTC, and the time zone moves from the
US to Taiwan and back. The numbers are random draws around round, invented
values.

    python -m recovery.simulator sample
    python -m recovery --export "sample/Google Health" --db data/demo.duckdb --calendar calendar.example.csv
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

SLEEP_HEADER = (
    "sleep_id,sleep_type,minutes_in_sleep_period,minutes_after_wake_up,minutes_to_fall_asleep,"
    "minutes_asleep,minutes_awake,minutes_longest_awakening,minutes_to_persistent_sleep,"
    "start_utc_offset,sleep_start,end_utc_offset,sleep_end,data_source,algorithm_version,"
    "sleep_created,sleep_last_updated"
)
SCORE_HEADER = (
    "sleep_id,sleep_score_id,data_source,score_utc_offset,score_time,overall_score,duration_score,"
    "composition_score,revitalization_score,sleep_time_minutes,deep_sleep_minutes,rem_sleep_percent,"
    "resting_heart_rate,sleep_goal_minutes,waso_count_long_wakes,waso_count_all_wake_time,"
    "restlessness_normalized,hr_below_resting_hr,sleep_score_created,sleep_score_last_updated"
)

START, END = date(2026, 6, 3), date(2026, 11, 2)
TAIWAN = (date(2026, 6, 14), date(2026, 9, 22))


def _offset(day: date) -> int:
    """UTC offset in minutes for a simulated summer in Taiwan and a term in Los Angeles."""
    if TAIWAN[0] <= day <= TAIWAN[1]:
        return 480
    return -480 if day >= date(2026, 11, 1) else -420


def _offset_text(minutes: int) -> str:
    sign = "-" if minutes < 0 else "+"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def _utc(local: datetime, offset: int) -> str:
    return (local - timedelta(minutes=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write(path: Path, header: str, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([header, *rows]) + "\n")


def simulate_export(out: Path, seed: int = 0) -> Path:
    """Write the fake export under `out` and return its 'Google Health' folder."""
    rng = np.random.default_rng(seed)
    root = Path(out) / "Google Health"
    health = root / "Health Fitness Data_GoogleData"
    physical = root / "Physical Activity_GoogleData"

    sleeps, scores, steps, active, resting, hrv_rows, readiness = [], [], [], [], [], [], []
    hrv = 120.0
    sleep_id = 1000
    days = (END - START).days + 1
    for i in range(days):
        day = START + timedelta(days=i)
        offset = _offset(day)
        in_taiwan = offset == 480
        tz = _offset_text(offset)

        # The night that ends this morning.
        bedtime = 0.5 if in_taiwan else 1.5
        bedtime += 0.6 if day.weekday() >= 5 else 0
        start = datetime.combine(day, datetime.min.time()) + timedelta(hours=rng.normal(bedtime, 0.7))
        asleep = int(np.clip(rng.normal(420, 60), 200, 640))
        end = start + timedelta(minutes=asleep + 40)
        for algorithm, shift, trim in [("sleep_session_v2", 0, 0), ("sleep_session_v1", 2, 25)]:
            sleep_id += 1
            s, e = start + timedelta(minutes=shift), end + timedelta(minutes=shift // 2)
            sleeps.append(
                f"{sleep_id},STAGES,{asleep + 40},0,{rng.integers(0, 15)},{asleep - trim},40,0,0,"
                f"{tz},{_utc(s, offset)},{tz},{_utc(e, offset)},DERIVED,{algorithm},"
                f"{_utc(e, offset)},{_utc(e, offset)}"
            )
            score = np.clip(rng.normal(70 + asleep / 30, 4), 40, 98)
            scores.append(
                f"{sleep_id},{sleep_id * 7},DERIVED,{tz},{_utc(e, offset)},{score:.2f},-2,-2,-2,"
                f"{asleep},{int(asleep * rng.uniform(0.12, 0.22))},{rng.uniform(15, 28):.2f},50,480,"
                f"2,25,{rng.uniform(0.05, 0.15):.3f},0.8,{_utc(e, offset)},{_utc(e, offset)}"
            )
        if rng.random() < 0.15:
            sleep_id += 1
            nap = datetime.combine(day, datetime.min.time()) + timedelta(hours=14)
            sleeps.append(
                f"{sleep_id},CLASSIC,45,0,5,35,10,0,0,{tz},{_utc(nap, offset)},{tz},"
                f"{_utc(nap + timedelta(minutes=45), offset)},DERIVED,sleep_session_v2,"
                f"{_utc(nap, offset)},{_utc(nap, offset)}"
            )

        # Daily Fitbit numbers: HRV wanders slowly and a short night pulls it down.
        hrv = 0.8 * hrv + 0.2 * 122 + rng.normal(0, 4)
        today_hrv = hrv + (asleep - 420) / 20 + rng.normal(0, 12)
        rhr = rng.normal(51 if in_taiwan else 49.5, 1.5)
        label = f"{day}T00:00:00Z"
        resting.append(f"{label},{rhr:.2f},Google Health App")
        hrv_rows.append(f"{label},{today_hrv:.2f},45.0,3.4,{today_hrv * 0.95:.2f},Google Health App")
        ready = int(np.clip(60 + (today_hrv - 122) * 0.8 + (asleep - 420) / 6 + rng.normal(0, 10), 1, 99))
        readiness.append(f"{day},{ready},MEDIUM,TYPE_UNSPECIFIED,HIGH,MEDIUM,HIGH,Google Health App")

        # Steps through the waking day, counted by the watch and, less fully, the phone.
        total = max(500, rng.normal(10000 if in_taiwan else 6500, 2500))
        for hour, share in zip(range(9, 23), rng.dirichlet(np.ones(14))):
            when = datetime.combine(day, datetime.min.time()) + timedelta(hours=hour)
            steps.append(f"{_utc(when, offset)},{int(total * share)},Fitbit Air")
            if rng.random() < 0.7:
                steps.append(f"{_utc(when + timedelta(seconds=5), offset)},{int(total * share * 0.7)},Phone Health Kit")
        for minute in range(int(rng.integers(0, 30))):
            when = datetime.combine(day, datetime.min.time()) + timedelta(hours=18, minutes=minute)
            active.append(f"{_utc(when, offset)},FAT_BURN,1,Fitbit Air")

    _write(health / "UserSleeps_2026-06-03.csv", SLEEP_HEADER, sleeps)
    _write(health / "UserSleepScores_2026-06-03.csv", SCORE_HEADER, scores)
    _write(physical / "Steps" / "steps_2026-06-01.csv", "timestamp,steps,data source", steps)
    _write(physical / "Active Zone Minutes" / "active_zone_minutes_2026-06-01.csv",
           "timestamp,heart rate zone,total minutes,data source", active)
    _write(physical / "Daily Resting Heart Rate" / "daily_resting_heart_rate.csv",
           "timestamp,beats per minute,data source", resting)
    _write(physical / "Daily Heart Rate Variability" / "daily_heart_rate_variability.csv",
           "timestamp,average heart rate variability milliseconds,non rem heart rate beats per minute,"
           "entropy,deep sleep root mean square of successive differences milliseconds,data source",
           hrv_rows)
    _write(physical / "Daily Readiness" / "daily_readiness.csv",
           "timestamp,score,type,readiness level,sleep readiness,heart rate variability readiness,"
           "resting heart rate readiness,data source", readiness)
    return root


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "sample")
    print(f"Wrote a simulated export to {simulate_export(out)}")
