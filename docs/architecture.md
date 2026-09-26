# Architecture

Module boundaries, shared contracts, and database schema. Anything in this
document is a **contract**: changing it is a contract change, called out
explicitly in the PR that makes it.

## Layers

```text
      api/ (FastAPI)        cli/ (Typer)        delivery
             └───────┬───────────┘
                 pipeline/                      orchestration, export, wiring
      ┌──────────────┼───────────────┬──────────────┐
 ingestion/     validation/      filtering/   preprocessing/  enrichment/
      └──────────────┼───────────────┴──────────────┘
                   core/                        contracts, protocols, config,
                                                logging, exceptions
                   auth/                        API keys, user accounts, sessions,
                                                invitations, org multi-tenancy
                   storage/                      SQLAlchemy models, repositories
```

| Rule | Enforced by |
|---|---|
| `ingestion`, `validation`, `filtering`, `preprocessing`, `enrichment`, `auth`, `storage` import only from `core` | Code review |
| Concrete classes are wired only in `pipeline/factory.py` | Composition root |
| `api` and `cli` never touch SQLAlchemy | `Repositories` protocol bundle |
| Values crossing a module boundary are Pydantic models | `core/schemas.py` |
| Every org-scoped repository method takes an explicit `org_id` from the authenticated principal, never from a request body | Tenant isolation |

## Pipeline run

```text
SourceSpec → Connector.fetch → RawRecord[]
                                   │
                                   ▼
                             Validator.run → NormalizedRecord[] + QualityReport
                                   │
                   DatasetRepository.create (records persisted — required for the FKs below)
                                   │
                        ┌──────────┴──────────┐
                  Featurizer            EnrichmentService
              (RDKit descriptors)    (GenMol, or skipped)
```

Runs move through `pending → running → succeeded | failed`. A bad record
never fails a run; it is recorded as a `ValidationIssue` on the quality
report. A run is marked `failed` only on infrastructure errors (ingestion,
storage), with the error persisted on the run row.

Ordering constraint: the dataset and its records must be persisted before
any feature vector or enrichment result, since both reference
`normalized_records.id` by foreign key. Enforced by stage order in
`pipeline/orchestrator.py`.

## Contracts (`core/schemas.py`)

| Model | Purpose |
|---|---|
| `Organization` / `ApiKeyCreated` / `ApiKeyRecord` | Tenant, one-time key reveal, its persisted (hashed) form |
| `OrgContext` | Resolved auth context per request: `org_id`, `principal` (`api_key` / `user`), `role` (`admin` / `member`), and the key or user + session behind it |
| `User` / `UserCredentials` / `UserSession` / `Invitation` | Account, its sign-in state (hash, failure count, lock; internal to auth), a session and an invitation — the latter two persisted by token hash only |
| `LoginRequest` / `SessionCreated` | Sign-in body; one-time reveal of a session token with its expiry and user |
| `InvitationCreate` / `AdminInvitationCreate` / `InvitationCreated` / `InvitationToken` / `InvitationPreview` / `InvitationAccept` / `PasswordChange` | Invitation and password request/response bodies; emails are normalized (trimmed, lowercased) on input |
| `SourceSpec` | Ingest request: `source`, `identifiers` (PubChem CIDs), `csv_path`, `json_path`, `chembl_target`, `dataset_name` — cross-validated per source |
| `RawRecord` | Unvalidated connector output; numeric fields may still be strings; unknown fields go into `extra` |
| `NormalizedRecord` | Model-ready row keyed by `record_key` (InChIKey); always carries `dataset_id` |
| `ValidationIssue` | `rule`, `severity` (`error` / `warning`), `source_record_id`, `field`, `message` |
| `QualityReport` | Counts, `issues_by_rule`, `issues`, `pass_rate` for one run |
| `DatasetFilter` | Record query filters (MW range, target, source, activity range, pagination) |
| `FeatureVector` | RDKit descriptors + Morgan fingerprint for one record |
| `EnrichmentRequest` / `GeneratedCandidate` / `EnrichmentResult` | One record submitted for GenMol enrichment, one generated analog, per-record outcome (`enriched` / `skipped_no_key` / `failed`) |
| `PipelineRun` | `org_id`, `status`, `error`, `dataset_id`, timestamps |
| `Dataset` / `DatasetWithRecords` | Stored dataset metadata, with or without records — both `org_id`-scoped |

