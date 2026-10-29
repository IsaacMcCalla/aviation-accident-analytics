"""Download an NTSB aviation accident database and unzip it into data/ntsb/.

    python src/download_ntsb.py                    # avall.zip: 2008 to present, updated monthly
    python src/download_ntsb.py --file Pre2008     # Pre2008.zip: 1982-2007, no longer updated
    python src/download_ntsb.py --url <link>       # if the NTSB moves the file

Each zip holds one Microsoft Access .mdb file. Check the current link on the NTSB
"aviation data" download page (data.ntsb.gov/avdata) before the first run.
"""
import argparse
import datetime
import os
import zipfile

import requests

from config import get_connection, log_run, setup_logging

log = setup_logging("download_ntsb")

URL_TEMPLATE = "https://data.ntsb.gov/avdata/FileDirectory/DownloadFile?fileID=C%3A%5Cavdata%5C{name}.zip"
OUT_DIR = os.path.join("data", "ntsb")


def download(url: str, dest: str) -> int:
    with requests.get(url, stream=True, timeout=(15, 300)) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "html" in content_type.lower():
            raise RuntimeError(f"expected a zip file, got {content_type}; the download link may have changed")
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return os.path.getsize(dest)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default="avall", choices=["avall", "Pre2008"])
    parser.add_argument("--url", help="full download link (default: the NTSB link for --file)")
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    zip_path = os.path.join(OUT_DIR, f"{args.file}.zip")
    try:
        size = download(args.url or URL_TEMPLATE.format(name=args.file), zip_path)
        with zipfile.ZipFile(zip_path) as z:
            mdb = next((n for n in z.namelist() if n.lower().endswith(".mdb")), None)
            if mdb is None:
                raise RuntimeError(f"no .mdb file in the zip: {z.namelist()}")
            z.extract(mdb, OUT_DIR)
            file_date = datetime.datetime(*z.getinfo(mdb).date_time)
        message = f"{mdb} dated {file_date:%Y-%m-%d}, zip {size / 1e6:.0f} MB"
        log.info("done: %s -> %s", message, os.path.join(OUT_DIR, mdb))
        status = "OK"
    except Exception as exc:
        log.exception("NTSB download failed")
        message, status = str(exc), "FAILED"

    # The download itself does not need the database, so a database error here is only a warning
    try:
        conn = get_connection()
        log_run(conn, "ntsb_download", status, 0, message)
        conn.close()
    except Exception:
        log.warning("could not write to dbo.ingest_log (has sql/01_schema.sql been run?)")

    if status != "OK":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
