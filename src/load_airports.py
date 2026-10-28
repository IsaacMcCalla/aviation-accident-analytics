"""Load U.S. airports into dbo.stg_airports (sql/02_transform.sql builds dim_airport from it).

1. Download airports.csv from OurAirports (ourairports.com/data, public domain) into data/.
2. python src/load_airports.py data/airports.csv

NTSB events name the nearest airport by its FAA identifier (ev_nr_apt_id), which matches
OurAirports' local_code for U.S. airports.
"""
import sys

import pandas as pd

from config import get_connection, insert_sql, log_run, setup_logging

log = setup_logging("load_airports")

COLUMNS = ["ident", "type", "name", "latitude_deg", "longitude_deg", "iso_region",
           "municipality", "iata_code", "local_code", "gps_code"]


def main(path):
    if not path:
        sys.exit("usage: python src/load_airports.py data/airports.csv")
    conn = get_connection()
    cur = conn.cursor()
    cur.fast_executemany = True
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, usecols=COLUMNS + ["iso_country"])
        df = df[df["iso_country"] == "US"][COLUMNS]
        df = df.apply(lambda s: s.str.strip())
        df = df.astype(object).where(df.ne(""), None)
        rows = list(df.itertuples(index=False, name=None))
        cur.execute("TRUNCATE TABLE dbo.stg_airports")
        cur.executemany(insert_sql("stg_airports", COLUMNS), rows)
        conn.commit()
        log.info("loaded %d U.S. airports", len(rows))
        log_run(conn, "airports", "OK", len(rows), f"loaded {path}")
    except Exception as exc:
        log.exception("airport load failed")
        log_run(conn, "airports", "FAILED", 0, str(exc))
        raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
