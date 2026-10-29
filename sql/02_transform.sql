/* 02_transform.sql
   Staging -> star schema. Run after the loaders. Safe to re-run:
   dimensions are upserted (new values added) and facts are fully rebuilt,
   because avall.mdb (and Pre2008.mdb, when loaded) are complete snapshots.
   Events before 1982 (a handful of stray records) are left out: the NTSB's
   systematic coverage starts in 1982. */
USE AviationSafety;
GO

/* ---------- Helpers ---------- */
/* '334512N' or '1173045W' (degrees, minutes, seconds, hemisphere) -> decimal degrees */
CREATE OR ALTER FUNCTION dbo.fn_ntsb_coord (@s varchar(20))
RETURNS float
AS
BEGIN
    -- separate checks: T-SQL does not promise to short-circuit OR, and LEFT() fails on short input
    IF @s IS NULL OR LEN(@s) NOT IN (7, 8) RETURN NULL;
    IF RIGHT(@s, 1) NOT IN ('N', 'S', 'E', 'W') RETURN NULL;

    DECLARE @digits varchar(20) = LEFT(@s, LEN(@s) - 1);
    IF @digits LIKE '%[^0-9]%' RETURN NULL;

    DECLARE @value float = CAST(LEFT(@digits, LEN(@digits) - 4) AS int)
                         + CAST(SUBSTRING(@digits, LEN(@digits) - 3, 2) AS int) / 60.0
                         + CAST(RIGHT(@digits, 2) AS int) / 3600.0;
    RETURN CASE WHEN RIGHT(@s, 1) IN ('S', 'W') THEN -@value ELSE @value END;
END
GO

/* Typed, cleaned views over staging. Everything below reads these, not the raw tables. */
CREATE OR ALTER VIEW dbo.vw_stg_events_clean
AS
SELECT e.ev_id,
       e.ntsb_no,
       ISNULL(e.ev_type, 'UNK')                                                  AS ev_type,
       TRY_CAST(e.ev_date AS date)                                               AS ev_date,
       e.ev_country,
       e.ev_state,
       e.ev_city,
       COALESCE(TRY_CAST(e.dec_latitude AS float),  dbo.fn_ntsb_coord(e.latitude))  AS latitude,
       COALESCE(TRY_CAST(e.dec_longitude AS float), dbo.fn_ntsb_coord(e.longitude)) AS longitude,
       CASE WHEN e.ev_nr_apt_id IN ('NONE', 'PVT', 'PRIV', 'N/A', 'NA', 'UNK') THEN NULL
            ELSE e.ev_nr_apt_id END                                           AS ev_nr_apt_id,   -- placeholders mean "no airport"
       e.ev_highest_injury,
       TRY_CAST(e.inj_tot_f AS int)                                              AS inj_tot_f,
       e.light_cond,
       CASE WHEN e.wx_cond_basic IN ('VMC', 'IMC') THEN e.wx_cond_basic ELSE 'UNK' END AS wx_cond_basic,
       e.ev_time,          -- local hhmm, for src/enrich_weather.py
       e.ev_tmzn,
       e.wx_obs_fac_id,
       CASE WHEN TRY_CAST(e.ev_date AS date) >= '19820101' THEN 1 ELSE 0 END    AS in_scope
FROM dbo.stg_ntsb_events e;
GO

CREATE OR ALTER VIEW dbo.vw_stg_aircraft_clean
AS
SELECT a.ev_id,
       TRY_CAST(a.aircraft_key AS smallint)                        AS aircraft_key,
       a.regis_no,
       ISNULL(UPPER(a.acft_make), N'UNKNOWN')                      AS make,
       ISNULL(UPPER(a.acft_model), N'UNKNOWN')                     AS model,
       ISNULL(UPPER(a.acft_category), 'UNK')                       AS acft_category,
       TRY_CAST(a.num_eng AS tinyint)                              AS num_eng,
       a.damage,
       ISNULL(UPPER(a.far_part), 'UNK')                            AS far_part,
       CASE WHEN a.homebuilt IN ('Y', '1') THEN 1
            WHEN a.homebuilt IN ('N', '0') THEN 0 END              AS homebuilt
