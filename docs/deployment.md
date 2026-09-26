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
4. Confirm the database is migrated: `GET /api/v1/health/ready` returns
   `{"status": "ok", "database": "ok"}`.
5. Onboard the first organization — create it, then invite its admin:
   ```bash
   API=https://dndlabs-api.onrender.com/api/v1
   SECRET=<the generated secret>
   curl -X POST $API/admin/orgs -H "X-Admin-Secret: $SECRET" \
     -H "content-type: application/json" -d '{"name": "Your Org"}'
   # -> {"org_id": "...", "raw_key": "ddl_live_...", ...}  API key, shown once
   curl -X POST $API/admin/orgs/<org_id>/invitations -H "X-Admin-Secret: $SECRET" \
     -H "content-type: application/json" -d '{"email": "admin@yourorg.com"}'
   # -> {"accept_url": "https://dndlabs-web.onrender.com/invite#token=ddl_inv_...", ...}
   ```
6. Send the `accept_url` to the admin over a trusted channel. It works once
   and expires after 72 hours. Opening it, they choose their own password
   and are signed in. From the web app's **Team** page they then invite
   the rest of their organization; nobody else needs the admin secret.

Keep the API key for programmatic access, or discard it — web users never
need it. Additional keys: `POST /admin/orgs/{org_id}/keys`.

### Accounts and access

| Who | Signs in with | Can |
|---|---|---|
| Operator | `X-Admin-Secret` (`DNDLABS_ADMIN_BOOTSTRAP_SECRET`) | Create organizations, issue API keys, invite each organization's first admin, issue a reset link when no admin can sign in |
| Org admin | Email + password | Everything a member can, plus manage the team (invite, change roles, reset passwords, remove members, revoke invitations) and delete the organization's data |
| Org member | Email + password | Run pipelines; view, filter and export the organization's datasets |
| Program | Org API key (`X-API-Key`) | The same as an org admin, over the API |