IDs are UUID4. Timestamps are timezone-aware UTC.

## Protocols (`core/protocols.py`)

```python
class Connector(Protocol):
    source: SourceType

    def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]: ...  # async generator


class ValidationRule(Protocol):
    name: str

    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome: ...


class Featurizer(Protocol):
    def featurize(self, record: NormalizedRecord) -> FeatureVector: ...


class EnrichmentClient(Protocol):
    def is_enabled(self) -> bool: ...
    async def enrich_batch(
        self, requests: Sequence[EnrichmentRequest]
    ) -> list[EnrichmentResult]: ...
```

`Connector.fetch` is a plain (non-`async`) method typed to return
`AsyncIterator[RawRecord]`: implementations are async generator functions,
so `fetch(spec)` returns an iterator immediately, with no `await` before
the `async for`.

Repositories (`OrganizationRepository`, `ApiKeyRepository`, `UserRepository`,
`SessionRepository`, `InvitationRepository`, `RunRepository`,
`DatasetRepository`, `QualityReportRepository`, `FeatureRepository`,
`EnrichmentRepository`) are bundled as `Repositories`. Every org-scoped
method takes `org_id` explicitly — the entire tenant-isolation mechanism;
there is no other check. A lookup of a missing or wrong-org entity raises
`NotFoundError`. Two kinds of method are deliberately not org-scoped:

- lookups that *establish* identity before any org is known — an API key
  by prefix, a user by email (emails are globally unique), a session or
  invitation by token hash;
- `OrganizationRepository.ping()`, used only by the readiness probe.

## Auth

Two kinds of principal authenticate a request. `auth/dependencies.py`
resolves either into an `OrgContext` that scopes every downstream call; an
API key wins if a request sends both.

| Principal | Header | For | Role |
|---|---|---|---|
| API key | `X-API-Key: ddl_live_…` | Programmatic access, CLI-style integrations | `admin` |
| User session | `Authorization: Bearer ddl_sess_…` | People using the web app | The user's own (`admin` or `member`) |

