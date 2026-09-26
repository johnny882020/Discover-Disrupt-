# NVIDIA BioNeMo NIM Integration

## What it does

For each accepted, normalized record, the enrichment stage calls **GenMol**
— a BioNeMo NIM for property-guided molecule generation — using the
record's canonical SMILES as a seed, and stores the scored candidate
analogs returned (`enrichment_results.candidates`). This is generation, not
annotation: GenMol proposes new molecules similar to the seed, scored by an
oracle (default QED — Quantitative Estimate of Drug-Likeness), rather than
returning a fixed embedding for the input as given.

Without `DNDLABS_NVIDIA_NIM_API_KEY`, enrichment is explicitly skipped
(`status: "skipped_no_key"`) — surfaced honestly in the API and UI, never
approximated.

## Why generation, not embeddings

No small-molecule NIM in NVIDIA's public BioNeMo Blueprint repositories
(`generative-protein-binder-design`, `generative-virtual-screening`)
exposes a fixed-embedding endpoint for an arbitrary existing molecule.
GenMol's generate-and-score contract is the closest fit, and arguably a
stronger one for a model-ready-dataset product: it adds generative value
on top of validated data rather than a plain annotation.

Every protein-oriented NIM in the same blueprints (OpenFold2/3,
RFdiffusion, ProteinMPNN, MSA-search, DiffDock) requires 1–4 dedicated GPUs
and 64GB+ RAM even self-hosted. Render has no GPU tier at any price, so
this integration can only ever call NVIDIA's hosted cloud endpoint —
self-hosting any BioNeMo NIM is not an option on this platform.

## Contract

Verified against NVIDIA's own notebook source (self-hosted call; NIM
containers expose the same API hosted or not):

```python
POST {GENMOL_HOST}/generate
{"smiles": "<seed>", "num_molecules": 5, "temperature": 1, "noise": 0.2,
 "step_size": 4, "scoring": "QED"}
→ {"molecules": [{"smiles": "...", "score": 0.87}, ...]}
```

Every BioNeMo NIM also exposes `GET /v1/health/ready`; hosted (cloud)
calls add `Authorization: Bearer <NVIDIA_API_KEY>`.

**Unverified: the hosted base URL.** `DNDLABS_NVIDIA_NIM_BASE_URL` defaults
to `https://health.api.nvidia.com/v1/biology/nvidia/genmol`, inferred from
the `/v1/biology/<org>/<model>/<action>` convention used by other hosted
BioNeMo biology NIMs — not confirmed against a live endpoint or real key.
Confirm before depending on this in production. The assumption is isolated
to `_to_request_body`/`_from_response_body` in `enrichment/client.py` plus
one config value — a one-place fix if wrong.

**No retry on failure, by design.** Unlike the PubChem/ChEMBL connectors,
`HttpGenMolClient` does not retry a failed call; a transient NIM error
marks that record `status: "failed"` immediately and the run proceeds.
Enrichment is a best-effort addition to an already-valid dataset, not
something a run should stall on. Add the same backoff pattern already used
by the ingestion connectors if production volumes need it.

## Testing without a real key

- `tests/unit/enrichment/` uses `httpx.MockTransport` against a recorded
  fixture (`tests/fixtures/genmol/generate_response.json`) matching the
  contract above — same pattern as the PubChem/ChEMBL fixtures.
- `tests/live/test_genmol_live.py` is `@pytest.mark.live`, skipped unless
  `DNDLABS_LIVE_TESTS=1` **and** a real `DNDLABS_NVIDIA_NIM_API_KEY` are
  set; never runs in CI. Run it once real access exists, to confirm or
  correct the base URL above, and update this file accordingly.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `DNDLABS_NVIDIA_NIM_API_KEY` | unset | Enrichment is skipped cleanly when unset |
| `DNDLABS_NVIDIA_NIM_BASE_URL` | `https://health.api.nvidia.com/v1/biology/nvidia/genmol` | Unverified — see above |
| `DNDLABS_NVIDIA_NIM_NUM_CANDIDATES` | `5` | Candidates generated per seed molecule |
| `DNDLABS_NVIDIA_NIM_SCORING` | `QED` | Oracle GenMol optimizes for |
