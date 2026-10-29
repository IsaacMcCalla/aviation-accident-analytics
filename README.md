# Aviation Accident Analytics

An end-to-end data project on civil aviation accidents. It loads the NTSB's public accident database (1982 to present, about 90,000 accidents) into SQL Server, models and quality-checks it, validates it against the NTSB's published statistics, tunes the heavy reports, and presents the results in a Power BI dashboard and a public web dashboard.

**Live dashboard:** https://aviation-dashboard.braveriver-68d22d3c.eastus.azurecontainerapps.io (hosted on Azure Container Apps; the first visit after a quiet spell takes about 10–20 seconds to wake it)

**Question it answers:** what patterns show up in aviation accidents (phase of flight, weather, aircraft, pilot experience, type of operation), and how have accident rates changed over time?

## Key findings (U.S. general aviation, 1982–2026)

1. **Flying got safer.** The fatal accident rate fell 48%, from 1.71 per 100,000 flight hours (1990–94) to 0.89 (2020–24). 2024 was the lowest on record.
2. **There are fewer accidents, not milder ones.** The share of accidents that are fatal barely moved (18.6% in the 1980s, 16.4% in the 2020s).
3. **Instrument weather multiplies the danger.** 64% of accidents in instrument conditions were fatal, against 15% in visual conditions.
4. **Maneuvering is deadly; landing is not.** Maneuvering is 14% of accidents but 28% of fatal ones. Landing is 28% of accidents but 3% of fatal ones.
5. **The most common problems are the most survivable.** Engine power loss and fuel exhaustion are fatal 11–14% of the time; spatial disorientation (91%), VFR flight into IMC (82%) and impairment (80%) almost always are.
6. **A simple model confirms it.** Tested on 2019 onward after training on earlier years, it ranks fatal accidents correctly 84% of the time.

Details, method and limits: [docs/findings.md](docs/findings.md) and [docs/model_report.md](docs/model_report.md).

## How it fits together

```
Public sources  ──►  Python loaders (src/)  ──►  SQL Server: staging ─► star schema ─► reporting views (sql/)
                                                                                          │
                                       Power BI dashboard (powerbi/)  ◄───────────────────┤
                                       Web dashboard (web/): Docker locally, Azure Container Apps publicly  ◄── snapshot export
```

| Folder | Contents |
| --- | --- |
| `src/` | Python: download, extract, load, narrative tagging, fatality model, web export |
| `sql/` | Numbered T-SQL scripts: schema, transform, tuning, report procedure, quality checks, reporting views |
| `powerbi/` | Power BI project (`AccidentDashboard.pbip`) |
| `web/` | Streamlit web app, Dockerfiles (local and cloud), compose file, and the published data snapshot |
| `deploy/` | One-time Azure setup script (lets GitHub Actions deploy to the Container App) |
| `reference/` | Small public reference data (flight hours by year) |
| `tests/` | `pytest` suite, run on every push by GitHub Actions |
| `docs/` | Developer guide, findings, model report and references |

## Documentation

