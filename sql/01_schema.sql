/* 01_schema.sql
   Creates the database, staging tables, dimensions, and fact tables.
   Run first. Targets SQL Server 2019+ (Developer edition is free). */

IF DB_ID('AviationSafety') IS NULL CREATE DATABASE AviationSafety;
GO
USE AviationSafety;
GO

/* ---------- Staging (raw text, one table per source table) ----------
   Loaders stage every value as trimmed text; 02_transform.sql converts types,
   so a bad value becomes NULL there instead of failing the load. */
IF OBJECT_ID('dbo.stg_ntsb_events') IS NULL
    CREATE TABLE dbo.stg_ntsb_events (
        ev_id             varchar(20)   NOT NULL,
        ntsb_no           varchar(20)   NULL,
        ev_type           varchar(5)    NULL,    -- ACC accident / INC incident
        ev_date           varchar(30)   NULL,
        ev_time           varchar(10)   NULL,    -- local hhmm
        ev_city           nvarchar(100) NULL,
        ev_state          varchar(5)    NULL,
        ev_country        varchar(5)    NULL,
        latitude          varchar(20)   NULL,    -- DDMMSS + hemisphere, e.g. 334512N
        longitude         varchar(20)   NULL,
        dec_latitude      varchar(30)   NULL,    -- decimal degrees (newer releases only)
        dec_longitude     varchar(30)   NULL,
        ev_nr_apt_id      varchar(10)   NULL,    -- nearest airport, FAA identifier
        apt_name          nvarchar(100) NULL,
        ev_highest_injury varchar(5)    NULL,    -- FATL / SERS / MINR / NONE
        inj_tot_f         varchar(10)   NULL,
        inj_tot_s         varchar(10)   NULL,
        inj_tot_m         varchar(10)   NULL,
        inj_tot_n         varchar(10)   NULL,
        light_cond        varchar(5)    NULL,
        wx_cond_basic     varchar(5)    NULL,    -- VMC / IMC / UNK
        wind_vel_kts      varchar(10)   NULL,
        vis_sm            varchar(30)   NULL,
        mid_air           varchar(5)    NULL
    );
GO

IF OBJECT_ID('dbo.stg_ntsb_aircraft') IS NULL
    CREATE TABLE dbo.stg_ntsb_aircraft (
        ev_id         varchar(20)   NOT NULL,
        aircraft_key  varchar(5)    NULL,    -- 1, 2, ... per event (2+ only for collisions)
        regis_no      varchar(20)   NULL,
        acft_make     nvarchar(100) NULL,
        acft_model    nvarchar(100) NULL,
        acft_category varchar(10)   NULL,    -- AIR / HELI / GLI / BALL / ...
        damage        varchar(5)    NULL,    -- DEST / SUBS / MINR / NONE
        far_part      varchar(5)    NULL,    -- 091 / 121 / 135 / ...
        type_fly      varchar(10)   NULL,
        num_eng       varchar(5)    NULL,
        homebuilt     varchar(5)    NULL,
        oper_sched    varchar(5)    NULL
    );
GO

IF OBJECT_ID('dbo.stg_ntsb_events_sequence') IS NULL
    CREATE TABLE dbo.stg_ntsb_events_sequence (
        ev_id                  varchar(20)   NOT NULL,
        aircraft_key           varchar(5)    NULL,
        occurrence_no          varchar(10)   NULL,
        occurrence_code        varchar(20)   NULL,
        occurrence_description nvarchar(500) NULL,
        phase_no               varchar(10)   NULL,
        eventsoe_no            varchar(10)   NULL,
        defining_ev            varchar(5)    NULL     -- 1 = the defining event for this aircraft
    );
GO

IF OBJECT_ID('dbo.stg_ntsb_findings') IS NULL
    CREATE TABLE dbo.stg_ntsb_findings (
        ev_id               varchar(20)   NOT NULL,
        aircraft_key        varchar(5)    NULL,
        finding_no          varchar(10)   NULL,
        finding_code        varchar(20)   NULL,
        finding_description nvarchar(500) NULL,
        cause_factor        varchar(5)    NULL     -- C cause / F factor
    );
GO

