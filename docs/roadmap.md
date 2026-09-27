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

The gaps are measured against how drug-discovery projects are judged. The
reference is Mount Sinai Innovation Partners' *Assessment of a Drug
Development Project — Hit/Lead Edition* (v1.8): a scorecard of weighted
questions on the product profile, the target, the hit phase, the lead phase
and ADME/Tox. Line numbers below are the guide's own.

| Guide section (lines) | What a project must show | Status today | Planned in |
|---|---|---|---|
| Hit/lead properties (32–38, 55–61) | MW < 500, clogP < 5, Lipinski, rotatable bonds < 10, PSA < 140 Å² (< 90 Å² for CNS), for the majority and for the 5 most potent compounds | Descriptors are computed and stored, but not shown or exported | R2 |
| Potency (21, 24–25, 41, 44–49) | Hit: IC50/Ki < 10 µM; lead: < 1 µM, ideally < 100 nM; biochemical and cell-based assays judged separately; more than 10 actives | Activity normalized to nM; no potency classes or assay format | R2 |
| Assays and controls (14–15, 24–25, 44, 47) | Named assays (binding, competition, selectivity) with positive and negative controls | No assay metadata | R2 |
| Reactive metabolites (37, 60) | No functional groups known to form reactive metabolites | No structural alerts | R2 |
| Novelty, SAR, series (28–31, 52–54) | Novel scaffold, SAR-amenable, pharmacophore, 1–2 series | None | R3 |
| ADME/Tox (35, 58, 64–67, 77–92) | Solubility at pH 7.4, plasma protein binding, CYP inhibition, PXR, hERG, PAMPA, Caco-2, metabolic stability, cytotoxicity, micronucleus, AMES | None; one activity per record | R3: measured results plus ADMET-AI predictions |
| PK (69–72, 95) | Cmax, Tmax, t½, AUC; single and multiple dose; rodent, then non-rodent | None | R3 |
| Target (7–12, 18–19) | Novelty, human-genetic support, biomarker, animal model, crystal and co-crystal structures | Target is free text | R4 |
| The assessment itself (1–4) | Product profile, a status and weight per question, summary | None | R4 |

The guide's "mM" thresholds in lines 24–25 and 45–49 are a typo for µM, as
its own definitions (lines 21 and 41) state.

Also open:

| Gap | Consequence for users | Planned in |
|---|---|---|
| Export is a flat CSV/JSONL | ML teams still split, filter and convert by hand | R5 |

Wet-lab and animal experiments are out of scope: the platform records and
assesses their results; it does not run or order them.

## Open-source models and libraries

| Purpose | Choice | License | Runs in |
|---|---|---|---|
| Structure standardization | ChEMBL Structure Pipeline on RDKit | MIT / BSD | API |
| Drug-likeness and structural alerts | RDKit: Lipinski/Veber, QED, PAINS + Brenk filter catalogs, SA score; a reactive-metabolite SMARTS set | BSD | API |
| Pharmacophore features | RDKit feature factories | BSD | API |
| Name → structure | PubChem name lookup (online, only for columns the user maps for lookup); OPSIN (MIT, offline IUPAC names) later | — / MIT | API |
| 2D depiction | RDKit.js (WebAssembly) | BSD | Browser |
| Structure editor | Ketcher | Apache-2.0 | Browser |
| Similarity and substructure search | RDKit Morgan fingerprints (Tanimoto), SMARTS | BSD | API |
| ADMET prediction (~41 endpoints: solubility, hERG, CYP inhibition, BBB, AMES, clearance, …) | ADMET-AI (Chemprop, trained on TDC) | MIT | Model worker |
| Custom property models on an org's own assays | Chemprop v2 | MIT | Model worker |
| Optional natural-language assistant | Qwen2.5-7B-Instruct (Apache-2.0) or Phi-3.5-mini (MIT), self-hosted behind an OpenAI-compatible endpoint | Apache-2.0 / MIT | Customer-hosted, opt-in |

Public data sources (free, called over HTTPS; only public identifiers or
user-approved values are sent):

| Source | Used for |
|---|---|
| PubChem, ChEMBL | Ingestion (today); structure lookup; novelty and prior-art checks |
| SureChEMBL | Patent novelty of actives and scaffolds |
| Open Targets Platform | Target–disease genetic evidence, known drugs |
| RCSB PDB | Crystal and ligand co-crystal structures of the target |
| UniProt | Target identity and function |

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

### R2 — Hit-phase triage

