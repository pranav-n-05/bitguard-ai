# Deploying on Render

`render.yaml` (repo root) is a Render **Blueprint**. It creates:

| Resource | Type | Notes |
|---|---|---|
| `bitguard` | Web service (Docker) | One container runs the API, the Celery worker and the built React console, so they share one persistent disk |
| `bitguard-db` | PostgreSQL 16 | `basic-256mb`; private network connection string injected automatically |
| `bitguard-redis` | Key Value | `free`; Celery broker and rate-limit counters only |
| `bitguard-data` | Persistent disk, 10 GB at `/data` | Uploaded datasets, generated reports, model artifacts (survive redeploys) |

## Steps
1. Push this repository to GitHub.
2. Render dashboard → **New → Blueprint** → select the repository → **Apply**.
3. When prompted, enter `BITGUARD_BOOTSTRAP_ADMIN_EMAIL` and `BITGUARD_BOOTSTRAP_ADMIN_PASSWORD`
   (≥12 characters, three of lower/upper/digit/symbol). `BITGUARD_JWT_SECRET` is generated for you.
4. Wait for the first deploy. The service runs migrations and seeds roles + the admin user on every start (idempotent).
5. Open `https://<service>.onrender.com`, sign in, go to **Data ingestion** and upload a dataset
   (or generate one locally with `scripts/generate_synthetic.py` and upload it).

## What to know
* **Plan size.** The pipeline (pandas, scikit-learn, SHAP) plus Celery plus the API needs memory; `standard` (2 GB) is configured.
  `starter` (512 MB) may be killed (OOM) on larger datasets. Change `plan:` in `render.yaml` if you accept that trade-off.
* **Uploads.** `BITGUARD_MAX_UPLOAD_MB` is 100 on Render; raise it together with disk size if you ingest bigger files.
* **Single instance.** A persistent disk ties the service to one instance (no horizontal scaling) — acceptable for this workload.
* **Real client IPs.** `FORWARDED_ALLOW_IPS=*` lets login rate limiting see the client address behind Render's load balancer.
* **HTTPS** is terminated by Render. Cookies are not used; tokens are sent as bearer headers.
* **Backups.** Enable Render Postgres backups and disk snapshots. `scripts/backup.sh` / `restore.sh` target the local Docker Compose stack only.
* **Data labels.** Synthetic datasets are labelled `synthetic` throughout the UI; label any real data you load as `historical`/`external`.
* **Security.** Change the admin password after first sign-in, enable MFA (Administration → My security) and create named analyst accounts.
* **Local rehearsal.** The same image runs locally:
  `docker build -f infrastructure/docker/render.Dockerfile -t bitguard .` then run with `BITGUARD_DATABASE_URL`, `BITGUARD_REDIS_URL`, `BITGUARD_JWT_SECRET`, `PORT`.
