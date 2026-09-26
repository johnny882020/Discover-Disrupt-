# Product Roadmap

What comes next for D&D Labs, in release order. Each release closes a gap
that blocks users today before adding new capability. This document is the
plan; the rest of `docs/` describes what is built.

## Principles

1. **Close workflow gaps before adding AI.** A chemist must be able to
   upload, inspect and fix their own data before predictions matter.
2. **Free, permissively licensed models.** MIT, Apache-2.0 or BSD only, runnable
   on CPU. No customer data is sent to a third-party model API.
3. **Every prediction is labelled.** Values are marked *measured*,
   *computed* or *predicted*, with the model and version, and an
   applicability signal where one exists.
4. **The free-tier deployment keeps working.** Heavier models run in an
   optional worker; without it, the features that need it are shown as
   unavailable, never approximated (the pattern GenMol enrichment already
   follows).

## Gaps this roadmap closes

| Gap | Consequence for users |
|---|---|
| Export is a flat CSV/JSONL | ML teams still split, filter and convert by hand |
| No predictions beyond RDKit descriptors (GenMol needs a paid key) | "Is this compound worth pursuing?" goes unanswered |

## Open-source models and libraries

| Purpose | Choice | License | Runs in |
|---|---|---|---|
| Structure standardization | ChEMBL Structure Pipeline on RDKit | MIT / BSD | API |
| Drug-likeness and structural alerts | RDKit: Lipinski/Veber, QED, PAINS + Brenk filter catalogs, SA score | BSD | API |
| Name → structure | OPSIN | MIT | API image (Java runtime) |
| 2D depiction | RDKit.js (WebAssembly) | BSD | Browser |
| Structure editor | Ketcher | Apache-2.0 | Browser |
| Similarity and substructure search | RDKit Morgan fingerprints (Tanimoto), SMARTS | BSD | API |
| ADMET prediction (~41 endpoints: solubility, hERG, CYP inhibition, BBB, AMES, clearance, …) | ADMET-AI (Chemprop, trained on TDC) | MIT | Model worker |
| Custom property models on an org's own assays | Chemprop v2 | MIT | Model worker |
| Optional natural-language assistant | Qwen2.5-7B-Instruct (Apache-2.0) or Phi-3.5-mini (MIT), self-hosted behind an OpenAI-compatible endpoint | Apache-2.0 / MIT | Customer-hosted, opt-in |

Deferred: structure recognition from images/PDFs (DECIMER, MolScribe) and
retrosynthesis (AiZynthFinder) need GPU hosting.

## Releases

### R1 — Core workflow *(done)*

| Feature | Status |
|---|---|
| Chemical standardization (salts, charges, functional groups) in validation; salt forms de-duplicate | Done |
| Account management: admin-issued password-reset links, remove members, change roles, revoke pending invitations | Done |
| Structure depiction with RDKit.js, with a text fallback | Done |
| Browser upload (CSV, TSV, XLSX, SDF) stored per organization | Done |
| Column-mapping step with auto-detected roles and reusable templates | Done |

### R2 — Trust and flow

- **Actionable quality report:** issues grouped by cause; bulk fixes (map
  an unknown unit once, resolve names via OPSIN or PubChem); edit and
  re-validate a rejected row; re-run only failed records.
- **Drug-likeness and liability panel:** Lipinski/Veber, QED, SA score,
  PAINS/Brenk alerts highlighted on the structure; dataset filters such as
  "hide PAINS".
- **Background job queue** (Postgres-backed) with a live run stepper and
  per-stage record counts.
- **Onboarding:** first-run checklist, a sample dataset, useful empty states.

### R3 — Decision support

- **ADMET-AI predictions** as a pipeline stage in the model worker, stored
  with model version and DrugBank percentile; per-compound traffic-light
  profile and dataset heat map.
- **Similarity and substructure search** across an organization's datasets,
  with a structure editor.
- **Scaffold analysis:** Bemis–Murcko grouping with counts and activity
  ranges.
- **Compound drawer:** structure, identifiers, provenance, validation
  history, alerts, predictions and nearest neighbours.

### R4 — ML-ready delivery

- **Export presets:** random, scaffold or time splits with a recorded seed;
  Parquet and SDF; a dataset card describing sources, filters,
  standardization and split.
- **Dataset versioning:** immutable versions, diffs, version IDs in every
  export.
- **Custom models:** train Chemprop on an activity column; held-out metrics
  on a scaffold split, parity plot and an applicability-domain flag; score
  other datasets with it.

### R5 — Optional

- **Natural-language assistant** (self-hosted, off by default): turns
  requests into validated, read-only filters; suggests column mappings;
  explains quality reports.
- **Scheduled source refresh** for ChEMBL targets and PubChem lists, with
  a diff of what changed.
- **Email delivery** of invitations and reset links (SMTP).

## Architecture changes

- **Job queue and worker process** — runs move out of the API process
  (Postgres-backed, no new infrastructure).
- **Model worker** — a separate service holding PyTorch, ADMET-AI and
  Chemprop (about 2 GB RAM, a paid instance). Required from R3; R1 and R2
  run on the current free tier.
- **Schema** — new Alembic revisions for predictions, dataset versions and
  trained models.
- **Contracts** — new protocols (`PropertyPredictor`, `JobQueue`) with
  in-memory fakes, documented in
  [architecture.md](architecture.md).

## Success measures

- A new user reaches their first cleaned export in under 5 minutes.
- At least 95% of rows in typical lab exports are accepted after column
  mapping, and every rejection has an actionable reason.
- For 1,000 compounds, a run completes in under 60 s without predictions
  and under 3 min with ADMET-AI.