- **Structures in every format** *(done)*: MOL blocks, InChIKeys, PubChem
  CIDs, ChEMBL IDs and names, as well as SMILES and InChI; `.smi` and
  `.mol` files. Identifiers are resolved via PubChem/ChEMBL, but only for
  columns the user maps for lookup.
- **Properties in view:** the computed descriptors (MW, clogP, TPSA, H-bond
  donors/acceptors, rotatable bonds, QED) in the API, the records table,
  the compound view and exports.
- **Hit/lead criteria panel:** the guide's thresholds per compound and
  aggregated as the guide asks (majority; 5 most potent). Potency classes:
  hit < 10 µM, lead < 1 µM, optimized < 100 nM. Count of actives.
- **Liabilities:** PAINS, Brenk and reactive-metabolite alerts, highlighted
  on the structure; filters such as "hide PAINS".
- **Assay metadata:** assay format (biochemical / cell-based), readout and
  control flag as column roles, so potency is judged per assay format.
- **Actionable quality report:** issues grouped by cause; bulk fixes (map
  an unknown unit once); edit and re-validate a rejected row; re-run only
  failed records.
- **Background job queue** (Postgres-backed) with a live run stepper and
  per-stage record counts.
- **Onboarding:** first-run checklist, a sample dataset, useful empty states.

### R3 — Lead-phase evidence

- **Series and SAR:** Bemis–Murcko series with counts and activity ranges;
  SAR tables and activity cliffs; key pharmacophore features.
- **Novelty check:** actives and scaffolds against PubChem, ChEMBL and
  SureChEMBL patents.
- **Measured ADME/Tox results:** several endpoints per compound (e.g.
  from CRO reports): solubility, plasma protein binding, CYP isoforms, PXR,
  hERG, PAMPA, Caco-2, metabolic stability, cytotoxicity panel,
  micronucleus, AMES.
- **ADMET-AI predictions** in the model worker, mapped to the same
  endpoints and always labelled *predicted* beside *measured* values.
- **PK parameters:** Cmax, Tmax, t½, AUC per compound, species, route and
  dose.
- **Similarity and substructure search** with a structure editor; a
  **compound drawer** bringing all of the above together.

### R4 — Target dossier and project assessment

- **Target dossier:** Open Targets genetic evidence and known drugs,
  ChEMBL prior art, RCSB PDB structures and co-crystals, UniProt.
- **Project assessment:** a project (target, indication, product profile)
  whose hit-to-lead scorecard is filled in from the platform's data where
  it can be; the rest is answered by the team, with a status, weight and
  summary per question. Exported in the Mount Sinai layout.

### R5 — ML-ready delivery

- **Export presets:** random, scaffold or time splits with a recorded seed;
  Parquet and SDF; a dataset card describing sources, filters,
  standardization and split.
- **Dataset versioning:** immutable versions, diffs, version IDs in every
  export.
- **Custom models:** train Chemprop on an activity column; held-out metrics
  on a scaffold split, parity plot and an applicability-domain flag; score
  other datasets with it.

### R6 — Optional

- **Natural-language assistant** (self-hosted, off by default): turns
  requests into validated, read-only filters; suggests column mappings;
  explains quality reports.
- **Scheduled source refresh** for ChEMBL targets and PubChem lists, with
  a diff of what changed.
- **Email delivery** of invitations and reset links (SMTP).
- **Experiment planner:** next assays suggested from a project's open
  scorecard questions, with typical costs.

## Architecture changes

- **Job queue and worker process** — runs move out of the API process
  (Postgres-backed, no new infrastructure).
- **Model worker** — a separate service holding PyTorch, ADMET-AI and
  Chemprop (about 2 GB RAM, a paid instance). Required from R3; R1 and R2
  run on the current free tier.
- **Schema** — new Alembic revisions for assays, measured results, PK
  parameters, predictions, projects and assessments, dataset versions and
  trained models.
- **Contracts** — new protocols (`StructureResolver`, `PropertyPredictor`,
  `JobQueue`, `TargetInformation`) with in-memory fakes, documented in
  [architecture.md](architecture.md).

## Success measures

- A new user reaches their first cleaned export in under 5 minutes.
- At least 95% of rows in typical lab exports are accepted after column
  mapping, and every rejection has an actionable reason.
- For any uploaded dataset, the scorecard questions that data can answer
  (properties, potency, liabilities, novelty) are answered without manual
  work.
- For 1,000 compounds, a run completes in under 60 s without predictions
  and under 3 min with ADMET-AI.
