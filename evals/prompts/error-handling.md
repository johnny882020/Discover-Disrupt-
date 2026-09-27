# Error handling

- **id:** `error-handling`
- **scope:** `src/dndlabs/**/*.py`
- **run with:** every file in scope, especially `api/errors.py`,
  `api/routes/**`, `pipeline/**`, `validation/**`, `enrichment/**`,
  `ingestion/**`; `CLAUDE.md` (Errors, Logging); `docs/api.md` (Errors)

## Prompt

You are reviewing D&D Labs's error handling. You are read-only: do not edit
any file.

The rules (`CLAUDE.md`): raise subclasses of `DndLabsError`; no bare
`except:`. A bad record becomes a `ValidationIssue`, not an exception. A
failed enrichment call becomes `status="failed"`, never raised into the
pipeline. An exception's own message never reaches an API client:
`api/errors.py` returns a fixed generic `500` body and logs the detail
server-side, and only mapped 4xx responses carry a client-facing message.

Check:

1. **No leaked exception text.** Trace every path from an exception to an
   HTTP response: the handlers in `api/errors.py`, every `HTTPException`,
   every `str(exc)`/`repr(exc)`/`exc.args` put in a response body, header,
   run `error` field, quality report or export that a client can read.
   Report any path where an exception's message, a stack trace, SQL, a file
   path or a third-party response body reaches a client, other than a
   mapped 4xx whose message is written for the client.
2. **Status mapping.** Every `DndLabsError` subclass maps to the status
   `docs/api.md` gives it; anything else is a generic `500`.
3. **Bad records.** Malformed, unparsable or out-of-range input records
   (connectors, uploads, validation, structure lookup) become
   `ValidationIssue`s or rejected rows, never an exception that fails the
   run.
4. **Enrichment.** Every failure of an enrichment call (HTTP error, timeout,
   bad response, missing key) becomes a result with `status="failed"` (or
   `skipped_no_key`), never an exception out of the enrichment stage.
5. **Catches.** No bare `except:`; each `except Exception` / broad catch is
   justified, logs the detail via `core.logging.get_logger` without a raw
   credential, and does not swallow an error the caller needed.

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
