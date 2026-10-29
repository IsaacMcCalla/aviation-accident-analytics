# Aviation Accident Analytics

An end-to-end data project on civil aviation accidents. It loads the NTSB's public accident database (2008 to present) into SQL Server, models and quality-checks it, tunes the heavy reports, and presents the results in a Power BI dashboard and a public web dashboard.

**Live dashboard:** https://jsaviationanalytics.streamlit.app/

**Question it answers:** what patterns show up in aviation accidents (phase of flight, weather, aircraft, pilot experience, type of operation), and how have accident and fatality counts changed over time?

## How it fits together

```
Public sources  ──►  Python loaders (src/)  ──►  SQL Server: staging ─► star schema ─► reporting views (sql/)
                                                                                          │
                                       Power BI dashboard (powerbi/)  ◄───────────────────┤
                                       Web dashboard (web/): Docker locally, Streamlit Cloud publicly  ◄── snapshot export
```

| Folder | Contents |
| --- | --- |
| `src/` | Python: download, extract, load, narrative tagging, web export |
| `sql/` | Numbered T-SQL scripts: schema, transform, tuning, report procedure, quality checks, reporting views |
| `powerbi/` | Power BI project (`AccidentDashboard.pbip`) |
| `web/` | Streamlit web app, Dockerfile, compose file, and the published data snapshot |
| `docs/` | Developer guide and references |

## Documentation

| Read this | When you want to |
| --- | --- |
| **[docs/developer_guide.md](docs/developer_guide.md)** | Set up a machine, run the pipeline, do the monthly update, or change anything. **Start here** |
| [docs/data_dictionary.md](docs/data_dictionary.md) | Look up NTSB codes and how they're mapped |
| [docs/runbook_failed_ingestion.md](docs/runbook_failed_ingestion.md) | Fix a failed download or load |
| [docs/performance_log.md](docs/performance_log.md) | See the query-tuning measurements |
| [web/README.md](web/README.md) | Work on the web app, Docker, or publishing |
| [docs/portfolio_notes.md](docs/portfolio_notes.md) | Findings template and presentation notes |

## Quick start

On Windows with SQL Server, ODBC Driver 18, the Access Database Engine (x64), and Python 3.14 installed (details in the [developer guide](docs/developer_guide.md#3-setting-up-a-development-machine)):

```
py -V:3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
sqlcmd -S localhost -E -C -b -i sql\01_schema.sql
.venv\Scripts\python.exe src\download_ntsb.py
.venv\Scripts\python.exe src\extract_ntsb.py data\ntsb\avall.mdb
sqlcmd -S localhost -E -C -b -i sql\02_transform.sql
```

Then follow [section 4 of the guide](docs/developer_guide.md#4-first-full-build) for the reference data, quality checks, Power BI, and the web app.

**Monthly update:** [section 6.1 of the guide](docs/developer_guide.md#61-monthly-update-ntsb-publishes-a-new-file-monthly). The last step, `.\publish_web.ps1`, refreshes the public site.

## Data sources (public, no personal data loaded)

| Source | Used for | Notes |
| --- | --- | --- |
| NTSB aviation accident database (`avall.zip`, data.ntsb.gov/avdata) | Events, aircraft, findings, narratives, injuries, crew | Microsoft Access file, 2008 to present (~31,000 events), updated monthly. Older events are in a separate file (`Pre2008.mdb`), not loaded |
| FAA aircraft registry (`ReleasableAircraft.zip`) | Registered fleet by manufacturer | Aircraft fields only; registrant names and addresses are not loaded |
| OurAirports `airports.csv` | Airport names and coordinates | Public domain; joined on the FAA identifier |
| FAA General Aviation and Part 135 Activity Survey | Flight hours per year (`ref_ga_hours`, typed in) | Needed for rates; not filled in yet |

## Additional Information

- Extracted 31,000+ NTSB accident records (2008–present) from a Microsoft Access source into a SQL Server star schema, with automated data quality checks and an ingestion log
- Cut a heavy safety report from 438 ms to 134 ms and from 455,000 to under 1,000 logical reads by replacing correlated per-row lookups with indexed set-based joins and a pre-computed text flag, validated against identical results
- Delivered a Power BI dashboard and a parameterized ad hoc report procedure, documented with a README, developer guide, data dictionary, and troubleshooting runbook
- Published a public web dashboard (Streamlit, containerized with Docker) fed by a monthly snapshot export: https://jsaviationanalytics.streamlit.app/
- Classified 28,500+ accident narratives with rule-based text tagging to quantify causes such as fuel exhaustion and VFR flight into IMC

## Known limitations

- NTSB data records accidents, not exposure. Counts without flight hours or fleet size say little about relative risk.
- Coverage starts in 2008. Phase of flight and findings use the NTSB's post-2008 coding.
- About 11% of aircraft rows (7% of accidents) have no location, mostly non-U.S. events the NTSB records without coordinates. Maps show located events only.
- Recent events can still be preliminary, without a probable cause or findings.
- Make names are as reported (one manufacturer can appear under several spellings, and amateur-built aircraft list the builder's name), and FAA fleet counts reflect today's registry, not the fleet in the accident year.
- Narrative tags are keyword rules that undercount; spot-check them before quoting numbers. Correlation is not causation.
