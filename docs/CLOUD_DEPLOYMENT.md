# Cloud deployment

The project runs fully on a laptop. Cloud deployment is **optional** and publishes the *dashboard and API*. Three things should be kept clearly separate:

| | What it is | Status |
|---|---|---|
| 1. Local simulation | scheduler, ledger and UI on your laptop | **default, fully working** |
| 2. App deployed to the internet | the same containers on a cloud VM or PaaS | **configuration provided** (needs your account) |
| 3. Real cloud workload execution | jobs actually dispatched to cloud servers or Kubernetes | **not implemented**; workloads remain simulated |

Nothing has been deployed for you, no paid resources were created, and no credentials were used. The steps below are what *you* run.

## Option A (recommended): one VM + Docker Compose + automatic HTTPS

**Why.** A single VM keeps the SQLite file on a persistent disk, and there is only one instance. That makes SQLite durable and safe here, and the autoplay thread, ledger lock and experiments all behave exactly as they do locally. Caddy obtains a Let's Encrypt certificate automatically.

**Provider.** *Azure for Students* (VIT students are eligible with the university email): **USD 100 credit for 12 months, no credit card**, plus free hours for small burstable VMs (B1s / B2ats v2 / B2pts v2). Several regions no longer offer B1s to student subscriptions; if it is missing, choose `Standard_B2ats_v2` or `Standard_B1ms` and do not pin an availability zone. Check the live offer page before relying on these details. An AWS EC2 free-tier `t3.micro` works the same way.

### Steps

1. **Create the VM** (Azure portal → Virtual machines → Create):
   Ubuntu Server 24.04 LTS · size B2ats_v2 (or B1ms) · authentication = SSH public key · inbound ports **22, 80, 443**.
   Under *Networking → Public IP → Configuration*, set a **DNS name label**, for example `carbondebt-<yourname>`. Your domain becomes `carbondebt-<yourname>.<region>.cloudapp.azure.com`.
2. **Install Docker** on the VM:
   ```bash
   ssh azureuser@<domain>
   curl -fsSL https://get.docker.com | sudo sh
   sudo usermod -aG docker $USER && exit      # log in again afterwards
   ```
3. **Copy the project** (from your laptop, in PowerShell):
   ```powershell
   scp -r "C:\path\to\cloud project\backend" "C:\path\to\cloud project\frontend" "C:\path\to\cloud project\deploy" "C:\path\to\cloud project\docker-compose.yml" azureuser@<domain>:~/carbon-debt/
   ```
   (Or push the repository to GitHub and `git clone` it on the VM. Exclude `backend/.venv` and `node_modules`.)
4. **Configure secrets** on the VM. These live in `.env` on the server only and are never committed:
   ```bash
   cd ~/carbon-debt
   cat > .env <<EOF
   DOMAIN=carbondebt-<yourname>.<region>.cloudapp.azure.com
   ADMIN_TOKEN=$(openssl rand -hex 24)
   ENVIRONMENT=production
   LOG_LEVEL=INFO
   EOF
   chmod 600 .env && grep ADMIN_TOKEN .env    # keep this value for the dashboard
   ```
5. **Start** (requires Docker Compose ≥ 2.24 for the `!reset` override):
   ```bash
   docker compose -f docker-compose.yml -f deploy/docker-compose.cloud.yml up -d --build
   docker compose ps
   ```
   The database is created automatically on first start (`create_all`); no migration step is needed for a fresh deployment.
6. **Verify:**
   ```bash
   curl -s https://$DOMAIN/api/health                       # {"status":"ok",...,"admin_token_required":true}
   curl -s -o /dev/null -w "%{http_code}\n" -X POST https://$DOMAIN/api/sim/advance -H 'Content-Type: application/json' -d '{"slots":1}'   # 401
   curl -s -X POST https://$DOMAIN/api/sim/advance -H "X-Admin-Token: $ADMIN_TOKEN" -H 'Content-Type: application/json' -d '{"slots":1}'
   docker compose logs --tail 50 backend                    # JSON logs
   ```
7. **Confirm the frontend talks to the deployed backend.** Open `https://<domain>`, go to Telemetry & settings, and paste the admin token. The *Data sources* panel should show `Environment: production`. Run the scenario and watch `docker compose logs -f backend` print the POST requests. Browser DevTools → Network should show requests to `https://<domain>/api/...` (same origin, served through nginx).