**API keys.** An operator creates an organization and its first key with
`POST /api/v1/admin/orgs`, guarded by `DNDLABS_ADMIN_BOOTSTRAP_SECRET`
(compared in constant time, and distinct from any org's key). The raw key
is returned once. Only an Argon2id hash and a 12-character lookup `prefix`
are stored, and a prefix collision is retried at issue time. A key can
revoke itself (`POST /auth/keys/revoke`).

**User accounts: invitation, then password.** There is no self-service
sign-up; an organization decides who joins.

1. The operator invites an org's first admin:
   `POST /api/v1/admin/orgs/{org_id}/invitations`, or
   `dnd-pipeline invite-admin <org_id> <email>`.
2. After that, that admin — or any org API key — invites colleagues as
   `admin` or `member` (`POST /auth/invitations`, or the web app's Team
   page).
3. An invitation is a single-use `ddl_inv_…` token, valid for
   `DNDLABS_INVITATION_TTL_HOURS` (default 72). There is no email delivery:
   it is returned once, as a link to the web app —
   `{DNDLABS_FRONTEND_ORIGIN}/invite#token=…` — for the inviter to send. The
   token sits in the URL fragment, which browsers never send to a server,
   and the app removes it from the address bar on load.
4. Redeeming it (`POST /auth/invitations/accept`) sets the invitee's own
   password and signs them in. Marking the invitation used and creating the
   user happen in one transaction: a failed redemption leaves the
   invitation usable, and concurrent redemptions cannot create two accounts.

**Passwords** follow NIST SP 800-63B:
- Length: at least `DNDLABS_PASSWORD_MIN_LENGTH` (default 12) and at most
  128 characters.
- Screening: a password is rejected if it is a common password, a single
  repeated character, or the account's email address or its local part.
- There are no composition rules and no forced rotation.

Passwords are hashed with Argon2id (argon2-cffi defaults, the RFC 9106
low-memory profile), and a hash is upgraded on the next sign-in whenever
those parameters change.

**Sign-in** (`POST /auth/login`) returns an opaque session token:
- **Token and storage.** The token is `ddl_sess_` followed by 256 random
  bits. Only its SHA-256 digest is stored. A fast hash is sufficient for a
  high-entropy random value, and it allows an indexed lookup.
- **Expiry and revocation.** A session expires `DNDLABS_SESSION_TTL_HOURS`
  (default 12) after sign-in. Sign-out (`POST /auth/logout`) revokes it
  immediately. A password change (`POST /auth/password`, which requires the
  current password) revokes all of the user's other sessions.
- **Housekeeping.** Sessions that expired more than 30 days earlier are
  deleted during later sign-ins.

The bearer token is used instead of cookies because the web app and API
are on different `onrender.com` subdomains. `onrender.com` is on the Public
Suffix List, so the two are cross-site, and browsers that block third-party
cookies would break a cookie session.

**Brute-force protection:**
- **Identical failures.** An unknown email and a wrong password fail the
  same way (`401 invalid email or password`). An unknown email still pays
  for one Argon2 verification, so response timing does not reveal whether
  an account exists.
- **Lockout.** After `DNDLABS_LOGIN_MAX_ATTEMPTS` (default 5) consecutive
  failures, the account is locked for `DNDLABS_LOGIN_LOCKOUT_MINUTES`
  (default 15). Sign-in then returns `429` with `Retry-After`, even for the
  right password. The counter is incremented in the database, so the lock
  holds across workers and restarts.
- **Known limit: lockout reveals existence.** An attacker who triggers a
  lockout on purpose learns that the account exists — an accepted trade-off
  against telling a locked-out user nothing.
- **Known limit: no per-IP limit.** Rate limiting by client IP (credential
  stuffing across many accounts) is not implemented. Put the API behind a
  rate-limiting proxy before exposing it widely.

**Authorization within an org:**
- Inviting and deleting the organization's data require the `admin` role.
- Sign-out and password change require a user session.
- Key revocation requires an API key.
- Every other endpoint is open to any authenticated principal of the org.

## Validation

Record rules run in order; each receives the record as the previous rule
left it.

| # | Rule | Errors (record rejected) | Warnings (record kept) |
|---|---|---|---|
| 1 | `schema` | No SMILES or InChI; molecular weight not numeric or ≤ 0 | — |
| 2 | `compound_identity` | Unparsable SMILES/InChI; SMILES and InChI describe different compounds | Supplied InChIKey/formula disagrees with the structure (computed value used) |
| 3 | `unit_normalization` | Value not numeric or negative; missing/unsupported unit; unsupported relation operator | Unit given without a value |

The dataset-level `duplicates` rule then keeps the first record per
`record_key` and drops the rest with a warning. `record_key` is the
InChIKey RDKit computes from the structure, so duplicates are caught across
sources and SMILES spellings. `activity_value_nm` is normalized to
nanomolar; accepted units are `M`, `mM`, `uM`/`µM`/`μM`, `nM`, `pM` and
`mol/L` variants (case-insensitive except molar, which must be `M`).

## Filtering & preprocessing

`filtering/query.py` translates a `DatasetFilter` into a SQL predicate at
the repository layer (`GET /datasets/{id}/records?mw_min=&target=&...`) —
selection, distinct from validation's correctness checks.
`preprocessing/featurize.py` computes RDKit descriptors (MW, LogP, TPSA,
HBD/HBA, rotatable bonds, ring count, QED) and a Morgan fingerprint for
every accepted record with a canonical SMILES, stored in `feature_vectors`.

## NVIDIA BioNeMo enrichment

See [`docs/nvidia-nim.md`](nvidia-nim.md) for the full contract and its
verification status. Summary: for each accepted record, `EnrichmentService`
calls GenMol (a BioNeMo NIM) with the record's canonical SMILES as a seed,
generating scored candidate analogs — property-guided generation, not an
embedding lookup (no such small-molecule endpoint exists in NVIDIA's
published blueprints). Without `DNDLABS_NVIDIA_NIM_API_KEY`, a
`NullEnrichmentClient` marks every record `skipped_no_key`; enrichment is
explicit or absent, never approximated.

## Connectors

| Source | Module | Notes |
|---|---|---|
| PubChem | `ingestion/pubchem.py` | PUG REST property endpoint. CIDs batched (default 100). Exponential backoff on 429/5xx/transport errors. |
| ChEMBL | `ingestion/chembl.py` | `/activity.json?target_chembl_id=...`, paginated via `page_meta.next` (domain-root prefix stripped before reuse against the client's own `base_url`). Same backoff pattern as PubChem. |
| CSV | `ingestion/csv_connector.py` | Delimiter sniffed (`,` `;` tab); header aliases case-insensitive; unknown columns go into `extra`. |
| JSON | `ingestion/json_connector.py` | A top-level list, or `{"records": [...]}` with flat scalar values. |
| UniProt, PDB | `ingestion/registry.py` | Planned, not implemented. Not valid `SourceSpec` sources, so the API rejects them (`422`); the registry lists them in `PLANNED_SOURCES`. |

## Exceptions (`core/exceptions.py`)

```text
DndLabsError
├── ConfigurationError
├── IngestionError
│   └── ConnectorNotFoundError
├── ValidationError        # validator failure, not a bad record
├── StorageError
│   └── NotFoundError
├── AuthError
│   ├── NotAuthenticatedError      # 401 (no/invalid/expired credential)
│   │   └── InvalidApiKeyError
│   ├── InvalidCredentialsError    # 401 (sign-in)
│   ├── AccountLockedError         # 429 + Retry-After
│   ├── InvitationInvalidError     # 400
│   ├── PasswordPolicyError        # 422
│   ├── ForbiddenError             # 403 (role or credential type)
│   └── ConflictError              # 409 (email already has an account)
├── PipelineError
├── ExportError
└── EnrichmentError
```

Every `DndLabsError` maps to an HTTP status in `api/errors.py`; the
exception's own message is never returned to the client for the generic
(`DndLabsError`) case or for anything outside this hierarchy — see
[docs/api.md#errors](api.md#errors).

## Database schema

Alembic head: `0003`.

| Table | Key columns | Notes |
|---|---|---|
| `organizations` | `id`, `name`, `is_active` | Tenant root |
| `api_keys` | `org_id`, `prefix` (unique), `hashed_key`, `revoked_at` | Raw key never stored |
| `users` | `org_id`, `email` (unique), `password_hash`, `role`, `failed_login_count`, `locked_until` | Email stored lowercased |
| `user_sessions` | `user_id`, `org_id`, `token_hash` (unique), `expires_at`, `revoked_at` | Raw token never stored |
| `user_invitations` | `org_id`, `email`, `role`, `token_hash` (unique), `expires_at`, `accepted_at` | Raw token never stored |
| `pipeline_runs` | `org_id`, `source`, `status`, `dataset_id`, `request_payload` (JSON) | |
| `datasets` | `org_id`, `run_id` (unique), `record_count` | One per run |
| `normalized_records` | `org_id`, `dataset_id`, `record_key`, all `NormalizedRecord` fields | Unique `(dataset_id, record_key)` |
| `validation_issues` | `org_id`, `dataset_id`, `severity`, `rule`, `message` | |
| `feature_vectors` | `org_id`, `record_id` (unique), `descriptors` (JSON), `fingerprint_bits` (JSON) | |
| `enrichment_results` | `org_id`, `record_id`, `status`, `candidates` (JSON) | |

`GUID`/`StringArray` custom column types make UUID and array columns native
on PostgreSQL and JSON/TEXT-backed on SQLite, so the same models and
migration run identically against Postgres (Docker/Render) and SQLite
(local dev, tests).

`dnd-pipeline init-db` applies migrations (the API container runs it on
every boot, via `docker/entrypoint.sh`). If it finds a schema created by
`DNDLABS_AUTO_CREATE_SCHEMA=true` (dev convenience) with no
`alembic_version` table, it stamps revision `0001` before upgrading, and
logs a `WARNING` (`migration_stamp_shortcut`) — that path assumes the
existing schema actually matches `0001`; verify it does before relying on
the stamp.

| Revision | Purpose |
|---|---|
| `0001` | Platform schema (table above) |
| `0002` | Retires the pre-rebuild MVP schema. The MVP also used revision id `0001` for an unrelated schema, so databases that ran it reported `0001` as current and never received the platform tables. `0002` detects that state (`organizations` missing), moves the MVP tables into a `legacy_mvp` schema — data preserved, no name collisions — and applies the platform schema. No-op on any database that already has it. |
| `0003` | Adds `users`, `user_sessions` and `user_invitations` (each only if absent, so a stamped `create_all` schema upgrades cleanly). Deletes the organization the removed shared-password login used (`00000000-0000-0000-0000-000000000001`) and everything it owned. |

Migrations are tested against both SQLite and real PostgreSQL
(`tests/integration/test_migrations_postgres.py`, run in CI against a
Postgres 16 service), including the legacy-MVP upgrade path using the MVP's
own vendored migration (`tests/fixtures/legacy_mvp_alembic/`), the `0003`
upgrade and downgrade, and the account repositories' transactional
behaviour (`tests/account_repository_checks.py`, shared by both dialects).

## Readiness vs. liveness

`GET /health` never touches the database — pure liveness, safe for a
platform health check to gate restarts on.
`GET /api/v1/health/ready` does, via `OrganizationRepository.ping()`, and
returns `503` if the database is unreachable or unmigrated. The two are
deliberately different endpoints: a broken database must not restart an
otherwise-healthy process, but it must be possible to detect from outside
without reading logs. See [docs/api.md](api.md#service-and-health-no-auth).

## Connection pooling

`storage/database.py`'s `create_db_engine` sets `pool_size=3,
max_overflow=2, pool_recycle=300` for Postgres — conservative by design,
sized for Render's free-tier connection cap; a single worker does not need
more even under load.

## Frontend

A separate React 18 + TypeScript + Vite SPA under `web/`, deployed as its
own Render Static Site.

**Signing in.** Users sign in with email and password, or with an org API
key via "Use an API key instead". New users arrive through an invitation
link (`/invite`) and choose their password there. Admins invite colleagues
from the Team page, and the Account page changes the password.

**Credential handling.** `auth/SessionContext.tsx` holds the credential — a
session token or an API key — in memory and `sessionStorage` (never
`localStorage`, so it does not outlive the tab):
- `api/client.ts` sends it as `Authorization: Bearer` or `X-API-Key`.
- A stored credential is re-verified against `/auth/whoami` on load.
- Any `401` signs the user out with a notice.
- The query cache is cleared whenever the identity changes, so one org's
  data is never shown to another.

**Development and tests.** The app is built against a mock server (MSW)
that mirrors the real API contract, auth included, so it can be developed
without a backend. Its Playwright e2e test runs it against the real backend.
See `web/src/design-system/tokens.css` for the palette, type and spacing
system.