IF OBJECT_ID('dbo.stg_ntsb_narratives') IS NULL
    CREATE TABLE dbo.stg_ntsb_narratives (
        ev_id        varchar(20)   NOT NULL,
        aircraft_key varchar(5)    NULL,
        narr_accp    nvarchar(max) NULL,    -- factual narrative
        narr_cause   nvarchar(max) NULL     -- probable cause statement
    );
GO

IF OBJECT_ID('dbo.stg_ntsb_injury') IS NULL
    CREATE TABLE dbo.stg_ntsb_injury (
        ev_id               varchar(20) NOT NULL,
        aircraft_key        varchar(5)  NULL,
        inj_person_category varchar(10) NULL,    -- Crew / Pass / Grnd / ...
        injury_level        varchar(5)  NULL,    -- FATL / SERS / MINR / NONE
        inj_person_count    varchar(10) NULL
    );
GO

IF OBJECT_ID('dbo.stg_ntsb_flight_crew') IS NULL
    CREATE TABLE dbo.stg_ntsb_flight_crew (
        ev_id         varchar(20) NOT NULL,
        aircraft_key  varchar(5)  NULL,
        crew_no       varchar(5)  NULL,
        crew_category varchar(10) NULL,    -- PLT = pilot
        crew_age      varchar(5)  NULL
    );
GO

IF OBJECT_ID('dbo.stg_ntsb_flight_time') IS NULL
    CREATE TABLE dbo.stg_ntsb_flight_time (
        ev_id        varchar(20) NOT NULL,
        aircraft_key varchar(5)  NULL,
        crew_no      varchar(5)  NULL,
        flight_type  varchar(10) NULL,    -- TOTL = total time
        flight_craft varchar(10) NULL,    -- ALL = all aircraft
        flight_hours varchar(30) NULL
    );
GO

IF OBJECT_ID('dbo.stg_ntsb_codes') IS NULL
    CREATE TABLE dbo.stg_ntsb_codes (
        table_name  nvarchar(100)  NULL,
        column_name nvarchar(100)  NULL,
        code        nvarchar(50)   NULL,
        meaning     nvarchar(1000) NULL
    );
GO

IF OBJECT_ID('dbo.stg_faa_master') IS NULL
    CREATE TABLE dbo.stg_faa_master (
        n_number      varchar(10) NULL,    -- without the leading N
        mfr_mdl_code  varchar(10) NULL,
        year_mfr      varchar(5)  NULL,
        type_aircraft varchar(5)  NULL,
        type_engine   varchar(5)  NULL,
        status_code   varchar(5)  NULL
    );
GO

IF OBJECT_ID('dbo.stg_faa_acftref') IS NULL
    CREATE TABLE dbo.stg_faa_acftref (
        code      varchar(10)   NULL,
        mfr       nvarchar(100) NULL,
        model     nvarchar(100) NULL,
        type_acft varchar(5)    NULL,
        type_eng  varchar(5)    NULL,
        ac_cat    varchar(5)    NULL,
        no_eng    varchar(5)    NULL,
        no_seats  varchar(5)    NULL
    );
GO

IF OBJECT_ID('dbo.stg_airports') IS NULL
    CREATE TABLE dbo.stg_airports (
        ident         varchar(10)   NULL,
        type          varchar(30)   NULL,
        name          nvarchar(200) NULL,
        latitude_deg  varchar(30)   NULL,
        longitude_deg varchar(30)   NULL,
        iso_region    varchar(10)   NULL,    -- US-NY
        municipality  nvarchar(100) NULL,
        iata_code     varchar(5)    NULL,
        local_code    varchar(10)   NULL,    -- FAA identifier, matches NTSB ev_nr_apt_id
        gps_code      varchar(10)   NULL
    );
GO

/* ---------- Dimensions ---------- */
IF OBJECT_ID('dbo.dim_date') IS NULL
BEGIN
    CREATE TABLE dbo.dim_date (
        date_key  int      PRIMARY KEY,   -- yyyymmdd
        full_date date     NOT NULL UNIQUE,
        [year]    smallint NOT NULL,
        [quarter] tinyint  NOT NULL,
        [month]   tinyint  NOT NULL,
        decade    smallint NOT NULL
    );

    WITH n AS (
        SELECT TOP (DATEDIFF(DAY, '19800101', '20351231') + 1)
               ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS i
        FROM sys.all_objects a CROSS JOIN sys.all_objects b
    ), d AS (
        SELECT DATEADD(DAY, i, CAST('19800101' AS date)) AS dt FROM n
    )
    INSERT dbo.dim_date (date_key, full_date, [year], [quarter], [month], decade)
    SELECT YEAR(dt) * 10000 + MONTH(dt) * 100 + DAY(dt), dt, YEAR(dt),
           DATEPART(QUARTER, dt), MONTH(dt), YEAR(dt) / 10 * 10
    FROM d;