People join only by invitation: the link works once, expires after 72
hours, and is where the invitee chooses their password. Sessions last 12
hours; five wrong passwords lock an account for 15 minutes. Details:
[Auth](architecture.md#auth).

### Configuration

The variables below matter for a deployment; every setting, with its
default, is listed in [`.env.example`](../.env.example).

| Variable | Where | Notes |
|---|---|---|
| `DNDLABS_NVIDIA_NIM_API_KEY` | API service env | Unset → enrichment runs but marks every record `skipped_no_key`; see [nvidia-nim.md](nvidia-nim.md) |
| `DNDLABS_FRONTEND_ORIGIN` | API service env | Must match the deployed Static Site's URL: it is the CORS origin and the base of invitation links |
| `DNDLABS_UPLOAD_MAX_BYTES`, `DNDLABS_UPLOAD_MAX_ROWS` | API service env | Optional; defaults 25 MiB and 100,000 rows per uploaded file |
| `DNDLABS_SESSION_TTL_HOURS`, `DNDLABS_INVITATION_TTL_HOURS`, `DNDLABS_PASSWORD_RESET_TTL_HOURS`, `DNDLABS_LOGIN_MAX_ATTEMPTS`, `DNDLABS_LOGIN_LOCKOUT_MINUTES`, `DNDLABS_PASSWORD_MIN_LENGTH` | API service env | Optional; defaults 12 h, 72 h, 24 h, 5, 15 min, 12 characters — see [Auth](architecture.md#auth) |
| `VITE_API_BASE_URL` | Static Site env (**build-time**) | Vite bakes `VITE_*` vars in at build; changing this requires a rebuild, not a restart |

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Sent back to sign-in with "Your session has ended" | The session expired (12 h), was signed out elsewhere, or the password was changed on another device — sign in again |
| `401 invalid email or password` | Wrong email or password. After 5 failures the account locks for 15 minutes (`429`) |
| A user forgot their password, or is locked out | An admin opens **Team** → **Reset password** for them and sends the link (valid 24 h); redeeming it also clears the lock. If no admin can sign in, the operator calls `POST /admin/orgs/{org_id}/password-resets` |
| Invitation or reset link says "invalid, expired or already used" | Links work once and expire (invitations 72 h, resets 24 h); revoked or superseded links stop working — ask an admin (Team page) for a new one |
| `401` on every API call from a script | Missing/wrong `X-API-Key`, or the key was revoked — issue a new key |
| Enrichment always `skipped_no_key` | Expected until `DNDLABS_NVIDIA_NIM_API_KEY` is set; confirm the hosted base URL first — see [nvidia-nim.md](nvidia-nim.md) |
| Upload rejected with `422` | The file is empty, over the size or row limit, not CSV/TSV/XLSX/SDF, or unreadable (e.g. ragged CSV rows); the message says which |
| CSV/JSON run fails with "file not found" | `csv_path`/`json_path` are read from the **API container's** filesystem, not the browser's — users should upload the file instead |
| First request is slow | Free web service sleeps when idle; first request wakes it (~30–60s). The Static Site never sleeps. |
| Free Postgres expired | 30-day limit on Render's free tier; upgrade the plan for anything long-lived |
| `/api/v1/health/ready` returns `503` | The database is unreachable, or not at the deployed code's newest migration. Check `dndlabs-api`'s boot log for the `init-db` outcome: `Running upgrade …` then `Database is up to date.` means migrations applied; `Error: migration failed: …` names the cause. A database that ran the pre-rebuild MVP is repaired automatically by revision `0002` on the next deploy (see [architecture.md](architecture.md#database-schema)). If readiness still fails after a clean **Manual Deploy → Deploy latest commit**, confirm `DNDLABS_DATABASE_URL` on `dndlabs-api` is linked to `dndlabs-db` and that `dndlabs-db` is `Available`. |

## Local development

### Docker Compose

```bash
docker compose up --build
```

Starts Postgres, the API (`localhost:8000`, migrations applied
automatically via `docker/entrypoint.sh`), and the frontend dev server
(`localhost:5173`, against the real API). The admin secret defaults to
`dev-admin-secret`. Onboard a user with the same two calls as on Render
(step 5 above), against `http://localhost:8000/api/v1`.

### Without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
dnd-pipeline init-db
dnd-pipeline bootstrap-org "Acme Pharma"          # prints org_id and api_key
dnd-pipeline invite-admin <org_id> you@acme.com   # prints a one-time sign-up link
dnd-pipeline run --org-id <org_id> --source pubchem --ids 2244,3672

uvicorn dndlabs.api.app:create_app --factory --reload   # API on :8000

cd web && npm ci && npm run dev   # frontend on :5173, mock API by default
                                  # (mock sign-in: ada@acme.example / correct horse battery)
```

## CI

`.github/workflows/ci.yml` gates every push and PR on four jobs:

| Job | Checks |
|---|---|
| `backend` | `ruff check`/`ruff format --check`, `mypy --strict`, `pytest --cov` (including migration tests against a Postgres 16 service), `pip-audit .` (project runtime dependencies) |
| `frontend` | `eslint`, `tsc --noEmit` (source, tests, e2e and configs), `vitest`, `vite build`, `npm audit --audit-level=high` |
| `docker` | Builds and smoke-tests the API image, builds the local-dev web image, validates `docker-compose.yml` — catches a broken image here, not on a Render deploy |
| `e2e` | After `backend` and `frontend` pass: Postgres service → `init-db` → per-run admin secret → API → production frontend build → Playwright (`web/e2e/`). Each test provisions its own org and invitation through the admin API, then drives invitation → password → sign-out/sign-in → file upload and column mapping → pipeline run → report → export; team management (invite, password reset, removal); and API-key sign-in. Uploads the Playwright report and API log on failure. |

The dependency scans block merges. `.github/dependabot.yml` opens weekly
update PRs (pip, npm, GitHub Actions, Docker base images) so a newly
disclosed vulnerability arrives as a fix PR rather than only as a red build.

## Checking a deployment

Two workflows check the live API after a deploy. Neither uses the admin
secret.

### Post-deploy check (automatic)

`.github/workflows/post-deploy.yml` runs `scripts/post_deploy_check.py`
after every successful Render deploy of `dndlabs-api` (Render reports
deploys to GitHub), and on demand (**Actions → Post-deploy check → Run
workflow**). It sends no credentials and creates no data. It waits out a
cold start, then checks:

- liveness, and readiness, which fails unless the database is at the
  deployed code's newest migration;
- that the API serves exactly the routes the deployed commit defines;
- that every protected route rejects an anonymous request with `401`.

A failure shows as a failed workflow run on the deployed commit.

### Smoke test (on demand)

`.github/workflows/smoke.yml` (**Actions → Smoke test → Run workflow**)
runs `scripts/smoke_test.py`, which exercises the product end to end as a
dedicated smoke-test organization: user sign-in (invite → accept → sign out
→ sign in → removal), a file upload with the suggested and a saved column
mapping, a pipeline run, the quality report, export, and isolation from a
second organization. It deletes everything it created, pass or fail, and
refuses to run as any organization without "smoke" in its name.

One-time setup: create the two organizations and store their API keys as
repository secrets (Settings → Secrets and variables → Actions) named
`DNDLABS_SMOKE_API_KEY` and `DNDLABS_SMOKE_ISOLATION_API_KEY`. Each key
reaches only its own organization.

```bash
API=https://dndlabs-api.onrender.com/api/v1
for name in "Smoke test" "Smoke test (isolation)"; do
  curl -X POST $API/admin/orgs -H "X-Admin-Secret: $SECRET" \
    -H "content-type: application/json" -d "{\"name\": \"$name\"}"
done   # each response's raw_key is one secret, shown once
```

Run it locally with the same keys:

```bash
DNDLABS_SMOKE_API_KEY=<key> DNDLABS_SMOKE_ISOLATION_API_KEY=<key> \
  python scripts/smoke_test.py https://dndlabs-api.onrender.com
```

## Known limitations

- **NVIDIA enrichment:** the request/response contract is verified from
  NVIDIA's own source; the hosted base URL is not yet confirmed against a
  live endpoint — see [nvidia-nim.md](nvidia-nim.md).
- **Accounts:** invitation-only, with no email delivery — invitation and
  password-reset links are handed over manually, and there is no
  self-service "forgot password".
- **Sign-in throttling** is per account, not per client IP — see
  [Auth](architecture.md#auth).
- **Sources:** UniProt and PDB are planned, not implemented.
- **Uploads** are stored in PostgreSQL and count toward the database's
  size (1 GB on Render's free tier). Runs execute inside the API process,
  so a large upload competes with API requests for the free instance's
  memory.
- **Dependencies:** no Python lockfile — `pip install` resolves unpinned
  floor versions (the frontend is pinned by `package-lock.json`).
- **Security scanning:** dependency audits (`pip-audit`, `npm audit`) cover
  known-vulnerable packages only — no code-level SAST, and no scanning of
  the container base image's OS packages.
- **Privacy:** [`PRIVACY_POLICY.md`](../PRIVACY_POLICY.md) is a draft
  pending legal review.
