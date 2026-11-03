# Sleep and Recovery

<p align="center">
  <img src="docs/dashboard.png" alt="Dashboard with term averages for sleep, bedtime, resting heart rate and steps, and a sleep trend chart" width="800">
  <br><em>The dashboard, running on simulated data.</em>
</p>

A data pipeline and analysis built on my own Google Health export: about eight months of sleep, heart rate, HRV, and activity from two wearables, across two countries. Most of the work is turning a messy export into a table that can be trusted. That meant finding duplicate records, mixed time zones, a device change partway through, overlapping step counters, and partial days, then fixing each one with code and a test.

On top of that clean table, the analysis asks whether school changes how I sleep and recover. It compares summer with the term, an internship with free summer days, and exam days with ordinary ones, and tests whether tomorrow's HRV can be predicted. Several answers turned out to be "no clear effect", which is a finding too. It's a study of one person, so the results describe me and nobody else.

## Problems found in the export

These came up while building the table, and each one would have changed the results if missed. Each fix has a test in `tests/test_build.py` that uses a small fake export with the same problem.

- **Most nights are in the export twice.** Fitbit's `sleep_session_v1` and `sleep_session_v2` both score the same night, with slightly different times. Counting both doubled sleep totals and made nearly every day look like it had a nap. Overlapping records are merged and v2 is kept, which removed about half the sleep records.
- **The time zone moves.** Timestamps are in UTC, and the data spans the US and Taiwan. Each sleep saves its own offset, so times are converted to local time with that.
- **The device changed in June 2026.** Apple Watch HRV is SDNN and Fitbit HRV is RMSSD, so their values differ a lot and can't be compared directly. Comparisons of HRV use Fitbit days only, or compare each day with a baseline from the same device.
- **The phone and the watch both count steps.** Adding them double-counts, so each day uses the single source with the most steps.
- **The first and last days are partial.** The export begins and ends partway through a day, which made those days look inactive.
- **Missing values have markers.** Sleep sub-scores use `-2` for "not calculated", and some Apple HRV rows are `0`. Both are treated as missing.
- **Some data is too sparse to use.** The stress score has 4 days, there are 21 workouts, and there's no sleep data from the Apple Watch period.

## Privacy

None of my health data or results are in this repository. The code runs on the real export locally, and on a simulated one everywhere else.

- The raw export stays in `~/Downloads` and is only read, never copied.
- Everything built from it goes to `data/`. The executed notebook and the written report go to `private/`. `.gitignore` excludes both folders, along with `calendar.csv`, which has personal dates.
- `explore.ipynb` is saved without outputs. `tests/test_privacy.py` fails if it ever has outputs, so real charts can't be committed by accident.
- The dashboard only listens on localhost and doesn't send Streamlit usage statistics (`.streamlit/config.toml`).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -e .
```

## Try it with simulated data

```bash
.venv/bin/python -m recovery.simulator data/sample
.venv/bin/python -m recovery --export "data/sample/Google Health" --db data/demo.duckdb --calendar calendar.example.csv
.venv/bin/streamlit run app.py
```

The build prints what the cleaning found. On the simulated export:

```text
Data cleaning
  Sleep records:   328 in the export, 175 after merging overlapping v1/v2 records of the same sleep
  Time zones:      3 UTC offsets, every timestamp converted to local time
  Steps:           2 overlapping sources, one chosen per day (0 days from the phone)
  Heart devices:   0 Apple Watch days and 151 Fitbit days, kept apart because they measure HRV differently
  Partial days:    2 dropped at the start and end of the export
```

`recovery/simulator.py` writes an invented export with the same files and quirks as a real one: duplicate sleep records, two step counters, and a move from the US to Taiwan and back. The dashboard simulates one by itself when there's no real database.

## Build the database from a real export

```bash
.venv/bin/python -m recovery --export "~/Downloads/health data/Google Health"
```

This creates `data/health.duckdb` and prints how many days each measurement covers. Label exams, trips, and other periods in `calendar.csv` (the format is in `calendar.example.csv`):

- `midterms` and `finals` mark exam days.
- A period whose name ends in `trip` is left out of the comparisons.
- Ranges can overlap, and the narrowest one wins, so an exam day inside a summer is labeled as the exam.

Open the result from Python:

```python
import duckdb
daily = duckdb.connect("data/health.duckdb", read_only=True).table("daily").df()
```

## The `daily` table

One row per day. The first and last days of the export are left out, because the export starts and ends partway through a day. A day's sleep is the sleep you woke up from that morning, which is also how Fitbit dates resting heart rate, HRV, and readiness.

| Column | Meaning |
|---|---|
| `location`, `utc_offset_min` | Taiwan for +08:00 and US for the US zones, from the time zone saved with each sleep |
| `period` | Label from `calendar.csv`, or empty |
| `sleep_algorithm`, `bedtime`, `wake_time` | Which Fitbit algorithm scored the main sleep, and its local times |
| `main_sleep_minutes`, `total_sleep_minutes`, `nap_count` | Longest sleep, all sleep including naps, and the number of naps |
| `sleep_score`, `deep_sleep_minutes`, `rem_sleep_percent`, `restlessness` | From Fitbit's sleep score |
| `resting_hr`, `hrv_ms`, `heart_device` | Daily resting heart rate and HRV, and which device measured them |
| `readiness_score`, `readiness_level` | Fitbit's daily readiness |
| `steps`, `steps_source` | Steps from the device that counted the most that day |
| `active_zone_minutes` | Minutes in fat burn, cardio, or peak zones |

The SQL that builds it is in `sql/`. `01_staging.sql` types and cleans each file, and `02_daily.sql` joins them by day.

## Analysis

`explore.ipynb` covers data coverage, trends, summer vs. term, internship vs. free summer days, term weekdays vs. weekends, jet lag, sleep vs. HRV, exams, and HRV prediction. Run it into `private/` so the outputs stay out of git:

```bash
.venv/bin/jupyter nbconvert --to notebook --execute explore.ipynb --output-dir private
```

Then open `private/explore.ipynb` to read it.

The methods, in `recovery/analysis.py` and `recovery/model.py`:

- **Group comparisons** use a block bootstrap that resamples runs of 7 days within each group, because neighboring days are too alike to count as independent. They leave out Apple Watch days, trips, and the first 7 days after each long flight.
- **Summer vs. term** mixes the effect of school with a change of country and time zone. Internship vs. free summer days (both in Taiwan) and weekdays vs. weekends (both in the term) compare days in the same place.
- **Exams** are each compared with their own baseline: the 7 most recent ordinary days ending 3 days before, from the same device. That keeps the device change and the seasons out of the result, so exams from both devices count. The interval resamples whole exam periods, since exams days apart share a stretch of time.
- **HRV prediction** compares two ridge regression models with "same as yesterday" and "average of the last 7 days", walk-forward, so each day's model is trained only on earlier days. The evening model uses only what's known before going to sleep, and the morning model adds the night's sleep. The tests check that changing future days doesn't change earlier predictions, and that the model finds a sleep effect planted in simulated data.

## Dashboard

```bash
.venv/bin/streamlit run app.py
```

It shows the real database when `data/health.duckdb` exists, with a switch to simulated data. It has headline numbers, trends, the comparisons, and the model results. Start it with `SIMULATED_ONLY=1` to make sure it never reads the real database, which is how the screenshot above was taken.

## Tests

```bash
.venv/bin/python -m pytest
```