FROM dbo.stg_ntsb_aircraft a;
GO

SET NOCOUNT ON;

/* ---------- 1. Dimensions (add new values) ---------- */
INSERT dbo.dim_airport (faa_id, icao, iata, name, state, city, latitude, longitude, airport_type)
SELECT s.local_code, s.gps_code, s.iata_code, ISNULL(s.name, s.local_code), RIGHT(s.iso_region, 2),
       s.municipality, TRY_CAST(s.latitude_deg AS float), TRY_CAST(s.longitude_deg AS float), s.type
FROM (
    -- a few FAA identifiers appear twice (closed and open fields); prefer the larger airport
    SELECT *, ROW_NUMBER() OVER (
               PARTITION BY local_code
               ORDER BY CASE type WHEN 'large_airport' THEN 1 WHEN 'medium_airport' THEN 2
                                  WHEN 'small_airport' THEN 3 WHEN 'closed' THEN 9 ELSE 5 END) AS rn
    FROM dbo.stg_airports
    WHERE local_code IS NOT NULL
) s
WHERE s.rn = 1
  AND NOT EXISTS (SELECT 1 FROM dbo.dim_airport d WHERE d.faa_id = s.local_code);

INSERT dbo.dim_aircraft (make, model, acft_category, num_eng)
SELECT DISTINCT a.make, a.model, a.acft_category, a.num_eng
FROM dbo.vw_stg_aircraft_clean a
WHERE NOT EXISTS (SELECT 1 FROM dbo.dim_aircraft d
                  WHERE d.make = a.make AND d.model = a.model AND d.acft_category = a.acft_category
                    AND ISNULL(d.num_eng, 255) = ISNULL(a.num_eng, 255));

INSERT dbo.dim_operation (far_part, operation_name, is_general_aviation)
SELECT DISTINCT a.far_part, CONCAT(N'Other (code ', a.far_part, N')'), 0
FROM dbo.vw_stg_aircraft_clean a
WHERE NOT EXISTS (SELECT 1 FROM dbo.dim_operation o WHERE o.far_part = a.far_part);

/* Phase codes are seeded in 01_schema.sql; a code the NTSB adds later still gets a row.
   (Pre-2008 codes are a closed list, fully seeded; stray ones map to Unknown below.) */
INSERT dbo.dim_phase (phase_code, phase_name, phase_group)
SELECT DISTINCT q.phase_no, CONCAT(N'Phase code ', q.phase_no), N'Unknown'
FROM dbo.stg_ntsb_events_sequence q
WHERE q.phase_no IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dbo.dim_phase p WHERE p.phase_code = q.phase_no);

/* ---------- 2. Facts (full rebuild) ---------- */
DELETE dbo.fact_accident;
DELETE dbo.fact_injury;
DELETE dbo.fact_finding;
DELETE dbo.fact_narrative;   -- DELETE, not TRUNCATE: 04 may add a full-text index on it

