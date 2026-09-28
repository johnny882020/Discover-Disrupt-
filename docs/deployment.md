# Deployment

## Render (free tier)

`render.yaml` provisions three resources:

| Resource | Type | Notes |
|---|---|---|
| `dndlabs-api` | Web service (Docker) | `docker/Dockerfile.api`; health check `/health`; `DNDLABS_ADMIN_BOOTSTRAP_SECRET` auto-generated; `DNDLABS_NVIDIA_NIM_API_KEY` left unset (`sync: false`) — set manually once available |
| `dndlabs-web` | Static Site | Builds `web/` with Vite; CDN-backed, no cold start |
| `dndlabs-db` | PostgreSQL | Free tier expires after 30 days |

Pre-deploy note: `DNDLABS_ADMIN_BOOTSTRAP_SECRET` has no default and must be
at least 24 characters — the API refuses to start without one. `render.yaml`
generates a value automatically (`generateValue: true`); an operator-supplied
value must meet the same minimum.

### Deploy

1. Render Dashboard → **New → Blueprint** → connect this repo → pick the branch.
2. **Apply.** The API's first build takes a few minutes (mostly RDKit).
3. Retrieve the generated admin secret: `dndlabs-api` → Environment →
   `DNDLABS_ADMIN_BOOTSTRAP_SECRET`.
4. Confirm the database is migrated: `GET /api/v1/health/ready` returns
   `{"status": "ok", "database": "ok"}`.
5. Check the client IP the API sees once: `FORWARDED_ALLOW_IPS` (below) must
   trust only Render's own proxy, or a client could set its own
   `X-Forwarded-For` and pick whatever IP the per-IP rate limits key on. From
   one network, send `DNDLABS_SIGNIN_LIMIT_PER_IP` failed sign-ins
   (`POST /auth/login` with a wrong password) with a made-up
   `X-Forwarded-For` header added to each; confirm the last one still gets
   `429` and not a fresh limit — if it succeeds, the header is being trusted
   from an untrusted hop and `FORWARDED_ALLOW_IPS` needs narrowing.
6. Onboard the first organization — create it, then invite its admin:
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
7. Send the `accept_url` to the admin over a trusted channel. It works once
   and expires after 72 hours. Opening it, they choose their own password
   and are signed in. From the web app's **Team** page they then invite
   the rest of their organization; nobody else needs the admin secret.

Keep the API key for programmatic access, or discard it — web users never
need it. Additional keys: `POST /admin/orgs/{org_id}/keys`.

