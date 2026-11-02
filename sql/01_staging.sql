-- Load the raw export into typed tables.
--
-- Timestamps in the export are UTC. The one exception is the daily Fitbit
-- summaries (data source "Google Health App"), whose midnight-UTC timestamp is
-- really a date label for the night that ended that morning.

CREATE OR REPLACE MACRO utc_ts(s) AS CAST(replace(s, 'Z', '') AS TIMESTAMP);

-- '+08:00' -> 480, '-07:00' -> -420
CREATE OR REPLACE MACRO offset_minutes(o) AS
    (CASE WHEN left(o, 1) = '-' THEN -1 ELSE 1 END)
    * (CAST(substr(o, 2, 2) AS INTEGER) * 60 + CAST(substr(o, 5, 2) AS INTEGER));

-- -2 is the export's marker for a score it didn't calculate.
CREATE OR REPLACE MACRO score(s) AS NULLIF(CAST(s AS DOUBLE), -2);


CREATE OR REPLACE TABLE sleeps AS
SELECT
    sleep_id,
    sleep_type,
    algorithm_version,
    utc_ts(sleep_start) AS start_utc,
    utc_ts(sleep_end) AS end_utc,
    offset_minutes(end_utc_offset) AS utc_offset_min,
    utc_ts(sleep_start) + to_minutes(offset_minutes(start_utc_offset)) AS start_local,
    utc_ts(sleep_end) + to_minutes(offset_minutes(end_utc_offset)) AS end_local,
    CAST(minutes_asleep AS INTEGER) AS minutes_asleep,
    CAST(minutes_awake AS INTEGER) AS minutes_awake,
    CAST(minutes_to_fall_asleep AS INTEGER) AS minutes_to_fall_asleep
FROM read_csv('{health}/UserSleeps_*.csv', all_varchar = true);


-- Most sleeps are in the export twice, scored by sleep_session_v1 and by
-- sleep_session_v2, with slightly different start and end times. Overlapping
-- records are grouped into one episode, and one record is kept per episode:
-- v2 when there is one so every Fitbit night uses the same algorithm, then v1,
-- then unversioned records (mostly Apple Watch nights).
CREATE OR REPLACE TABLE sleep_episodes AS
WITH ordered AS (
    SELECT
        *,
        max(end_utc) OVER (
            ORDER BY start_utc, end_utc ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
        ) AS previous_end
    FROM sleeps
),
numbered AS (
    SELECT
        *,
        sum(CASE WHEN previous_end IS NULL OR start_utc >= previous_end THEN 1 ELSE 0 END)
            OVER (ORDER BY start_utc, end_utc ROWS UNBOUNDED PRECEDING) AS episode
    FROM ordered
)
SELECT * EXCLUDE (previous_end)
FROM numbered
QUALIFY row_number() OVER (
    PARTITION BY episode
    ORDER BY
        CASE algorithm_version WHEN 'sleep_session_v2' THEN 0 WHEN 'sleep_session_v1' THEN 1 ELSE 2 END,
        minutes_asleep DESC
) = 1;


CREATE OR REPLACE TABLE sleep_scores AS
SELECT
    sleep_id,
    score(overall_score) AS sleep_score,
    CAST(deep_sleep_minutes AS INTEGER) AS deep_sleep_minutes,
    CAST(rem_sleep_percent AS DOUBLE) AS rem_sleep_percent,
    CAST(restlessness_normalized AS DOUBLE) AS restlessness
FROM read_csv('{health}/UserSleepScores_*.csv', all_varchar = true)
QUALIFY row_number() OVER (PARTITION BY sleep_id ORDER BY sleep_score_last_updated DESC) = 1;


-- Where you were, as far as the export knows. Each sleep records its UTC
-- offset, and that offset is assumed to hold from that wake-up until the next.
-- Anything before the first recorded sleep falls back to the first offset.
CREATE OR REPLACE TABLE tz_timeline AS
SELECT end_utc AS valid_from_utc, utc_offset_min FROM sleeps;

CREATE OR REPLACE MACRO first_offset() AS
    (SELECT utc_offset_min FROM tz_timeline ORDER BY valid_from_utc LIMIT 1);


-- The phone and the watch both count steps, so rows are kept per source here
-- and only one source is chosen per day in 02_daily.sql.
CREATE OR REPLACE TABLE steps AS
WITH raw AS (
    SELECT
        utc_ts("timestamp") AS ts_utc,
        CAST(steps AS INTEGER) AS steps,
        "data source" AS source
    FROM read_csv('{physical}/Steps/steps_*.csv', all_varchar = true)
)
SELECT
    raw.*,
    CAST(raw.ts_utc + to_minutes(COALESCE(tz.utc_offset_min, first_offset())) AS DATE) AS date
FROM raw ASOF LEFT JOIN tz_timeline tz ON raw.ts_utc >= tz.valid_from_utc;


CREATE OR REPLACE TABLE active_minutes AS
WITH raw AS (
    SELECT
        utc_ts("timestamp") AS ts_utc,
        "heart rate zone" AS zone,
        CAST("total minutes" AS INTEGER) AS minutes
    FROM read_csv('{physical}/Active Zone Minutes/active_zone_minutes_*.csv', all_varchar = true)
)
SELECT
    raw.*,
    CAST(raw.ts_utc + to_minutes(COALESCE(tz.utc_offset_min, first_offset())) AS DATE) AS date
FROM raw ASOF LEFT JOIN tz_timeline tz ON raw.ts_utc >= tz.valid_from_utc;


-- Resting heart rate and HRV came from an Apple Watch until June 2026 and from
-- Fitbit after. The two measure HRV differently (Apple reports SDNN, Fitbit
-- RMSSD), so the device is kept on every row and the values shouldn't be
-- compared across it.
CREATE OR REPLACE TABLE daily_heart AS
WITH raw AS (
    SELECT
        'resting_hr' AS metric,
        "timestamp" AS ts,
        CAST("beats per minute" AS DOUBLE) AS value,
        "data source" AS source
    FROM read_csv('{physical}/Daily Resting Heart Rate/daily_resting_heart_rate.csv', all_varchar = true)
    UNION ALL
    SELECT
        'hrv_ms',
        "timestamp",
        CAST("average heart rate variability milliseconds" AS DOUBLE),
        "data source"
    FROM read_csv('{physical}/Daily Heart Rate Variability/daily_heart_rate_variability.csv', all_varchar = true)
),
timed AS (
    SELECT *, utc_ts(ts) AS ts_utc FROM raw WHERE value > 0
),
dated AS (
    SELECT
        timed.metric,
        timed.value,
        CASE WHEN timed.source = 'Google Health App' THEN 'fitbit' ELSE 'apple_watch' END AS device,
        CASE
            WHEN timed.source = 'Google Health App' THEN CAST(left(timed.ts, 10) AS DATE)
            ELSE CAST(timed.ts_utc + to_minutes(COALESCE(tz.utc_offset_min, first_offset())) AS DATE)
        END AS date
    FROM timed ASOF LEFT JOIN tz_timeline tz ON timed.ts_utc >= tz.valid_from_utc
)
SELECT date, metric, value, device
FROM dated
-- In the overlap weeks of June, keep Fitbit.
QUALIFY row_number() OVER (PARTITION BY date, metric ORDER BY device = 'fitbit' DESC) = 1;


CREATE OR REPLACE TABLE readiness AS
SELECT
    CAST("timestamp" AS DATE) AS date,
    CAST(score AS INTEGER) AS readiness_score,
    "type" AS readiness_level
FROM read_csv('{physical}/Daily Readiness/daily_readiness.csv', all_varchar = true);
