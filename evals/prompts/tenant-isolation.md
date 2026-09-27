# Tenant isolation

- **id:** `tenant-isolation`
- **scope:** `src/dndlabs/api/**`, `src/dndlabs/auth/**`,
  `src/dndlabs/storage/**`, `src/dndlabs/pipeline/**`,
  `src/dndlabs/core/protocols.py`, `src/dndlabs/core/schemas.py`
- **run with:** every file in scope; `CLAUDE.md` (Tenant isolation);
  `docs/architecture.md` (Auth, Run queue and worker, Database schema)

## Prompt

You are reviewing D&D Labs for cross-tenant data access. You are read-only:
do not edit any file.

The rule (`CLAUDE.md`): every org-scoped repository method takes `org_id`
explicitly, derived server-side from the authenticated principal (API key or
user session), never from a request body, query parameter, path parameter
or header other than the credential. The run queue's claim/lease methods,
which the worker calls across organizations, are the documented exception —
check that they are documented as such and that the runs they return are
then executed under the run's own stored `org_id`.

Check:

1. Every repository protocol and implementation method that reads, writes or
   deletes org-owned rows (runs, datasets, records, issues, reports,
   features, enrichment results, uploads, mapping templates, users,
   sessions, invitations, keys) takes `org_id` and filters by it in the
   query itself — including joins, bulk deletes and counts.
2. Every route gets `org_id` only from the resolved principal
   (`OrgContext`). Trace each route's `org_id` to its source. Report any
   route or schema that accepts `org_id` (or an ID that selects an org) from
   the client, outside the admin-secret routes under `/api/v1/admin`.
3. A lookup by ID for another org's object returns `404`, not `403` or
   the object.
4. Background work (the run worker, enrichment, exports) carries the run's
   `org_id` through every repository call it makes.
5. Session and invitation tokens resolve to their own org; a user of one
   org cannot act in another.

Report each path by which one organization could read, change or delete, or
learn of the existence of, another organization's data.

## Output format

Return only a JSON array, no prose around it. One object per finding:

```json
[
  {
    "file": "path/relative/to/repo",
    "line": 42,
    "claim": "What is wrong, in one sentence",
    "evidence": "The code that shows it: path:line and the relevant text",
    "severity": "blocker"
  }
]
```

- `line` is an integer, or `null` when the finding is about a whole file.
- `severity`: `blocker` (wrong in a way that breaks a user, a deploy or a
  security property), `major` (misleads a reader or hides a defect),
  `minor` (imprecise, incomplete or cosmetic).
- Report only what you verified in the code. Cite the code in `evidence`;
  a finding without evidence is not a finding. No findings → `[]`.
