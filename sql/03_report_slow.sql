/* 03_report_slow.sql
   The "before" version of a heavy safety report: fatal share by decade, phase of flight,
   and aircraft category, with findings per aircraft and a fuel-related narrative count.
   Written the way these reports often start out:
     - YEAR() on the date column in WHERE (not sargable)
     - per-row lookups into fact_finding and fact_narrative with no supporting index
     - leading-wildcard LIKE searches over nvarchar(max) narratives
   Run with "Include Actual Execution Plan" on. Record elapsed time, CPU, and logical
   reads per table (Messages tab) in docs/performance_log.md before running 04. */
USE AviationSafety;
GO

-- CHECKPOINT; DBCC DROPCLEANBUFFERS;   -- uncomment for a cold-cache run, on a dev instance ONLY
SET STATISTICS IO ON;
SET STATISTICS TIME ON;

SELECT (YEAR(f.ev_date) / 10) * 10                                   AS decade,
       p.phase_name,
       ac.acft_category,
       COUNT(*)                                                      AS aircraft_involved,
       SUM(CAST(f.is_fatal AS int))                                  AS fatal,
       100.0 * SUM(CAST(f.is_fatal AS int)) / COUNT(*)               AS pct_fatal,
       AVG(CAST(fc.findings AS float))                               AS avg_findings,
       SUM(ISNULL(fu.fuel_related, 0))                               AS fuel_related
FROM dbo.fact_accident f
JOIN dbo.dim_phase p     ON p.phase_key = f.phase_key
JOIN dbo.dim_aircraft ac ON ac.aircraft_dim_key = f.aircraft_dim_key
OUTER APPLY (SELECT COUNT(*) AS findings
             FROM dbo.fact_finding x
             WHERE x.ev_id = f.ev_id AND x.aircraft_key_ntsb = f.aircraft_key_ntsb) fc
OUTER APPLY (SELECT MAX(1) AS fuel_related
             FROM dbo.fact_narrative n
             WHERE n.ev_id = f.ev_id AND n.aircraft_key_ntsb = f.aircraft_key_ntsb
               AND (n.narr_cause LIKE N'%fuel exhaustion%' OR n.narr_cause LIKE N'%fuel starvation%')) fu
WHERE YEAR(f.ev_date) BETWEEN 1990 AND 2024
  AND f.ev_type = 'ACC'
GROUP BY (YEAR(f.ev_date) / 10) * 10, p.phase_name, ac.acft_category
ORDER BY decade, p.phase_name, ac.acft_category;
GO
