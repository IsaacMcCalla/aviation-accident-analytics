/* 05_adhoc_report_proc.sql
   Parameterized report procedure for ad hoc requests ("every fatal Part 135 helicopter
   accident in Alaska since 2015"). One row per aircraft involved.
   Use it as the data source for the Power BI dashboard and as an SSRS rebuild.
   Leave a parameter NULL to skip that filter. */
USE AviationSafety;
GO

CREATE OR ALTER PROCEDURE dbo.usp_accident_report
    @start_date date,
    @end_date   date,
    @state      varchar(5)    = NULL,
    @make       nvarchar(100) = NULL,   -- matched as a prefix: 'CESSNA' finds every Cessna make spelling that starts with it
    @far_part   varchar(5)    = NULL,   -- '091', '121', '135', ...
    @fatal_only bit           = 0
AS
BEGIN
    SET NOCOUNT ON;

    SELECT f.ev_id,
           f.ntsb_no,
           f.ev_date,
           d.[year],
           f.ev_state,
           f.ev_city,
           f.latitude,
           f.longitude,
           ap.faa_id                         AS nearest_airport,
           ap.name                           AS nearest_airport_name,
           ac.make,
           ac.model,
           ac.acft_category,
           o.far_part,
           o.operation_name,
           p.phase_name,
           w.wx_code                         AS weather,
           f.light_cond,
           f.damage,
           f.highest_injury,
           f.is_fatal,
           f.event_fatalities,
           f.aircraft_fatalities,
           f.is_primary_aircraft,
           f.defining_event,
           f.pilot_age,
           f.pilot_hours_band
    FROM dbo.fact_accident f
    JOIN dbo.dim_date d          ON d.date_key = f.date_key
    JOIN dbo.dim_aircraft ac     ON ac.aircraft_dim_key = f.aircraft_dim_key
    JOIN dbo.dim_operation o     ON o.operation_key = f.operation_key
    JOIN dbo.dim_phase p         ON p.phase_key = f.phase_key
    JOIN dbo.dim_weather_cond w  ON w.wx_cond_key = f.wx_cond_key
    LEFT JOIN dbo.dim_airport ap ON ap.airport_key = f.airport_key
    WHERE f.ev_type = 'ACC'
      AND f.ev_date >= @start_date
      AND f.ev_date <  DATEADD(DAY, 1, @end_date)
      AND (@state IS NULL OR f.ev_state = @state)
      AND (@make IS NULL OR ac.make LIKE UPPER(@make) + N'%')
      AND (@far_part IS NULL OR o.far_part = @far_part)
      AND (@fatal_only = 0 OR f.is_fatal = 1)
    ORDER BY f.ev_date, f.ev_id, f.aircraft_key_ntsb
    OPTION (RECOMPILE);   -- optional filters: let each call get a plan for the filters it uses
END
GO

-- Example: EXEC dbo.usp_accident_report @start_date='2015-01-01', @end_date='2024-12-31', @state='AK', @far_part='135', @fatal_only=1;
