# Comments and docstrings

- **id:** `comments`
- **scope:** `src/dndlabs/**/*.py`, `scripts/*.py`, `web/src/**/*.{ts,tsx}`,
  `web/e2e/**/*.ts`
- **run with:** every file in scope (or, for a change, the changed files and
  the code they call); `CLAUDE.md` for the standards

## Prompt

You are reviewing the code comments and docstrings of D&D Labs. You are
read-only: do not edit any file.

For each file in scope, check:

1. **Module docstring.** Every Python module (and every non-trivial TS
   module's header comment, where present) states the module's
   responsibility — what it owns and, where the layering in `CLAUDE.md`
   makes it relevant, what it must not do. Report a missing docstring, or
   one that describes a responsibility the module no longer has.
2. **Why-comments.** A non-obvious decision (an ordering constraint, a
   workaround, a security or tenant-isolation choice, a performance trade-off,
   a magic number, a swallowed error) has a comment saying why. Report a
   non-obvious decision without one only when a maintainer would plausibly
   undo it by mistake.
3. **Agreement with the code.** Every docstring (Google style: `Args`,
   `Returns`, `Raises`) and comment says what the code does now: parameter
   names and meanings, return values, exceptions actually raised, defaults,
   units, ordering, "never"/"always" claims. Report each disagreement.
4. **Stale or misleading comments.** Comments that refer to removed code,
   old behaviour, TODOs already done, or that restate the code wrongly.

Do not report comments that are merely redundant or could be worded better.
Check every claim against the code before reporting it.

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