WITH defining AS (
    SELECT ev_id, TRY_CAST(aircraft_key AS smallint) AS aircraft_key, phase_no, occurrence_description,
           ROW_NUMBER() OVER (PARTITION BY ev_id, aircraft_key ORDER BY TRY_CAST(occurrence_no AS int)) AS rn
    FROM dbo.stg_ntsb_events_sequence
    WHERE defining_ev = '1'
), first_occ AS (
    -- Pre-2008 events have no "defining event"; use the first occurrence, as NTSB studies of that era do
    SELECT o.ev_id, TRY_CAST(o.aircraft_key AS smallint) AS aircraft_key,
           'P' + o.phase_of_flight AS phase_code, c.meaning AS occurrence_description,
           ROW_NUMBER() OVER (PARTITION BY o.ev_id, o.aircraft_key ORDER BY TRY_CAST(o.occurrence_no AS int)) AS rn
    FROM dbo.stg_ntsb_occurrences o
    LEFT JOIN (SELECT code, MIN(meaning) AS meaning FROM dbo.stg_ntsb_codes
               WHERE table_name = 'Occurrences' AND column_name = 'Occurrence_Code'
               GROUP BY code) c ON c.code = o.occurrence_code
), pilot AS (
    SELECT c.ev_id, TRY_CAST(c.aircraft_key AS smallint) AS aircraft_key,
           TRY_CAST(c.crew_age AS smallint)               AS age,
           TRY_CAST(TRY_CAST(t.flight_hours AS float) AS int) AS total_hours,
           ROW_NUMBER() OVER (PARTITION BY c.ev_id, c.aircraft_key ORDER BY TRY_CAST(c.crew_no AS int)) AS rn
    FROM dbo.stg_ntsb_flight_crew c
    LEFT JOIN dbo.stg_ntsb_flight_time t
           ON t.ev_id = c.ev_id AND t.aircraft_key = c.aircraft_key AND t.crew_no = c.crew_no
          AND t.flight_type = 'TOTL' AND t.flight_craft = 'ALL'
    WHERE c.crew_category = 'PLT'
), inj AS (
    SELECT ev_id, TRY_CAST(aircraft_key AS smallint) AS aircraft_key,
           SUM(CASE WHEN injury_level = 'FATL' THEN TRY_CAST(inj_person_count AS int) ELSE 0 END) AS fatal,
           SUM(CASE WHEN injury_level = 'SERS' THEN TRY_CAST(inj_person_count AS int) ELSE 0 END) AS serious
    FROM dbo.stg_ntsb_injury
    WHERE injury_level <> 'TOTL'   -- TOTL rows repeat the sum of the other levels; see data_dictionary.md
    GROUP BY ev_id, aircraft_key
)
INSERT dbo.fact_accident (
    ev_id, aircraft_key_ntsb, ntsb_no, ev_type, ev_date, date_key, ev_country, ev_state, ev_city,
    latitude, longitude, airport_key, aircraft_dim_key, operation_key, phase_key, wx_cond_key,
    light_cond, damage, highest_injury, is_fatal, event_fatalities, aircraft_fatalities, aircraft_serious,
    is_primary_aircraft, aircraft_in_event, homebuilt, regis_no, defining_event,
    pilot_age, pilot_total_hours, pilot_hours_band)
SELECT e.ev_id,
       a.aircraft_key,
       e.ntsb_no,
       e.ev_type,
       e.ev_date,
       YEAR(e.ev_date) * 10000 + MONTH(e.ev_date) * 100 + DAY(e.ev_date),
       e.ev_country,
       e.ev_state,
       e.ev_city,
       CASE WHEN e.latitude  BETWEEN -90  AND 90  THEN e.latitude  END,
       CASE WHEN e.longitude BETWEEN -180 AND 180 THEN e.longitude END,
       COALESCE(ap_faa.airport_key, ap_icao.airport_key),
       da.aircraft_dim_key,
       o.operation_key,
       COALESCE(ph.phase_key, ph_old.phase_key, ph_unk.phase_key),
       w.wx_cond_key,
       e.light_cond,
       a.damage,
       e.ev_highest_injury,
       CASE WHEN e.ev_highest_injury = 'FATL' OR e.inj_tot_f > 0 THEN 1 ELSE 0 END,
       e.inj_tot_f,
       i.fatal,
       i.serious,
       CASE WHEN a.aircraft_key = MIN(a.aircraft_key) OVER (PARTITION BY e.ev_id) THEN 1 ELSE 0 END,
       COUNT(*) OVER (PARTITION BY e.ev_id),
       a.homebuilt,
       a.regis_no,
       COALESCE(d.occurrence_description, fo.occurrence_description),
       p.age,
       p.total_hours,
       CASE WHEN p.total_hours IS NULL THEN 'Unknown'
            WHEN p.total_hours < 100   THEN '0-99'
            WHEN p.total_hours < 500   THEN '100-499'
            WHEN p.total_hours < 1000  THEN '500-999'
            WHEN p.total_hours < 5000  THEN '1,000-4,999'
            ELSE '5,000+' END
FROM dbo.vw_stg_events_clean e
JOIN dbo.vw_stg_aircraft_clean a ON a.ev_id = e.ev_id
JOIN dbo.dim_aircraft da   ON da.make = a.make AND da.model = a.model AND da.acft_category = a.acft_category
                          AND ISNULL(da.num_eng, 255) = ISNULL(a.num_eng, 255)
