"""A tiny fake Google Health export, so the tests never read real health data.

The fake person sleeps in Taiwan (+08:00) on the night ending 2026-07-28 and
in Los Angeles (-07:00) on the night ending 2026-09-25.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from recovery import build
from recovery.simulator import SCORE_HEADER, SLEEP_HEADER

def sleep(sleep_id, offset, start, end, asleep, algorithm="sleep_session_v2"):
    return (
        f"{sleep_id},STAGES,{asleep + 30},0,5,{asleep},30,0,0,{offset},{start},{offset},{end},"
        f"DERIVED,{algorithm},{end},{end}"
    )


SLEEPS = [
    # Taiwan night, 00:30 to 07:30 local, recorded by both algorithms.
    sleep(1, "+08:00", "2026-07-27T16:30:00Z", "2026-07-27T23:30:00Z", 390),
    sleep(2, "+08:00", "2026-07-27T16:31:00Z", "2026-07-27T23:40:00Z", 400, "sleep_session_v1"),
    # Afternoon nap the same day, 14:00 to 14:40 local.
    sleep(3, "+08:00", "2026-07-28T06:00:00Z", "2026-07-28T06:40:00Z", 35),
    # Los Angeles night, 01:00 to 08:00 local.
    sleep(4, "-07:00", "2026-09-25T08:00:00Z", "2026-09-25T15:00:00Z", 380),
]

SCORES = [
    "1,11,DERIVED,+08:00,2026-07-27T23:30:00Z,81.5,-2,-2,-2,390,70,20.0,52,480,1,20,0.1,0.8,"
    "2026-07-27T23:31:00Z,2026-07-27T23:31:00Z",
    "4,44,DERIVED,-07:00,2026-09-25T15:00:00Z,-2,-2,-2,-2,380,60,18.0,50,480,1,20,0.1,0.8,"
    "2026-09-25T15:01:00Z,2026-09-25T15:01:00Z",
]

STEPS = [
    "timestamp,steps,data source",
    # Partial days at both ends of the export, which the build leaves out.
    "2026-07-27T02:00:00Z,50,Fitbit Air",
    "2026-09-26T20:00:00Z,50,Fitbit Air",
    # 2026-07-28 local in Taiwan: the watch saw more than the phone.
    "2026-07-28T01:00:00Z,3000,Fitbit Air",
    "2026-07-28T02:00:00Z,2000,Fitbit Air",
    "2026-07-28T01:00:05Z,4000,Phone Health Kit",
    # 17:00 UTC is 01:00 the next morning in Taiwan, so this is 2026-07-29.
    "2026-07-28T17:00:00Z,700,Fitbit Air",
]

RESTING_HR = [
    "timestamp,beats per minute,data source",
    # Fitbit's daily rows are date labels at midnight UTC.
    "2026-07-28T00:00:00Z,52.0,Google Health App",
    "2026-07-28T03:00:00Z,60.0,Apple Health Health Kit",
    "2026-09-25T00:00:00Z,50.0,Google Health App",
]

HRV = [
    "timestamp,average heart rate variability milliseconds,non rem heart rate beats per minute,"
    "entropy,deep sleep root mean square of successive differences milliseconds,data source",
    "2026-07-28T00:00:00Z,120.0,45.0,3.4,118.0,Google Health App",
    "2026-09-25T00:00:00Z,0.0,0.0,0.0,0.0,Google Health App",
]

AZM = [
    "timestamp,heart rate zone,total minutes,data source",
    "2026-07-28T10:00:00Z,FAT_BURN,1,Fitbit Air",
    "2026-07-28T10:01:00Z,CARDIO,2,Fitbit Air",
]

READINESS = [
    "timestamp,score,type,readiness level,sleep readiness,heart rate variability readiness,"
    "resting heart rate readiness,data source",
    "2026-07-28,64,MEDIUM,TYPE_UNSPECIFIED,HIGH,MEDIUM,HIGH,Google Health App",
]

CALENDAR = [
    "start_date,end_date,period",
    "2026-06-01,2026-09-20,summer",
    "2026-09-21,2026-12-11,term",
    "2026-09-24,2026-09-26,midterms",
]


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture
def export(tmp_path: Path) -> Path:
    root = tmp_path / "Google Health"
    health = root / "Health Fitness Data_GoogleData"
    physical = root / "Physical Activity_GoogleData"
    _write(health / "UserSleeps_2026-05-25.csv", [SLEEP_HEADER, *SLEEPS])
    _write(health / "UserSleepScores_2026-05-25.csv", [SCORE_HEADER, *SCORES])
    _write(physical / "Steps" / "steps_2026-07-01.csv", STEPS)
    _write(physical / "Daily Resting Heart Rate" / "daily_resting_heart_rate.csv", RESTING_HR)
    _write(physical / "Daily Heart Rate Variability" / "daily_heart_rate_variability.csv", HRV)
    _write(physical / "Active Zone Minutes" / "active_zone_minutes_2026-07-01.csv", AZM)
    _write(physical / "Daily Readiness" / "daily_readiness.csv", READINESS)
    return root


@pytest.fixture
def con(export: Path, tmp_path: Path):
    calendar = tmp_path / "calendar.csv"
    _write(calendar, CALENDAR)
    connection = build(export, tmp_path / "test.duckdb", calendar)
    yield connection
    connection.close()


@pytest.fixture
def day(con):
    """Return one row of the daily table as a dict."""

    def get(date: str) -> dict:
        cursor = con.execute("SELECT * FROM daily WHERE date = ?", [date])
        columns = [d[0] for d in cursor.description]
        row = cursor.fetchone()
        assert row is not None, f"no daily row for {date}"
        return dict(zip(columns, row))

    return get
