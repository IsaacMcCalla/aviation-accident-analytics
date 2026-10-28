# Runbook: Failed or Missing NTSB Ingestion

Audience: whoever maintains the pipeline (including future you).
Typical trigger: `usp_check_data_quality` shows FAIL on "last ingestion run succeeded" or "staged aircraft match fact rows", WARN on "data is current", or the dashboard looks stale.

## 1. Confirm the symptom

```sql
EXEC dbo.usp_check_data_quality;

SELECT TOP 10 * FROM dbo.ingest_log ORDER BY log_id DESC;   -- source, status, rows_loaded, message

SELECT 'staging' AS layer, COUNT(*) AS events, MAX(TRY_CAST(ev_date AS date)) AS latest FROM dbo.stg_ntsb_events
UNION ALL
SELECT 'fact', COUNT(DISTINCT ev_id), MAX(ev_date) FROM dbo.fact_accident;
```

- Staging is current but facts are not: the transform did not run or failed (step 5).
- Staging is old too: the download or the extract failed (steps 2 to 4).

## 2. Which step failed?

Look at the `source` of the latest FAILED row in `ingest_log`, then open the matching log file:

| source | Script | Log file |
| --- | --- | --- |
| `ntsb_download` | `download_ntsb.py` | `logs/download_ntsb.log` |
| `ntsb` | `extract_ntsb.py` | `logs/extract_ntsb.log` |
| `faa_registry` | `load_faa_registry.py` | `logs/load_faa_registry.log` |
| `airports` | `load_airports.py` | `logs/load_airports.log` |
| `nlp_tags` | `nlp_narratives.py` | `logs/nlp_narratives.log` |

## 3. Read the error

| Log message or symptom | Likely cause | Fix |
| --- | --- | --- |
| `expected a zip file, got text/html` | The NTSB moved the download link | Find the current link on data.ntsb.gov/avdata; pass it with `--url` |
| `HTTPError 5xx` or timeouts | Source outage | Retry later. The previous `avall.mdb` stays usable |
| `Data source name not found and no default driver specified` (IM002) | Access Database Engine not installed, or its bitness differs from Python's | Install the 64-bit redistributable for 64-bit Python. Check with `python -c "import pyodbc; print(pyodbc.drivers())"`. Or use the mdbtools route (step 4) |
| `table X not found in the source` | NTSB renamed or dropped a table | List the tables (`AccessSource(path).tables()` in a Python shell) and update `TABLES` in `extract_ntsb.py` |
| `columns not found, loaded as NULL` warning | A column was renamed | Compare with the data dictionary shipped with the file; update the column map. Harmless if the column is unused |
| `String or binary data would be truncated` | A value is longer than its staging column | The message names the column (SQL Server 2019+); widen it in `01_schema.sql` with `ALTER TABLE` |
| Narratives load very slowly or run out of memory | Large nvarchar(max) text | Expected to be the slowest table. Close other programs; loading with `--from-year` first confirms the rest works |
| `pyodbc.InterfaceError` / login failed | Wrong credentials, server down, driver missing | Test with SSMS using the same credentials; verify `DB_*` variables and the ODBC driver name |
| Transform: `Violation of UNIQUE KEY constraint 'uq_fact_accident_event_aircraft'` | Duplicate (ev_id, Aircraft_Key) rows in staging | `SELECT ev_id, aircraft_key, COUNT(*) FROM dbo.stg_ntsb_aircraft GROUP BY ev_id, aircraft_key HAVING COUNT(*) > 1;` then check the source |
| "staged aircraft match fact rows" FAIL | Rows dropped by a dimension join | Re-run the dimension section of `02_transform.sql`; check for new `far_part` or category codes |

## 4. No Access driver: the mdbtools route

mdbtools runs on Linux, macOS, or WSL on Windows (`sudo apt install mdbtools`). Export each table to CSV with ISO dates, then load the folder:

```
mkdir -p data/ntsb/csv
for t in events aircraft events_sequence Findings narratives injury Flight_Crew flight_time eADMSPUB_DataDictionary; do
  mdb-export -D '%Y-%m-%d' data/ntsb/avall.mdb "$t" > "data/ntsb/csv/$t.csv"
done
```

```
python src/extract_ntsb.py --csv-dir data/ntsb/csv
```

## 5. Re-run and rebuild

The extract is a full refresh, so re-running it is safe. After it succeeds:

1. Run `sql/02_transform.sql`.
2. Re-run sections 1 and 2 of `sql/04_tune.sql` so `narrative_flag` matches the new data.
3. Run `python src/nlp_narratives.py` if you use the tags.

## 6. Verify and close

```sql
EXEC dbo.usp_check_data_quality;   -- no FAIL rows
```

Spot-check one recent event against the NTSB CAROL search website (same date, location, aircraft, and injuries).

## 7. Write it down

Add a line to your incident notes: date, symptom, root cause, fix, and any prevention step (for example, alerting when `ingest_log` shows FAILED).