JOIN dbo.dim_operation o   ON o.far_part = a.far_part
JOIN dbo.dim_weather_cond w ON w.wx_code = e.wx_cond_basic
CROSS JOIN (SELECT phase_key FROM dbo.dim_phase WHERE phase_code = 'UNK') ph_unk
LEFT JOIN defining d       ON d.ev_id = e.ev_id AND d.aircraft_key = a.aircraft_key AND d.rn = 1
LEFT JOIN dbo.dim_phase ph ON ph.phase_code = d.phase_no
LEFT JOIN first_occ fo     ON fo.ev_id = e.ev_id AND fo.aircraft_key = a.aircraft_key AND fo.rn = 1
LEFT JOIN dbo.dim_phase ph_old ON ph_old.phase_code = fo.phase_code
LEFT JOIN pilot p          ON p.ev_id = e.ev_id AND p.aircraft_key = a.aircraft_key AND p.rn = 1
LEFT JOIN inj i            ON i.ev_id = e.ev_id AND i.aircraft_key = a.aircraft_key
-- most events give the FAA identifier; some give the ICAO code (KATL) instead
LEFT JOIN dbo.dim_airport ap_faa ON ap_faa.faa_id = e.ev_nr_apt_id
LEFT JOIN (SELECT icao, MIN(airport_key) AS airport_key
           FROM dbo.dim_airport WHERE icao IS NOT NULL GROUP BY icao) ap_icao
       ON ap_icao.icao = e.ev_nr_apt_id
WHERE e.ev_date IS NOT NULL
  AND e.in_scope = 1
  AND a.aircraft_key IS NOT NULL;

/* Child facts skip the rows of out-of-scope (pre-1982) events */
INSERT dbo.fact_injury (ev_id, aircraft_key_ntsb, person_category, injury_level, person_count)
SELECT s.ev_id, TRY_CAST(s.aircraft_key AS smallint), s.inj_person_category, s.injury_level, TRY_CAST(s.inj_person_count AS int)
FROM dbo.stg_ntsb_injury s
WHERE TRY_CAST(s.aircraft_key AS smallint) IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dbo.vw_stg_events_clean e WHERE e.ev_id = s.ev_id AND e.in_scope = 0);

INSERT dbo.fact_finding (ev_id, aircraft_key_ntsb, finding_no, finding_code, finding_description,
                         finding_category, cause_factor)
SELECT ev_id, TRY_CAST(aircraft_key AS smallint), TRY_CAST(finding_no AS smallint), finding_code,
       finding_description,
       LEFT(finding_description, CHARINDEX('-', finding_description + '-') - 1),
       CASE WHEN cause_factor IN ('C', 'F') THEN cause_factor END
FROM dbo.stg_ntsb_findings
WHERE TRY_CAST(aircraft_key AS smallint) IS NOT NULL;

/* Pre-2008 causes and factors (seq_of_events). They use a different coding system, so they
   keep their own categories, prefixed "Pre-2008:", instead of a guessed mapping to the 2008+ ones.
   finding_no = occurrence * 100 + position in that occurrence's sequence. */
INSERT dbo.fact_finding (ev_id, aircraft_key_ntsb, finding_no, finding_code, finding_description,
                         finding_category, cause_factor)
SELECT s.ev_id, TRY_CAST(s.aircraft_key AS smallint),
       TRY_CAST(s.occurrence_no AS int) * 100 + TRY_CAST(s.seq_event_no AS int),
       s.subj_code,
       ISNULL(UPPER(LEFT(c.meaning, 1)) + LOWER(SUBSTRING(c.meaning, 2, 200)), CONCAT(N'Subject code ', s.subj_code)),
       CASE s.group_code WHEN '1' THEN N'Pre-2008: Aircraft and environment'
                         WHEN '2' THEN N'Pre-2008: Human performance'
                         WHEN '3' THEN N'Pre-2008: Direct underlying factor'
                         WHEN '4' THEN N'Pre-2008: Indirect underlying factor'
                         ELSE N'Pre-2008: Other' END,
       CASE WHEN s.cause_factor IN ('C', 'F') THEN s.cause_factor END