END
GO

IF OBJECT_ID('dbo.dim_airport') IS NULL
    CREATE TABLE dbo.dim_airport (
        airport_key  int IDENTITY(1,1) PRIMARY KEY,
        faa_id       varchar(10)   NOT NULL UNIQUE,
        icao         varchar(10)   NULL,
        iata         varchar(5)    NULL,
        name         nvarchar(200) NOT NULL,
        state        char(2)       NULL,
        city         nvarchar(100) NULL,
        latitude     float         NULL,
        longitude    float         NULL,
        airport_type varchar(30)   NULL
    );
GO

IF OBJECT_ID('dbo.dim_aircraft') IS NULL
    CREATE TABLE dbo.dim_aircraft (
        aircraft_dim_key int IDENTITY(1,1) PRIMARY KEY,
        make             nvarchar(100) NOT NULL,   -- upper case, as reported to the NTSB
        model            nvarchar(100) NOT NULL,
        acft_category    varchar(10)   NOT NULL,
        num_eng          tinyint       NULL
    );
GO

IF OBJECT_ID('dbo.dim_operation') IS NULL
BEGIN
    CREATE TABLE dbo.dim_operation (
        operation_key  int IDENTITY(1,1) PRIMARY KEY,
        far_part       varchar(5)    NOT NULL UNIQUE,
        operation_name nvarchar(100) NOT NULL,
        is_general_aviation bit      NOT NULL
    );

    INSERT dbo.dim_operation (far_part, operation_name, is_general_aviation) VALUES
        ('091', N'Part 91: General aviation', 1),
        ('091K', N'Part 91K: Fractional ownership', 1),
        ('103', N'Part 103: Ultralight', 1),
        ('107', N'Part 107: Small unmanned aircraft', 0),
        ('121', N'Part 121: Air carrier', 0),
        ('125', N'Part 125: Large aircraft, non-air carrier', 0),
        ('129', N'Part 129: Foreign air carrier', 0),
        ('133', N'Part 133: Rotorcraft external load', 0),
        ('135', N'Part 135: Commuter and on-demand', 0),
        ('137', N'Part 137: Agricultural', 0),
        ('NUSC', N'Non-U.S. commercial', 0),
        ('NUSN', N'Non-U.S. non-commercial', 0),
        ('PUBU', N'Public aircraft', 0),
        ('ARMF', N'Armed forces', 0),
        ('UNK', N'Unknown', 0);
END
GO

