# Developer Guide

This guide is for a developer who has never seen this project and needs to run it, keep it up to date, or add to it. Read sections 1–3 once, then use the rest as a reference: section 6 for the monthly routine, section 7 for step-by-step recipes.

Related documents:

| Document | Use it for |
| --- | --- |
| [data_dictionary.md](data_dictionary.md) | What the NTSB codes mean and every mapping decision |
| [runbook_failed_ingestion.md](runbook_failed_ingestion.md) | Fixing a failed download, extract, or load |
| [performance_log.md](performance_log.md) | The query-tuning measurements and what changed |
| [../web/README.md](../web/README.md) | The web app's files, Docker commands, and publishing |

---

## 1. What the system does

The project turns the NTSB's public aviation accident database into a cleaned SQL Server database, a Power BI dashboard, and a public web dashboard.

```
1. SOURCES (public files)        NTSB avall.mdb (monthly)   FAA aircraft registry   OurAirports airports.csv
        │                                 │                          │                        │
2. PYTHON LOADERS (src/)         download_ntsb.py            load_faa_registry.py     load_airports.py
                                 extract_ntsb.py
        │                                 └──────────────┬───────────┴────────────────────────┘
3. SQL SERVER  (sql/)            stg_*  staging tables, every value stored as raw text
   database AviationSafety                     │  02_transform.sql
                                 dim_* + fact_*  star schema (typed, cleaned)  ◄── nlp_narratives.py adds fact_narrative_tag
                                               │  06_data_quality.sql checks it
                                 vw_pbi_*  reporting views (07_powerbi_views.sql)
        │                                      ├──────────────────────────────┐
4. OUTPUTS                       Power BI project (powerbi/)       export_web_data.py ─► web/data/accidents.db
                                                                                            │
                                                                   Streamlit app (web/app.py)
                                                                   ├─ Docker, http://localhost:8080 (this PC only)
                                                                   └─ Streamlit Community Cloud (public site)
```

Five ideas explain most of the design:

1. **Data flows one way.** Each layer is rebuilt entirely from the one before it, so you never edit data by hand in a later layer.
2. **Loads are full refreshes.** `avall.mdb` is a complete snapshot, so the loaders empty each staging table and reload it, and the transform rebuilds every fact table. Running any step twice is safe.
3. **Staging is text.** Loaders store every value as text, and `02_transform.sql` converts types with `TRY_CAST`. A bad value becomes NULL (and shows up in a quality check) instead of failing the load.
4. **The `vw_pbi_*` views are the contract.** Power BI and the web export both read them, so a change there reaches both outputs.
5. **The public site never touches the database.** It reads a snapshot file committed to GitHub. SQL Server keeps Windows-only sign-in and no network access.

Live site: https://jsaviationanalytics.streamlit.app/ · Repository: https://github.com/IsaacMcCalla/aviation-accident-analytics

---

## 2. Repository map

