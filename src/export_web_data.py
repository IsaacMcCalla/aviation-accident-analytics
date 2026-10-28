"""Export the dashboard data to web/data/accidents.db (SQLite) for the web app in web/.

    python src/export_web_data.py

Run after the monthly update (after sql/07_powerbi_views.sql and nlp_narratives.py).
Reads the same dbo.vw_pbi_* views as Power BI, flattens the accident table so the web app
needs no joins, and swaps the new file in at the end so the running site never reads a
half-written file. The site picks up the new data on its next page load.
"""
import datetime
import os
import sqlite3
from contextlib import closing

import pandas as pd

from config import get_connection, log_run, setup_logging

log = setup_logging("export_web_data")

OUT_DIR = os.path.join("web", "data")
OUT_FILE = os.path.join(OUT_DIR, "accidents.db")

QUERIES = {
    "accidents": """
        SELECT a.accident_key, a.ev_id, a.ntsb_no, a.ev_date, c.[year], a.ev_country, a.ev_state, a.ev_city,
               a.latitude, a.longitude, CAST(a.is_us AS int) AS is_us,
               ac.make, ac.model, ac.acft_category, o.far_part, o.operation_name,
               p.phase_name, p.phase_group, p.phase_group_order, w.wx_name AS weather,
               a.light_cond, a.damage, a.highest_injury, CAST(a.is_fatal AS int) AS is_fatal, a.event_fatalities,
               CAST(a.is_primary_aircraft AS int) AS is_primary_aircraft, a.defining_event,
               a.pilot_hours_band, a.pilot_hours_order, a.nearest_airport, a.probable_cause
        FROM dbo.vw_pbi_accident a
        JOIN dbo.vw_pbi_calendar c   ON c.date_key = a.date_key
        JOIN dbo.vw_pbi_aircraft ac  ON ac.aircraft_dim_key = a.aircraft_dim_key
        JOIN dbo.vw_pbi_operation o  ON o.operation_key = a.operation_key
        JOIN dbo.vw_pbi_phase p      ON p.phase_key = a.phase_key
        JOIN dbo.vw_pbi_weather w    ON w.wx_cond_key = a.wx_cond_key""",
    "tags": "SELECT accident_key, ev_id, CAST(is_fatal AS int) AS is_fatal, tag FROM dbo.vw_pbi_tag",
    "findings": "SELECT accident_key, ev_id, finding_category, finding_role FROM dbo.vw_pbi_finding",
    "fleet": "SELECT make, registered_aircraft FROM dbo.vw_pbi_fleet",
}


def read(cur, sql: str) -> pd.DataFrame:
    cur.execute(sql)
    columns = [d[0] for d in cur.description]
    return pd.DataFrame.from_records(cur.fetchall(), columns=columns)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = OUT_FILE + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    conn = get_connection()
    try:
        cur = conn.cursor()
        frames = {name: read(cur, sql) for name, sql in QUERIES.items()}
        frames["accidents"]["ev_date"] = frames["accidents"]["ev_date"].astype(str)
        latest = frames["accidents"]["ev_date"].max()
        frames["meta"] = pd.DataFrame([{
            "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "latest_event": latest,
            "accident_rows": len(frames["accidents"]),
        }])

        # closing(): sqlite3's own "with" commits but leaves the file open, which blocks os.replace on Windows
        with closing(sqlite3.connect(tmp)) as lite:
            for name, df in frames.items():
                df.to_sql(name, lite, index=False)
            lite.execute("CREATE INDEX ix_tags_key ON tags (accident_key)")
            lite.execute("CREATE INDEX ix_findings_key ON findings (accident_key)")
            lite.commit()
        os.replace(tmp, OUT_FILE)

        summary = ", ".join(f"{n}={len(df)}" for n, df in frames.items() if n != "meta")
        log.info("done: %s, latest event %s -> %s", summary, latest, OUT_FILE)
        log_run(conn, "web_export", "OK", len(frames["accidents"]), summary)
    except Exception as exc:
        log.exception("web export failed")
        log_run(conn, "web_export", "FAILED", 0, str(exc))
        raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