FROM dbo.stg_ntsb_seq_of_events s
LEFT JOIN (SELECT code, MIN(meaning) AS meaning FROM dbo.stg_ntsb_ct_seqevt GROUP BY code) c ON c.code = s.subj_code
WHERE TRY_CAST(s.aircraft_key AS smallint) IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dbo.vw_stg_events_clean e WHERE e.ev_id = s.ev_id AND e.in_scope = 0);

INSERT dbo.fact_narrative (ev_id, aircraft_key_ntsb, narr_accp, narr_cause)
SELECT s.ev_id, TRY_CAST(s.aircraft_key AS smallint), s.narr_accp, s.narr_cause
FROM dbo.stg_ntsb_narratives s
WHERE TRY_CAST(s.aircraft_key AS smallint) IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM dbo.vw_stg_events_clean e WHERE e.ev_id = s.ev_id AND e.in_scope = 0);
GO

/* ---------- 3. Reporting views ---------- */
/* Current registered fleet by manufacturer, to normalize accident counts by make.
   FAA and NTSB spell makes differently at times; check the top makes match. */
CREATE OR ALTER VIEW dbo.vw_fleet_by_make
AS
SELECT UPPER(r.mfr) AS make,
       r.type_acft,
       COUNT(*)     AS registered_aircraft
FROM dbo.stg_faa_master m
JOIN dbo.stg_faa_acftref r ON r.code = m.mfr_mdl_code
GROUP BY UPPER(r.mfr), r.type_acft;
GO

/* U.S. general aviation accidents per 100,000 flight hours, by year.
   "General aviation" follows the NTSB's definition as closely as the public file allows: civil
   flying in the U.S. (territories are coded USA) other than Parts 121, 135 and 129, foreign
   (NUSC/NUSN), military (ARMF) and drone (107) operations. vw_ga_accident is that set.
   This project's counts are within about 3% of the NTSB's published accident counts and run
   3-7% below its fatal-accident counts since 2008; the published counts (ntsb_*) are kept next
   to them, so quote the ntsb_* rates for trends and use this project's counts for breakdowns.
   Rates are NULL for years with no FAA flight-hour estimate (see dbo.ref_ga_hours). */
CREATE OR ALTER VIEW dbo.vw_ga_accident
AS
SELECT f.*
FROM dbo.fact_accident f
JOIN dbo.dim_operation o ON o.operation_key = f.operation_key
WHERE f.ev_type = 'ACC'
  AND f.ev_country = 'USA'
  AND o.far_part NOT IN ('121', '135', '129', 'NUSC', 'NUSN', 'ARMF', '107');
GO

CREATE OR ALTER VIEW dbo.vw_ga_rate_by_year
AS
SELECT d.[year],
       COUNT(DISTINCT f.ev_id)                                    AS ga_accidents,
       COUNT(DISTINCT CASE WHEN f.is_fatal = 1 THEN f.ev_id END)  AS ga_fatal_accidents,
       h.ntsb_accidents,
       h.ntsb_fatal_accidents,
       h.ga_hours,
       100000.0 * COUNT(DISTINCT f.ev_id) / NULLIF(h.ga_hours, 0) AS accidents_per_100k_hours,
       100000.0 * COUNT(DISTINCT CASE WHEN f.is_fatal = 1 THEN f.ev_id END) / NULLIF(h.ga_hours, 0)
                                                                  AS fatal_per_100k_hours,
       100000.0 * h.ntsb_accidents / NULLIF(h.ga_hours, 0)       AS ntsb_accidents_per_100k_hours,
       100000.0 * h.ntsb_fatal_accidents / NULLIF(h.ga_hours, 0) AS ntsb_fatal_per_100k_hours
FROM dbo.vw_ga_accident f
JOIN dbo.dim_date d          ON d.date_key = f.date_key
LEFT JOIN dbo.ref_ga_hours h ON h.[year] = d.[year]
GROUP BY d.[year], h.ga_hours, h.ntsb_accidents, h.ntsb_fatal_accidents;
GO
