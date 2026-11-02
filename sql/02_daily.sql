-- One row per day. A day's sleep is the sleep you woke up from that day, which
-- matches how Fitbit dates resting heart rate, HRV and readiness.

CREATE OR REPLACE TABLE nights AS
SELECT
    CAST(end_local AS DATE) AS date,
    arg_max(sleep_id, minutes_asleep) AS main_sleep_id,
    sum(minutes_asleep) AS total_sleep_minutes,
    count(*) - 1 AS nap_count
FROM sleep_episodes
GROUP BY 1;


-- The source with the most steps that day, since the others missed part of it.
CREATE OR REPLACE TABLE daily_steps AS
WITH by_source AS (
    SELECT date, source, sum(steps) AS steps FROM steps GROUP BY 1, 2
)
SELECT date, max(steps) AS steps, arg_max(source, steps) AS steps_source
FROM by_source
GROUP BY 1;


CREATE OR REPLACE TABLE daily AS
WITH bounds AS (
    SELECT min(date) AS first_day, max(date) AS last_day
    FROM (
        SELECT date FROM nights
        UNION ALL SELECT date FROM daily_heart
        UNION ALL SELECT date FROM daily_steps
    )
),
-- The export starts and ends partway through a day, so its first and last
-- days are left out.
days AS (
    SELECT
        CAST(g.day AS DATE) AS date,
        g.day + INTERVAL 12 HOUR AS noon_utc
    FROM bounds, generate_series(bounds.first_day + 1, bounds.last_day - 1, INTERVAL 1 DAY) AS g(day)
),
-- A day's offset is the one its own sleep was recorded in. Days without a
-- sleep take the offset of the last wake-up before them.
located AS (
    SELECT days.date, COALESCE(own.utc_offset_min, tz.utc_offset_min) AS utc_offset_min
    FROM days
    ASOF LEFT JOIN tz_timeline tz ON days.noon_utc >= tz.valid_from_utc
    LEFT JOIN nights n ON n.date = days.date
    LEFT JOIN sleep_episodes own ON own.sleep_id = n.main_sleep_id
),
heart AS (
    SELECT
        date,
        max(value) FILTER (WHERE metric = 'resting_hr') AS resting_hr,
        max(value) FILTER (WHERE metric = 'hrv_ms') AS hrv_ms,
        max(device) AS heart_device
    FROM daily_heart
    GROUP BY 1
),
zones AS (
    SELECT date, sum(minutes) AS active_zone_minutes FROM active_minutes GROUP BY 1
)
SELECT
    l.date,
    dayname(l.date) AS weekday,
    isodow(l.date) >= 6 AS is_weekend,
    l.utc_offset_min,
    -- From the offsets in your export: +08:00 is Taiwan, the US zones are the rest.
    CASE
        WHEN l.utc_offset_min IS NULL THEN 'unknown'
        WHEN l.utc_offset_min = 480 THEN 'Taiwan'
        WHEN l.utc_offset_min BETWEEN -600 AND -240 THEN 'US'
        ELSE 'other'
    END AS location,
    (
        SELECT c.period FROM calendar c
        WHERE l.date BETWEEN c.start_date AND c.end_date
        -- The narrowest range wins, so midterms can sit inside a term.
        ORDER BY c.end_date - c.start_date
        LIMIT 1
    ) AS period,

    s.algorithm_version AS sleep_algorithm,
    s.start_local AS bedtime,
    s.end_local AS wake_time,
    s.minutes_asleep AS main_sleep_minutes,
    n.total_sleep_minutes,
    n.nap_count,
    s.minutes_awake,
    s.minutes_to_fall_asleep,
    sc.sleep_score,
    sc.deep_sleep_minutes,
    sc.rem_sleep_percent,
    sc.restlessness,

    h.resting_hr,
    h.hrv_ms,
    h.heart_device,
    r.readiness_score,
    r.readiness_level,

    st.steps,
    st.steps_source,
    z.active_zone_minutes
FROM located l
LEFT JOIN nights n USING (date)
LEFT JOIN sleep_episodes s ON s.sleep_id = n.main_sleep_id
LEFT JOIN sleep_scores sc ON sc.sleep_id = n.main_sleep_id
LEFT JOIN heart h USING (date)
LEFT JOIN readiness r USING (date)
LEFT JOIN daily_steps st USING (date)
LEFT JOIN zones z USING (date)
ORDER BY l.date;
