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
- **User accounts**: for each person who joins an organization by
  invitation — their email address, their role (`admin`/`member`), an
  Argon2id hash of their password (never the password itself), a count of
  recent failed sign-ins, and the times the account and password were
  created or changed. Sign-in sessions and pending invitations are stored
  only as SHA-256 hashes of their tokens, with expiry and revocation times.
- **Ingested chemical/biological data**: whatever a customer submits via
  `POST /pipelines/run` (PubChem/ChEMBL identifiers, or uploaded CSV/JSON
  content) and the normalized, validated records the pipeline produces
  from it, plus AI-generated candidate molecules from the enrichment
  stage (when configured).
- No payment information or browsing analytics are collected. The API has
  no tracking, and the frontend stores the signed-in session token (or API
  key) only in the browser's `sessionStorage` (cleared when the tab
  closes), never `localStorage` or a cookie.

## Technical safeguards (built, not aspirational)

- **Tenant isolation.** Every stored row belongs to exactly one
  organization (`org_id`), and every repository method that reads or
  writes org-scoped data requires `org_id` as an explicit argument,
  derived only from the authenticated credential (API key or user
  session) — never from a request body or query parameter a caller could
  forge. One organization's key or user cannot read, list, or delete
  another organization's data (enforced in code and covered by automated
  tests: `tests/integration/test_pipeline_e2e.py::test_two_orgs_are_fully_isolated`,
  `tests/unit/api/test_routes.py::test_org_isolation`,
  `tests/unit/api/test_auth_routes.py::test_session_principal_is_tenant_isolated`).
- **Credential handling.** API keys and passwords are hashed with Argon2id
  before storage; session and invitation tokens are stored only as SHA-256
  hashes. None of them is ever logged: the structured logger redacts
  fields named like `api_key`/`token`/`authorization`, removes password
  fields entirely, and masks any `Bearer <token>` substring in log messages
  (see `core/logging.py`). Invitation links carry their token in the URL
  fragment, which browsers do not send to servers.
- **Deletion.** `DELETE /orgs/me/data` removes every run, dataset,
  normalized record, quality report, feature vector and enrichment result
  belonging to the calling organization, in one call; only an
  organization admin (or API key) may call it. User accounts are
  kept (so the organization is not locked out); there is not yet an
  endpoint to delete an individual user account.
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