IF OBJECT_ID('dbo.dim_phase') IS NULL
BEGIN
    CREATE TABLE dbo.dim_phase (
        phase_key   int IDENTITY(1,1) PRIMARY KEY,
        phase_code  varchar(10)   NOT NULL UNIQUE,
        phase_name  nvarchar(200) NOT NULL,
        phase_group nvarchar(50)  NOT NULL    -- top-level phase, for dashboards
    );

    /* NTSB phase_no codes. The names are the prefixes of events_sequence.Occurrence_Description
       in avall.mdb (the code table in the file has no meanings for phase_no). */
    INSERT dbo.dim_phase (phase_code, phase_name, phase_group) VALUES
        ('100', N'Prior to flight', N'Standing'),
        ('150', N'Standing', N'Standing'),
        ('151', N'Standing-engine(s) not operating', N'Standing'),
        ('152', N'Standing-engine(s) start-up', N'Standing'),
        ('153', N'Standing-engine(s) operating', N'Standing'),
        ('154', N'Standing-engine(s) shutdown', N'Standing'),
        ('200', N'Pushback/towing', N'Taxi'),
        ('201', N'Pushback/tow-engine not operating', N'Taxi'),
        ('202', N'Pushback/tow-engine start-up', N'Taxi'),
        ('203', N'Pushback/tow-engine operating', N'Taxi'),
        ('250', N'Taxi', N'Taxi'),
        ('251', N'Taxi-to runway', N'Taxi'),
        ('252', N'Taxi-into takeoff position', N'Taxi'),
        ('253', N'Taxi-from runway', N'Taxi'),
        ('300', N'Takeoff', N'Takeoff'),
        ('301', N'Takeoff-rejected takeoff', N'Takeoff'),
        ('350', N'Initial climb', N'Initial climb'),
        ('400', N'Enroute', N'Enroute'),
        ('401', N'Enroute-climb to cruise', N'Enroute'),
        ('402', N'Enroute-cruise', N'Enroute'),
        ('403', N'Enroute-change of cruise level', N'Enroute'),
        ('404', N'Enroute-descent', N'Enroute'),
        ('405', N'Enroute-holding (IFR)', N'Enroute'),
        ('450', N'Maneuvering', N'Maneuvering'),
        ('451', N'Maneuvering-aerobatics', N'Maneuvering'),
        ('452', N'Maneuvering-low-altitude flying', N'Maneuvering'),
        ('453', N'Maneuvering-hover', N'Maneuvering'),
        ('500', N'Approach', N'Approach'),
        ('501', N'Approach-IFR initial approach', N'Approach'),
        ('502', N'Approach-IFR final approach', N'Approach'),
        ('503', N'Approach-circling (IFR)', N'Approach'),
        ('504', N'Approach-IFR missed approach', N'Approach'),
        ('505', N'Approach-VFR pattern crosswind', N'Approach'),
        ('506', N'Approach-VFR pattern downwind', N'Approach'),
        ('507', N'Approach-VFR pattern base', N'Approach'),
        ('508', N'Approach-VFR pattern final', N'Approach'),
        ('509', N'Approach-VFR go-around', N'Approach'),
        ('550', N'Landing', N'Landing'),
        ('551', N'Landing-flare/touchdown', N'Landing'),
        ('552', N'Landing-landing roll', N'Landing'),
        ('553', N'Landing-aborted after touchdown', N'Landing'),
        ('600', N'Emergency descent', N'Emergency'),
        ('601', N'Autorotation', N'Emergency'),
        ('650', N'Uncontrolled descent', N'Emergency'),
        ('700', N'Post-impact', N'Post-impact'),
        ('750', N'After landing', N'Landing'),
        ('800', N'Other', N'Other'),
        ('990', N'Unknown', N'Unknown'),
        ('UNK', N'Unknown / not coded', N'Unknown');
END
GO

IF OBJECT_ID('dbo.dim_weather_cond') IS NULL
BEGIN
    CREATE TABLE dbo.dim_weather_cond (
        wx_cond_key int IDENTITY(1,1) PRIMARY KEY,
        wx_code     varchar(5)   NOT NULL UNIQUE,
        wx_name     nvarchar(60) NOT NULL
    );
    INSERT dbo.dim_weather_cond (wx_code, wx_name) VALUES
        ('VMC', N'Visual meteorological conditions'),
        ('IMC', N'Instrument meteorological conditions'),
        ('UNK', N'Unknown');
END
GO

/* ---------- Facts ---------- */
/* fact_accident has ONLY its clustered PK and the (ev_id, aircraft) key.
   The slow report in 03 scans it. Indexes arrive in 04 so you can measure the gain. */
