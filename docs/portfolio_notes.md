# Portfolio Notes

Notes for presenting this project (resume, interviews). Moved here from the README so the README can stay a developer-facing front door.

**Why this project exists:** it shows the same skills used in production support and reporting roles (file and database extraction, T-SQL modeling and performance tuning, data quality checks, ad hoc reporting, dashboards, deployment, and documentation) on public data, with measured results. It's a companion to the airport delay project and uses the same stack and conventions.

## Resume bullets

- Extracted 31,000+ NTSB accident records (2008–present) from a Microsoft Access source into a SQL Server star schema, with automated data quality checks and an ingestion log
- Cut a heavy safety report from 438 ms to 134 ms and from 455,000 to under 1,000 logical reads by replacing correlated per-row lookups with indexed set-based joins and a pre-computed text flag, validated against identical results
- Delivered a Power BI dashboard and a parameterized ad hoc report procedure, documented with a README, developer guide, data dictionary, and troubleshooting runbook
- Published a public web dashboard (Streamlit, containerized with Docker) fed by a monthly snapshot export: https://jsaviationanalytics.streamlit.app/
- Classified 28,500+ accident narratives with rule-based text tagging to quantify causes such as fuel exhaustion and VFR flight into IMC

## Findings (fill in after analysis)

- Finding 1: [e.g., the Part 91 fatal accident rate fell from X to Y per 100,000 hours between the 2000s and the 2020s]
- Finding 2: [e.g., accidents in IMC were X times as likely to be fatal as accidents in VMC]
- Finding 3: [e.g., maneuvering accounts for X% of fatal accidents but Y% of all accidents]

## Talking points on limitations

See "Known limitations" in the README; be upfront about them in interviews.
