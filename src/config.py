"""Shared configuration, logging, and database connection."""
import logging
import os
from logging.handlers import RotatingFileHandler

import pyodbc


def get_connection() -> pyodbc.Connection:
    """Connect to SQL Server using environment variables.

    DB_SERVER   default: localhost
    DB_NAME     default: AviationSafety
    DB_DRIVER   default: ODBC Driver 18 for SQL Server
    DB_USER / DB_PASSWORD   optional; if DB_USER is unset, Windows auth is used
    """
    server = os.environ.get("DB_SERVER", "localhost")
    database = os.environ.get("DB_NAME", "AviationSafety")
    driver = os.environ.get("DB_DRIVER", "ODBC Driver 18 for SQL Server")
    user = os.environ.get("DB_USER")
    if user:
        auth = f"UID={user};PWD={os.environ.get('DB_PASSWORD', '')}"
    else:
        auth = "Trusted_Connection=yes"
    conn_str = (
        f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};"
        f"{auth};TrustServerCertificate=yes"
    )
    return pyodbc.connect(conn_str)


def setup_logging(name: str) -> logging.Logger:
    """Log to console and to logs/<name>.log (rotating)."""
    os.makedirs("logs", exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logfile = RotatingFileHandler(f"logs/{name}.log", maxBytes=1_000_000, backupCount=3)
    logfile.setFormatter(fmt)
    logger.addHandler(console)
    logger.addHandler(logfile)
    return logger


def log_run(conn: pyodbc.Connection, source: str, status: str, rows: int, message: str) -> None:
    """Write one row to dbo.ingest_log (read by the data quality checks)."""
    cur = conn.cursor()
    cur.execute(
        "INSERT dbo.ingest_log (source, status, rows_loaded, message) VALUES (?,?,?,?)",
        source, status, rows, message[:500],
    )
    conn.commit()


def insert_sql(table: str, columns: list) -> str:
    """INSERT statement with one ? per column, for executemany."""
    return f"INSERT dbo.{table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"
