"""Match each U.S. accident to the weather report from a nearby station at the time it happened.

    python src/enrich_weather.py              # events not matched yet (the monthly run)
    python src/enrich_weather.py --limit 200  # a small test batch
    python src/enrich_weather.py --rebuild    # clear dbo.fact_event_weather and match everything

Source: the Iowa Environmental Mesonet (IEM) ASOS archive, a free public service of Iowa State
University (mesonet.agron.iastate.edu). This script sends one small request per accident date,
one at a time with a pause between them; keep it that way. The first full run takes about an hour.

How a station is chosen, per event (primary aircraft of U.S. accidents with coordinates and a time):
  1. the station the NTSB named in its report (events.wx_obs_fac_id), if IEM has it within 50 km;
  2. otherwise the nearest stations that were reporting that day, within 40 km.
The report closest in time, within 90 minutes, from the first station that has one is kept.
NTSB event dates and times are UTC, like the IEM archive.
"""
import argparse
import csv
import io
import json
import math
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import get_connection, insert_sql, log_run, setup_logging

log = setup_logging("enrich_weather")

IEM = "https://mesonet.agron.iastate.edu"
STATION_CACHE = os.path.join("data", "iem", "stations.json")
NTSB_STATION_KM = 50
NEAREST_KM = 40
CANDIDATES = 2          # nearest stations tried when the NTSB's station has no report
MAX_MINUTES = 90
PAUSE_SECONDS = 0.25    # between requests, to stay polite to the public service
FIELDS = ["tmpf", "dwpf", "sknt", "gust", "vsby", "skyc1", "skyc2", "skyc3", "skyc4",
          "skyl1", "skyl2", "skyl3", "skyl4", "wxcodes"]
COLUMNS = ["ev_id", "station", "station_choice", "distance_km", "obs_time_utc", "minutes_from_event",
           "temp_c", "dewpoint_c", "wind_kt", "gust_kt", "visibility_sm", "ceiling_ft",
           "flight_category", "wx_codes"]

EVENTS_SQL = """
SELECT f.ev_id, f.ev_date, TRY_CAST(e.ev_time AS int) AS hhmm, f.latitude, f.longitude, e.wx_obs_fac_id
FROM dbo.fact_accident f
JOIN dbo.vw_stg_events_clean e ON e.ev_id = f.ev_id
WHERE f.is_primary_aircraft = 1
  AND f.ev_type = 'ACC'
  AND f.ev_country = 'USA'
  AND f.latitude IS NOT NULL AND f.longitude IS NOT NULL
  AND TRY_CAST(e.ev_time AS int) BETWEEN 0 AND 2359
  AND TRY_CAST(e.ev_time AS int) % 100 < 60
  AND NOT EXISTS (SELECT 1 FROM dbo.fact_event_weather w WHERE w.ev_id = f.ev_id)
ORDER BY f.ev_date
"""


