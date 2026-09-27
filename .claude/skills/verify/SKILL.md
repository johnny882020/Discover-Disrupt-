---
name: verify
description: Verify a change end to end before every commit or PR, and after any change to code, docs, UI or deployment config.
---

# Verify

Work through the steps that apply to the change, in order. Stop and fix at
the first failure, then restart from step 1. Commands run from the repo root
unless noted.

## 1. Re-read the diff adversarially

- `git diff` (and `git diff --staged`). Read every hunk as a reviewer
  looking for the bug: wrong condition, missing `org_id`, exception text
  reaching a client, a secret logged, a record stored after what references
  it, a test that cannot fail.
- Check the change against `CLAUDE.md` (layering, types, docstrings,
  tenant isolation, errors, logging, config, tests in the same commit,
  contracts → `docs/architecture.md` + a new Alembic revision).

## 2. Fast checks, scoped to what changed

Backend:

```bash
ruff check . && ruff format --check .
mypy src/
pytest --cov=dndlabs
DNDLABS_TEST_POSTGRES_URL=postgresql+psycopg://… pytest tests/integration   # storage/migration changes
pip-audit .                                                                  # dependency changes
```

Frontend (`cd web`):

```bash
npm run lint && npm run typecheck && npm test -- --run && npm run build && npm audit --audit-level=high
```

## 3. Docs evals (layer 1)

```bash
pytest tests/docs
```

A failure means the docs and code disagree: fix the doc (or the code), never
the check. Run after any change to routes, schemas, models, migrations,
exceptions, settings or `*.md`.

## 4. UI changes: screenshots

1. Start the API with its worker on `:8000` (step 5), build the web app
   against it (`VITE_API_BASE_URL=http://localhost:8000 npm run build` in
   `web/`).
2. Run:

   ```bash
   cd web
   DNDLABS_ADMIN_BOOTSTRAP_SECRET=<API's secret> npx playwright test e2e/screenshots.spec.ts
   ```

   Set `PLAYWRIGHT_CHROMIUM_PATH` if Playwright's headless shell is missing.
3. Open every PNG in `web/e2e/screenshots/` and check it: layout, no
   overflow at 390 px, legible in light and dark, numbers match the
   scenario, accessible labels. Do not report a screen as checked without
   opening its image.

## 5. Runtime changes: the real stack

For changes to the API, worker, pipeline, storage, auth or deployment:

1. Run the API with its worker on `:8000` against Postgres
   (`docker compose up --build`, or `dnd-pipeline init-db` + uvicorn with
   `DNDLABS_DATABASE_URL` pointing at Postgres).
2. `cd web && DNDLABS_ADMIN_BOOTSTRAP_SECRET=<API's secret> npx playwright test`
3. `DNDLABS_SMOKE_API_KEY=<key> DNDLABS_SMOKE_ISOLATION_API_KEY=<key> python scripts/smoke_test.py http://localhost:8000`
4. `python scripts/post_deploy_check.py http://localhost:8000`

## 6. Prompt evals (layer 2)

Follow `evals/README.md`: for each prompt in `evals/prompts/` whose `scope`
the change touches, run it 3 times with fresh read-only reviewer agents (at
most five in parallel), accept findings reported by at least 2 of 3 runs,
verify each accepted finding in the code before fixing it. Keep run logs in
the session scratchpad, not the repo.

## 7. Report

List separately:

- **Verified:** each step run, with the command and its result.
- **Not verified:** each step skipped or blocked, and why (no Postgres, no
  browser, no secret, …).

Never report a step as passing that you did not run.