| Read this | When you want to |
| --- | --- |
| **[docs/developer_guide.md](docs/developer_guide.md)** | Set up a machine, run the pipeline, do the monthly update, or change anything. **Start here** |
| [docs/findings.md](docs/findings.md) | The findings, with numbers and the SQL behind them |
| [docs/model_report.md](docs/model_report.md) | The fatality model: method, accuracy, factors (generated) |
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
.venv\Scripts\python.exe src\download_ntsb.py --file Pre2008
.venv\Scripts\python.exe src\extract_ntsb.py data\ntsb\avall.mdb data\ntsb\Pre2008.mdb
sqlcmd -S localhost -E -C -b -i sql\02_transform.sql
.venv\Scripts\python.exe -m pytest
```

Then follow [section 4 of the guide](docs/developer_guide.md#4-first-full-build) for the reference data, quality checks, the model, Power BI, and the web app.

**Monthly update:** [section 6.1 of the guide](docs/developer_guide.md#61-monthly-update-ntsb-publishes-a-new-file-monthly). The last step, `.\publish_web.ps1`, refreshes the public site.

## Data sources (public, no personal data loaded)

| Source | Used for | Notes |
| --- | --- | --- |
| NTSB aviation accident database (`avall.zip`, data.ntsb.gov/avdata) | Events, aircraft, findings, narratives, injuries, crew | Microsoft Access file, 2008 to present (~31,000 events), updated monthly |
| NTSB `Pre2008.zip` (same site) | The same, 1982–2007 (~63,000 events) | Older phase and cause coding, mapped as described in the data dictionary. No longer updated |
| FAA aircraft registry (`ReleasableAircraft.zip`) | Registered fleet by manufacturer | Aircraft fields only; registrant names and addresses are not loaded |
| OurAirports `airports.csv` | Airport names and coordinates | Public domain; joined on the FAA identifier |
| BTS *National Transportation Statistics* Table 2-14 | FAA general aviation flight hours and the NTSB's published GA counts, by year | Copied into `reference/` with its sources; used for rates and to validate this project's counts |
| Iowa Environmental Mesonet ASOS archive | Weather reported at the nearest station at the time of each accident | **Partly loaded (1982–1998)**: shown in the web app, not yet used by the model (developer guide 6.4) |

## Additional Information

- Integrated 94,000+ NTSB accident and incident records (1982–present) from two Microsoft Access sources with different coding systems into a SQL Server star schema, with automated data quality checks and an ingestion log
- Validated accident counts against the NTSB's published statistics (within 3% every year) and computed accident rates per 100,000 flight hours from FAA activity data, showing a 48% drop in the general aviation fatal accident rate since the early 1990s
- Built a fatality model (logistic regression and gradient boosting) on 78,000+ accidents, tested on held-out recent years (ROC AUC 0.84), with interpretable odds ratios
- Cut a heavy safety report from 438 ms to 134 ms and from 455,000 to under 1,000 logical reads by replacing correlated per-row lookups with indexed set-based joins and a pre-computed text flag, validated against identical results
- Delivered a Power BI dashboard and a parameterized ad hoc report procedure, documented with a README, developer guide, data dictionary, and troubleshooting runbook
- Published a public web dashboard (Streamlit, containerized with Docker) on Azure Container Apps, deployed by a GitHub Actions pipeline (tests, image build, deploy) that signs in with OpenID Connect and a least-privilege identity, with scale-to-zero hosting and a budget alert: https://aviation-dashboard.braveriver-68d22d3c.eastus.azurecontainerapps.io
- Wrote a 57-test pytest suite covering the loaders, text rules, the published data snapshot and a headless render of the web app, run on every push
- Classified 90,000+ accident narratives with rule-based text tagging to quantify causes such as fuel exhaustion and VFR flight into IMC

## Known limitations

- NTSB data records accidents, not exposure. Rates per flight hour exist only for general aviation as a whole and only for years with an FAA estimate (none for 1982–84, 1986–89 or 2011); breakdowns by phase, weather or aircraft describe accidents, not the risk of a flight.
- Coverage starts in 1982. Before 2008 the NTSB used different phase and cause coding: phases are mapped to the same groups, but causes are kept as separate "Pre-2008" categories, so cause trends don't run across 2008. Older narratives are terser, so narrative tags undercount more before 2008.
- About 16% of aircraft rows have no location: non-U.S. events the NTSB records without coordinates, and older U.S. events. Maps show located events only.
- Recent events can still be preliminary, without a probable cause or findings.
- Make names are as reported (one manufacturer can appear under several spellings, and amateur-built aircraft list the builder's name), and FAA fleet counts reflect today's registry, not the fleet in the accident year.
- Narrative tags are keyword rules that undercount; spot-check them before quoting numbers. Correlation is not causation, and the model describes how severe accidents are, not what causes them.
- Weather in the findings and the model is the NTSB investigator's VMC/IMC call. Observed station weather so far covers 1982–1998 and appears only on the web app's Weather and pilot tab.
