"""Checks against the local SQL Server database (skipped when it cannot be reached, as on GitHub).

Run after a load to confirm the whole chain agrees: quality checks, counting rules, the GA
definition against the NTSB's published counts, and the web snapshot against the database.
"""
import sqlite3
from contextlib import closing

import pytest

from conftest import SNAPSHOT

pytestmark = pytest.mark.db


def rows(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    return cur.fetchall()


def test_data_quality_checks_have_no_failures(db):
    failed = [r for r in rows(db, "EXEC dbo.usp_check_data_quality") if r[1] == "FAIL"]
    assert not failed, failed


def test_ga_counts_match_the_ntsb_within_5_percent(db):
    off = rows(db, "SELECT [year], ga_accidents, ntsb_accidents FROM dbo.vw_ga_rate_by_year "
                   "WHERE ntsb_accidents > 0 AND ABS(1.0 * ga_accidents / ntsb_accidents - 1) > 0.05")
    assert not off, off


def test_pre_2008_events_have_phases(db):
    unknown_share = rows(db, """
        SELECT 1.0 * SUM(CASE WHEN p.phase_code = 'UNK' THEN 1 ELSE 0 END) / COUNT(*)
        FROM dbo.fact_accident f JOIN dbo.dim_phase p ON p.phase_key = f.phase_key
        WHERE f.ev_date < '20080101'""")[0][0]
    assert unknown_share < 0.05


def test_web_snapshot_matches_the_database(db):
    """The published snapshot should hold the same accidents as the database (re-export if this fails)."""
    expected = rows(db, "SELECT COUNT(*), COUNT(DISTINCT ev_id), SUM(CAST(is_fatal AS int)) FROM dbo.vw_pbi_accident")[0]
    with closing(sqlite3.connect(f"file:{SNAPSHOT}?mode=ro", uri=True)) as lite:
        actual = lite.execute("SELECT COUNT(*), COUNT(DISTINCT ev_id), SUM(is_fatal) FROM accidents").fetchone()
    assert tuple(actual) == tuple(expected)
