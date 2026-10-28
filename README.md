# Aviation Accident Analytics

An end-to-end data project on U.S. civil aviation accidents: extract the NTSB accident database, model it as a star schema in SQL Server, check its quality, tune the heavy reports, and present the results in Power BI.

**Why this project exists:** it shows the same skills used in production support and reporting roles (file and database extraction, T-SQL modeling and performance tuning, data quality checks, ad hoc reporting, and documentation) on public data, with measured results. It is a companion to the airport delay project and uses the same stack and conventions.

**Question it answers:** what patterns show up in U.S. aviation accidents (phase of flight, weather, aircraft, pilot experience, type of operation), and how have accident and fatality rates changed over time?

**Live dashboard:** https://jsaviationanalytics.streamlit.app/

> Status: in progress. Replace this line with your key finding once done.

## Architecture

```
NTSB avall.mdb ──> extract_ntsb.py ──> stg_ntsb_* ──────┐
FAA registry  ──> load_faa_registry.py ──> stg_faa_* ───┼─> 02_transform.sql ─> dims + fact_accident ─> reports / Power BI
OurAirports   ──> load_airports.py ──> stg_airports ────┘                         │
                                                         nlp_narratives.py ─> fact_narrative_tag
```

Grain of `fact_accident`: one row per aircraft per event. A midair collision is one event with two rows, so count events with `COUNT(DISTINCT ev_id)` or filter `is_primary_aircraft = 1`.

## Data sources (public, no client data)

| Source | Used for | Notes |
| --- | --- | --- |
| NTSB aviation accident database (`avall.zip`, data.ntsb.gov/avdata) | Events, aircraft, findings, narratives, injuries, crew | Microsoft Access file covering 2008 to present (about 31,000 events), updated monthly. Older events are in a separate NTSB file (`Pre2008.mdb`) with older coding, not loaded here |
| FAA aircraft registry (`ReleasableAircraft.zip`) | Registered fleet by manufacturer | Used only to normalize by fleet size. Registrant names and addresses are not loaded |
| OurAirports `airports.csv` | Airport names and coordinates | Public domain; joins on the FAA identifier |
| FAA General Aviation and Part 135 Activity Survey | Flight hours per year (typed into `ref_ga_hours`) | Needed for *rates*; without it you only have counts |

Check each source's current documentation, format, and terms before running. The scripts were written without live access to these files, so test with a small slice first (`--from-year`).

## Setup

1. Install SQL Server Developer edition (free) or create an Azure SQL free-tier database, plus SSMS. Add the Full-Text Search feature if you want the optional narrative search in `04_tune.sql`.
2. Install the Microsoft ODBC Driver 18 for SQL Server.
3. To read `avall.mdb` directly, install the Microsoft Access Database Engine redistributable with the same bitness as your Python (almost always 64-bit). No Access driver? See the mdbtools route in `docs/runbook_failed_ingestion.md`.
4. Create the project's virtual environment and install the packages. Use Python 3.14 or earlier: pyodbc has no prebuilt package for 3.15 yet.
   `py -V:3.14 -m venv .venv`, then `.venv\Scripts\python.exe -m pip install -r requirements.txt`.
   Run the scripts with `.venv\Scripts\python.exe src\<script>.py`, or activate the environment first with `.venv\Scripts\Activate.ps1`.
5. Set environment variables (Windows auth is used if `DB_USER` is not set):
   `DB_SERVER`, `DB_NAME` (default `AviationSafety`), `DB_USER`, `DB_PASSWORD`

## Run order

| Step | Command | What it does |
| --- | --- | --- |
| 1 | Run `sql/01_schema.sql` | Database, staging, dimensions, facts, log |
| 2 | `python src/download_ntsb.py` | Downloads `avall.zip` and extracts `avall.mdb` into `data/ntsb/` |
| 3 | `python src/extract_ntsb.py data/ntsb/avall.mdb --from-year 2023` | Loads a small slice into staging. Run steps 6 and 7 on it, then re-run without `--from-year` |
| 4 | Download `ReleasableAircraft.zip`, unzip into `data/faa/`, then `python src/load_faa_registry.py data/faa` | Fleet reference data |
| 5 | Download `airports.csv` into `data/`, then `python src/load_airports.py data/airports.csv` | Airport reference data |
| 6 | Run `sql/02_transform.sql` | Builds the dimensions and facts (full rebuild) |
| 7 | Run `sql/06_data_quality.sql`, then `EXEC dbo.usp_check_data_quality` | Verifies the load |
| 8 | Run `sql/03_report_slow.sql` with the actual execution plan on | **Record the timings and reads** in `docs/performance_log.md` |
| 9 | Run `sql/04_tune.sql` | Indexes, pre-computed narrative flag, rewritten query. Record the new timings |
| 10 | Run `sql/05_adhoc_report_proc.sql` | Parameterized report procedure for ad hoc requests |
| 11 | `python src/nlp_narratives.py` (optional `--top-terms 40`) | Tags narratives (fuel exhaustion, VFR into IMC, ...) |
| 12 | Fill in `dbo.ref_ga_hours` (below) | Turns counts into rates in `vw_ga_rate_by_year` |
| 13 | Run `sql/07_powerbi_views.sql`, then open `powerbi/AccidentDashboard.pbip` in Power BI Desktop and click **Refresh** | The dashboard (see below) |