def make_session() -> requests.Session:
    retry = Retry(total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = "aviation-accident-analytics (portfolio project)"
    return s


# ------------------------------------------------------------------ stations
def to_date(text):
    return date.fromisoformat(text[:10]) if text else None


def load_stations(session) -> list:
    """U.S. ASOS/AWOS stations from IEM (one network per state or territory), cached for 30 days."""
    if os.path.exists(STATION_CACHE) and time.time() - os.path.getmtime(STATION_CACHE) < 30 * 86400:
        with open(STATION_CACHE) as f:
            return json.load(f)
    networks = session.get(f"{IEM}/geojson/networks.geojson", timeout=60).json()["features"]
    names = sorted(n["id"] for n in networks if re.fullmatch(r"[A-Z]{2}_ASOS", n["id"]))
    stations = []
    for name in names:
        for feat in session.get(f"{IEM}/geojson/network/{name}.geojson", timeout=60).json()["features"]:
            lon, lat = feat["geometry"]["coordinates"]
            props = feat["properties"]
            stations.append({"id": feat["id"], "lat": lat, "lon": lon,
                             "begin": props.get("archive_begin"), "end": props.get("archive_end")})
        time.sleep(PAUSE_SECONDS)
    os.makedirs(os.path.dirname(STATION_CACHE), exist_ok=True)
    with open(STATION_CACHE, "w") as f:
        json.dump(stations, f)
    log.info("cached %d stations from %d networks", len(stations), len(names))
    return stations


class StationIndex:
    def __init__(self, stations: list):
        self.ids = [s["id"] for s in stations]
        self.pos = {sid: i for i, sid in enumerate(self.ids)}
        self.lat = np.radians([s["lat"] for s in stations])
        self.lon = np.radians([s["lon"] for s in stations])
        far_past, far_future = date(1900, 1, 1), date(2100, 1, 1)
        self.begin = np.array([(to_date(s["begin"]) or far_past).toordinal() for s in stations])
        self.end = np.array([(to_date(s["end"]) or far_future).toordinal() for s in stations])

    def distances_km(self, lat, lon) -> np.ndarray:
        lat, lon = math.radians(lat), math.radians(lon)
        a = (np.sin((self.lat - lat) / 2) ** 2
             + math.cos(lat) * np.cos(self.lat) * np.sin((self.lon - lon) / 2) ** 2)
        return 6371.0 * 2 * np.arcsin(np.sqrt(a))

    def candidates(self, lat, lon, day: date, ntsb_id) -> list:
        """[(station, choice, km)] in the order to try them."""
        dist = self.distances_km(lat, lon)
        out = []
        ntsb = (ntsb_id or "").strip().upper()
        ntsb = ntsb[1:] if len(ntsb) == 4 and ntsb.startswith("K") else ntsb   # KVNY -> VNY
        if ntsb in self.pos and dist[self.pos[ntsb]] <= NTSB_STATION_KM:
            out.append((ntsb, "ntsb", float(dist[self.pos[ntsb]])))
        active = (self.begin <= day.toordinal()) & (self.end >= day.toordinal()) & (dist <= NEAREST_KM)
        for i in np.where(active)[0][np.argsort(dist[active])][:CANDIDATES]:
            if self.ids[i] != ntsb:
                out.append((self.ids[i], "nearest", float(dist[i])))
        return out


# ------------------------------------------------------------------ reports
def to_float(value):
    if value in (None, "", "M", "T"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def lowest_ceiling(rec):
    bases = [to_float(rec.get(f"skyl{i}")) for i in range(1, 5)
             if rec.get(f"skyc{i}") in ("BKN", "OVC", "VV")]
    bases = [b for b in bases if b is not None]
    return int(min(bases)) if bases else None


def flight_category(vis_sm, ceiling_ft):
    """FAA flight category from visibility (statute miles) and ceiling (feet)."""
    vis = 99.0 if vis_sm is None else vis_sm
    ceil = 99999 if ceiling_ft is None else ceiling_ft
    if vis < 1 or ceil < 500:
        return "LIFR"
    if vis < 3 or ceil < 1000:
        return "IFR"
    if vis <= 5 or ceil <= 3000:
        return "MVFR"
    return "VFR"


def fetch_reports(session, stations, day: date) -> dict:
    """{station: [(time, record), ...]} from 2 hours before to 2 hours after the UTC day."""
    start = datetime.combine(day, datetime.min.time()) - timedelta(hours=2)
    end = start + timedelta(hours=28)
    params = [("station", s) for s in sorted(stations)] + [("data", f) for f in FIELDS]
    params += [("sts", f"{start:%Y-%m-%dT%H:%MZ}"), ("ets", f"{end:%Y-%m-%dT%H:%MZ}"), ("tz", "Etc/UTC"),
               ("format", "onlycomma"), ("latlon", "no"), ("missing", "M"), ("trace", "T"),
               ("direct", "no"), ("report_type", "3"), ("report_type", "4")]
    resp = session.get(f"{IEM}/cgi-bin/request/asos.py", params=params, timeout=120)
    resp.raise_for_status()
    reports = defaultdict(list)
    for rec in csv.DictReader(io.StringIO(resp.text)):
        if rec.get("valid"):
            reports[rec["station"]].append((datetime.strptime(rec["valid"], "%Y-%m-%d %H:%M"), rec))
    return reports


def match(ev_id, when: datetime, candidates, reports) -> tuple:
    for station, choice, km in candidates:
        best = min(reports.get(station, []), key=lambda r: abs(r[0] - when), default=None)
        if best and abs(best[0] - when) <= timedelta(minutes=MAX_MINUTES):
            obs_time, rec = best
            tmpf, dwpf = to_float(rec.get("tmpf")), to_float(rec.get("dwpf"))
            vis, ceil = to_float(rec.get("vsby")), lowest_ceiling(rec)
            wind, gust = to_float(rec.get("sknt")), to_float(rec.get("gust"))
            wx = rec.get("wxcodes")
            return (ev_id, station, choice, round(km, 1), obs_time,
                    int((obs_time - when).total_seconds() // 60),
                    None if tmpf is None else round((tmpf - 32) * 5 / 9, 1),
                    None if dwpf is None else round((dwpf - 32) * 5 / 9, 1),
                    None if wind is None else int(wind), None if gust is None else int(gust),
                    vis, ceil, flight_category(vis, ceil),
                    None if wx in (None, "", "M") else wx[:60])
    return (ev_id, None, "none", None, None, None, None, None, None, None, None, None, None, None)


# ---------------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="clear dbo.fact_event_weather first")
    parser.add_argument("--limit", type=int, help="match at most this many events (testing)")
    args = parser.parse_args()

    session = make_session()
    conn = get_connection()
    cur = conn.cursor()
    total = matched = 0
    try:
        if args.rebuild:
            cur.execute("TRUNCATE TABLE dbo.fact_event_weather")
            conn.commit()
        index = StationIndex(load_stations(session))
        events = cur.execute(EVENTS_SQL).fetchall()[:args.limit]
        by_day = defaultdict(list)
        for ev in events:
            when = datetime.combine(ev.ev_date, datetime.min.time()) + timedelta(hours=ev.hhmm // 100,
                                                                                 minutes=ev.hhmm % 100)
            by_day[ev.ev_date].append((ev.ev_id, when, index.candidates(ev.latitude, ev.longitude,
                                                                        ev.ev_date, ev.wx_obs_fac_id)))
        log.info("%d events on %d dates to match", len(events), len(by_day))

        sql = insert_sql("fact_event_weather", COLUMNS)
        for n, (day, day_events) in enumerate(sorted(by_day.items()), 1):
            stations = {s for _, _, cands in day_events for s, _, _ in cands}
            reports = fetch_reports(session, stations, day) if stations else {}
            rows = [match(ev_id, when, cands, reports) for ev_id, when, cands in day_events]
            cur.executemany(sql, rows)
            conn.commit()   # per day, so an interrupted run resumes where it stopped
            total += len(rows)
            matched += sum(r[1] is not None for r in rows)
            if n % 250 == 0:
                log.info("%d/%d dates, %d events, %d matched (%.0f%%)", n, len(by_day), total, matched,
                         100 * matched / max(total, 1))
            if stations:
                time.sleep(PAUSE_SECONDS)
        message = f"{total} events, {matched} matched to a report"
        log_run(conn, "weather", "OK", total, message)
        log.info("done: %s", message)
    except Exception as exc:
        log.exception("weather enrichment failed")
        log_run(conn, "weather", "FAILED", total, str(exc)[:500])
        raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
