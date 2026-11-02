import argparse
import os
from pathlib import Path

from recovery.build import DEFAULT_CALENDAR, DEFAULT_DB, build, coverage, quality

DEFAULT_EXPORT = "~/Downloads/health data/Google Health"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build data/health.duckdb from a Google Health export.")
    parser.add_argument(
        "--export",
        type=Path,
        default=Path(os.environ.get("HEALTH_EXPORT", DEFAULT_EXPORT)),
        help="the 'Google Health' folder from the export (default: %(default)s)",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    args = parser.parse_args()

    con = build(args.export, args.db, args.calendar)
    total, first, last = con.execute("SELECT count(*), min(date), max(date) FROM daily").fetchone()
    print(f"Built {args.db}: {total} days, {first} to {last}\n")

    q = quality(con)
    print("Data cleaning")
    print(f"  Sleep records:   {q['sleep_records']} in the export, {q['sleeps_after_merge']} after merging "
          "overlapping v1/v2 records of the same sleep")
    print(f"  Time zones:      {q['time_zones']} UTC offsets, every timestamp converted to local time")
    print(f"  Steps:           {q['step_sources']} overlapping sources, one chosen per day "
          f"({q['days_steps_not_from_watch']} days from the phone)")
    print(f"  Heart devices:   {q['apple_watch_heart_days']} Apple Watch days and {q['fitbit_heart_days']} Fitbit days, "
          "kept apart because they measure HRV differently")
    print(f"  Partial days:    {q['partial_days_dropped']} dropped at the start and end of the export\n")

    print(f"{'column':<22}{'days':>6}  range")
    for column, days, start, end in coverage(con):
        print(f"{column:<22}{days:>6}  {start} to {end}")
    if not args.calendar.exists():
        print(f"\nNo {args.calendar.name} yet, so 'period' is empty. Copy calendar.example.csv and fill in your dates.")


if __name__ == "__main__":
    main()