| Path | What it is |
| --- | --- |
| `src/config.py` | Shared helpers: `get_connection()` (SQL Server via ODBC), `setup_logging()`, `log_run()` (writes `dbo.ingest_log`), `insert_sql()` |
| `src/download_ntsb.py` | Downloads `avall.zip` from the NTSB and extracts `avall.mdb` into `data/ntsb/` |
| `src/extract_ntsb.py` | Copies NTSB tables from the Access file (or mdbtools CSVs) into `stg_ntsb_*`. The `TABLES` dict maps source tables and columns to staging |
| `src/load_faa_registry.py` | Loads FAA `MASTER.txt` and `ACFTREF.txt` (aircraft fields only; registrant names and addresses are skipped on purpose) |
| `src/load_airports.py` | Loads U.S. airports from OurAirports into `stg_airports` |
| `src/nlp_narratives.py` | Keyword rules (`TAGS`) that tag accident narratives; writes `fact_narrative_tag` |
| `src/export_web_data.py` | Exports the `vw_pbi_*` views to `web/data/accidents.db` (SQLite) for the web app |
| `sql/01_schema.sql` | Creates the database and every table; seeds lookup dimensions (operations, phases, weather) |
| `sql/02_transform.sql` | Staging → dimensions and facts; also creates helper views and `fn_ntsb_coord` |
| `sql/03_report_slow.sql` | The deliberately slow "before" report used for the tuning exercise |
| `sql/04_tune.sql` | Indexes, the `narrative_flag` table, and the tuned report. **Rerun after every transform** |
| `sql/05_adhoc_report_proc.sql` | `dbo.usp_accident_report`: parameterized report procedure |
| `sql/06_data_quality.sql` | `dbo.usp_check_data_quality`: the checks to run after every load |
| `sql/07_powerbi_views.sql` | The `vw_pbi_*` reporting views used by Power BI and the web export |
| `powerbi/AccidentDashboard.pbip` | Power BI project (open in Power BI Desktop). Model in `*.SemanticModel/` (TMDL), pages in `*.Report/` (PBIR JSON) |
| `powerbi/build_pbip.py` | Generator that originally wrote the Power BI project. See [7.4](#74-change-the-power-bi-report) before using it |
| `web/app.py` | The web dashboard (Streamlit) |
| `web/Dockerfile`, `web/compose.yaml` | Local container: Python 3.12, port 8080 on localhost only, data mounted read-only |
| `web/data/accidents.db` | The snapshot the web app reads. **Committed to git** because the public site needs it |
| `publish_web.ps1` | Exports the snapshot, commits only that file, and pushes, which redeploys the public site |
| `docs/` | This guide and the other references |
| `data/`, `logs/`, `.venv/` | Not in git: raw downloads (~700 MB), run logs, Python environment |

---

## 3. Setting up a development machine

Everything is built and tested on Windows 11 with Windows PowerShell 5.1. Run every command from the **repository root**: scripts use relative paths (`data/`, `logs/`, `web/data/`).

### 3.1 Install the prerequisites

| Software | Version used | Needed for | Notes |
| --- | --- | --- | --- |
| SQL Server | 2025 Developer (2019+ works) | The database | Free edition. Includes `sqlcmd`. Full-Text Search is optional (only `04_tune.sql` section 5 uses it) |
| Microsoft ODBC Driver 18 for SQL Server | 18 | Python ↔ SQL Server | Usually installed with SQL Server |
| Python | **3.14** | All scripts | **Not 3.15:** pyodbc had no prebuilt package for 3.15 when this was built. Install with `py install 3.14` |
| Microsoft Access Database Engine 2016 | x64 | Reading `avall.mdb` | Must match Python's bitness (64-bit). See the install note below |
| Power BI Desktop | 2.159 (Oct 2026) | The Power BI dashboard | Windows only |
| Git | 2.56 | Version control, publishing | Includes Git Credential Manager for GitHub sign-in |
| Docker Desktop (+ WSL2) | 29.9 | Optional: the local web container | Needs virtualization and one restart after installing WSL |

**Access Database Engine install note:** `winget install Microsoft.AccessDatabaseEngine2016` downloads the installer but may not run it (winget treats it as a portable app). If `pyodbc.drivers()` doesn't list `Microsoft Access Driver (*.mdb, *.accdb)`, run the downloaded `accessdatabaseengine_X64.exe /quiet` yourself as administrator. It refuses to install next to a 32-bit Microsoft Office; in that case use the mdbtools route in the runbook.

### 3.2 SQL Server memory setting (do this on any PC under 32 GB)

On a busy 16 GB machine, Windows can shrink SQL Server's memory until queries wait forever (status `RESOURCE_SEMAPHORE`), which makes Power BI refreshes hang. Reserve a floor and set a ceiling:

```sql
EXEC sp_configure 'show advanced options', 1; RECONFIGURE;
EXEC sp_configure 'min server memory (MB)', 1024;
EXEC sp_configure 'max server memory (MB)', 4096;
RECONFIGURE;
EXEC sp_configure 'show advanced options', 0; RECONFIGURE;
```

If you run Docker, also cap WSL in `%UserProfile%\.wslconfig` (`[wsl2]` then `memory=2GB`), then run `wsl --shutdown` and restart Docker Desktop.

### 3.3 Get the code and the Python environment

```
git clone https://github.com/IsaacMcCalla/aviation-accident-analytics.git
cd aviation-accident-analytics
py -V:3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run scripts as `.venv\Scripts\python.exe src\<script>.py`, or activate the environment once per terminal with `.venv\Scripts\Activate.ps1` and then use `python`.

### 3.4 Connection settings

`src/config.py` reads these environment variables; the defaults suit a local default instance with Windows sign-in.

| Variable | Default | Notes |
| --- | --- | --- |
| `DB_SERVER` | `localhost` | |
| `DB_NAME` | `AviationSafety` | |
| `DB_DRIVER` | `ODBC Driver 18 for SQL Server` | |
| `DB_USER`, `DB_PASSWORD` | unset | If `DB_USER` is unset, Windows authentication is used |

The `sqlcmd` examples in this guide use `-S localhost -E -C`: local server, Windows sign-in, trust the local self-signed certificate. Add `-b` so a script stops on the first error.

---

## 4. First full build

About 15 minutes on a desktop PC. Expected counts are for the October 2026 NTSB file.

| # | Command | Result |
| --- | --- | --- |
| 1 | `sqlcmd -S localhost -E -C -b -i sql\01_schema.sql` | Database `AviationSafety` with ~25 tables |
| 2 | `.venv\Scripts\python.exe src\download_ntsb.py` | `data\ntsb\avall.mdb` (~535 MB) |
| 3 | `.venv\Scripts\python.exe src\extract_ntsb.py data\ntsb\avall.mdb --from-year 2023` | A small slice for a first test. Run steps 6–7 on it, then rerun **without** `--from-year` (~31,300 events, ~40 s) |
| 4 | Download `ReleasableAircraft.zip` from the FAA registry site, unzip to `data\faa\`, then `.venv\Scripts\python.exe src\load_faa_registry.py data\faa` | ~318,000 registered aircraft |
| 5 | Download `airports.csv` from OurAirports to `data\`, then `.venv\Scripts\python.exe src\load_airports.py data\airports.csv` | ~32,700 U.S. airports |
| 6 | `sqlcmd -S localhost -E -C -b -i sql\02_transform.sql` | ~31,850 rows in `fact_accident` (~5 s) |
| 7 | `sqlcmd -S localhost -E -C -b -i sql\06_data_quality.sql` then `sqlcmd -S localhost -E -C -d AviationSafety -Q "EXEC dbo.usp_check_data_quality"` | No FAIL rows (see [section 9](#9-testing-and-verification)) |
| 8 | `sqlcmd -S localhost -E -C -b -i sql\04_tune.sql` | Indexes and `narrative_flag` |
| 9 | `sqlcmd -S localhost -E -C -b -i sql\05_adhoc_report_proc.sql` | `usp_accident_report` |
| 10 | `.venv\Scripts\python.exe src\nlp_narratives.py` | ~11,600 tags |
| 11 | `sqlcmd -S localhost -E -C -b -i sql\07_powerbi_views.sql` | The `vw_pbi_*` views |
| 12 | Open `powerbi\AccidentDashboard.pbip` in Power BI Desktop, click **Refresh**, then **Ctrl+S** | Dashboard with data. First refresh: choose Windows sign-in; accept the unencrypted-connection prompt (local server) |
| 13 | `.venv\Scripts\python.exe src\export_web_data.py` | `web\data\accidents.db` (~18 MB) |
| 14 | Optional: `docker compose -f web\compose.yaml up -d --build` | Web app at http://localhost:8080 |

`sql/03_report_slow.sql` is only for the tuning comparison and isn't needed to run the system.

---

## 5. The data model

### 5.1 Objects in `AviationSafety`

| Layer | Objects | Notes |
| --- | --- | --- |
| Staging | `stg_ntsb_events`, `_aircraft`, `_events_sequence`, `_findings`, `_narratives`, `_injury`, `_flight_crew`, `_flight_time`, `_codes`; `stg_faa_master`, `stg_faa_acftref`; `stg_airports` | All columns text. Emptied and reloaded by the loaders |
| Dimensions | `dim_date`, `dim_airport`, `dim_aircraft`, `dim_operation`, `dim_phase`, `dim_weather_cond` | `dim_operation`, `dim_phase`, `dim_weather_cond` are seeded in `01`; the transform only adds new codes |
| Facts | `fact_accident`, `fact_injury`, `fact_finding`, `fact_narrative`, `fact_narrative_tag` | Rebuilt by `02` (tags by `nlp_narratives.py`) |
| Reference | `ref_ga_hours` | Flight hours per year, typed in by hand (empty until someone fills it) |
| Tuning | `narrative_flag` | Built by `04`; rerun `04` after each transform |
| Views | `vw_stg_events_clean`, `vw_stg_aircraft_clean` (typed staging), `vw_fleet_by_make`, `vw_ga_rate_by_year`, `vw_pbi_*` (reporting) | |
| Code | `fn_ntsb_coord` (DDMMSS → decimal degrees), `usp_accident_report`, `usp_check_data_quality` | |
| Log | `ingest_log` | One row per script run: source, status OK/FAILED, rows, message |

### 5.2 Counting rules (get these right or numbers will be wrong)

- **Grain:** `fact_accident` has **one row per aircraft per event**. A midair collision is one event with two rows.
- **Count events** with `COUNT(DISTINCT ev_id)`, never `COUNT(*)`. In Power BI that's the `Accidents` measure; in the web app it's `nunique()` on `ev_id`.
- **Fatalities:** `event_fatalities` is the event total repeated on each aircraft row. Sum it only where `is_primary_aircraft = 1`.
- **Accidents vs. incidents:** reports use `ev_type = 'ACC'`. The `vw_pbi_*` views already filter to accidents.
- **Coverage:** `avall.mdb` starts in 2008. Phase of flight and findings use the NTSB's post-2008 coding.

### 5.3 Where codes are translated

| Code type | Translated in |
| --- | --- |
| FAR part → operation name | `dim_operation` seed in `01_schema.sql` |
| Phase number → name and group | `dim_phase` seed in `01_schema.sql` (the NTSB file has no names for these) |
| Injury, damage, and light codes (`FATL`, `SUBS`, `NDRK`, …) → words | `vw_pbi_accident` in `07_powerbi_views.sql` |
| Aircraft category (`AIR`, `HELI`, …) → words | `vw_pbi_aircraft` in `07` |
| Narrative tag ids → display names | `vw_pbi_tag` in `07` |

Full code meanings: [data_dictionary.md](data_dictionary.md).

---

## 6. Routine operations

### 6.1 Monthly update (NTSB publishes a new file monthly)

```
.venv\Scripts\python.exe src\download_ntsb.py
.venv\Scripts\python.exe src\extract_ntsb.py data\ntsb\avall.mdb
sqlcmd -S localhost -E -C -b -i sql\02_transform.sql
sqlcmd -S localhost -E -C -b -i sql\04_tune.sql
.venv\Scripts\python.exe src\nlp_narratives.py
sqlcmd -S localhost -E -C -d AviationSafety -Q "EXEC dbo.usp_check_data_quality"
```

Then:

1. Read the quality check. **Stop at any FAIL** and use the runbook. WARN rows are worth a glance.
2. Open the Power BI project, click **Refresh**, then **Ctrl+S**.
3. Run `.\publish_web.ps1`. It exports the snapshot, commits only `web/data/accidents.db`, and pushes; the public site redeploys within a couple of minutes. The local Docker site picks up the new file on its next page load.

The update is done when the quality check has no FAIL rows, the "latest event" date on the web page has moved forward, and the Power BI totals match the web page.

### 6.2 Every few months

Reload the slower-changing reference data: download fresh FAA and OurAirports files, run `load_faa_registry.py` and `load_airports.py`, then `02_transform.sql` and the rest of the monthly steps.

### 6.3 When published

When the FAA publishes its General Aviation Activity Survey, add the year's hours to `dbo.ref_ga_hours` to get accident rates in `vw_ga_rate_by_year`:

```sql
INSERT dbo.ref_ga_hours ([year], ga_hours, source)
VALUES (2025, 0, N'FAA GA Survey CY2025, table 1.3');   -- replace 0 with the published figure
```

Note which operations the survey covers next to any rate you publish.

---

## 7. Making changes: recipes

Every recipe ends with verification. Change one thing at a time and commit when it works.

### 7.1 Add an NTSB field end to end

Example: show surface wind speed (`events.wind_vel_kts`) on the dashboards. A new field passes through every layer:

1. **Extract:** if the column isn't in `TABLES` in `src/extract_ntsb.py`, add it there and a matching `varchar` column in the staging table in `01_schema.sql`. (`wind_vel_kts` is already staged.)
2. **Schema:** add the typed column to the fact table in `01_schema.sql`, for example `wind_kts smallint NULL` on `fact_accident`.
   **Important:** `01` only creates tables that don't exist yet; it doesn't change existing ones. On a database that already exists, also run the change yourself:
   ```sql
   ALTER TABLE dbo.fact_accident ADD wind_kts smallint NULL;
   ```
3. **Transform:** in `02_transform.sql`, add the column to the `INSERT dbo.fact_accident (...)` list and its value to the `SELECT` (`TRY_CAST(e.wind_vel_kts AS smallint)`, adding it to `vw_stg_events_clean` if needed).
4. **Views:** add it to `vw_pbi_accident` in `07_powerbi_views.sql`, then run `07`.
5. **Power BI:** in Power BI Desktop, **Transform data** and refresh the `Accident` query; the new column appears. Build the visual, then save.
6. **Web:** add the column to the `accidents` query in `src/export_web_data.py`, run it, then use the column in `web/app.py`.
7. **Verify:** run `02`, `04`, and the quality check; check a few values against the NTSB CAROL website; check that Power BI and the web page agree.

### 7.2 Add a narrative tag

1. Add a rule to `TAGS` in `src/nlp_narratives.py`: `"carb_ice": (r"\bcarburetor ic(e|ing)\b", "cause")`. Use `"cause"` for causes (searches only the probable-cause statement) and `"all"` for physical events (also searches the factual report). Factual reports quote FAA guidance and toxicology results, so cause-type rules matched against them give false positives.
2. Add the display name to the `CASE` in `vw_pbi_tag` (`07_powerbi_views.sql`) and run `07`.
3. Run `nlp_narratives.py`, then spot-check matches. A quick way to see some:
   ```sql
   SELECT TOP 10 t.ev_id, LEFT(n.narr_cause, 300)
   FROM dbo.fact_narrative_tag t
   JOIN dbo.fact_narrative n ON n.ev_id = t.ev_id AND n.aircraft_key_ntsb = t.aircraft_key_ntsb
   WHERE t.tag = 'carb_ice';
   ```
4. Refresh Power BI and re-export or publish the web data.

### 7.3 Add a data quality check

Add a `UNION ALL SELECT '<check name>', <status>, <detail>` block to `dbo.usp_check_data_quality` in `06_data_quality.sql`, following the existing ones. Use `'PASS'`/`'FAIL'` for things that must hold, `'WARN'` for things worth a look, and `'INFO'` for context. Rerun `06` to replace the procedure, then `EXEC` it.

### 7.4 Change the Power BI report

The Power BI pages and the web app's tabs mirror each other:

| Page / tab | Contents |
| --- | --- |
| Overview | Accidents, fatal accidents, fatalities, fatal share; trend by year; accidents by type of operation |
| Phase of flight | Accidents and fatal share by phase group, in flight order; detailed phase table |
| Causes | Narrative tags (count and fatal share); NTSB finding categories |
| Aircraft | Accidents vs. today's registered fleet by make; accidents by aircraft category |
| Weather and pilot | Fatal share by weather and light; accidents and fatal share by pilot total hours |
| Locations (Power BI) / Map (web) | Accident locations: a longitude/latitude scatter in Power BI, a real map on the web |
| Accident list | Table with the probable cause, filtered by year, state, operation, and injury (searchable on the web) |

If you add a page or tab to one, consider adding it to the other.

**Edit in Power BI Desktop and save.** That's the supported path now.

`powerbi/build_pbip.py` generated the original project, but **regenerating deletes and rewrites the `*.SemanticModel` and `*.Report` folders**, including anything changed in Power BI Desktop. Power BI Desktop has already added its own files (`.platform`, `diagramLayout.json`, `cultures/`). Only rerun the generator if you're deliberately going back to generated files, and commit first so you can compare.

Model notes for anyone editing:

- Measures live on the `Accident`, `Tag`, `Finding`, and `Fleet` tables. Count accidents with the existing `[Accidents]` measure, not by counting rows.
- `Fleet` has no relationship. `[Registered Aircraft]` looks up each `Aircraft[make]` with `TREATAS`, and `[Accidents per 1,000 Registered]` is blank below 100 registered aircraft (tiny exact-name matches give absurd rates).
- Data source: Power Query parameters `Server` and `Database` (**Transform data > Edit parameters**).

### 7.5 Change the web app

1. Edit `web/app.py`. Data comes from `web/data/accidents.db` (tables `accidents`, `tags`, `findings`, `fleet`, `meta`). To add data, change `QUERIES` in `src/export_web_data.py` and re-export.
2. Try it locally without Docker: in a separate virtual environment, `pip install -r web\requirements.txt` then `streamlit run web\app.py` and open http://localhost:8501.
3. Local container: `docker compose -f web\compose.yaml up -d --build`, then check http://localhost:8080.
4. Public site: commit and push (`git add web\app.py`, `git commit -m "..."`, `git push`). Streamlit Cloud redeploys on every push to `main`.

Keep the counting rules from 5.2 (the `accident_stats` and `by` helpers in `app.py` already follow them). Pin exact package versions in `web/requirements.txt`; the cloud and Docker builds install exactly those.

### 7.6 Add a new data source

Follow the existing loader pattern (see `src/load_airports.py`, the simplest):

1. Add a `stg_<name>` table in `01_schema.sql` with text columns.
2. Write `src/load_<name>.py`: connect with `get_connection()`, `TRUNCATE` the staging table, bulk insert with `cursor.fast_executemany = True` and `insert_sql()`, record the run with `log_run(conn, "<source>", "OK"|"FAILED", rows, message)`, and exit with code 1 on failure.
3. Type and join it in `02_transform.sql`; add a quality check in `06`.
4. Document the source in the README table and its codes in the data dictionary.

Never load personal data you don't need. The FAA loader skips registrant names and addresses for this reason.

### 7.7 Add or rename a phase of flight

Phase names are seeded in `01_schema.sql` (`dim_phase`). On an existing database, run an `INSERT` or `UPDATE` against `dim_phase` yourself, and also update the seed so a fresh build matches. The quality check "phase codes with no name" warns when the NTSB starts using a new code.

---

## 8. Conventions

**SQL**
- Scripts are idempotent: `IF OBJECT_ID(...) IS NULL CREATE ...`, `CREATE OR ALTER` for views, procedures, and functions.
- Numbered scripts run in order; each starts with a comment block saying what it does and when to run it.
- Prefixes: `stg_` staging, `dim_` dimension, `fact_` fact, `ref_` hand-maintained reference, `vw_` view (`vw_pbi_` = reporting contract), `usp_` stored procedure, `fn_` function.
- Convert staging text with `TRY_CAST`, never `CAST`.

**Python**
- Use the helpers in `config.py` for connections, logging, and `ingest_log`.
- Each script writes `logs/<script>.log` and one `ingest_log` row, and exits with code 1 on failure.
- Stage values with `to_text()` in `extract_ntsb.py`: trimmed text, empty strings become NULL, booleans `1`/`0`, dates ISO.

**Git**
- Commit identity is the GitHub noreply address (`git config user.email`), which keeps personal email out of public history.
- `data/`, `logs/`, and `.venv/` are ignored. `web/data/accidents.db` is the one data file that is committed (each publish adds about 18 MB to history, fine for years of monthly updates).
- The repository is public: never commit passwords, connection strings with passwords, or personal data.

---

## 9. Testing and verification

There's no automated test suite; quality comes from these layers:

| Check | How | Pass looks like |
| --- | --- | --- |
| Load quality | `EXEC dbo.usp_check_data_quality` | No FAIL. Known WARN: ~45 events marked fatal with zero recorded fatalities (as in the source) |
| Source fidelity | Spot-check a few recent events on the NTSB CAROL website; compare yearly totals with NTSB published statistics | Same date, place, aircraft, injuries |
| Output consistency | Compare totals in SQL, Power BI, and the web page | Identical (Oct 2026 file: 28,951 accidents, 6,392 fatal, 16,831 fatalities, 22.1%) |
| Query changes | For report rewrites, diff old vs. new result sets row for row before comparing speed | Zero differences |
| Web app | Run locally, click every tab, try the filters and the search | No errors in the page or the log |

A useful SQL check of the headline numbers:

```sql
SELECT COUNT(DISTINCT ev_id) AS accidents,
       COUNT(DISTINCT CASE WHEN is_fatal = 1 THEN ev_id END) AS fatal_accidents,
       SUM(CASE WHEN is_primary_aircraft = 1 THEN event_fatalities END) AS fatalities
FROM dbo.fact_accident WHERE ev_type = 'ACC';
```

A good next improvement is a small `pytest` suite for `to_text()`, `fn_ntsb_coord`, and the tag rules.

---

## 10. Deployment

| Target | How it's built | How it's updated | Where to look when it fails |
| --- | --- | --- | --- |
| Power BI (local) | `powerbi/*.pbip` opened in Power BI Desktop | Refresh, then save | Power BI's error dialog; SQL Server waits (see section 11) |
| Web, local | `web/compose.yaml`: image `aviation-dashboard`, `127.0.0.1:8080 → 8501`, `web/data` mounted read-only, restarts with Docker | Data: re-export (no restart). Code: `docker compose -f web\compose.yaml up -d --build` | `docker compose -f web\compose.yaml logs --tail 50` |
| Web, public | Streamlit Community Cloud, from this repo, branch `main`, main file `web/app.py`, Python 3.12, installs `web/requirements.txt`. No secrets | Any push to `main` redeploys. Data: `.\publish_web.ps1` | share.streamlit.io → the app → **Manage app** (logs, reboot, settings) |

Publishing requires push access to the GitHub repository; Git Credential Manager remembers the sign-in after the first push. The public app sleeps after several days without visitors, and the next visitor clicks a "wake up" button.

---

## 11. Known pitfalls

| Symptom | Cause | Fix |
| --- | --- | --- |
| `pip install` fails building pyodbc ("Microsoft Visual C++ 14.0 or greater is required") | Python 3.15 has no prebuilt pyodbc package | Use Python 3.14 for `.venv` |
| `Data source name not found` when extracting | Access Database Engine missing or wrong bitness | Section 3.1 install note, or the runbook's mdbtools route |
| `String or binary data would be truncated` in a loader | A source value is longer than its staging column | Widen the staging column (`ALTER TABLE`) and in `01` |
| Power BI refresh hangs; SQL shows `RESOURCE_SEMAPHORE` waits | Windows trimmed SQL Server's memory | Section 3.2 memory settings; close memory-heavy apps |
| Power BI: "certificate chain was issued by an authority that is not trusted" | Local SQL Server uses a self-signed certificate | Accept the unencrypted connection for `localhost` |
| Power BI edits disappeared | `build_pbip.py` was rerun | Restore from git; edit in Power BI Desktop from now on |
| Export fails with `WinError 32` (file in use) | An SQLite connection left open | Keep the `closing()` wrapper in `export_web_data.py` |
| Fatality totals too high | Summed `event_fatalities` over every aircraft row | Filter `is_primary_aircraft = 1` (section 5.2) |
| A new NTSB code shows as "Phase code N" or "Other (code X)" | NTSB added a code | Add it to the seed in `01` and to the table (section 7.7) |
| Narrative tag counts look too high | Rule matches boilerplate in factual reports | Use `"cause"` scope; spot-check samples |
| Docker won't start: "virtualization is not enabled" | WSL2 needs CPU virtualization | Restart after installing WSL; if it persists, enable VT-x/SVM in BIOS |
| PowerShell shows red text from a successful Python script | Python logging writes to stderr, which PowerShell displays in red | Check the exit code (`$LASTEXITCODE`), not the color |

For load failures, follow [runbook_failed_ingestion.md](runbook_failed_ingestion.md) step by step.

---

## 12. Ideas for future work

- Load `Pre2008.mdb` (NTSB data from 1982) and map its older phase and cause codes into `dim_phase` and the findings.
- Fill `ref_ga_hours` to publish accident rates per 100,000 flight hours.
- A make-name mapping table (for example, ROBINSON / ROBINSON HELICOPTER / ROBINSON HELICOPTER COMPANY) so fleet rates cover more manufacturers.
- One script, or a Windows scheduled task, that runs the whole monthly update.
- Automated tests (section 9).

---

## 13. Glossary

| Term | Meaning here |
| --- | --- |
| Staging | Raw copies of source tables, all text, rebuilt on every load |
| Star schema | A central fact table (accidents) joined to lookup tables (date, aircraft, phase, …) |
| Grain | What one row of a table represents (here: one aircraft in one event) |
| Dimension / fact | Lookup table / table of events or measurements |
| View | A saved query that behaves like a table |
| Measure | A Power BI calculation written in DAX |
| PBIP / TMDL / PBIR | Power BI's text-based project format: the model (TMDL) and the report pages (PBIR JSON) |
| Snapshot | `web/data/accidents.db`, the SQLite export the web app reads |
| Streamlit | The Python library the web app is written in |
| `ev_id` | NTSB's event identifier, the key that ties all NTSB tables together |
| FAR part | The operating rule a flight was under: 91 general aviation, 121 airlines, 135 charter/commuter |
| VMC / IMC | Visual / instrument meteorological conditions (good / poor visibility weather) |
