"""extract_ntsb.py: value conversion and loading several Access files without duplicates."""
import datetime

import extract_ntsb
from extract_ntsb import load_source, to_text


def test_to_text_converts_values_to_trimmed_text():
    assert to_text(None) is None
    assert to_text("  ") is None
    assert to_text(" KDEN ") == "KDEN"
    assert to_text(True) == "1" and to_text(False) == "0"
    assert to_text(3.0) == "3"
    assert to_text(2.5) == "2.5"
    assert to_text(datetime.datetime(2024, 5, 1)) == "2024-05-01"
    assert to_text(datetime.datetime(2024, 5, 1, 13, 45)) == "2024-05-01 13:45:00"
    assert to_text(datetime.date(1999, 12, 31)) == "1999-12-31"


class FakeSource:
    """Stands in for an Access file: {table: [row dicts]}."""

    def __init__(self, tables):
        self.data = tables

    def tables(self):
        return {name.lower(): name for name in self.data}

    def columns(self, table):
        return list(self.data[table][0]) if self.data[table] else ["ev_id"]

    def rows(self, table, columns):
        yield [tuple(r.get(c) for c in columns) for r in self.data[table]]


class FakeCursor:
    def __init__(self, inserted):
        self.inserted = inserted
        self.fast_executemany = False

    def executemany(self, sql, values):
        table = sql.split()[1].removeprefix("dbo.")
        self.inserted.setdefault(table, []).extend(values)


class FakeConn:
    def __init__(self):
        self.inserted = {}

    def cursor(self):
        return FakeCursor(self.inserted)

    def commit(self):
        pass


def make_file(ev_ids, aircraft_ev_ids=None):
    """A minimal NTSB file: events, aircraft and the other required tables."""
    tables = {name: [] for name, _ in extract_ntsb.TABLES.items() if name not in extract_ntsb.OPTIONAL}
    tables["events"] = [{"ev_id": e, "ev_date": "2001-01-01"} for e in ev_ids]
    tables["aircraft"] = [{"ev_id": e, "Aircraft_Key": 1} for e in (aircraft_ev_ids or ev_ids)]
    return FakeSource(tables)


def test_later_file_skips_events_already_loaded_and_their_child_rows():
    conn, counts = FakeConn(), {}
    seen = load_source(make_file(["A", "B"]), conn, set(), None, counts)
    assert seen == {"A", "B"}
    added = load_source(make_file(["B", "C"]), conn, seen, None, counts)
    assert added == {"C"}
    assert [r[0] for r in conn.inserted["stg_ntsb_events"]] == ["A", "B", "C"]
    assert [r[0] for r in conn.inserted["stg_ntsb_aircraft"]] == ["A", "B", "C"]   # B's aircraft not loaded twice
    assert counts["stg_ntsb_events"] == 3


def test_first_file_keeps_orphan_child_rows_for_the_quality_check():
    conn = FakeConn()
    load_source(make_file(["A"], aircraft_ev_ids=["A", "ORPHAN"]), conn, set(), None, {})
    assert {r[0] for r in conn.inserted["stg_ntsb_aircraft"]} == {"A", "ORPHAN"}


def test_optional_tables_may_be_missing():
    # make_file has no Occurrences / seq_of_events / ct_seqevt / code table, like avall.mdb
    load_source(make_file(["A"]), FakeConn(), set(), None, {})
