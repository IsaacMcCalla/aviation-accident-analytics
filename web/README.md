# Web dashboard (Docker)

A web version of the Power BI dashboard, served from a Docker container at **http://localhost:8080**, reachable from this computer only.

```
SQL Server ──> src/export_web_data.py ──> web/data/accidents.db ──(read-only mount)──> container: Streamlit app
```

The container never connects to SQL Server. It reads a snapshot file that `src/export_web_data.py` writes after each monthly update, so SQL Server keeps its Windows-only sign-in and stays closed to network connections.

| File | Purpose |
| --- | --- |
| `app.py` | The web app (Streamlit): sidebar filters and seven tabs that mirror the Power BI pages |
| `requirements.txt` | Pinned Python packages for the container |
| `Dockerfile` | How the image is built (Python 3.12 slim, runs as a non-root user, health check) |
| `compose.yaml` | How the container runs: port 8080 on localhost, `data/` mounted read-only, restarts automatically |
| `.streamlit/config.toml` | Streamlit settings (no usage statistics sent) |
| `data/accidents.db` | The snapshot, created by the export script; committed to git so the public site has data |

## First run

Docker Desktop must be running (whale icon in the taskbar). From the project folder:

```
.venv\Scripts\python.exe src\export_web_data.py
docker compose -f web\compose.yaml up -d --build
```

Then open http://localhost:8080. Docker Desktop starts the container again after a reboot (`restart: unless-stopped`), as long as Docker Desktop itself starts with Windows (its default).

## Monthly update

After the usual update steps (download, extract, transform, tune, tag), run:

```
.venv\Scripts\python.exe src\export_web_data.py
```

Reload the page. No rebuild or restart is needed: the app notices the new file.

## Public site (Streamlit Community Cloud)

Live at **https://jsaviationanalytics.streamlit.app/**. The same `app.py` runs on Streamlit Community Cloud, deployed from this repository's GitHub copy (main file `web/app.py`; it installs `web/requirements.txt`). `web/data/accidents.db` is committed so the cloud copy has data.

To publish a monthly update, run this from the project folder after the usual update steps:

```
.\publish_web.ps1
```

It exports, commits only the data file, and pushes; the public site redeploys within a couple of minutes. The file is about 38 MB (1982 onward), and each update adds about 13 MB to the repository's history after git compresses it, about 160 MB a year of monthly updates. GitHub recommends staying under about 1 GB, so that's several years of headroom; avoid publishing many times a day. When the history gets large, move the file to Git LFS or a GitHub release asset.

## Changing the app

Edit `app.py`, then rebuild and restart the container:

```
docker compose -f web\compose.yaml up -d --build
```

To try changes without Docker first, install `web/requirements.txt` into a separate virtual environment (Python 3.12–3.14) and run `streamlit run web\app.py`, which serves on http://localhost:8501. To show a new database column, add it to the query in `src/export_web_data.py`, re-export, then use it in `app.py`.

## Useful commands

| Command | What it does |
| --- | --- |
| `docker compose -f web\compose.yaml ps` | Is it running and healthy? |
| `docker compose -f web\compose.yaml logs --tail 50` | Recent app output and errors |
| `docker compose -f web\compose.yaml down` | Stop and remove the container (the image and data stay) |
| `docker compose -f web\compose.yaml up -d` | Start it again |

## Troubleshooting

- **Page says "No data file"**: run the export script; check that `web\data\accidents.db` exists.
- **Port 8080 already in use**: change the left number in `compose.yaml` (`"127.0.0.1:8090:8501"`) and run `up -d` again.
- **Map shows dots but no background**: map tiles load from the internet; everything else works offline.
- **`docker` not found or "cannot connect to the Docker daemon"**: start Docker Desktop and wait until it says it's running.
- **Docker Desktop says virtualization is disabled**: turn on Intel VT-x (or AMD SVM) in the PC's BIOS/UEFI settings.
- **Containers run out of memory**: Docker's Linux VM is capped at 2 GB by `%UserProfile%\.wslconfig` (`memory=2GB`), so it can't starve SQL Server and Power BI. That is plenty for this dashboard. If you add heavier containers, raise the number, then run `docker desktop stop`, `wsl --shutdown`, and `docker desktop start`.
