# D&D Labs Privacy Policy — DRAFT

> **This is a draft, not a substitute for legal review.** It has not been
> reviewed by a lawyer and must not be published, shown to a customer, or
> relied on as a real privacy commitment until qualified counsel has
> reviewed and approved it (and it has been reconciled with wherever the
> product is actually deployed and hosted, and with GDPR/HIPAA/CCPA or
> other regimes that may apply to your customers). It exists to document
> the technical privacy safeguards actually built into the platform, so
> counsel has an accurate starting point.

## What data the platform holds

- **Organization**: a name, and a set of hashed API keys (never the raw
  key — it is shown once at creation and never stored).
- **Ingested chemical/biological data**: whatever a customer submits via
  `POST /pipelines/run` (PubChem/ChEMBL identifiers, or uploaded CSV/JSON
  content) and the normalized, validated records the pipeline produces
  from it, plus AI-generated candidate molecules from the enrichment
  stage (when configured).
- No end-user accounts, passwords, payment information, or browsing
  analytics are collected. The API has no tracking, and the frontend
  stores the API key only in the browser's `sessionStorage` (cleared when
  the tab closes), never `localStorage` or a cookie.

## Technical safeguards (built, not aspirational)

- **Tenant isolation.** Every stored row belongs to exactly one
  organization (`org_id`), and every repository method that reads or
  writes org-scoped data requires `org_id` as an explicit argument,
  derived only from the authenticated API key — never from a request body
  or query parameter a caller could forge. One organization's key cannot
  read, list, or delete another organization's data (enforced in code and
  covered by automated tests: `tests/integration/test_pipeline_e2e.py::test_two_orgs_are_fully_isolated`,
  `tests/unit/api/test_routes.py::test_org_isolation`).

  **Exception, while enabled:** if `DNDLABS_FREE_TIER_SHARED_PASSWORD` is
  set (see `docs/architecture.md#auth`), every caller who knows that one
  shared password authenticates as the same organization — isolation holds
  between that identity and any *other* organization's real key, but not
  between different users of the shared password itself. Clear the
  variable before onboarding any customer who needs data isolated from
  other users of this value.
- **Key handling.** API keys are hashed with Argon2 before storage; the
  raw secret is never logged (the structured logger redacts fields named
  like `api_key`/`raw_key`/`authorization` and any `Bearer <token>`
  substring in log messages — see `core/logging.py`).
- **Deletion.** `DELETE /orgs/me/data` removes every run, dataset,
  normalized record, quality report, feature vector and enrichment result
  belonging to the calling organization, in one call.
- **Third parties.** Ingested identifiers/SMILES may be sent to PubChem,
  ChEMBL, and (when configured) NVIDIA's hosted BioNeMo GenMol NIM, solely
  to fetch or enrich the requested data — never sold, never used for
  advertising, never sent anywhere else.

## What this draft does not yet cover

Data retention periods, a subprocessor list, breach notification
commitments, cross-border transfer terms, a designated privacy contact,
and how this interacts with any customer's own regulatory obligations
(e.g. if ingested data is itself subject to HIPAA or a research
institution's IRB terms) are all business/legal decisions this document
does not make. Do not represent this policy to a customer until those
gaps are closed by someone qualified to close them.