Monthly refresh: steps 2, 3 (without `--from-year`), 6, 7, the first two sections of 4, and 11.

### Flight hours for rates

Copy total general aviation hours per year from the FAA General Aviation and Part 135 Activity Survey tables:

```sql
INSERT dbo.ref_ga_hours ([year], ga_hours, source) VALUES
    (2022, 0, N'FAA GA Survey CY2022, table 1.3'),   -- replace 0 with the published figure
    (2023, 0, N'FAA GA Survey CY2023, table 1.3');
SELECT * FROM dbo.vw_ga_rate_by_year ORDER BY [year];
```

Check which table and which operations the survey's hours cover, and say so next to any rate you publish. The NTSB's own published GA rates are a good cross-check.

## Power BI dashboard

`powerbi/AccidentDashboard.pbip` is a Power BI project generated by `powerbi/build_pbip.py`. It imports the `dbo.vw_pbi_*` views from `sql/07_powerbi_views.sql` (accidents only). If your server or database name differs, change the `Server` and `Database` parameters in Power BI (Transform data > Edit parameters).

Model: `Accident` (one row per aircraft) joined to `Calendar`, `Aircraft`, `Operation`, `Phase`, and `Weather`; `Tag` and `Finding` hang off `Accident`. `Fleet` has no relationship: the `Registered Aircraft` measure looks up each `Aircraft[make]` with `TREATAS`, so makes without an exact FAA match show a blank fleet count instead of grouping into one blank row.

On the first refresh Power BI asks how to sign in (choose Windows, current credentials) and may warn that SQL Server's self-signed certificate isn't trusted; accepting the unencrypted connection is fine for a local server. Save in Power BI (Ctrl+S) to keep the loaded data between sessions.

If a refresh hangs, check SQL Server for queries waiting on `RESOURCE_SEMAPHORE` (memory). On a busy 16 GB PC, Windows can trim SQL Server's memory until queries can't start. Setting `min server memory` (1,024 MB here) prevents that. Measures count accidents with `DISTINCTCOUNT(ev_id)`, so a midair counts once.

| Page | Contents |
| --- | --- |
| Overview | Accidents, fatal accidents, fatalities, fatal share; trend by year; accidents by type of operation |
| Phase of flight | Accidents and fatal share by phase group, in flight order; detailed phase table |
| Causes | Narrative tags (count and fatal share); NTSB finding categories |
| Aircraft | Accidents vs. today's registered fleet by make; accidents by aircraft category |
| Weather and pilot | Fatal share by weather and light; accidents and fatal share by pilot total hours |
| Locations | Longitude/latitude scatter as a simple map. Large selections are sampled, so filter by state or year. The Azure Maps visual is an alternative if it is enabled in your Power BI settings |
| Accident list | Searchable table with the probable cause, filtered by year, state, FAR part, and injury |

To change the layout permanently, edit `build_pbip.py` and regenerate, or edit in Power BI Desktop and save (after that, stop regenerating, or your edits are overwritten).

## Web dashboard (Docker)

`web/` holds a web version of the dashboard, built from a snapshot that `src/export_web_data.py` exports after each update. It runs two ways: publicly at https://jsaviationanalytics.streamlit.app/ (Streamlit Community Cloud, updated with `.\publish_web.ps1`), and locally at http://localhost:8080 from a Docker container. See [web/README.md](web/README.md).

## Findings (fill in after analysis)

- Finding 1: [e.g., the Part 91 fatal accident rate fell from X to Y per 100,000 hours between the 2000s and the 2020s]
- Finding 2: [e.g., accidents in IMC were X times as likely to be fatal as accidents in VMC]
- Finding 3: [e.g., maneuvering accounts for X% of fatal accidents but Y% of all accidents]

## Performance tuning

See `docs/performance_log.md` for before/after runtimes, logical reads, execution plan changes, and what each change did.

## Troubleshooting

See `docs/runbook_failed_ingestion.md`. Code meanings and mapping decisions are in `docs/data_dictionary.md`.

## Resume bullets (fill in with your real numbers once built)

- Extracted 31,000+ NTSB accident records (2008–present) from a Microsoft Access source into a SQL Server star schema, with automated data quality checks and an ingestion log
- Cut a heavy safety report from 438 ms to 134 ms and from 455,000 to under 1,000 logical reads by replacing correlated per-row lookups with indexed set-based joins and a pre-computed text flag, validated against identical results
- Delivered a Power BI dashboard and a parameterized ad hoc report procedure, documented with a README, data dictionary, and troubleshooting runbook
- Classified [X] accident narratives with rule-based text tagging to quantify causes such as fuel exhaustion and VFR flight into IMC

## Known limitations (be upfront about these in interviews)

- NTSB data records accidents, not exposure. Counts without flight hours or fleet size say little about relative risk.
- Coverage starts in 2008, when the NTSB changed its cause coding. Adding the older `Pre2008.mdb` file would extend trends back to 1982, but its phase and cause codes need mapping to the newer system.
- About one in five accident rows has no location, mostly non-U.S. events the NTSB records without coordinates. The map page covers located events only.
- Recent events can still be preliminary, without a probable cause or findings.
- Make names are as reported (for example, several spellings of one manufacturer), and FAA fleet counts are today's registry, not the fleet in the accident year.
- Narrative tags are keyword rules: spot-check them before quoting numbers. Correlation is not causation.
