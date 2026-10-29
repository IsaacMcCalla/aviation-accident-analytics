"""Copy tables from the NTSB Access files into the stg_ntsb_* staging tables.

Two ways to read the Access files:

    python src/extract_ntsb.py data/ntsb/avall.mdb data/ntsb/Pre2008.mdb
        Needs the Microsoft Access Database Engine (64-bit if your Python is 64-bit),
        which provides the "Microsoft Access Driver (*.mdb, *.accdb)" ODBC driver.

    python src/extract_ntsb.py --csv-dir data/ntsb/csv
        Reads <table>.csv files exported with mdbtools (see docs/runbook_failed_ingestion.md).

Give the files newest first: an event that appears in more than one file is loaded from the
first file only. Pre2008.mdb is optional; without it, the project covers 2008 onward.
Add --from-year 2023 to load a small slice first.
Staging is a full refresh: each staging table is emptied, then reloaded. Every value is
staged as text; sql/02_transform.sql does the type conversion.
Column names have shifted between NTSB releases. Missing columns load as NULL and are logged.
"""
import argparse
import datetime
import os

import pandas as pd
import pyodbc

from config import get_connection, insert_sql, log_run, setup_logging

log = setup_logging("extract_ntsb")

ACCESS_DRIVER = "Microsoft Access Driver (*.mdb, *.accdb)"


def same(*columns):
    """Source columns whose staging name is the lowercase source name."""
    return {c: c.lower() for c in columns}


# source table -> (staging table, {source column: staging column}). events must come first.
TABLES = {
    "events": ("stg_ntsb_events", same(
        "ev_id", "ntsb_no", "ev_type", "ev_date", "ev_time", "ev_city", "ev_state", "ev_country",
        "latitude", "longitude", "dec_latitude", "dec_longitude", "ev_nr_apt_id", "apt_name",
        "ev_highest_injury", "inj_tot_f", "inj_tot_s", "inj_tot_m", "inj_tot_n",
        "light_cond", "wx_cond_basic", "wind_vel_kts", "vis_sm", "mid_air", "ev_tmzn", "wx_obs_fac_id")),
    "aircraft": ("stg_ntsb_aircraft", same(
        "ev_id", "Aircraft_Key", "regis_no", "acft_make", "acft_model", "acft_category",
        "damage", "far_part", "type_fly", "num_eng", "homebuilt", "oper_sched")),
    "events_sequence": ("stg_ntsb_events_sequence", same(
        "ev_id", "Aircraft_Key", "Occurrence_No", "Occurrence_Code", "Occurrence_Description",
        "phase_no", "eventsoe_no", "Defining_ev")),
    "Findings": ("stg_ntsb_findings", same(
        "ev_id", "Aircraft_Key", "finding_no", "finding_code", "finding_description", "Cause_Factor")),
    "narratives": ("stg_ntsb_narratives", same("ev_id", "Aircraft_Key", "narr_accp", "narr_cause")),
    "injury": ("stg_ntsb_injury", same(
        "ev_id", "Aircraft_Key", "inj_person_category", "injury_level", "inj_person_count")),
    "Flight_Crew": ("stg_ntsb_flight_crew", same("ev_id", "Aircraft_Key", "crew_no", "crew_category", "crew_age")),
    "flight_time": ("stg_ntsb_flight_time", same(
        "ev_id", "Aircraft_Key", "crew_no", "flight_type", "flight_craft", "flight_hours")),
    # Code lookup table that ships in each file
    "eADMSPUB_DataDictionary": ("stg_ntsb_codes", {
        "Table": "table_name", "Column": "column_name", "code_iaids": "code", "meaning": "meaning"}),
    # Pre-2008 coding, only in Pre2008.mdb: phase of flight and causes/factors
    "Occurrences": ("stg_ntsb_occurrences", same(
        "ev_id", "Aircraft_Key", "Occurrence_No", "Occurrence_Code", "Phase_of_Flight")),
    "seq_of_events": ("stg_ntsb_seq_of_events", same(
        "ev_id", "Aircraft_Key", "Occurrence_No", "seq_event_no", "group_code", "Subj_Code", "Cause_Factor")),
    "ct_seqevt": ("stg_ntsb_ct_seqevt", same("code", "meaning")),
}
OPTIONAL = {"eADMSPUB_DataDictionary", "Occurrences", "seq_of_events", "ct_seqevt"}
BATCH = 20_000


class AccessSource:
    def __init__(self, path: str):
        self.conn = pyodbc.connect(f"DRIVER={{{ACCESS_DRIVER}}};DBQ={os.path.abspath(path)};")

    def tables(self) -> dict:
        return {r.table_name.lower(): r.table_name for r in self.conn.cursor().tables(tableType="TABLE")}

    def columns(self, table: str) -> list:
        cur = self.conn.cursor()
        cur.execute(f"SELECT * FROM [{table}] WHERE 1=0")
        return [d[0] for d in cur.description]

    def rows(self, table: str, columns: list):
        cur = self.conn.cursor()
        cur.execute(f"SELECT {', '.join(f'[{c}]' for c in columns)} FROM [{table}]")
        while batch := cur.fetchmany(BATCH):
            yield batch


