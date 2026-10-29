/* 07_powerbi_views.sql
   Views the Power BI model (powerbi/) imports. One view per model table, accidents only
   (ev_type = 'ACC'), with the column names the report expects. Run after 02_transform.sql;
   re-run only if a view changes. Requires src/nlp_narratives.py for vw_pbi_tag rows. */
USE AviationSafety;
GO

/* One row per aircraft involved; join key for every other table is accident_key */
CREATE OR ALTER VIEW dbo.vw_pbi_accident
AS
SELECT f.accident_key,
       f.ev_id,
       f.ntsb_no,
       f.ev_date,
       f.date_key,
       f.ev_country,
       f.ev_state,
       f.ev_city,
       f.latitude,
       f.longitude,
       CAST(CASE WHEN f.ev_country = 'USA' THEN 1 ELSE 0 END AS bit) AS is_us,
       f.aircraft_dim_key,
       f.operation_key,
       f.phase_key,
       f.wx_cond_key,
       CASE f.light_cond WHEN 'DAYL' THEN 'Day' WHEN 'DUSK' THEN 'Dusk' WHEN 'DAWN' THEN 'Dawn'
                         WHEN 'NITE' THEN 'Night' WHEN 'NDRK' THEN 'Night (dark)' WHEN 'NBRT' THEN 'Night (bright)'
                         ELSE 'Unknown' END                           AS light_cond,
       CASE f.damage WHEN 'DEST' THEN 'Destroyed' WHEN 'SUBS' THEN 'Substantial' WHEN 'MINR' THEN 'Minor'
                     WHEN 'NONE' THEN 'None' ELSE 'Unknown' END       AS damage,
       CASE f.highest_injury WHEN 'FATL' THEN 'Fatal' WHEN 'SERS' THEN 'Serious' WHEN 'MINR' THEN 'Minor'
                             WHEN 'NONE' THEN 'None' ELSE 'Unknown' END AS highest_injury,
       f.is_fatal,
       f.event_fatalities,
       f.is_primary_aircraft,
       f.defining_event,
       f.pilot_age,
       f.pilot_hours_band,
       CASE f.pilot_hours_band WHEN '0-99' THEN 1 WHEN '100-499' THEN 2 WHEN '500-999' THEN 3
                               WHEN '1,000-4,999' THEN 4 WHEN '5,000+' THEN 5 ELSE 6 END AS pilot_hours_order,
       ap.faa_id                                                      AS nearest_airport,
       ap.name                                                        AS nearest_airport_name,
       LEFT(n.narr_cause, 4000)                                       AS probable_cause
FROM dbo.fact_accident f
LEFT JOIN dbo.dim_airport ap   ON ap.airport_key = f.airport_key
LEFT JOIN dbo.fact_narrative n ON n.ev_id = f.ev_id AND n.aircraft_key_ntsb = f.aircraft_key_ntsb
WHERE f.ev_type = 'ACC';
GO

CREATE OR ALTER VIEW dbo.vw_pbi_calendar
AS
SELECT date_key, full_date, [year], [quarter], [month], decade
FROM dbo.dim_date
WHERE full_date >= '19820101' AND full_date < DATEADD(YEAR, 1, DATEFROMPARTS(YEAR(SYSUTCDATETIME()), 1, 1));
GO

CREATE OR ALTER VIEW dbo.vw_pbi_aircraft
AS
SELECT aircraft_dim_key, make, model,
       CASE acft_category WHEN 'AIR' THEN N'Airplane' WHEN 'HELI' THEN N'Helicopter' WHEN 'GLI' THEN N'Glider'
                          WHEN 'BALL' THEN N'Balloon' WHEN 'GYRO' THEN N'Gyroplane' WHEN 'WSFT' THEN N'Weight-shift'
                          WHEN 'PPAR' THEN N'Powered parachute' WHEN 'ULTR' THEN N'Ultralight'
                          WHEN 'PLFT' THEN N'Powered lift' WHEN 'BLIM' THEN N'Blimp' WHEN 'RCKT' THEN N'Rocket'
                          WHEN 'UNK' THEN N'Unknown' ELSE acft_category END AS acft_category,
       num_eng
