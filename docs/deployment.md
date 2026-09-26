# Deployment

## Render (free tier)

`render.yaml` provisions three resources:

| Resource | Type | Notes |
|---|---|---|
| `dndlabs-api` | Web service (Docker) | `docker/Dockerfile.api`; health check `/health`; `DNDLABS_ADMIN_BOOTSTRAP_SECRET` auto-generated; `DNDLABS_NVIDIA_NIM_API_KEY` left unset (`sync: false`) — set manually once available |
| `dndlabs-web` | Static Site | Builds `web/` with Vite; CDN-backed, no cold start |
| `dndlabs-db` | PostgreSQL | Free tier expires after 30 days |

### Deploy

1. Render Dashboard → **New → Blueprint** → connect this repo → pick the branch.
2. **Apply.** The API's first build takes a few minutes (mostly RDKit).
3. Retrieve the generated admin secret: `dndlabs-api` → Environment →
   `DNDLABS_ADMIN_BOOTSTRAP_SECRET`.
4. Bootstrap the first organization:
   ```bash
   curl -X POST https://dndlabs-api.onrender.com/api/v1/admin/orgs \
     -H "X-Admin-Secret: <the generated secret>" \
     -H "content-type: application/json" -d '{"name": "Your Org"}'
   # -> {"raw_key": "ddl_live_...", ...}  — shown once, save it now
   ```
5. Open `https://dndlabs-web.onrender.com`, enter the key.

For a quick smoke check instead of step 4, sign in with the shared
credential (`DNDLABS_FREE_TIER_SHARED_PASSWORD`, default `freetier2026`) —
it authenticates with no database lookup, so it works before migrations
have even run. Temporary and insecure; see [Auth](architecture.md#auth).

### Configuration

| Variable | Where | Notes |
|---|---|---|
| `DNDLABS_NVIDIA_NIM_API_KEY` | API service env | Unset → enrichment runs but marks every record `skipped_no_key`; see [nvidia-nim.md](nvidia-nim.md) |
| `DNDLABS_FREE_TIER_SHARED_PASSWORD` | API service env | Default `freetier2026`. Clear it once real org keys are in use; see [Auth](architecture.md#auth) |
| `DNDLABS_FRONTEND_ORIGIN` | API service env | Must match the deployed Static Site's URL (CORS) |
| `VITE_API_BASE_URL` | Static Site env (**build-time**) | Vite bakes `VITE_*` vars in at build; changing this requires a rebuild, not a restart |

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `401` on every request | Missing/wrong `X-API-Key`, or the key was revoked — bootstrap a new org or issue a new key |
| Enrichment always `skipped_no_key` | Expected until `DNDLABS_NVIDIA_NIM_API_KEY` is set; confirm the hosted base URL first — see [nvidia-nim.md](nvidia-nim.md) |
| CSV/JSON run fails with "file not found" | `csv_path`/`json_path` are read from the **API container's** filesystem, not the browser's |
| First request is slow | Free web service sleeps when idle; first request wakes it (~30–60s). The Static Site never sleeps. |
| Free Postgres expired | 30-day limit on Render's free tier; upgrade the plan for anything long-lived |
| `relation "organizations" does not exist` on any DB-backed call | Migrations haven't run against the linked database. Diagnose with `GET /api/v1/health/ready` (`503` confirms it) before reading logs. Fix: **Manual Deploy → Deploy latest commit** on `dndlabs-api` (not "Restart"), then check its logs for `Database is up to date.` or a `migration_stamp_shortcut` warning. If `/health/ready` still fails after a clean redeploy, the database itself is in a stale state (e.g. `alembic_version` says "head" but the tables were dropped independently) — delete and let the Blueprint recreate `dndlabs-db`, then redeploy `dndlabs-api`. `DNDLABS_FREE_TIER_SHARED_PASSWORD` still works throughout, since it never touches the database. |

## Docker Compose (local)

```bash
docker compose up --build
```

Starts Postgres, the API (`localhost:8000`, migrations applied
automatically via `docker/entrypoint.sh`), and the frontend dev server
(`localhost:5173`).

## CI

`.github/workflows/ci.yml` runs three jobs on every push and PR:

| Job | Checks |
|---|---|
| `backend` | `ruff check`/`ruff format --check`, `mypy --strict`, `pytest --cov`, `pip-audit` (informational) |
| `docker` | Builds `docker/Dockerfile.api`, smoke-tests the image — catches a broken Dockerfile here, not on a Render deploy |
| `frontend` | `eslint`, `tsc --noEmit`, `vitest`, `vite build`, `npm audit --audit-level=high` (informational) |

The dependency scans are informational, not merge-blocking, until their
current findings are triaged — see README's Known limitations.

`.github/workflows/smoke.yml` is a manual `workflow_dispatch` that runs
`scripts/smoke_test.py` against a deployed URL, given the admin secret.