**Security in this setup.** TLS is terminated by Caddy (HSTS on). Every mutating endpoint requires `X-Admin-Token`, while reads stay public. FastAPI `debug=False`. CORS allows only `https://$DOMAIN`. Containers run as a non-root user. The India Energy Atlas API key goes in the server `.env` only. Job execution is bounded (a ≤ 500-job limit, a 20 ms proxy kernel, no user-supplied code).

**Backups.** `docker run --rm -v carbon-debt_carbon_data:/d -v $PWD:/b alpine cp /d/carbon_debt.db /b/backup.db`. Also save the ledger head hash (Debt ledger → *Save head as checkpoint*, then copy it off the server).

**Teardown.** Delete the **resource group** in the Azure portal; this removes the VM, disk, IP and network. Check *Cost Management* afterwards to confirm nothing remains.

## Option B: Render (free, one web service, SQLite)

`render.yaml` defines **one free Docker web service** built from the root `Dockerfile`. The image builds the React UI and FastAPI serves it on the same origin, so the UI calls `/api/...` directly: no `VITE_API_BASE_URL`, no second service. CORS also allows Render's own URL automatically (`RENDER_EXTERNAL_URL`). Uvicorn runs as a single process, which the in-process scheduler thread and ledger lock require; do not add workers or instances.

1. Push the project to a GitHub repository (the `.gitignore` already excludes `.env`, databases, `.venv`, `node_modules`).
2. Render dashboard → **New → Blueprint** → connect GitHub → pick the repository → **Apply**. Leave `INDIA_ENERGY_ATLAS_API_KEY` empty unless you want Live grid data.
3. Wait for the build (about 5–10 minutes the first time), then open `https://<service>.onrender.com/api/health` → `"status":"ok","environment":"production","admin_token_required":true`.
4. Service → **Environment** → reveal `ADMIN_TOKEN` and copy it. On the site open **Live Mode** → *Admin token* → paste → **Save**. Without it, every button that changes something returns 401 (reading is public).

**Data persistence — stated honestly.** The free filesystem is **ephemeral**. Simulation jobs, the ledger and experiment results are **lost on every redeploy, restart and spin-down** (after 15 minutes without traffic). The app re-creates its tables and defaults automatically on start, and the scenario and experiments re-run in seconds, so this is acceptable for a demonstration. For persistence, add a Render Postgres database and set `DATABASE_URL` to its *Internal Database URL*. Note that free Postgres expires after 30 days, and this path was never tested against a real Postgres server. A paid persistent disk is the other option.

**Before presenting:** open the site 2–3 minutes early (a cold start takes about a minute). Keep the tab **visible**: the UI polls only while visible, and that traffic keeps the instance awake.

**Live mode in the cloud:** the process list shows the **Render server's** processes, labelled as such, not the presenter's laptop. Grid data needs `INDIA_ENERGY_ATLAS_API_KEY`; without it Live mode shows *Unavailable* and never substitutes simulated readings.

## Option C: run locally and present

For the classroom demonstration, **run locally** (`start-dev.ps1`). It needs no internet apart from the optional live-grid panel, and it has no cold starts.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `ENVIRONMENT` | development | `production` in the cloud |
| `DATABASE_URL` | SQLite file in `backend/data` | `postgresql://…` is accepted and normalised to the psycopg 3 driver |
| `CORS_ORIGINS` | localhost:5173 | comma-separated exact origins |
| `ADMIN_TOKEN` | empty | **required** for any public deployment |
| `STATIC_DIR` | unset | set in the single-container image to serve the built UI |
| `KERNEL_MS` | 20 | real CPU proxy work per job-slot |
| `LIVE_SLOT_SECONDS`, `LIVE_JOB_DUTY`, `LIVE_MAX_JOBS_RUNNING` | 30, 0.35, bounded | Live mode workers (a cloud VM monitors itself, not your laptop) |
| `INDIA_ENERGY_ATLAS_API_KEY`, `INDIA_ENERGY_ATLAS_STATE` | empty | Live mode grid data (key from energymap.in); state needs a state-level plan |
| `VITE_API_BASE_URL` | empty | only when the UI and API are on different origins |
| `DOMAIN` | — | Option A only |

## Not tested here

Docker is not installed on the development laptop, so the Dockerfiles and compose files were written but **not built or run in this environment**. The production configuration was smoke-tested without Docker: built UI served by FastAPI, `ENVIRONMENT=production`, `ADMIN_TOKEN`, `PORT`, `RENDER_EXTERNAL_URL`, and no API key. The PostgreSQL path (URL normalisation and portable column types) is implemented but was exercised only against SQLite.
