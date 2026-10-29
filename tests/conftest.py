"""Shared test setup.

Tests run from the repository root:  .venv\\Scripts\\python.exe -m pytest
Tests marked "db" need the local SQL Server database and are skipped when it cannot be reached
(as on GitHub Actions). Everything else runs anywhere.
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.chdir(ROOT)   # scripts use paths relative to the repository root

SNAPSHOT = os.path.join(ROOT, "web", "data", "accidents.db")


@pytest.fixture(scope="session")
def db():
    """A connection to the AviationSafety database, or skip the test."""
    try:
        from config import get_connection
        conn = get_connection()
    except Exception as exc:  # no driver, no server, no database
        pytest.skip(f"database not available: {exc.__class__.__name__}")
    yield conn
    conn.close()
