"""Load U.S. general aviation flight hours and NTSB GA accident counts into dbo.ref_ga_hours.

    python src/load_ga_hours.py                      # reads reference/ga_activity_bts_table_2_14.csv
    python src/load_ga_hours.py <other.csv>

The CSV is a copy of BTS National Transportation Statistics Table 2-14 (sources are in its
header). To add a new year, append a row from the latest edition of that table and re-run.
Hours are stored as whole hours (the table gives thousands).
"""
import sys

import pandas as pd

from config import get_connection, insert_sql, log_run, setup_logging

log = setup_logging("load_ga_hours")

DEFAULT_PATH = "reference/ga_activity_bts_table_2_14.csv"
SOURCE = "BTS NTS Table 2-14 (NTSB accident statistics; FAA GA survey hours)"
COLUMNS = ["year", "ga_hours", "ntsb_accidents", "ntsb_fatal_accidents", "ntsb_fatalities", "source"]


def read_rows(path: str) -> list:
    df = pd.read_csv(path, comment="#")
    hours = (df["flight_hours_thousands"] * 1000).round()
    rows = []
    for rec, h in zip(df.itertuples(index=False), hours):
        rows.append((int(rec.year), None if pd.isna(h) else int(h), int(rec.ntsb_accidents),
                     int(rec.ntsb_fatal_accidents), int(rec.ntsb_fatalities), SOURCE))
    return rows


def main(path):
    conn = get_connection()
    try:
        rows = read_rows(path)
        cur = conn.cursor()
        cur.execute("DELETE dbo.ref_ga_hours")
        cur.executemany(insert_sql("ref_ga_hours", [f"[{c}]" if c == "year" else c for c in COLUMNS]), rows)
        conn.commit()
        log.info("loaded %d years from %s", len(rows), path)
        log_run(conn, "ga_hours", "OK", len(rows), f"loaded {path}")
    except Exception as exc:
        log.exception("GA hours load failed")
        log_run(conn, "ga_hours", "FAILED", 0, str(exc))
        raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)