FROM dbo.dim_aircraft;
GO

CREATE OR ALTER VIEW dbo.vw_pbi_operation
AS
SELECT operation_key, far_part, operation_name, is_general_aviation
FROM dbo.dim_operation;
GO

CREATE OR ALTER VIEW dbo.vw_pbi_phase
AS
SELECT phase_key, phase_code, phase_name, phase_group,
       -- flight order, so charts can sort phases the way a flight happens
       CASE phase_group WHEN N'Standing' THEN 1 WHEN N'Taxi' THEN 2 WHEN N'Takeoff' THEN 3
                        WHEN N'Initial climb' THEN 4 WHEN N'Enroute' THEN 5 WHEN N'Maneuvering' THEN 6
                        WHEN N'Approach' THEN 7 WHEN N'Landing' THEN 8 WHEN N'Emergency' THEN 9
                        WHEN N'Post-impact' THEN 10 WHEN N'Other' THEN 11 ELSE 12 END AS phase_group_order
FROM dbo.dim_phase;
GO

CREATE OR ALTER VIEW dbo.vw_pbi_weather
AS
SELECT wx_cond_key, wx_code, wx_name
FROM dbo.dim_weather_cond;
GO

/* Narrative tags; is_fatal and ev_id repeated so tag measures don't need to cross the relationship */
CREATE OR ALTER VIEW dbo.vw_pbi_tag
AS
SELECT f.accident_key, f.ev_id, f.is_fatal,
       CASE t.tag WHEN 'fuel_exhaustion' THEN N'Fuel exhaustion/starvation' WHEN 'loss_of_control' THEN N'Loss of control'
                  WHEN 'vfr_into_imc' THEN N'VFR into IMC' WHEN 'stall' THEN N'Stall'
                  WHEN 'cfit' THEN N'Controlled flight into terrain' WHEN 'maintenance' THEN N'Maintenance'
                  WHEN 'density_altitude' THEN N'High density altitude' WHEN 'spatial_disorientation' THEN N'Spatial disorientation'
                  WHEN 'impairment' THEN N'Impairment' WHEN 'crosswind' THEN N'Crosswind'
                  WHEN 'engine_power_loss' THEN N'Engine power loss' WHEN 'midair' THEN N'Midair collision'
                  WHEN 'wire_strike' THEN N'Wire strike' WHEN 'bird_strike' THEN N'Bird strike'
                  ELSE t.tag END AS tag
FROM dbo.fact_narrative_tag t
JOIN dbo.fact_accident f ON f.ev_id = t.ev_id AND f.aircraft_key_ntsb = t.aircraft_key_ntsb
WHERE f.ev_type = 'ACC';
GO

CREATE OR ALTER VIEW dbo.vw_pbi_finding
AS
SELECT f.accident_key, f.ev_id,
       ISNULL(x.finding_category, N'Unknown') AS finding_category,
       x.finding_description,
       CASE x.cause_factor WHEN 'C' THEN N'Cause' WHEN 'F' THEN N'Factor' ELSE N'Finding' END AS finding_role
FROM dbo.fact_finding x
JOIN dbo.fact_accident f ON f.ev_id = x.ev_id AND f.aircraft_key_ntsb = x.aircraft_key_ntsb
WHERE f.ev_type = 'ACC';
GO

/* Registered fleet per make (all aircraft types), unique on make for the model relationship */
CREATE OR ALTER VIEW dbo.vw_pbi_fleet
AS
SELECT make, SUM(registered_aircraft) AS registered_aircraft
FROM dbo.vw_fleet_by_make
WHERE make IS NOT NULL
GROUP BY make;
GO