IF OBJECT_ID('dbo.fact_accident') IS NULL
    CREATE TABLE dbo.fact_accident (
        accident_key        int IDENTITY(1,1) PRIMARY KEY,
        ev_id               varchar(20)   NOT NULL,
        aircraft_key_ntsb   smallint      NOT NULL,
        ntsb_no             varchar(20)   NULL,
        ev_type             varchar(5)    NOT NULL,
        ev_date             date          NOT NULL,
        date_key            int           NOT NULL REFERENCES dbo.dim_date(date_key),
        ev_country          varchar(5)    NULL,
        ev_state            varchar(5)    NULL,
        ev_city             nvarchar(100) NULL,
        latitude            float         NULL,
        longitude           float         NULL,
        airport_key         int           NULL REFERENCES dbo.dim_airport(airport_key),
        aircraft_dim_key    int           NOT NULL REFERENCES dbo.dim_aircraft(aircraft_dim_key),
        operation_key       int           NOT NULL REFERENCES dbo.dim_operation(operation_key),
        phase_key           int           NOT NULL REFERENCES dbo.dim_phase(phase_key),
        wx_cond_key         int           NOT NULL REFERENCES dbo.dim_weather_cond(wx_cond_key),
        light_cond          varchar(5)    NULL,
        damage              varchar(5)    NULL,
        highest_injury      varchar(5)    NULL,      -- event level
        is_fatal            bit           NOT NULL,  -- event had at least one fatality
        event_fatalities    int           NULL,      -- event total; do not sum across aircraft
        aircraft_fatalities int           NULL,      -- this aircraft's occupants and ground
        aircraft_serious    int           NULL,
        is_primary_aircraft bit           NOT NULL,  -- 1 for one aircraft per event: use it to count events
        aircraft_in_event   tinyint       NOT NULL,
        homebuilt           bit           NULL,
        regis_no            varchar(20)   NULL,
        defining_event      nvarchar(500) NULL,
        pilot_age           smallint      NULL,
        pilot_total_hours   int           NULL,
        pilot_hours_band    varchar(20)   NOT NULL,
        CONSTRAINT uq_fact_accident_event_aircraft UNIQUE (ev_id, aircraft_key_ntsb)
    );
GO

IF OBJECT_ID('dbo.fact_injury') IS NULL
    CREATE TABLE dbo.fact_injury (
        injury_key        int IDENTITY(1,1) PRIMARY KEY,
        ev_id             varchar(20) NOT NULL,
        aircraft_key_ntsb smallint    NOT NULL,
        person_category   varchar(10) NULL,
        injury_level      varchar(5)  NULL,
        person_count      int         NULL
    );
GO

IF OBJECT_ID('dbo.fact_finding') IS NULL
    CREATE TABLE dbo.fact_finding (
        finding_key         int IDENTITY(1,1) PRIMARY KEY,
        ev_id               varchar(20)   NOT NULL,
        aircraft_key_ntsb   smallint      NOT NULL,
        finding_no          smallint      NULL,
        finding_code        varchar(20)   NULL,
        finding_description nvarchar(500) NULL,
        finding_category    nvarchar(100) NULL,   -- first segment, e.g. "Personnel issues"
        cause_factor        char(1)       NULL    -- C cause / F factor
    );
GO

IF OBJECT_ID('dbo.fact_narrative') IS NULL
    CREATE TABLE dbo.fact_narrative (
        narrative_key     int IDENTITY(1,1) CONSTRAINT pk_fact_narrative PRIMARY KEY,
        ev_id             varchar(20)   NOT NULL,
        aircraft_key_ntsb smallint      NOT NULL,
        narr_accp         nvarchar(max) NULL,
        narr_cause        nvarchar(max) NULL
    );
GO

/* Written by src/nlp_narratives.py */
IF OBJECT_ID('dbo.fact_narrative_tag') IS NULL
    CREATE TABLE dbo.fact_narrative_tag (
        ev_id             varchar(20) NOT NULL,
        aircraft_key_ntsb smallint    NOT NULL,
        tag               varchar(40) NOT NULL,
        CONSTRAINT pk_fact_narrative_tag PRIMARY KEY (ev_id, aircraft_key_ntsb, tag)
    );
GO

/* Exposure for rates: general aviation flight hours by year, typed in from the
   FAA General Aviation and Part 135 Activity Survey (see README). */
IF OBJECT_ID('dbo.ref_ga_hours') IS NULL
    CREATE TABLE dbo.ref_ga_hours (
        [year]   smallint      PRIMARY KEY,
        ga_hours bigint        NOT NULL,
        source   nvarchar(200) NULL
    );
GO

/* Ingestion log: one row per run, used by the runbook for troubleshooting */
IF OBJECT_ID('dbo.ingest_log') IS NULL
    CREATE TABLE dbo.ingest_log (
        log_id      int IDENTITY(1,1) PRIMARY KEY,
        run_time    datetime2(0) NOT NULL DEFAULT SYSUTCDATETIME(),
        source      varchar(20)  NOT NULL,
        status      varchar(10)  NOT NULL,   -- OK / FAILED
        rows_loaded int          NULL,
        message     nvarchar(500) NULL
    );
GO
