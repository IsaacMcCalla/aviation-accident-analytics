/* 06_data_quality.sql
   Data quality checks. Run after every load and transform.
   Any row with status = 'FAIL' needs a look; WARN is worth a look; INFO is context. */
USE AviationSafety;
GO

CREATE OR ALTER PROCEDURE dbo.usp_check_data_quality
AS
BEGIN
    SET NOCOUNT ON;

    SELECT 'staged events with no usable date' AS check_name,
           CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END AS status,
           CONCAT(COUNT(*), ' events skipped by the transform') AS detail
    FROM dbo.stg_ntsb_events
    WHERE TRY_CAST(ev_date AS date) IS NULL

    UNION ALL
    SELECT 'staged aircraft with no matching event',
           CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
           CONCAT(COUNT(*), ' orphan aircraft rows')
    FROM dbo.stg_ntsb_aircraft a
    WHERE NOT EXISTS (SELECT 1 FROM dbo.stg_ntsb_events e WHERE e.ev_id = a.ev_id)

    UNION ALL
    SELECT 'staged aircraft match fact rows',
           CASE WHEN s.n = f.n THEN 'PASS' ELSE 'FAIL' END,
           CONCAT('staged=', s.n, ' fact=', f.n, ' (difference: duplicate keys or a failed dimension join)')
    FROM (SELECT COUNT(*) n
          FROM dbo.stg_ntsb_aircraft a
          JOIN dbo.stg_ntsb_events e ON e.ev_id = a.ev_id
          WHERE TRY_CAST(e.ev_date AS date) >= '19820101'   -- same scope rule as 02_transform.sql
            AND TRY_CAST(a.aircraft_key AS smallint) IS NOT NULL) s,
         (SELECT COUNT(*) n FROM dbo.fact_accident) f

    UNION ALL
    SELECT 'events before 1982 left out by design',
           'INFO',
           CONCAT(COUNT(*), ' stray events dated before the NTSB''s 1982 coverage start')
    FROM dbo.stg_ntsb_events
    WHERE TRY_CAST(ev_date AS date) < '19820101'

    UNION ALL
    SELECT 'findings, injuries and narratives with no accident row',
           CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
           CONCAT(COUNT(*), ' child rows')
    FROM (SELECT ev_id, aircraft_key_ntsb FROM dbo.fact_finding
          UNION ALL SELECT ev_id, aircraft_key_ntsb FROM dbo.fact_injury
          UNION ALL SELECT ev_id, aircraft_key_ntsb FROM dbo.fact_narrative) c
    WHERE NOT EXISTS (SELECT 1 FROM dbo.fact_accident f
                      WHERE f.ev_id = c.ev_id AND f.aircraft_key_ntsb = c.aircraft_key_ntsb)

    UNION ALL
    SELECT 'coordinates that failed to parse or were out of range',
           'INFO',
           CONCAT(SUM(CASE WHEN latitude IS NULL OR longitude IS NULL THEN 1 ELSE 0 END), ' of ', COUNT(*),
                  ' accident rows have no usable location (mostly non-U.S. events with no coordinates in the source)')
    FROM dbo.fact_accident

    UNION ALL
    SELECT 'aircraft fatalities add up to the event total',
           CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'FAIL' END,
           CONCAT(COUNT(*), ' events where the injury table and the event total disagree (see data_dictionary.md)')
    FROM (SELECT ev_id, MAX(event_fatalities) AS event_total, SUM(ISNULL(aircraft_fatalities, 0)) AS by_aircraft
          FROM dbo.fact_accident
          WHERE event_fatalities IS NOT NULL
          GROUP BY ev_id) x
    WHERE x.event_total <> x.by_aircraft

    UNION ALL
    SELECT 'fatal events with zero recorded fatalities',
           CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
           CONCAT(COUNT(*), ' events')
    FROM dbo.fact_accident
    WHERE is_primary_aircraft = 1 AND highest_injury = 'FATL' AND ISNULL(event_fatalities, 0) = 0

    UNION ALL
    SELECT 'accidents with no defining event (phase unknown)',
           'INFO',
           CONCAT(CAST(100.0 * SUM(CASE WHEN p.phase_code = 'UNK' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) AS decimal(5,1)),
                  '% of accident rows (mostly recent events still under investigation)')
    FROM dbo.fact_accident f
    JOIN dbo.dim_phase p ON p.phase_key = f.phase_key

    UNION ALL
    SELECT 'earliest event with coded findings',
           'INFO',
           CONCAT('first: ', CONVERT(varchar(10), MIN(f.ev_date), 120), '; events before this have no findings')
    FROM dbo.fact_accident f
    WHERE EXISTS (SELECT 1 FROM dbo.fact_finding x WHERE x.ev_id = f.ev_id)

    UNION ALL
    SELECT 'phase codes with no name',
           CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
           CONCAT(COUNT(*), ' new codes shown as "Phase code N"; add them to the dim_phase seed in 01_schema.sql')
    FROM dbo.dim_phase
    WHERE phase_name LIKE N'Phase code %'

    UNION ALL
    SELECT 'GA accident counts match the NTSB''s published counts (within 5%)',
           CASE WHEN COUNT(*) = 0 THEN 'PASS' ELSE 'WARN' END,
           CONCAT(COUNT(*), ' years outside 5% (see vw_ga_rate_by_year); worst: ',
                  ISNULL(CAST(MAX(ABS(pct)) AS varchar(10)), '0'), '%')
    FROM (SELECT CAST(100.0 * ga_accidents / ntsb_accidents - 100 AS decimal(5,1)) AS pct
          FROM dbo.vw_ga_rate_by_year WHERE ntsb_accidents > 0) x
    WHERE ABS(pct) > 5

    UNION ALL
    SELECT 'data is current (latest event in the last 90 days)',
           CASE WHEN MAX(ev_date) >= DATEADD(DAY, -90, CAST(SYSUTCDATETIME() AS date)) THEN 'PASS' ELSE 'WARN' END,
           CONCAT('latest event: ', CONVERT(varchar(10), MAX(ev_date), 120))
    FROM dbo.fact_accident

    UNION ALL
    SELECT 'last ingestion run succeeded',
           CASE WHEN status = 'OK' THEN 'PASS' ELSE 'FAIL' END,
           CONCAT(source, ' @ ', CONVERT(varchar(20), run_time, 120), ': ', ISNULL(message, ''))
    FROM (SELECT TOP 1 * FROM dbo.ingest_log ORDER BY log_id DESC) l;
END
GO

-- EXEC dbo.usp_check_data_quality;
