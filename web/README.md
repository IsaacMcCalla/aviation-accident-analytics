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
| `Dockerfile` | How the local image is built (Python 3.12 slim, runs as a non-root user, health check) |
| `Dockerfile.cloud`, `Dockerfile.cloud.dockerignore` | The public site's image: the same, with the data snapshot built in |
| `compose.yaml` | How the container runs: port 8080 on localhost, `data/` mounted read-only, restarts automatically |
| `.streamlit/config.toml` | Streamlit settings (no usage statistics sent) |
| `data/accidents.db` | The snapshot, created by the export script; committed to git so the public site's image is built with it |

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

## Public site (Azure Container Apps)

Live at **https://aviation-dashboard.braveriver-68d22d3c.eastus.azurecontainerapps.io**.

```
git push ──> GitHub Actions "deploy" workflow: test ──> build Dockerfile.cloud ──> ghcr.io image ──> Azure Container App
```

| Piece | Where | Notes |
| --- | --- | --- |
| Image | `ghcr.io/isaacmccalla/aviation-dashboard` (GitHub's container registry, public, free) | Built from `Dockerfile.cloud`, which bakes `data/accidents.db` into the image (Azure has no folder to mount). Tagged `latest` and with each commit's ID |
| App | Azure subscription "Azure subscription 1", resource group `rg-aviation-dashboard` (East US), environment `cae-aviation`, Container App `aviation-dashboard` | 0.5 CPU, 1 GB memory, HTTPS on port 8501, scales from 0 to 1 copy |
| Deploys | `.github/workflows/deploy.yml` | Runs on any push that changes `web/`. Signs in to Azure with OpenID Connect through the `github-aviation-deploy` identity, which can change only this one app (set up by `deploy/link_github_to_azure.ps1`) |
| Cost | Container Apps consumption plan, with Azure's free monthly allowance | Scale to zero: nothing runs, and nothing is billed, while nobody is visiting. Budget `aviation-monthly` emails the subscription owner at 50% and 100% of $5 a month, and when the forecast passes $5 |

**Backup copy.** The earlier Streamlit Community Cloud deployment still runs at https://jsaviationanalytics.streamlit.app/. It redeploys from this repository on every push (main file `web/app.py`, data from the committed snapshot), so it stays in step with Azure at no cost. To retire it: share.streamlit.io → the app's **⋮** menu → **Delete**. Nothing in the repository depends on it.

**Cold start.** After a quiet spell the app has scaled to zero, so the first visitor waits about 10–20 seconds while it starts. Later visitors get it immediately. To keep one copy always running (no wait, but billed around the clock), set `--min-replicas 1`.

To publish a monthly update, run this from the project folder after the usual update steps:

```
.\publish_web.ps1
```

It exports, commits only the data file, and pushes. GitHub then tests, builds and deploys; the site updates in about 3–5 minutes (watch it in the repository's **Actions** tab). The file is about 38 MB (1982 onward), and each update adds about 13 MB to the repository's history after git compresses it, about 160 MB a year of monthly updates. GitHub recommends staying under about 1 GB, so that's several years of headroom; avoid publishing many times a day. When the history gets large, move the file to Git LFS or a GitHub release asset.

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

Azure (needs the Azure CLI and `az login` as the subscription owner):

| Command | What it does |
| --- | --- |
| `az containerapp show -n aviation-dashboard -g rg-aviation-dashboard --query properties.runningStatus` | Is it running? |
| `az containerapp logs show -n aviation-dashboard -g rg-aviation-dashboard --follow` | Live app output (wake the site first; there is no log storage, to avoid its cost) |
| `az containerapp revision list -n aviation-dashboard -g rg-aviation-dashboard -o table` | Each deployed version, and which one is serving |
| `az containerapp update -n aviation-dashboard -g rg-aviation-dashboard --image ghcr.io/isaacmccalla/aviation-dashboard:<commit id>` | Deploy (or roll back to) a specific build by hand |
| `az group delete -n rg-aviation-dashboard` | **Deletes the whole Azure site** and stops all its costs (the image on GitHub stays) |

## Troubleshooting

- **Page says "No data file"**: run the export script; check that `web\data\accidents.db` exists.
- **Port 8080 already in use**: change the left number in `compose.yaml` (`"127.0.0.1:8090:8501"`) and run `up -d` again.
- **Map shows dots but no background**: map tiles load from the internet; everything else works offline.
- **`docker` not found or "cannot connect to the Docker daemon"**: start Docker Desktop and wait until it says it's running.
- **Docker Desktop says virtualization is disabled**: turn on Intel VT-x (or AMD SVM) in the PC's BIOS/UEFI settings.
- **Azure site didn't update after a push**: open the repository's **Actions** tab, then the latest **deploy** run. A red `test` job means the app or data is broken (fix and push again). A skipped `deploy` job means the five `AZURE_*` repository variables are missing. A failed `azure/login` step means the federated credential doesn't match (it only trusts the `main` branch).
- **Azure site shows an error page or never loads**: check `az containerapp logs show` (above). If a bad version went out, roll back with `az containerapp update --image` and an earlier commit ID.
- **Containers run out of memory**: Docker's Linux VM is capped at 2 GB by `%UserProfile%\.wslconfig` (`memory=2GB`), so it can't starve SQL Server and Power BI. That is plenty for this dashboard. If you add heavier containers, raise the number, then run `docker desktop stop`, `wsl --shutdown`, and `docker desktop start`.
