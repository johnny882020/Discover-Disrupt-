# Prompt evals (layer 2)

`tests/docs/` (layer 1) catches the doc/code mismatches a parser can see:
routes, tables, migrations, exceptions, enum values, settings, links. Most
of what a reader relies on cannot be parsed — "a cancelled run keeps nothing
it stored", "no route accepts `org_id` from the client", "this comment
explains why". These prompts have a reviewer agent check those claims
against the code, in a way that is repeatable enough to act on.

## The suite

| Prompt | Checks |
|---|---|
| [docs-accuracy](prompts/docs-accuracy.md) | Every statement in `docs/*.md`, `README.md`, `PRIVACY_POLICY.md`, `CLAUDE.md` against the code |
| [comments](prompts/comments.md) | Module docstrings, why-comments, stale or misleading comments |
| [tenant-isolation](prompts/tenant-isolation.md) | `org_id` comes from the principal, never the client |
| [error-handling](prompts/error-handling.md) | No exception text reaches a client; bad records and failed enrichment are data, not exceptions |
| [ui-screenshots](prompts/ui-screenshots.md) | The PNGs in `web/e2e/screenshots/`: layout, 390 px overflow, light/dark legibility, numbers, labels |

Each file has a header (`id`, `scope` — the path globs it reviews, `run with`
— what the reviewer must read), the prompt, and the output format. The
prompts are fixed: change one only deliberately, in its own commit, so runs
stay comparable.

## Method

1. **Pick the prompts** whose `scope` a change touches (all of them before
   a release).
2. **Run each prompt 3 times** per change, each run by a fresh **read-only**
   reviewer agent (it may read files and run read-only commands; it edits
   nothing). One agent per prompt area; at most **five** agents in parallel.
   Give the agent the prompt file verbatim plus the `run with` inputs.
3. **Collect findings.** Every run returns a JSON array of
   `{"file", "line", "claim", "evidence", "severity"}`; `[]` means none.
   Discard any output that is not valid JSON in that shape and rerun.
4. **Compare across runs.** Key each finding by `(file, claim)`, matching
   claims that state the same defect in different words (same file, same
   subject; line numbers may differ). A finding is **accepted only if at
   least 2 of the 3 runs report it**. Single-run findings are noise until
   a later run repeats them.
5. **Verify before fixing.** Open the cited code and confirm each accepted
   finding yourself. A finding the code does not support is rejected, and
   noted as a false positive against the prompt.
6. **Fix, then rerun** the prompt that produced the finding to confirm it is
   gone (and `pytest tests/docs` if a doc changed).
7. **Keep run logs in the session scratchpad**, not the repo: the raw output
   of every run, the vote table and the verification notes. The repo keeps
   only the prompts and the fixes.

Findings a parser could catch belong in `tests/docs/test_docs_consistency.py`
instead: when a prompt keeps finding the same kind of mismatch, turn it into
a layer-1 check.
