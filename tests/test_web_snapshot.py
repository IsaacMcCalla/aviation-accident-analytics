"""The published web snapshot (web/data/accidents.db) and the web app that reads it.

These run on GitHub Actions too: the snapshot is committed, so no database is needed.
"""
import sqlite3
from contextlib import closing

import pytest

from conftest import ROOT, SNAPSHOT

TABLES = {"accidents", "tags", "findings", "finding_categories", "fleet", "rates", "model_factors", "model_run", "meta"}


@pytest.fixture(scope="module")
def lite():
    with closing(sqlite3.connect(f"file:{SNAPSHOT}?mode=ro", uri=True)) as conn:
        yield conn


def one(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_snapshot_has_every_table(lite):
    names = {r[0] for r in lite.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert TABLES <= names


def test_one_row_per_aircraft_and_one_primary_aircraft_per_event(lite):
    assert one(lite, "SELECT COUNT(*) - COUNT(DISTINCT accident_key) FROM accidents") == 0
    assert one(lite, "SELECT COUNT(*) FROM (SELECT ev_id FROM accidents GROUP BY ev_id "
                     "HAVING SUM(is_primary_aircraft) <> 1)") == 0


def test_fatal_flag_and_fatality_counts_agree(lite):
    # an event with deaths is fatal; fatalities are counted once per event (primary aircraft)
    assert one(lite, "SELECT COUNT(*) FROM accidents WHERE is_primary_aircraft = 1 "
                     "AND event_fatalities > 0 AND is_fatal = 0") == 0


def test_coverage_starts_in_1982_and_is_current(lite):
    assert one(lite, "SELECT MIN(year) FROM accidents") == 1982
    latest = one(lite, "SELECT latest_event FROM meta")
    assert latest == one(lite, "SELECT MAX(ev_date) FROM accidents")


def test_general_aviation_is_us_only(lite):
    assert one(lite, "SELECT COUNT(*) FROM accidents WHERE is_ga = 1 AND is_us = 0") == 0
    assert one(lite, "SELECT COUNT(*) FROM accidents WHERE is_ga = 1 AND far_part IN ('121', '135')") == 0


def test_child_rows_point_at_accidents(lite):
    # NOT IN, not a correlated NOT EXISTS: accidents.accident_key has no index in the snapshot,
    # and SQLite would compare every pair of rows (billions); NOT IN builds one lookup table
    for table in ("tags", "findings"):
        assert one(lite, f"SELECT COUNT(*) FROM {table} WHERE accident_key NOT IN "
                         f"(SELECT accident_key FROM accidents)") == 0, table
    assert one(lite, "SELECT COUNT(*) FROM findings WHERE category_id NOT IN "
                     "(SELECT category_id FROM finding_categories)") == 0


def test_observed_weather_is_valid_and_us_only(lite):
    assert one(lite, "SELECT COUNT(*) FROM accidents WHERE observed_category IS NOT NULL "
                     "AND observed_category NOT IN ('VFR', 'MVFR', 'IFR', 'LIFR')") == 0
    assert one(lite, "SELECT COUNT(*) FROM accidents WHERE observed_category IS NOT NULL AND is_us = 0") == 0


def test_model_scores_are_sensible(lite):
    lr, gb = lite.execute("SELECT lr_roc_auc, gb_roc_auc FROM model_run").fetchone()
    assert 0.7 < lr <= 1 and 0.7 < gb <= 1


def test_web_app_renders_without_errors():
    testing = pytest.importorskip("streamlit.testing.v1")
    at = testing.AppTest.from_file(f"{ROOT}/web/app.py", default_timeout=300).run()
    assert not at.exception, [e.value for e in at.exception]
    headings = [h.value for h in at.subheader]
    assert len(headings) == 6 and headings[0].startswith("1. Flying got safer")
