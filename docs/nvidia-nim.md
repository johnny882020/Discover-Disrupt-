# NVIDIA BioNeMo NIM Integration

## What it does

For each accepted, normalized record, the pipeline's enrichment stage calls
**GenMol** — a BioNeMo NIM for property-guided molecule generation — using
the record's canonical SMILES as a seed, and stores the scored candidate
analogs it returns (`enrichment_results.candidates`). This is **generation**,
not annotation: GenMol proposes new molecules similar to the seed, scored by
an oracle (default: QED, the Quantitative Estimate of Drug-Likeness), rather
than returning a fixed embedding for the input as given.

If `DNDLABS_NVIDIA_NIM_API_KEY` is unset, enrichment is explicitly skipped
(`status: "skipped_no_key"`) — surfaced honestly in the API and UI, never
silently faked.

## Why GenMol, and why generation instead of embeddings

The original plan target was "property & embedding enrichment" — attach a
predicted-property/embedding vector to an *existing* molecule. Research
during planning (cloning and reading two of NVIDIA's own public BioNeMo
Blueprint repositories — `NVIDIA-BioNeMo-blueprints/generative-protein-binder-design`
and `NVIDIA-BioNeMo-blueprints/generative-virtual-screening`) found no
small-molecule NIM in either that does that. What exists:

- **GenMol** (small molecules): `POST /generate` with a seed SMILES,
  returns generated+scored analogs. This is real, documented, and has a
  hosted "try it" demo at `build.nvidia.com/nvidia/generative-virtual-screening-for-drug-discovery`.
- **DiffDock** (protein-ligand docking): needs a folded protein target per
  call — not applicable to enriching an arbitrary compound record with no
  associated target structure. Documented here as a future extension, not
  built.
- Every protein-oriented NIM in these blueprints (OpenFold2/3, RFdiffusion,
  ProteinMPNN, MSA-search) needs 1–4 dedicated GPUs and 64GB+ RAM even
  self-hosted — confirming that **Render (no GPU tier at any price) can only
  ever call NVIDIA's hosted cloud endpoint**, never self-host any BioNeMo NIM.

Given that, GenMol's generation-and-scoring output is arguably a stronger
fit for a "model-ready dataset" pitch than a plain embedding would have
been — it's generative AI adding new candidates on top of validated data,
not just an annotation.

## Contract: what's verified vs. what's a documented guess

Ground truth learned from NVIDIA's own notebook code (self-hosted call, but
NIM containers are built to expose the identical API hosted or not):

```python
POST {GENMOL_HOST}/generate
{"smiles": "<seed>", "num_molecules": 5, "temperature": 1, "noise": 0.2,
 "step_size": 4, "scoring": "QED"}
→ {"molecules": [{"smiles": "...", "score": 0.87}, ...]}
```

Also confirmed: every BioNeMo NIM exposes `GET /v1/health/ready`; hosted
(cloud) calls add `Authorization: Bearer <NVIDIA_API_KEY>`.

**Not verified** (this build sandbox's network proxy blocks every NVIDIA
domain, including `build.nvidia.com`, so this could not be confirmed
live): the exact hosted base URL/path. `DNDLABS_NVIDIA_NIM_BASE_URL`
defaults to a best-informed guess,
`https://health.api.nvidia.com/v1/biology/nvidia/genmol`, following the
`/v1/biology/<org>/<model>/<action>` gateway convention used by other
hosted BioNeMo biology NIMs in the same blueprint notebooks — **this one
detail needs confirming against NVIDIA's live API catalog** (or a real key)
before relying on it in production. It is isolated to two functions,
`_to_request_body`/`_from_response_body` in `enrichment/client.py`, plus
one config value, so correcting it is a one-place change.

## How it's tested without a real key

- Unit tests (`tests/unit/enrichment/`) use `httpx.MockTransport` fed by a
  recorded fixture (`tests/fixtures/genmol/generate_response.json`) built
  from the real response shape above — the same pattern the codebase uses
  for PubChem/ChEMBL fixtures.
- `tests/live/test_genmol_live.py` is `@pytest.mark.live`, skipped unless
  `DNDLABS_LIVE_TESTS=1` **and** a real `DNDLABS_NVIDIA_NIM_API_KEY` are
  set — never runs in CI. Run it once real access exists to confirm (or
  correct) the base URL above, then update this file.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `DNDLABS_NVIDIA_NIM_API_KEY` | unset | Enrichment is skipped cleanly when unset |
| `DNDLABS_NVIDIA_NIM_BASE_URL` | `https://health.api.nvidia.com/v1/biology/nvidia/genmol` | Unverified — see above |
| `DNDLABS_NVIDIA_NIM_NUM_CANDIDATES` | `5` | Candidates generated per seed molecule |
| `DNDLABS_NVIDIA_NIM_SCORING` | `QED` | Oracle GenMol optimizes for |

**No retry on failure (by design).** Unlike the PubChem/ChEMBL connectors,
`HttpGenMolClient` does not retry a failed call — a transient NIM error
marks that record `status: "failed"` immediately and the pipeline moves on.
Enrichment is a best-effort, per-record add-on to an already-valid dataset,
not something a run should stall or fail on; if this needs to change for
production volumes, add the same backoff pattern already used by the
ingestion connectors.
