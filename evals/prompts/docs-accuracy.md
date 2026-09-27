# Docs accuracy

- **id:** `docs-accuracy`
- **scope:** `docs/*.md`, `README.md`, `PRIVACY_POLICY.md`, `CLAUDE.md`
- **run with:** every file in scope, then the code each statement describes
  (`src/dndlabs/**`, `web/src/**`, `scripts/*.py`, `docker/**`,
  `docker-compose.yml`, `render.yaml`, `.github/workflows/*`, `.env.example`,
  `pyproject.toml`, `web/package.json`)

## Prompt

You are reviewing the D&D Labs documentation for accuracy. You are
read-only: do not edit any file.

Read every file in scope. For each factual statement — a route, status code,
field, default, limit, count, command, file path, env var, behaviour, order
of operations, guarantee ("never", "always", "only"), or privacy claim — find
the code that implements it and check that the statement is true of the code
as it is now. Read the code; do not infer from names.

Report a statement when:

- the code does something different (wrong value, default, status, order,
  field name, route, command or path);
- the doc claims completeness ("every", "all", "one of") and the code has
  more or fewer items;
- a guarantee has an exception in the code (a path that logs a secret, a
  route that skips a check, a case that is not handled);
- a command in the doc would not work as written from the stated directory;
- the privacy policy or README promises something the code does not do, or
  omits data the code stores or sends to a third party.

Do not report style, wording or missing topics unless the omission makes a
statement false. Do not report what `pytest tests/docs` already checks
(route tables, ORM tables, Alembic revisions, the exception tree, enum
values, worker settings, relative links) unless you found it by reading.

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
