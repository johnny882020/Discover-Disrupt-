# Deployment

## Render (free tier)

`render.yaml` provisions three resources:

| Resource | Type | Notes |
|---|---|---|
| `dndlabs-api` | Web service (Docker) | `docker/Dockerfile.api`; health check `/health`; `DNDLABS_ADMIN_BOOTSTRAP_SECRET` auto-generated; `DNDLABS_NVIDIA_NIM_API_KEY` left unset (`sync: false`) — set it manually in the dashboard when you have one |
| `dndlabs-web` | Static Site | Builds `web/` with Vite; no cold start (static, CDN-backed) |
| `dndlabs-db` | PostgreSQL | Free tier expires after 30 days |

### Deploy

1. In the Render Dashboard: **New → Blueprint**, connect this repo, pick the branch.
2. **Apply.** The API's first build takes a few minutes (mostly RDKit).
3. **Retrieve the admin secret** Render generated: API service → Environment
   → `DNDLABS_ADMIN_BOOTSTRAP_SECRET`.
4. **Bootstrap your first org:**
   ```bash
   curl -X POST https://dndlabs-api.onrender.com/api/v1/admin/orgs \
     -H "X-Admin-Secret: <the generated secret>" \
     -H "content-type: application/json" -d '{"name": "Your Org"}'
   # -> {"raw_key": "ddl_live_...", ...}  — save this now, it is shown once
   ```
5. Open `https://dndlabs-web.onrender.com`, enter the key, and use the app.

**Fastest path (temporary, insecure):** skip step 4 and enter
`freetier2026` directly in the web app instead of a real key — see
`DNDLABS_FREE_TIER_SHARED_PASSWORD` below. This authenticates with no
database lookup, so it works even if migrations haven't run yet. Rotate or
clear it before onboarding real customers.

### Configuration

| Variable | Where | Notes |
|---|---|---|
| `DNDLABS_NVIDIA_NIM_API_KEY` | API service env | Unset → enrichment stage runs but marks every record `skipped_no_key`; see `docs/nvidia-nim.md` |
| `DNDLABS_FREE_TIER_SHARED_PASSWORD` | API service env | Default `freetier2026`. One shared, unrevocable login for every caller who knows it — no per-org isolation between them. Clear it (empty value) once real org keys are in use; see `docs/architecture.md#auth` |
| `DNDLABS_FRONTEND_ORIGIN` | API service env | Must match the deployed Static Site's URL for CORS |
| `VITE_API_BASE_URL` | Static Site env (**build-time**) | Vite bakes `VITE_*` vars in at build, so changing this requires a rebuild, not just a restart |

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `401` on every request | Missing/wrong `X-API-Key`, or the org's key was revoked — bootstrap a new org or issue a new key |
| Enrichment always `skipped_no_key` | Expected until `DNDLABS_NVIDIA_NIM_API_KEY` is set — see `docs/nvidia-nim.md` for the one unverified detail (hosted base URL) to confirm first |
| CSV/JSON run fails with "file not found" | `csv_path`/`json_path` are read from the **API container's** filesystem, not the browser's |
| First request slow | Free web service sleeps when idle; first request wakes it (~30–60s). The Static Site frontend never sleeps. |
| Free Postgres expired | 30-day limit on Render's free tier; upgrade the plan for anything long-lived |
| `relation "organizations" does not exist` (or similar, on any `/admin/orgs` or dataset call) | Migrations haven't run against the currently-linked database. **First, check `GET /api/v1/health/ready`** — `503` confirms this before you dig through logs at all. Then redeploy `dndlabs-api` (**Manual Deploy → Deploy latest commit**, not "Restart") and check its logs for `Database is up to date.` right before the server starts, or a `migration_stamp_shortcut` warning if the schema pre-existed without Alembic's own bookkeeping. If `/health/ready` still fails after a clean redeploy, the database itself is likely in a stale state (e.g. `alembic_version` says "head" but the tables were dropped independently) — delete and let the Blueprint recreate `dndlabs-db`, then redeploy `dndlabs-api` again. In the meantime, `DNDLABS_FREE_TIER_SHARED_PASSWORD` still logs you into the web app, since it never touches the database. |

## Docker Compose (local)

```bash
docker compose up --build
```

Starts Postgres, the API (`localhost:8000`, migrations applied automatically
via `docker/entrypoint.sh`), and the frontend dev server (`localhost:5173`).

## CI

`.github/workflows/ci.yml` runs three parallel jobs on every push and PR:
`backend` (ruff, mypy `--strict`, `pytest --cov`, plus a non-blocking
`pip-audit` scan), `docker` (builds `docker/Dockerfile.api` and smoke-tests
the image so a broken Dockerfile fails here, not on a Render deploy), and
`frontend` (eslint, `tsc --noEmit`, vitest, `vite build`, plus a
non-blocking `npm audit --audit-level=high`). The two dependency scans are
informational, not gating, until their current findings are triaged (see
"Status / known limitations" in `README.md`). `.github/workflows/smoke.yml`
is a manual `workflow_dispatch` that runs `scripts/smoke_test.py` against a
deployed URL, given the admin secret.