class CsvSource:
    def __init__(self, folder: str):
        self.paths = {os.path.splitext(f)[0].lower(): os.path.join(folder, f)
                      for f in os.listdir(folder) if f.lower().endswith(".csv")}

    def tables(self) -> dict:
        return {name: name for name in self.paths}

    def columns(self, table: str) -> list:
        return list(pd.read_csv(self.paths[table], nrows=0).columns)

    def rows(self, table: str, columns: list):
        for chunk in pd.read_csv(self.paths[table], usecols=columns, dtype=str,
                                 keep_default_na=False, chunksize=BATCH):
            yield chunk[columns].itertuples(index=False, name=None)


def to_text(value):
    """Stage every value as trimmed text; empty strings become NULL."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, datetime.datetime):
        return value.date().isoformat() if value.time() == datetime.time() else value.isoformat(sep=" ")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    return text or None


def load_table(src, conn, src_table: str, stg_table: str, colmap: dict, keep=None) -> tuple:
    """Append src_table to stg_table. keep(ev_id) -> bool filters rows when given.
    Returns (rows loaded, set of ev_ids loaded)."""
    available = {c.lower(): c for c in src.columns(src_table)}
    picked = [(available[s.lower()], dst) for s, dst in colmap.items() if s.lower() in available]
    missing = [s for s in colmap if s.lower() not in available]
    if missing:
        log.warning("%s: columns not found, loaded as NULL: %s", src_table, ", ".join(missing))
    if not picked:
        raise RuntimeError(f"{src_table}: none of the expected columns exist")
    src_cols = [s for s, _ in picked]
    stg_cols = [d for _, d in picked]
    ev_pos = stg_cols.index("ev_id") if "ev_id" in stg_cols else None

    cur = conn.cursor()
    # fast_executemany buffers whole batches; it struggles with nvarchar(max) narratives
    cur.fast_executemany = stg_table != "stg_ntsb_narratives"
    sql = insert_sql(stg_table, stg_cols)
    total, ev_ids = 0, set()
    for batch in src.rows(src_table, src_cols):
        values = [tuple(to_text(v) for v in row) for row in batch]
        if keep is not None and ev_pos is not None:
            values = [v for v in values if keep(v[ev_pos])]
        if values:
            cur.executemany(sql, values)
            total += len(values)
            if ev_pos is not None:
                ev_ids.update(v[ev_pos] for v in values)
    conn.commit()
    return total, ev_ids


def trim_events(conn, from_year: int) -> set:
    """Keep only events from from_year onward; return the ev_ids left in staging."""
    cur = conn.cursor()
    cur.execute("DELETE dbo.stg_ntsb_events WHERE ISNULL(TRY_CAST(ev_date AS date), '19000101') < DATEFROMPARTS(?, 1, 1)",
                from_year)
    conn.commit()
    return {r.ev_id for r in cur.execute("SELECT ev_id FROM dbo.stg_ntsb_events").fetchall()}


def load_source(src, conn, seen: set, from_year, counts: dict) -> set:
    """Load one Access file (or CSV folder). Events whose ev_id is in seen came from an earlier
    file and are skipped, along with their child rows. Returns the ev_ids this file added."""
    names = src.tables()
    event_ids = set()  # ev_ids this file added to staging
    file_ids = None    # when set, child rows are filtered to these ev_ids
    for src_table, (stg_table, colmap) in TABLES.items():
        actual = names.get(src_table.lower())
        if actual is None:
            if src_table in OPTIONAL:
                log.info("table %s not in this file, skipped", src_table)
                continue
            raise RuntimeError(f"table {src_table} not found in the source")
        # code tables (no ev_id) load from every file; each file names its own codes
        if src_table == "events":
            keep = (lambda e: e not in seen) if seen else None
        else:
            keep = file_ids.__contains__ if file_ids is not None else None
        n, ids = load_table(src, conn, actual, stg_table, colmap, keep)

        if src_table == "events":
            event_ids = ids & trim_events(conn, from_year) if from_year else ids
            n = len(event_ids)
            # filter child rows only when some of this file's events were skipped or trimmed,
            # so orphan child rows still reach staging (and the data quality check) otherwise
            file_ids = event_ids if (from_year or seen) else None
        counts[stg_table] = counts.get(stg_table, 0) + n
        log.info("loaded %s -> %s: %d rows", actual, stg_table, n)
    return event_ids


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mdb", nargs="*", help="Access files, newest first (avall.mdb, then Pre2008.mdb)")
    parser.add_argument("--csv-dir", action="append", help="folder of <table>.csv files exported with mdbtools; repeat for more")
    parser.add_argument("--from-year", type=int, help="load only events from this year onward")
    args = parser.parse_args()
    if bool(args.mdb) == bool(args.csv_dir):
        parser.error("give either .mdb paths or --csv-dir")

    conn = get_connection()
    counts = {}
    try:
        cur = conn.cursor()
        for stg_table in {t for t, _ in TABLES.values()}:
            cur.execute(f"TRUNCATE TABLE dbo.{stg_table}")
        conn.commit()

        seen = set()
        for path in args.mdb or args.csv_dir:
            log.info("reading %s", path)
            src = AccessSource(path) if args.mdb else CsvSource(path)
            seen |= load_source(src, conn, seen, args.from_year, counts)
        summary = ", ".join(f"{t.replace('stg_ntsb_', '')}={n}" for t, n in counts.items())
        log_run(conn, "ntsb", "OK", sum(counts.values()), summary)
        log.info("done: %s", summary)
    except Exception as exc:
        log.exception("NTSB extract failed")
        log_run(conn, "ntsb", "FAILED", sum(counts.values()), str(exc))
        raise SystemExit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
