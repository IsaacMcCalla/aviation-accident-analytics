# Data Dictionary

The NTSB codes this project uses and how they are mapped. The authoritative meanings are in the code table that ships in `avall.mdb` (`eADMSPUB_DataDictionary`, loaded into `stg_ntsb_codes`) and the NTSB's data dictionary document. **Verify each code below against your download**; the NTSB has changed codes between releases.

```sql
-- every code the file defines for a column
SELECT code, meaning FROM dbo.stg_ntsb_codes WHERE column_name = 'far_part' ORDER BY code;
```

## Source tables used

| NTSB table | Staging table | Key fields used |
| --- | --- | --- |
| `events` | `stg_ntsb_events` | ev_id, ev_date, location, highest injury, weather, light |
| `aircraft` | `stg_ntsb_aircraft` | Aircraft_Key, make, model, category, damage, FAR part |
| `events_sequence` | `stg_ntsb_events_sequence` | defining event and its phase (2008+ coding) |
| `Findings` | `stg_ntsb_findings` | finding description, cause or factor (2008+ coding) |
| `Occurrences` (Pre2008.mdb) | `stg_ntsb_occurrences` | occurrence sequence and phase of flight (pre-2008 coding) |
| `seq_of_events`, `ct_seqevt` (Pre2008.mdb) | `stg_ntsb_seq_of_events`, `stg_ntsb_ct_seqevt` | causes and factors, and the names of their subject codes (pre-2008 coding) |
| `narratives` | `stg_ntsb_narratives` | factual narrative, probable cause |
| `injury` | `stg_ntsb_injury` | injuries by person category and level |
| `Flight_Crew`, `flight_time` | `stg_ntsb_flight_crew`, `stg_ntsb_flight_time` | pilot age and total hours |

Join key everywhere: `ev_id` plus `Aircraft_Key` (1 for the first aircraft; 2+ only in collisions).

## Codes

| Field | Code | Meaning |
| --- | --- | --- |
| `ev_type` | ACC / INC | Accident / incident. Reports filter on ACC |
| `ev_highest_injury`, `injury_level` | FATL / SERS / MINR / NONE | Fatal / serious / minor / none |
| `damage` | DEST / SUBS / MINR / NONE | Destroyed / substantial / minor / none |
| `wx_cond_basic` | VMC / IMC / UNK | Visual / instrument meteorological conditions / unknown |
| `light_cond` | DAYL / DUSK / DAWN / NDRK / NITE | Day / dusk / dawn / night dark / night (verify) |
| `acft_category` | AIR / HELI / GLI / BALL / GYRO / WSFT / PPAR / ULTR / UNK | Airplane / helicopter / glider / balloon / gyroplane / weight-shift / powered parachute / ultralight / unknown |
| `far_part` | 091 / 121 / 135 / 137 / ... | Operating rule; full list seeded in `dim_operation` |
| `Cause_Factor` | C / F | The finding is a cause / a contributing factor |
| `crew_category` | PLT | Pilot (others include copilot and student; verify) |
| `flight_type`, `flight_craft` | TOTL, ALL | Total hours, all aircraft: used for `pilot_total_hours` |
| `inj_person_category` | Flig / Pass / Cabi / LapC | Flight crew / passengers / cabin crew / lap children (as of the 2026-10 file) |
| `injury_level` in `injury` | TOTL | A total row that repeats the sum of the other levels; excluded from sums |
| `phase_no` | 100–990 | Phase of flight (2008+); names and groups are seeded in `dim_phase` (see below) |
| `Phase_of_Flight` (pre-2008) | 500–610 | Phase of flight (pre-2008), stored in `dim_phase` as `P500`–`P610` |
| `group_code` (pre-2008) | 1 / 2 / 3 / 4 | Aircraft and environment / human performance / direct underlying factor / indirect underlying factor |
| `ev_time` | hhmm | Event time in **UTC** (the date, `ev_date`, is the UTC date too), despite older documentation calling it local time. Checked against widely reported accidents |

## Mapping decisions

