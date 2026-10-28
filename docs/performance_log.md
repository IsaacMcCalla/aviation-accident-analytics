# Performance Log

Record every measurement. Use the same data, the same machine, and a warm and a cold run (`DBCC DROPCLEANBUFFERS` on a dev instance only). Confirm each version returns the same result set before comparing.

The NTSB data is small by warehouse standards (tens of thousands of events), so elapsed time may be short on a fast machine. Logical reads, especially on `fact_narrative` (LOB reads), are the clearer measure here. If elapsed times are too close to compare, run the report several times in a loop and record the total.

## Test setup (measured 2026-10-28)

- Data: NTSB `avall.mdb` dated 2026-10-01, events 2008-01-01 to 2026-09-30
- Rows in fact_accident: 31,854
- Rows in fact_finding: 73,002
- Rows in fact_narrative: 28,516
- SQL Server 2025 Standard Developer Edition (17.0.1000.7), Intel Core i5-14400F (16 logical CPUs), 16 GB RAM
- Each version run once cold (after `CHECKPOINT; DBCC DROPCLEANBUFFERS`) and three times warm; warm figures are the median

## Results

| Step | Change | Elapsed (ms) warm / cold | CPU (ms) warm | Logical reads (all tables) | Plan notes |
| --- | --- | --- | --- | --- | --- |
| 0 | Baseline: `03_report_slow.sql` | 438 / 559 | 968 | 454,926 | Scan count 9 on the base tables suggests a parallel plan (not yet confirmed in the actual plan). Worktable: scan count 53,556, 442,786 reads, the spool behind the per-row OUTER APPLY into fact_finding. fact_narrative scanned: 8,411 reads |
| 1–4 | All of `04_tune.sql`: date range via dim_date, `ix_fact_finding_event_aircraft`, `narrative_flag`, `ix_fact_accident_type_date` | 134 / 138 | 125 | 989 | Scan count 1 everywhere and no worktable reads: no spool. fact_accident 175 reads (covering index), fact_finding 555, narrative_flag 119 |
| 5 (optional) | Columnstore index instead of rowstore | | | | Not tried yet |

Results checked: both versions return the same 508 rows, identical line for line (decade, phase, category, counts, percentages, averages).

Steps 1–4 were applied together, so the individual effect of each change was not measured. To isolate them, apply one change at a time to a copy of the 03 query and record each row separately.

**Overall:** 3.3× faster elapsed, 7.7× less CPU, 460× fewer logical reads.

## What I learned

- **Biggest win and why:** removing the per-row correlated lookup. The OUTER APPLY into `fact_finding` made the optimizer build a spool and rescan it 53,556 times (442,786 reads, 97% of the total). A set-based join to a grouped subquery reads `fact_finding` once through the new index.
- **Change that did less than expected and why:** the narrative text search. The probable-cause text fits in-row, so there were no LOB reads, and scanning `fact_narrative` cost only 8,411 reads. Pre-computing `narrative_flag` cut that to 119, but it was never the bottleneck. It would matter more for searches over the long factual narrative (`narr_accp`, up to 79,000 characters, stored off-row).
- **What I would check next:** measure each change on its own; try the columnstore variant; compare the actual plans to see whether the date-range rewrite alone changes the plan shape (the date filter covers almost all rows here, so it should matter little).

## Resume line

"Reduced a multi-table aviation safety report from 438 ms and 455,000 logical reads to 134 ms and under 1,000 reads by replacing correlated per-row lookups with indexed set-based joins and a pre-computed text flag, validated against identical results."
