/* 04_tune.sql
   The tuned version. Run AFTER recording the slow timings from 03.
   Changes: (1) index the finding lookup, (2) pre-compute the narrative flag once,
   (3) covering index on fact_accident, (4) sargable date range via dim_date.
   Optional (5): full-text index for ad hoc narrative searches.
   Verify the result set matches 03 (same rows and numbers) before claiming a speedup.
   Re-run sections 1 and 2 after every 02_transform.sql rebuild. */
USE AviationSafety;
GO

/* 1. Index the per-aircraft finding lookup */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_fact_finding_event_aircraft')
    CREATE NONCLUSTERED INDEX ix_fact_finding_event_aircraft
        ON dbo.fact_finding (ev_id, aircraft_key_ntsb)
        INCLUDE (finding_category, cause_factor);

/* 2. Pre-compute the narrative flag once, with the SAME predicate as 03,
      so the report no longer scans nvarchar(max) text on every run */
IF OBJECT_ID('dbo.narrative_flag') IS NOT NULL DROP TABLE dbo.narrative_flag;

SELECT ev_id, aircraft_key_ntsb,
       MAX(CASE WHEN narr_cause LIKE N'%fuel exhaustion%' OR narr_cause LIKE N'%fuel starvation%'
                THEN 1 ELSE 0 END) AS fuel_related
INTO dbo.narrative_flag
FROM dbo.fact_narrative
GROUP BY ev_id, aircraft_key_ntsb;

ALTER TABLE dbo.narrative_flag
    ADD CONSTRAINT pk_narrative_flag PRIMARY KEY (ev_id, aircraft_key_ntsb);

/* 3. Covering index for the accident side of the report */
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_fact_accident_type_date')
    CREATE NONCLUSTERED INDEX ix_fact_accident_type_date
        ON dbo.fact_accident (ev_type, ev_date)
        INCLUDE (ev_id, aircraft_key_ntsb, date_key, phase_key, aircraft_dim_key, is_fatal);
GO

/* Optional experiment: compare against a columnstore index (drop ix_fact_accident_type_date first, record both)
   CREATE NONCLUSTERED COLUMNSTORE INDEX ncci_fact_accident
       ON dbo.fact_accident (ev_type, ev_date, date_key, phase_key, aircraft_dim_key, is_fatal, ev_id, aircraft_key_ntsb); */

SET STATISTICS IO ON;
SET STATISTICS TIME ON;

/* 4. Same report: sargable date range, indexed lookups, pre-computed flag */
SELECT d.decade,
       p.phase_name,
       ac.acft_category,
       COUNT(*)                                                      AS aircraft_involved,
       SUM(CAST(f.is_fatal AS int))                                  AS fatal,
       100.0 * SUM(CAST(f.is_fatal AS int)) / COUNT(*)               AS pct_fatal,
       AVG(CAST(ISNULL(fc.findings, 0) AS float))                    AS avg_findings,
       SUM(ISNULL(nf.fuel_related, 0))                               AS fuel_related
FROM dbo.fact_accident f
JOIN dbo.dim_date d      ON d.date_key = f.date_key
JOIN dbo.dim_phase p     ON p.phase_key = f.phase_key
JOIN dbo.dim_aircraft ac ON ac.aircraft_dim_key = f.aircraft_dim_key
LEFT JOIN (SELECT ev_id, aircraft_key_ntsb, COUNT(*) AS findings
           FROM dbo.fact_finding
           GROUP BY ev_id, aircraft_key_ntsb) fc
       ON fc.ev_id = f.ev_id AND fc.aircraft_key_ntsb = f.aircraft_key_ntsb
LEFT JOIN dbo.narrative_flag nf
       ON nf.ev_id = f.ev_id AND nf.aircraft_key_ntsb = f.aircraft_key_ntsb
WHERE f.ev_type = 'ACC'
  AND f.ev_date >= '19900101' AND f.ev_date < '20250101'
GROUP BY d.decade, p.phase_name, ac.acft_category
ORDER BY d.decade, p.phase_name, ac.acft_category;
GO

/* 5. Optional: full-text index for ad hoc narrative searches (needs the Full-Text Search
      feature, which SQL Server setup can add). CONTAINS matches whole words and phrases,
      so its counts can differ slightly from LIKE; it is for exploration, not for the report above.
   Example once built:
     SELECT TOP 50 ev_id, narr_cause FROM dbo.fact_narrative
     WHERE CONTAINS(narr_cause, N'"carburetor ice" OR "carburetor icing"'); */
IF FULLTEXTSERVICEPROPERTY('IsFullTextInstalled') = 1
BEGIN
    IF NOT EXISTS (SELECT 1 FROM sys.fulltext_catalogs WHERE name = 'ftc_narratives')
        EXEC ('CREATE FULLTEXT CATALOG ftc_narratives');
    IF NOT EXISTS (SELECT 1 FROM sys.fulltext_indexes WHERE object_id = OBJECT_ID('dbo.fact_narrative'))
        EXEC ('CREATE FULLTEXT INDEX ON dbo.fact_narrative (narr_accp, narr_cause)
               KEY INDEX pk_fact_narrative ON ftc_narratives WITH CHANGE_TRACKING AUTO');
END
ELSE
    PRINT 'Full-Text Search is not installed; skipped section 5.';
GO
