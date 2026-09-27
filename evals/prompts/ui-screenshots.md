# UI screenshots

- **id:** `ui-screenshots`
- **scope:** `web/e2e/screenshots/*.png`, `web/src/**`
- **run with:** every PNG in `web/e2e/screenshots/` (open each image);
  `web/e2e/screenshots.spec.ts` for the scenario each screenshot captures
  (its data, viewport and colour scheme); the components under `web/src/`
  that render each screen

## Prompt

You are reviewing the D&D Labs web app from its screenshots. You are
read-only: do not edit any file.

The screenshots are produced by `web/e2e/screenshots.spec.ts` against a real
API with a known scenario. Read the spec first to learn, for each PNG, the
screen, the viewport width, the colour scheme (light or dark) and the data
it seeded. Then open every PNG and check:

1. **Layout.** Nothing overlaps, is clipped, is cut off mid-word or is
   misaligned; empty, loading and error states look intentional.
2. **Overflow at 390 px.** At the phone viewport, no horizontal page scroll,
   no content wider than the screen; wide tables scroll inside their own
   container; buttons and inputs fit.
3. **Legibility in light and dark.** Text, icons, borders, focus rings and
   chart marks have enough contrast in both schemes (WCAG AA: 4.5:1 for body
   text, 3:1 for large text and UI components); nothing is invisible or
   hard-coded to one scheme.
4. **Numbers match the scenario.** Every count, percentage, potency class,
   status and stage shown equals what the seeded scenario produces; totals
   add up across the screen.
5. **Accessible labels.** From the components that render each screen: every
   input has a label, every icon-only button an accessible name, every chart
   or status colour a text equivalent; headings are in order.

Report the PNG file (and, where you traced it, the component and line that
causes the defect). Report only what is visible in a screenshot or verified
in the component code.

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
