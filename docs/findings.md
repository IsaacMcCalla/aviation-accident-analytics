# Findings

What the data says about U.S. general aviation accidents, 1982 to 2026. The numbers are from the data as loaded on 2026-10-29 (NTSB files through September 2026). The web app's **Findings** tab shows the same findings and recomputes them on each update. This page is a dated snapshot of them, with the method and the SQL needed to reproduce each number.

**Scope.** "General aviation" (GA) is civil flying other than airlines and charter. Here it means U.S. accidents excluding Parts 121, 135 and 129, foreign (NUSC/NUSN), military (ARMF) and drone (Part 107) operations: the set in `dbo.vw_ga_accident`, 78,861 accidents counted once each. This project's yearly GA accident counts are within 3% of the NTSB's published counts (checked by `usp_check_data_quality`).

## 1. Flying got safer: the fatal accident rate roughly halved

| Period | Fatal accidents per 100,000 flight hours | All accidents per 100,000 flight hours |
| --- | --- | --- |
| 1990-1994 (average) | 1.71 | 8.49 |
| 2020-2024 (average) | 0.89 | 5.07 |
| Change | **-48%** | -40% |

2024's fatal accident rate (0.73) is the lowest in the series. Flight hours fell far less than accidents (28.5 million in 1990, 24.8 million in 2024, -13%), so the drop is not just less flying.

*Rates use the NTSB's published counts over FAA flight-hour estimates (BTS Table 2-14, in `reference/`). There are no hour estimates for 1982-84, 1986-89 or 2011.*

```sql
SELECT [year], ntsb_fatal_per_100k_hours, fatal_per_100k_hours FROM dbo.vw_ga_rate_by_year ORDER BY [year];
```

## 2. There are fewer accidents, not milder ones

The share of accidents that were fatal barely moved: **18.6%** in the 1980s, 19.3% in the 1990s, 18.8% in the 2000s, 17.7% in the 2010s and **16.4%** in the 2020s. The improvement came from preventing accidents, not from surviving them more often.

## 3. Instrument weather makes an accident about four times as likely to be fatal

| Weather (NTSB investigator's call) | Accidents | Fatal share |
| --- | --- | --- |
| Visual (VMC) | 73,495 | 15.3% |
| Instrument (IMC) | 4,700 | **63.8%** |

IMC accidents are 6% of accidents but 21% of fatal accidents. At night in IMC, 68.7% are fatal; in daylight VMC, 14.4%. Night alone raises the fatal share from 16.5% (day) to 38.3%.

## 4. Maneuvering is deadly; landing is not

| Phase | Share of accidents | Share of fatal accidents | Fatal share |
| --- | --- | --- | --- |
| Enroute | 19.7% | 29.9% | 28.0% |
| Maneuvering | 13.7% | **28.4%** | 38.3% |
| Approach | 12.3% | 15.8% | 23.8% |
| Initial climb | 12.3% | 14.2% | 21.2% |
| Takeoff | 8.6% | 3.5% | 7.5% |
| Landing | **27.9%** | 2.7% | 1.8% |

Landing is the most common phase for an accident, and the least likely to be fatal. Maneuvering (low passes, turns, aerobatics, aerial application) is half as common but causes more than a quarter of fatal accidents.

*Pre-2008 phases use the NTSB's first-occurrence phase, mapped to the same groups as the 2008+ coding (see `data_dictionary.md`).*

## 5. The most common problems are the most survivable

| Accident type (narrative keyword tag) | Accidents | Fatal share |
| --- | --- | --- |
| Engine power loss | 6,365 | 13.5% |
| Fuel exhaustion/starvation | 4,426 | 10.9% |
| Crosswind | 2,441 | 2.3% |
| Loss of control | 2,961 | 48.8% |
| Stall | 2,013 | 56.4% |
| VFR into IMC | 769 | **81.9%** |
| Impairment (alcohol, drugs) | 604 | **80.0%** |
| Spatial disorientation | 772 | **91.3%** |

When the engine quits or the fuel runs out, the pilot usually still has a controllable aircraft and a forced landing. When a pilot loses track of which way is up, through weather, disorientation or impairment, almost no one survives.

*Tags are keyword rules over the NTSB's probable-cause text (`src/nlp_narratives.py`). They undercount, and pre-2008 narratives are terser, so compare tags within an era rather than across 2008.*

## 6. A simple model confirms it

A logistic regression trained on 1982-2018 accidents ranks a fatal accident above a non-fatal one **84% of the time** (ROC AUC 0.837) on 8,732 accidents from 2019 on that it never saw. A flexible gradient-boosting model does barely better (0.843), so the simple model's odds ratios are a fair summary. Phase of flight carries most of the predictive power. Holding the other factors equal:

- Maneuvering has 13 times the odds of a fatal outcome compared with takeoff.
- IMC has 4.6 times the odds compared with VMC.
- Agricultural flying has a quarter of the odds of personal flying, despite being low-level work. Professional pilots and aircraft designed for that work are plausible reasons, but the data cannot say which.

Full method and every factor: [model_report.md](model_report.md).

## Limits

- These are associations in accident records, not causes, and they describe how bad an accident is once it happens. Accident *risk* per flight needs exposure data by type of flying, which does not exist at this detail.
- The weather call is the NTSB investigator's VMC/IMC classification. Matching each accident to observed station weather (`src/enrich_weather.py`) is on hold.
- Coverage before 2008 uses the NTSB's older coding. Its cause codes are kept separate rather than mapped to the 2008+ taxonomy.
