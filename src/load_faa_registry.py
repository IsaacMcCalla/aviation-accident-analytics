"""Load the FAA aircraft registry into staging (used to normalize accident counts by fleet size).

1. Download ReleasableAircraft.zip from the FAA aircraft registry "download the database"
   page and unzip it into data/faa/.
2. python src/load_faa_registry.py data/faa

Only aircraft and model fields are loaded. Registrant names and addresses are personal
data and are skipped on purpose. Check the header names against your download.
"""
import os
import sys

import pandas as pd

from config import get_connection, insert_sql, log_run, setup_logging

log = setup_logging("load_faa_registry")

# file -> (staging table, {FAA column: staging column})
FILES = {
    "MASTER.txt": ("stg_faa_master", {
        "N-NUMBER": "n_number", "MFR MDL CODE": "mfr_mdl_code", "YEAR MFR": "year_mfr",
        "TYPE AIRCRAFT": "type_aircraft", "TYPE ENGINE": "type_engine", "STATUS CODE": "status_code"}),
    "ACFTREF.txt": ("stg_faa_acftref", {
        "CODE": "code", "MFR": "mfr", "MODEL": "model", "TYPE-ACFT": "type_acft",
        "TYPE-ENG": "type_eng", "AC-CAT": "ac_cat", "NO-ENG": "no_eng", "NO-SEATS": "no_seats"}),
}


def read_faa(path: str, columns: dict) -> list:
    # FAA files pad values with spaces, end each line with a comma, and may start with a BOM
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False,
                     usecols=lambda c: c.strip() in columns)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=columns)[list(columns.values())]
    df = df.apply(lambda s: s.str.strip())
    df = df.astype(object).where(df.ne(""), None)
    return list(df.itertuples(index=False, name=None))


def main(folder):
    if not folder:
        sys.exit("usage: python src/load_faa_registry.py data/faa")
    conn = get_connection()
    cur = conn.cursor()
    cur.fast_executemany = True
    total = 0
    try:
        for filename, (table, columns) in FILES.items():
            rows = read_faa(os.path.join(folder, filename), columns)
            cur.execute(f"TRUNCATE TABLE dbo.{table}")
            cur.executemany(insert_sql(table, list(columns.values())), rows)
            conn.commit()
            total += len(rows)
            log.info("loaded %s -> %s: %d rows", filename, table, len(rows))
        log_run(conn, "faa_registry", "OK", total, f"loaded {len(FILES)} files")
    except Exception as exc:
        log.exception("FAA registry load failed")
        log_run(conn, "faa_registry", "FAILED", total, str(exc))
        raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