- **Event counts vs aircraft counts.** `fact_accident` has one row per aircraft. Count events with `COUNT(DISTINCT ev_id)` or `is_primary_aircraft = 1`. `event_fatalities` is the event total, repeated on each aircraft row; do not sum it across aircraft.
- **Fatal.** `is_fatal = 1` when the event's highest injury is FATL or its fatality total is above zero.
- **Per-aircraft injuries** sum every person category in the injury table, excluding `injury_level = 'TOTL'` rows so nothing is counted twice. The data quality check "aircraft fatalities add up to the event total" catches a change in this coding.
- **Fatal-but-zero events.** A handful of events have highest injury FATL but zero fatalities in both the event and injury tables. That is how the source records them; the check "fatal events with zero recorded fatalities" lists them as WARN.
- **Phase of flight** comes from the defining event in `events_sequence`. Rows with no defining event (mostly recent events still under investigation) get the `UNK` phase.
- **Phase names** are seeded in `01_schema.sql`. The code table in `avall.mdb` has no meanings for `phase_no`, so the names were taken from the prefix of `Occurrence_Description` (for example "Approach-VFR pattern final"). `phase_group` rolls them up to Standing, Taxi, Takeoff, Initial climb, Enroute, Maneuvering, Approach, Landing, Emergency, Post-impact, Other, and Unknown. A new code the NTSB adds shows as "Phase code N" until it is added to the seed.
- **Two source files.** `avall.mdb` (2008 on) and `Pre2008.mdb` (1982–2007) share one table layout. `extract_ntsb.py` loads them newest first; an `ev_id` in both (one, as of 2026-10) is taken from `avall.mdb`. Seven stray events dated before 1982 are left out by the transform.
- **Pre-2008 phase of flight.** The older coding has no "defining event", so the phase comes from the **first occurrence** in `Occurrences` (`Occurrence_No` = 1), the convention of NTSB studies from that era. The 51 codes are named from the file's own code table and prefixed `P` in `dim_phase`, because the numbers overlap the 2008+ codes with different meanings (`500` is Standing before 2008 and Approach after). Each is mapped to the same `phase_group` as the closest 2008+ phase: climb, cruise and normal descent go to Enroute (as the 2008+ "Enroute-climb to cruise" and "Enroute-descent" do); emergency and uncontrolled descents and emergency landings go to Emergency; hover goes to Maneuvering. About 3% of pre-2008 rows have no usable phase and get `UNK`. Because "first occurrence" and "defining event" can differ for the same accident, compare phase shares across 2008 with care.
- **Pre-2008 causes.** Causes and factors come from `seq_of_events` (`Cause_Factor` C or F), named with `ct_seqevt` (sentence-cased). They are **not** mapped to the 2008+ finding taxonomy, which would be guesswork. Instead `finding_category` is "Pre-2008:" plus the `group_code` meaning, so the two systems never mix silently in a chart.
- **Location.** Non-U.S. events often have no coordinates in the source, and a few have malformed values (for example `131470N`, with 70 seconds). Both become NULL.
- **Finding category** is the first segment of the finding description, before the first hyphen (for example, "Personnel issues" or "Aircraft").
- **Coordinates** use the decimal columns when present, otherwise the DDMMSS text (`334512N`) converted by `dbo.fn_ntsb_coord`. Out-of-range values become NULL.
- **Nearest airport.** `ev_nr_apt_id` is matched to `dim_airport` on the FAA identifier first, then on the ICAO code (some events give `KATL` instead of `ATL`). Placeholders (`NONE`, `PVT`, `PRIV`, `N/A`, `NA`, `UNK`) are treated as no airport. As of the 2026-10 file, 65% of U.S. accident rows match an airport and 28% have no airport ID. About 2% have an ID OurAirports doesn't know, mostly closed or renamed private fields.
- **Make** is upper-cased but otherwise as reported, so one manufacturer can appear under several spellings. A make mapping table is the fix if a page depends on it.
- **Fleet normalization** (`vw_fleet_by_make`) joins on the exact make name. It works for the large manufacturers (CESSNA, PIPER, BEECH, MOONEY), but fails where the FAA spells the make differently or registers kit-built aircraft under the builder's name (`VANS` matches 1 registered aircraft). Show rates only for makes with a believable fleet count, and remember that registrations are not flight hours: airline types fly far more hours per aircraft than private ones.
- **Pilot hours band**: 0–99, 100–499, 500–999, 1,000–4,999, 5,000+, Unknown.
- **General aviation** (`vw_ga_accident`): U.S. accidents (`ev_country = 'USA'`, which includes the territories) other than FAR parts 121, 135, 129, NUSC, NUSN, ARMF and 107. This follows the NTSB's definition (U.S.-registered civil aircraft not under Part 121 or 135, accidents on U.S. soil) as closely as the public file allows. Yearly counts are within 3% of the NTSB's published GA accident counts; fatal-accident counts run 3–7% below the published ones since 2008. Requiring U.S. registration (`regis_no LIKE 'N%'`) made the match worse, so it isn't used.
- **Rates** (`vw_ga_rate_by_year`): accidents per 100,000 flight hours, using FAA flight-hour estimates from BTS Table 2-14 (`reference/`). Both this project's counts and the NTSB's published counts are kept; quote the NTSB-based rate for trends.
- **Narrative tags** (`fact_narrative_tag`, from `src/nlp_narratives.py`). Cause tags search only the probable-cause statement: searching the factual narrative too gave mostly false matches for `impairment` (negative toxicology results) and `vfr_into_imc` (quoted FAA guidance). For 2008 onward, 88% of narratives have a probable cause, so recent events still under investigation are not tagged; before 2008, 65% do, and the statements are terser. The tags undercount: from 2008 on, `vfr_into_imc` finds 203 events, while 391 have the structured occurrence "VFR encounter with IMC" in `events_sequence`. For counts you quote, prefer the structured fields where one exists, and use tags for topics with no structured code.
