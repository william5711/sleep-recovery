"""Turn a Google Health export into data/health.duckdb.

The raw export is only read, never copied. Run with:

    python -m recovery --export "~/Downloads/health data/Google Health"
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
DEFAULT_DB = ROOT / "data" / "health.duckdb"
DEFAULT_CALENDAR = ROOT / "calendar.csv"


def _quote(path: Path) -> str:
    """Make a path safe to put inside a single-quoted SQL string."""
    return str(path).replace("'", "''")


def _render(sql: str, export: Path) -> str:
    return sql.replace("{health}", _quote(export / "Health Fitness Data_GoogleData")).replace(
        "{physical}", _quote(export / "Physical Activity_GoogleData")
    )


def _load_calendar(con: duckdb.DuckDBPyConnection, calendar: Optional[Path]) -> None:
    con.execute(
        "CREATE OR REPLACE TABLE calendar (start_date DATE, end_date DATE, period VARCHAR)"
    )
    if calendar is not None and calendar.exists():
        con.execute(
            "INSERT INTO calendar SELECT start_date, end_date, period FROM read_csv(?)",
            [str(calendar)],
        )


def build(
    export: Path,
    db: Path = DEFAULT_DB,
    calendar: Optional[Path] = DEFAULT_CALENDAR,
) -> duckdb.DuckDBPyConnection:
    """Build every table and return an open connection to the database."""
    export = export.expanduser()
    if not (export / "Health Fitness Data_GoogleData").is_dir():
        raise FileNotFoundError(f"{export} doesn't look like a Google Health export folder")

    db.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db))
    _load_calendar(con, calendar)
    for script in sorted(SQL_DIR.glob("*.sql")):
        con.execute(_render(script.read_text(), export))
    return con


def quality(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Counts of what the cleaning found and fixed, for the build summary."""
    one = lambda sql: con.execute(sql).fetchone()[0]
    return {
        "sleep_records": one("SELECT count(*) FROM sleeps"),
        "sleeps_after_merge": one("SELECT count(*) FROM sleep_episodes"),
        "time_zones": one("SELECT count(DISTINCT utc_offset_min) FROM sleeps"),
        "step_sources": one("SELECT count(DISTINCT source) FROM steps"),
        "days_steps_not_from_watch": one(
            "SELECT count(*) FROM daily WHERE steps_source IS NOT NULL AND steps_source NOT IN ('Fitbit Air', 'Apple Health Health Kit')"
        ),
        "apple_watch_heart_days": one("SELECT count(*) FROM daily WHERE heart_device = 'apple_watch'"),
        "fitbit_heart_days": one("SELECT count(*) FROM daily WHERE heart_device = 'fitbit'"),
        "partial_days_dropped": one(
            "SELECT count(*) FROM (SELECT DISTINCT date FROM steps UNION SELECT date FROM nights UNION SELECT date FROM daily_heart) "
            "WHERE date NOT IN (SELECT date FROM daily)"
        ),
    }


def coverage(con: duckdb.DuckDBPyConnection) -> list[tuple[str, int, str, str]]:
    """For each main column: days with a value, and the first and last such day."""
    columns = [
        "main_sleep_minutes", "sleep_score", "resting_hr", "hrv_ms",
        "readiness_score", "steps", "active_zone_minutes",
    ]
    rows = []
    for column in columns:
        days, first, last = con.execute(
            f"SELECT count({column}), min(date) FILTER (WHERE {column} IS NOT NULL), "
            f"max(date) FILTER (WHERE {column} IS NOT NULL) FROM daily"
        ).fetchone()
        rows.append((column, days, str(first), str(last)))
    return rows