**Proxy headers.** `docker/Dockerfile.api` runs uvicorn with `--proxy-headers`
so it derives the client IP (what per-IP rate limits key on) from
`X-Forwarded-For` — but only when the immediate peer is a trusted proxy
(`--forwarded-allow-ips`, from `$FORWARDED_ALLOW_IPS`). `render.yaml` sets it
to Render's private address ranges (`10.0.0.0/8, 172.16.0.0/12,
192.168.0.0/16`); `docker-compose.yml` sets it to `127.0.0.1` (no proxy in
front locally). Never `*`: with it, uvicorn would trust the leftmost,
client-written entry of `X-Forwarded-For`, letting a client pick a fresh "IP"
per request and escape every per-IP limit.

### Accounts and access

| Who | Signs in with | Can |
|---|---|---|
| Operator | `X-Admin-Secret` (`DNDLABS_ADMIN_BOOTSTRAP_SECRET`) | Create organizations, issue API keys, invite each organization's first admin, issue a reset link when no admin can sign in |
| Org admin | Email + password | Everything a member can, plus manage the team (invite, change roles, reset passwords, remove members, revoke invitations) and delete the organization's data |
| Org member | Email + password | Run pipelines; view, filter and export the organization's datasets |
| Program | Org API key (`X-API-Key`) | The same as an org admin, over the API |

People join only by invitation: the link works once, expires after 72
hours, and is where the invitee chooses their password. Sessions last 12
hours; repeated failed sign-ins are rate-limited per client IP and per
email, not locked per account. Details: [Auth](architecture.md#auth).

### Configuration

The variables below matter for a deployment; every setting, with its
default, is listed in [`.env.example`](../.env.example).

| Variable | Where | Notes |
|---|---|---|
| `DNDLABS_NVIDIA_NIM_API_KEY` | API service env | Unset → enrichment runs but marks every record `skipped_no_key`; see [nvidia-nim.md](nvidia-nim.md) |
| `DNDLABS_FRONTEND_ORIGIN` | API service env | Must match the deployed Static Site's URL: it is the CORS origin and the base of invitation links |
| `DNDLABS_UPLOAD_MAX_BYTES`, `DNDLABS_UPLOAD_MAX_ROWS` | API service env | Optional; defaults 25 MiB and 100,000 rows per uploaded file |
| `DNDLABS_REQUEST_MAX_BYTES` | API service env | Optional; default 26 MiB. Largest request body accepted, checked before the body is read (413 if exceeded); must stay above `DNDLABS_UPLOAD_MAX_BYTES` or the API refuses to start |
| `DNDLABS_STRUCTURE_LOOKUP_LIMIT` | API service env | Optional; default 1,000 distinct InChIKeys, PubChem CIDs, ChEMBL IDs and names looked up per run. `0` disables lookups |
| `DNDLABS_PUBCHEM_MIN_INTERVAL_SECONDS` | API service env | Optional; default 0.2 s. Pause between PubChem requests (its 5-requests-per-second limit); also applied between structure-resolution lookups |
| `DNDLABS_WORKER_POLL_SECONDS`, `DNDLABS_WORKER_LEASE_SECONDS`, `DNDLABS_WORKER_MAX_LOST_LEASES`, `DNDLABS_WORKER_CONCURRENCY`, `DNDLABS_WORKER_SHUTDOWN_GRACE_SECONDS` | API service env | Optional; the run worker's poll interval (2 s), lease (120 s), unexpected stops before a run fails (3), runs at once (1) and shutdown grace (20 s). See [architecture](architecture.md#run-queue-and-worker) |
| `DNDLABS_SESSION_TTL_HOURS`, `DNDLABS_INVITATION_TTL_HOURS`, `DNDLABS_PASSWORD_RESET_TTL_HOURS`, `DNDLABS_PASSWORD_MIN_LENGTH` | API service env | Optional; defaults 12 h, 72 h, 24 h, 12 characters — see [Auth](architecture.md#auth) |
| `DNDLABS_RATE_LIMIT_WINDOW_SECONDS`, `DNDLABS_SIGNIN_LIMIT_PER_IP`, `DNDLABS_SIGNIN_LIMIT_PER_EMAIL_AND_IP`, `DNDLABS_SIGNIN_LIMIT_PER_EMAIL`, `DNDLABS_AUTH_FAILURE_LIMIT_PER_IP` | API service env | Optional; brute-force limit window (900 s) and, per window, failed sign-ins per client IP (20), per email from one IP (5), per email from all IPs (50), and failed API-key/session authentications per client IP (50) — see [Auth](architecture.md#auth) |
| `VITE_API_BASE_URL` | Static Site env (**build-time**) | Vite bakes `VITE_*` vars in at build; changing this requires a rebuild, not a restart |

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Sent back to sign-in with "Your session has ended" | The session expired (12 h), was signed out elsewhere, or the password was changed on another device — sign in again |
| `401 invalid email or password` | Wrong email or password — see the sign-in rate limits below if it keeps happening |
| `429 too many attempts; try again later` | A sign-in, per-email or auth-failure rate limit was reached (see [Auth](architecture.md#auth)); wait out the `Retry-After` seconds, or an admin issues a password-reset link, which also lifts the email's sign-in limits |
| A user forgot their password | An admin opens **Team** → **Reset password** for them and sends the link (valid 24 h). If no admin can sign in, the operator calls `POST /admin/orgs/{org_id}/password-resets` |
| Invitation or reset link says "invalid, expired or already used" | Links work once and expire (invitations 72 h, resets 24 h); revoked or superseded links stop working — ask an admin (Team page) for a new one |
| `401` on every API call from a script | Missing/wrong `X-API-Key`, or the key was revoked — issue a new key |
| Enrichment always `skipped_no_key` | Expected until `DNDLABS_NVIDIA_NIM_API_KEY` is set; confirm the hosted base URL first — see [nvidia-nim.md](nvidia-nim.md) |
| Upload rejected with `422` | The file is empty, over the size or row limit, not CSV/TSV/XLSX/SDF/SMILES/MOL, or unreadable (e.g. ragged CSV rows); the message says which |
| Request rejected with `413 request body too large` | The request body exceeds `DNDLABS_REQUEST_MAX_BYTES` (default 26 MiB), checked before the body is read — send a smaller file, or raise the limit (it must stay above `DNDLABS_UPLOAD_MAX_BYTES`) |
| Rows rejected by `structure_lookup` | The identifier was not found, a name matched several compounds, the run exceeded `DNDLABS_STRUCTURE_LOOKUP_LIMIT`, or PubChem/ChEMBL was unavailable; the quality report gives the reason per row. Re-run later for an outage |
| A run stays **Queued** (`pending`) | The worker executes `DNDLABS_WORKER_CONCURRENCY` runs at a time (default 1), shared fairly between organizations; the run starts when earlier work finishes. If nothing progresses, check that `dndlabs-api` is up (`/api/v1/health/ready`) |
| A run shows **Waiting to resume** | It is `pending` again after a deploy, restart or the free plan's idle shutdown stopped it cleanly; it restarts from the beginning automatically and does not count toward the failure limit |
| A run failed with "the run's worker stopped unexpectedly N times; start it again" | The API process stopped repeatedly while executing it, e.g. out of memory on the free instance. Check `dndlabs-api`'s log, reduce the file's size, and start the run again |
| Runs failed with "interrupted by a restart before runs could be resumed; start it again" | They were in progress when migration `0008` was applied; start them again |
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
(`localhost:5173`, against the real API). Set
`DNDLABS_ADMIN_BOOTSTRAP_SECRET` first (at least 24 characters; the API
refuses to start without one), as in the README's quick start. Onboard a user with the same two calls as on Render
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
| `e2e` | After `backend` and `frontend` pass: Postgres service → `init-db` → per-run admin secret → API → production frontend build → Playwright (`web/e2e/`). Each test provisions its own org and invitation through the admin API, then drives invitation → password → sign-out/sign-in → file upload and column mapping → pipeline run → hit/lead assessment → quality report → export → inviting a teammate; team management (invite, password reset, removal); potency judged per assay format with a control left out; and API-key sign-in (`full-workflow.spec.ts`). `screenshots.spec.ts` captures the Dashboard, the Run page mid-run and after cancel, a dataset page and a quality report at 1280 and 390 px in light and dark themes, asserts no horizontal overflow, and uploads the PNGs as a CI artifact. Uploads the Playwright report and API log on failure. |

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
mapping, a queued pipeline run (its final stage and counts), the quality
report, enrichment status, export, and isolation from a second
organization. It deletes everything it created, pass or fail, and
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
- **Structure lookups** depend on PubChem and ChEMBL being reachable from
  the API, and take about 0.2 s per InChIKey or name (PubChem's rate limit;
  CIDs and ChEMBL IDs are batched), inside the run.
- **Uploads** are stored in PostgreSQL and count toward the database's
  size (1 GB on Render's free tier).
- **Runs** execute in the API process on a worker thread, so they compete
  with API requests for the instance's memory and CPU. Render's free plan
  stops the service after 15 minutes without inbound requests — even while
  a run executes, if nobody has the app open — and a deploy stops it too.
  A run stopped this way returns to the queue and restarts from the
  beginning on the next start, without counting toward the failure limit;
  a very large run on the free plan may therefore take several starts.
- **Dependencies:** no Python lockfile — `pip install` resolves unpinned
  floor versions (the frontend is pinned by `package-lock.json`).
- **Security scanning:** dependency audits (`pip-audit`, `npm audit`) cover
  known-vulnerable packages only — no code-level SAST, and no scanning of
  the container base image's OS packages.
- **Privacy:** [`PRIVACY_POLICY.md`](../PRIVACY_POLICY.md) is a draft
  pending legal review.
