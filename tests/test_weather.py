"""enrich_weather.py: flight categories, ceilings, station choice and report matching."""
from datetime import date, datetime, timedelta

from enrich_weather import StationIndex, flight_category, lowest_ceiling, match


def test_flight_category_thresholds():
    assert flight_category(10, None) == "VFR"
    assert flight_category(5, None) == "MVFR"
    assert flight_category(10, 3000) == "MVFR"
    assert flight_category(2.5, 1300) == "IFR"
    assert flight_category(0.5, None) == "LIFR"
    assert flight_category(None, 400) == "LIFR"
    assert flight_category(None, None) == "VFR"


def test_lowest_ceiling_uses_broken_and_overcast_layers_only():
    rec = {"skyc1": "FEW", "skyl1": "800", "skyc2": "BKN", "skyl2": "2500", "skyc3": "OVC", "skyl3": "1800",
           "skyc4": "M", "skyl4": "M"}
    assert lowest_ceiling(rec) == 1800
    assert lowest_ceiling({"skyc1": "SCT", "skyl1": "900"}) is None


STATIONS = [
    {"id": "AAA", "lat": 40.00, "lon": -100.00, "begin": "1990-01-01", "end": None},
    {"id": "BBB", "lat": 40.10, "lon": -100.00, "begin": "1990-01-01", "end": None},   # ~11 km north
    {"id": "OLD", "lat": 40.01, "lon": -100.00, "begin": "1980-01-01", "end": "1995-01-01"},
    {"id": "FAR", "lat": 41.00, "lon": -100.00, "begin": "1990-01-01", "end": None},   # ~111 km
]


def test_candidates_prefer_the_ntsb_station_then_nearest_active():
    index = StationIndex(STATIONS)
    cands = index.candidates(40.0, -100.0, date(2020, 6, 1), "KBBB")
    assert [(s, c) for s, c, _ in cands] == [("BBB", "ntsb"), ("AAA", "nearest")]   # K prefix stripped; OLD closed


def test_candidates_include_stations_open_on_the_day_only():
    index = StationIndex(STATIONS)
    assert [s for s, _, _ in index.candidates(40.0, -100.0, date(1992, 6, 1), None)] == ["AAA", "OLD"]
    assert index.candidates(43.0, -100.0, date(2020, 6, 1), None) == []   # nothing within 40 km


def report(t, **fields):
    return (t, {"tmpf": "50", "dwpf": "40", "sknt": "8", "gust": "M", "vsby": "10", "skyc1": "CLR", "skyl1": "M",
                "wxcodes": "M", **fields})


def test_match_takes_the_closest_report_from_the_first_station_that_has_one():
    when = datetime(2020, 6, 1, 12, 0)
    reports = {"BBB": [report(when + timedelta(minutes=55), vsby="2", skyc1="OVC", skyl1="700"),
                       report(when - timedelta(minutes=20), vsby="3", skyc1="BKN", skyl1="900")]}
    row = match("E1", when, [("AAA", "ntsb", 1.0), ("BBB", "nearest", 11.1)], reports)
    assert row[1:3] == ("BBB", "nearest")                 # AAA had no reports
    assert row[5] == -20                                  # minutes from event
    assert row[11:13] == (900, "IFR")                     # ceiling, category
    assert row[6] == 10.0                                 # 50 F in C


def test_match_records_no_report_when_none_is_within_90_minutes():
    when = datetime(2020, 6, 1, 12, 0)
    row = match("E2", when, [("AAA", "nearest", 1.0)], {"AAA": [report(when + timedelta(minutes=91))]})
    assert row[0] == "E2" and row[1] is None and row[2] == "none"
