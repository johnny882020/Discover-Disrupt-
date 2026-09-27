# Architecture

Module boundaries, shared contracts, and database schema. Anything in this
document is a **contract**: changing it is a contract change, called out
explicitly in the PR that makes it.

## Layers

```text
      api/ (FastAPI)        cli/ (Typer)        delivery
             └───────┬───────────┘
                 pipeline/                      orchestration, run worker, export, wiring
      ┌──────────────┼───────────────┬──────────────┬──────────────┐
 ingestion/     validation/      filtering/   preprocessing/  enrichment/  assessment/
      └──────────────┼───────────────┴──────────────┴──────────────┘
                   core/                        contracts, protocols, config,
                                                logging, exceptions
                   auth/                        API keys, user accounts, sessions,
                                                invitations, org multi-tenancy
                   storage/                      SQLAlchemy models, repositories
```

| Rule | Enforced by |
|---|---|
| `ingestion`, `validation`, `filtering`, `preprocessing`, `enrichment`, `assessment`, `auth`, `storage` import only from `core` | Code review |
| Concrete classes are wired only in `pipeline/factory.py` | Composition root |
| `api` and `cli` never touch SQLAlchemy | `Repositories` protocol bundle |
| Values crossing a module boundary are Pydantic models | `core/schemas.py` |
| Every org-scoped repository method takes an explicit `org_id` from the authenticated principal, never from a request body | Tenant isolation |

## Pipeline run

```text
POST /pipelines/run → pending run (pipeline_runs)
  → RunWorker claims it (RunRepository.claim_next)
  → fetch        Connector.fetch / fetch_for_org → RawRecord[]
  → resolve      StructureResolver.resolve (MOL blocks; PubChem/ChEMBL lookups)
  → validate     Validator.run → NormalizedRecord[] + QualityReport
  → store        DatasetRepository.create (dataset + records), QualityReportRepository.save
  → featurize    Featurizer (RDKit descriptors, alerts, fingerprint)
  → enrich       EnrichmentService (GenMol, or skipped)
```

Stages run in this order, one after another (`pipeline/orchestrator.py`).
Runs move through `pending → running → succeeded | failed | cancelled`. A bad record
never fails a run; it is recorded as a `ValidationIssue` on the quality
report. A run is marked `failed` only on infrastructure errors (ingestion,
storage), after repeated unexpected worker stops (see below), or when it
was lost before revision `0008`; the error is persisted on the run row.

Ordering constraint: the dataset and its records must be persisted before
any feature vector or enrichment result, since both reference
`normalized_records.id` by foreign key. Enforced by stage order in
`pipeline/orchestrator.py`.

### Run queue and worker

`POST /pipelines/run` only queues a run: `pipeline_runs` is the queue, so a
run is its own job and nothing else has to be kept in sync.
`pipeline/worker.py` (`RunWorker`) executes runs inside the API process,
started and stopped with the app:

- **Claim.** It polls every `DNDLABS_WORKER_POLL_SECONDS`.
  `RunRepository.claim_next` picks among the runnable runs (`pending`, or
  `running` under an expired lease) the one whose organization has the
  fewest executing runs, oldest first, so one organization's backlog does not
  hold up another's. It reads the candidate with `FOR UPDATE SKIP LOCKED`
  (PostgreSQL) and claims it with an update conditioned on the state it
  read, so two workers never claim one run on any database. The claim sets
  `worker_id`, a lease (`DNDLABS_WORKER_LEASE_SECONDS`) and one more
  `attempts`.
- **Execute.** The run executes on a worker thread (`DNDLABS_WORKER_CONCURRENCY`
  at a time), so RDKit's CPU-bound stages never block the API's event loop.
  Meanwhile the lease is renewed every third of its length.
- **Checkpoints.** `PipelineService.execute` records the stage and counts
  between stages and within long stages: after each lookup request while
  resolving (`StructureResolver.resolve`'s `checkpoint`), every 500 records
  while validating (`Validator.run`'s `checkpoint`) and featurizing, and
  between enrichment batches (`EnrichmentService.enrich`'s `checkpoint`).
  At a checkpoint the run stops for a cancellation request (it ends
  `cancelled` and keeps nothing) or when the worker asks it to (shutdown,
  lost lease).
- **Clean stop** (shutdown, deploy, free-plan idle stop). The worker waits
  up to `DNDLABS_WORKER_SHUTDOWN_GRACE_SECONDS` for its runs to reach a
  checkpoint and `release`s each: the run returns to `pending` (its partial
  output deleted in the same transaction, so cancelling it then leaves
  nothing behind), and the next process resumes it at once. Clean stops
  never count as failures. A run still busy after the grace period keeps
  its lease until it expires, so it is never executed twice at once.
- **Unexpected stop** (crash, kill). The run is claimed again once its
  lease expires; each such re-claim increments the internal
  `pipeline_runs.lost_leases`. After `DNDLABS_WORKER_MAX_LOST_LEASES`
  unexpected stops, `fail_exhausted` fails the run ("the run's worker
  stopped unexpectedly N times; start it again").
- **Resume.** Every attempt first deletes what an earlier attempt stored
  (`DatasetRepository.delete_for_run`), so a resumed run never leaves a
  partial or duplicate dataset. If the organization's data is deleted while
  its run executes, the run stops quietly and leaves nothing behind.
- **CLI.** `dnd-pipeline run` claims its own run (`RunRepository.claim`)
  and executes it through the same worker code, so an API worker sharing
  the database never picks it up.

The queue methods are not scoped by organization (see
[Protocols](#protocols-coreprotocolspy)): the worker serves every
organization, and each run it claims carries the `org_id` under which
everything for that run is done.

## Contracts (`core/schemas.py`)

| Model | Purpose |
|---|---|
| `Organization` / `ApiKeyCreated` / `ApiKeyRecord` | Tenant, one-time key reveal, its persisted (hashed) form |
| `OrgContext` | Resolved auth context per request: `org_id`, `principal` (`api_key` / `user`), `role` (`admin` / `member`), and the key or user + session behind it |
| `User` / `UserCredentials` / `UserSession` / `Invitation` | Account, its sign-in state (hash, failure count, lock; internal to auth), a session and an invitation — the latter two persisted by token hash only |
| `LoginRequest` / `SessionCreated` | Sign-in body; one-time reveal of a session token with its expiry and user |
| `InvitationCreate` / `AdminInvitationCreate` / `InvitationCreated` / `InvitationToken` / `InvitationPreview` / `InvitationAccept` / `PasswordChange` | Invitation and password request/response bodies; emails are normalized (trimmed, lowercased) on input |
| `InvitationPurpose` / `MemberUpdate` / `PasswordResetRequest` / `PasswordResetCreated` / `PasswordResetPreview` | Single-use token purpose (`join` / `password_reset`); role change; operator reset request; one-time reset reveal; what a reset link sets |
| `SourceSpec` | Ingest request: `source`, `identifiers` (PubChem CIDs), `csv_path`, `json_path`, `chembl_target`, `upload_id` + `column_mapping`, `dataset_name` — cross-validated per source |
| `ColumnRole` | What an uploaded column holds (`smiles`, `inchi`, `mol_block`, `inchikey`, `pubchem_cid`, `chembl_id`, `lookup_name`, `name`, `assay_format`, `control`, `activity_value`, … or `ignore`); a mapping needs one of the `STRUCTURE_ROLES` and uses each other role once. `LOOKUP_ROLES` are the structure roles resolved by a PubChem/ChEMBL lookup |
| `Upload` / `UploadFormat` / `UploadPreview` | A stored file's metadata (`csv` / `tsv` / `xlsx` / `sdf` / `smi` / `mol`, size, SHA-256); its columns, first rows, row count and suggested mapping |
| `MappingTemplateCreate` / `MappingTemplate` | A named, org-saved column mapping, suggested for uploads whose headers include its columns |
| `RawRecord` | Unvalidated connector output; numeric fields may still be strings; unknown fields go into `extra`. Carries the structure as `smiles`/`inchi`/`mol_block` or an identifier to look up, plus resolution's `structure_source` or `structure_error` |
| `NormalizedRecord` | Model-ready row keyed by `record_key` (InChIKey); always carries `dataset_id`. `context_key()` hashes its measurement context (target, assay type, assay format, control), or is empty when it has none |
| `AssayFormat` / `ControlType` | A measurement's assay format (`biochemical` / `cell_based`) and control flag (`positive` / `negative`) |
| `ValidationIssue` | `rule`, `severity` (`error` / `warning`), `source_record_id`, `field`, `message` |
| `QualityReport` | Counts, `issues_by_rule`, `issues`, `pass_rate` for one run |
| `DatasetFilter` | Record query filters (MW range, target, source, activity range, pagination) |
| `FeatureVector` | RDKit descriptors, structural `alerts` and Morgan fingerprint for one record |
| `PotencyClass` / `Criterion` / `CompoundProfile` / `CriterionShare` / `CriterionSummary` / `FormatPotency` / `DatasetAssessment` | Hit/lead assessment: a compound's potency class (the most potent class a majority of its measurements reach), computed properties, alerts and criteria met; compound counts per assay format; each criterion over all compounds, actives and the five most potent |
| `AlertFamily` / `StructuralAlert` / `StoredFeatures` | A flagged substructure (PAINS, Brenk, reactive metabolite) with its matched atoms; a record's stored descriptors and alerts (`alerts` is `None` when stored before alerts existed) |
| `EnrichmentRequest` / `GeneratedCandidate` / `EnrichmentResult` | One record submitted for GenMol enrichment, one generated analog, per-record outcome (`enriched` / `skipped_no_key` / `failed`) |
| `PipelineRun` / `RunStatus` / `RunStage` / `RunProgress` | `org_id`, `spec`, `status`, `stage`, per-stage counts, `attempts`, `cancel_requested`, `error`, `dataset_id`, timestamps |
| `Dataset` / `DatasetWithRecords` | Stored dataset metadata, with or without records — both `org_id`-scoped |

IDs are UUID4. Timestamps are timezone-aware UTC.

## Protocols (`core/protocols.py`)

```python
class Connector(Protocol):
    source: SourceType

    def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]: ...  # async generator


class OrgScopedConnector(Protocol):  # reads org-owned input, e.g. an upload
    source: SourceType

    def fetch_for_org(self, org_id: uuid.UUID, spec: SourceSpec) -> AsyncIterator[RawRecord]: ...


class ValidationRule(Protocol):
    name: str

    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome: ...


class StructureResolver(Protocol):
    async def resolve(
        self, raws: Sequence[RawRecord], checkpoint: Callable[[int], None] | None = None
    ) -> list[RawRecord]: ...


class Featurizer(Protocol):
    def featurize(self, record: NormalizedRecord) -> FeatureVector: ...


class EnrichmentClient(Protocol):
    def is_enabled(self) -> bool: ...
    async def enrich_batch(
        self, requests: Sequence[EnrichmentRequest]
    ) -> list[EnrichmentResult]: ...


class Exporter(Protocol):
    def export(
        self,
        records: Iterable[NormalizedRecord],
        fmt: ExportFormat,
        profiles: Mapping[uuid.UUID, CompoundProfile] | None = None,
    ) -> bytes: ...
```

`Connector.fetch` is a plain (non-`async`) method typed to return
`AsyncIterator[RawRecord]`: implementations are async generator functions,
so `fetch(spec)` returns an iterator immediately, with no `await` before
the `async for`. The orchestrator calls `fetch_for_org` with the run's
`org_id` when a connector implements `OrgScopedConnector`, so a connector
reading stored org data can only reach the running org's rows.

Repositories (`OrganizationRepository`, `ApiKeyRepository`, `UserRepository`,
`SessionRepository`, `InvitationRepository`, `RunRepository`,
`DatasetRepository`, `QualityReportRepository`, `FeatureRepository`,
`EnrichmentRepository`, `UploadRepository`, `MappingTemplateRepository`)
are bundled as `Repositories`. Every org-scoped
method takes `org_id` explicitly — the entire tenant-isolation mechanism;
there is no other check. A lookup of a missing or wrong-org entity raises
`NotFoundError`. Three kinds of method are deliberately not org-scoped:

- lookups that *establish* identity before any org is known — an API key
  by prefix, a user by email (emails are globally unique), a session or
  invitation by token hash;
- `OrganizationRepository.ping()`, used only by the readiness probe;
- the run worker's queue methods `RunRepository.claim_next`,
  `fail_exhausted`, `renew_lease` and `release` (see
  [Run queue and worker](#run-queue-and-worker)).

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

**Managing the team.** Admins (and org API keys) list members, change
roles, remove members and revoke pending invitations. A removed member's
account and sessions are deleted at once; their email can be invited again.
An organization must always keep at least one admin user: demoting or
removing the last one is refused (`409`), and admins cannot remove
themselves.

**Password reset.** There is no self-service "forgot password" (no email
delivery). Instead, an admin issues a single-use reset link for a member
(`POST /auth/members/{id}/password-reset`), valid for
`DNDLABS_PASSWORD_RESET_TTL_HOURS` (default 24) at
`{DNDLABS_FRONTEND_ORIGIN}/reset#token=…`. It is the same token mechanism as
invitations (`user_invitations.purpose = "password_reset"`), and the two
kinds are not interchangeable. Issuing a new link supersedes the member's
earlier unused ones. Redeeming it sets the new password, clears any
sign-in lock and ends all of the user's sessions, in one transaction. If
no admin can sign in, the operator issues the link
(`POST /admin/orgs/{id}/password-resets`).

**Authorization within an org:**
- Managing members and invitations, and deleting the organization's data,
  require the `admin` role.
- Sign-out and password change require a user session.
- Key revocation requires an API key.
- Every other endpoint is open to any authenticated principal of the org.

## Validation

Record rules run in order; each receives the record as the previous rule
left it.

| # | Rule | Errors (record rejected) | Warnings (record kept) |
|---|---|---|---|
| 0 | `structure_lookup` | The structure could not be resolved from the record's MOL block or identifiers (the reason is the message) | Structure looked up (the source is the message, e.g. "structure from PubChem CID 2244") |
| 1 | `schema` | No structure and no identifier to look up; molecular weight not numeric or ≤ 0 | — |
| 2 | `compound_identity` | Unparsable SMILES/InChI; SMILES and InChI describe different compounds | Supplied InChIKey/formula disagrees with the structure (computed value used) |
| 3 | `standardization` | — | Structure changed by standardization (salts/solvents stripped, charges neutralized; the original structure is kept in the message); multi-component structure (mixture) |
| 4 | `unit_normalization` | Value not numeric or negative; missing/unsupported unit; unsupported relation operator | Unit given without a value |
| 5 | `assay_context` | — | Unrecognized assay format or control value (the field is left empty) |

`standardization` applies the [ChEMBL Structure
Pipeline](https://github.com/chembl/ChEMBL_Structure_Pipeline) (MIT) and
replaces the structure with its standardized parent, recomputing
identifiers, formula and molecular weight.

The dataset-level `duplicates` rule then keeps the first record per
`record_key` and measurement context (`context_key()`) and drops the rest
with a warning. `record_key` is the InChIKey of the standardized parent, so
duplicates are caught across sources, SMILES spellings and salt forms; the
same compound measured against another target, in another assay or format,
or as a control is kept. `activity_value_nm` is normalized to
nanomolar; accepted units are `M`, `mM`, `uM`/`µM`/`μM`, `nM`, `pM` and
`mol/L` variants (case-insensitive except molar, which must be `M`).

Example: `tests/fixtures/lab_export_malformed.csv` has 5 records; 3 are
accepted and 2 rejected (an invalid SMILES, a missing structure), each
rejection reported as a `ValidationIssue` in the run's `QualityReport`.
Malformed input never crashes a run.

## Filtering & preprocessing

`filtering/query.py` translates a `DatasetFilter` into a SQL predicate at
the repository layer (`GET /datasets/{id}/records?mw_min=&target=&...`) —
selection, distinct from validation's correctness checks.
`preprocessing/featurize.py` computes RDKit descriptors (MW, LogP, TPSA,
HBD/HBA, Lipinski's NH + OH and N + O counts, rotatable bonds, ring count,
QED), structural alerts (`preprocessing/alerts.py`: RDKit's PAINS and Brenk
catalogs plus a tested reactive-metabolite set, each with its matched
atoms) and a Morgan fingerprint for every accepted record with a canonical
SMILES, stored in `feature_vectors`.

## Hit/lead assessment

`assessment/criteria.py` holds the hit-to-lead thresholds and computes a
`DatasetAssessment` from records and their stored descriptors. It leaves
out control records, groups measurements by compound (`record_key`), gives
each compound the most potent class a majority of its measurements reach,
repeats that count per assay format, and evaluates each criterion over all
compounds, the actives and the five most potent (the groups a hit-to-lead
review uses).
`pipeline/assessment.py` (`AssessmentService`) loads a dataset and its
stored features (`FeatureRepository.features_for`, org-scoped) and
recomputes, in memory, descriptors or alerts missing from vectors stored
before they were added. It serves `GET /datasets/{id}/assessment`, and the exporter
writes the profiles' properties after the record fields.

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
| Upload | `ingestion/uploads.py` | Org-scoped: reads the stored file (`ingestion/tabular.py`: CSV/TSV, XLSX first worksheet, SDF, SMILES, MOL) and applies the run's `column_mapping`. `UploadService` stores and previews files and manages mapping templates; `ingestion/mapping.py` suggests a mapping from a template, then header aliases, then column contents. |
| CSV | `ingestion/csv_connector.py` | Server-side path (operators). Delimiter sniffed (`,` `;` tab); header aliases matched ignoring case, spacing and punctuation (`fields.normalize_header`); unknown columns go into `extra`. |
| JSON | `ingestion/json_connector.py` | Server-side path (operators). A top-level list, or `{"records": [...]}` with flat scalar values. |
| UniProt, PDB | `ingestion/registry.py` | Planned, not implemented. Not valid `SourceSpec` sources, so the API rejects them (`422`); the registry lists them in `PLANNED_SOURCES`. |

Every run's records then pass through structure resolution
(`ingestion/resolution.py`, `LookupStructureResolver`), before validation.
Records with SMILES or InChI are untouched. Otherwise a MOL block is read
locally, then the record's InChIKey, PubChem CID, name (PubChem PUG REST)
or ChEMBL ID (`/molecule.json`) is looked up. Lookups are de-duplicated,
batched where the service allows it, throttled and capped per run
(`DNDLABS_STRUCTURE_LOOKUP_LIMIT`). An unavailable service marks the
affected records unresolved rather than failing the run, as enrichment
does. PubChem, ChEMBL and resolution share one retry helper
(`ingestion/http.py`).

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
│   ├── RunInterruptedError        # stopped at a checkpoint (shutdown, lost lease); resumed, not a failure
│   └── RunDeletedError            # org data deleted mid-run; the run stops quietly, nothing recorded
├── ExportError
└── EnrichmentError
```

Every `DndLabsError` maps to an HTTP status in `api/errors.py`; the
exception's own message is never returned to the client for the generic
(`DndLabsError`) case or for anything outside this hierarchy — see
[docs/api.md#errors](api.md#errors).

## Database schema

Alembic head: `0008`.

| Table | Key columns | Notes |
|---|---|---|
| `organizations` | `id`, `name`, `is_active` | Tenant root |
| `api_keys` | `org_id`, `prefix` (unique), `hashed_key`, `revoked_at` | Raw key never stored |
| `users` | `org_id`, `email` (unique), `password_hash`, `role`, `failed_login_count`, `locked_until` | Email stored lowercased |
| `user_sessions` | `user_id`, `org_id`, `token_hash` (unique), `expires_at`, `revoked_at` | Raw token never stored |
| `user_invitations` | `org_id`, `email`, `role`, `purpose` (`join` / `password_reset`), `token_hash` (unique), `expires_at`, `accepted_at`, `revoked_at` | Invitations and reset links; raw token never stored |
| `pipeline_runs` | `org_id`, `source`, `status`, `stage`, `progress` (JSON), `attempts`, `cancel_requested`, `worker_id`, `lease_expires_at`, `lost_leases` (internal), `dataset_id`, `request_payload` (JSON), `error`, `created_at` (indexed), `started_at`, `finished_at` | Also the run queue (see [Run queue and worker](#run-queue-and-worker)) |
| `datasets` | `org_id`, `run_id` (unique), `record_count` | One per run |
| `normalized_records` | `org_id`, `dataset_id`, `record_key`, `context_key`, all `NormalizedRecord` fields | Unique `(dataset_id, record_key, context_key)`: one row per compound and measurement context |
| `validation_issues` | `org_id`, `dataset_id`, `source_record_id`, `severity`, `rule`, `field`, `message` | |
| `quality_reports` | `org_id`, `run_id` (unique), `dataset_id` (unique), `total_records`, `accepted_records`, `rejected_records`, `duplicate_records`, `pass_rate`, `report` (JSON) | One per run |
| `feature_vectors` | `org_id`, `record_id` (unique), `descriptors` (JSON), `alerts` (JSON, nullable), `fingerprint_bits` (JSON) | `alerts` is NULL for vectors stored before revision `0006` |
| `enrichment_results` | `org_id`, `record_id`, `status`, `candidates` (JSON) | |
| `uploads` | `org_id`, `filename`, `format`, `size_bytes`, `sha256`, `data` (bytes) | Uploaded files; stored in the database because the web service's disk is ephemeral |
| `mapping_templates` | `org_id`, `name`, `mapping` (JSON) | Unique `(org_id, name)` |

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
| `0001` | Initial platform schema |
| `0002` | Retires the pre-rebuild MVP schema. The MVP also used revision id `0001` for an unrelated schema, so databases that ran it reported `0001` as current and never received the platform tables. `0002` detects that state (`organizations` missing), moves the MVP tables into a `legacy_mvp` schema — data preserved, no name collisions — and applies the platform schema. No-op on any database that already has it. |
| `0003` | Adds `users`, `user_sessions` and `user_invitations` (each only if absent, so a stamped `create_all` schema upgrades cleanly). Deletes the organization the removed shared-password login used (`00000000-0000-0000-0000-000000000001`) and everything it owned. |
| `0004` | Adds `user_invitations.purpose` (existing rows become `join`) and `user_invitations.revoked_at`, for password-reset links and revocable invitations. |
| `0005` | Adds `uploads` and `mapping_templates` (each only if absent). |
| `0006` | Adds `feature_vectors.alerts` (nullable; existing rows keep NULL and get their alerts computed when read). |
| `0007` | Adds `normalized_records.assay_format`, `control` and `context_key` (existing rows get an empty key) and widens the unique constraint to `(dataset_id, record_key, context_key)`. |
| `0008` | Adds the run queue's columns to `pipeline_runs` (`stage`, `progress`, `attempts`, `lost_leases`, `cancel_requested`, `worker_id`, `lease_expires_at`, `started_at`) and an index on `created_at`. Runs left `pending` or `running` by the previous in-request background tasks were lost with their process; they become `failed` ("start it again") rather than starting unexpectedly. |

Migrations are tested against both SQLite and real PostgreSQL
(`tests/integration/test_migrations_postgres.py`, run in CI against a
Postgres 16 service), including the legacy-MVP upgrade path using the MVP's
own vendored migration (`tests/fixtures/legacy_mvp_alembic/`), the `0003`–`0005`,
`0007` and `0008` upgrades and downgrades, reading a vector stored before `0006`,
the account, upload and run-queue repositories' behaviour
(`tests/account_repository_checks.py`, `tests/upload_repository_checks.py`,
`tests/run_queue_checks.py`, shared by both dialects), and eight workers
claiming concurrently without ever sharing a run.

## Readiness vs. liveness

`GET /health` never touches the database — pure liveness, safe for a
platform health check to gate restarts on.
`GET /api/v1/health/ready` does, via `OrganizationRepository.ping()`, and
returns `503` if the database is unreachable or its `alembic_version` is not
the code's head revision (`storage/database.py:head_revision`), so a deploy
whose newest migration did not apply is not ready. A schema built by
`create_all` (`DNDLABS_AUTO_CREATE_SCHEMA=true`, development) has no
revision, and only reachability is checked. The two are
deliberately different endpoints: a broken database must not restart an
otherwise-healthy process, but it must be possible to detect from outside
without reading logs. See [docs/api.md](api.md#service-and-health-no-auth).

## Connection pooling

`storage/database.py`'s `create_db_engine` sets `pool_size=3,
max_overflow=2, pool_recycle=300` for Postgres — conservative by design,
sized for Render's free-tier connection cap; one API process with its run
worker does not need more even under load.

## Frontend

A separate React 18 + TypeScript + Vite SPA under `web/`, deployed as its
own Render Static Site.

**Signing in.** Users sign in with email and password, or with an org API
key via "Use an API key instead". New users arrive through an invitation
link (`/invite`) and choose their password there; a reset link (`/reset`)
sets a new one. On the Team page, admins invite colleagues, change roles,
issue reset links, remove members and revoke pending invitations. The
Account page changes the password.

**Credential handling.** `auth/SessionContext.tsx` holds the credential — a
session token or an API key — in memory and `sessionStorage` (never
`localStorage`, so it does not outlive the tab):
- `api/client.ts` sends it as `Authorization: Bearer` or `X-API-Key`.
- A stored credential is re-verified against `/auth/whoami` on load.
- Any `401` signs the user out with a notice.
- The query cache is cleared whenever the identity changes, so one org's
  data is never shown to another.

**Datasets.** A dataset's page shows the hit/lead criteria
(`assessment/HitLeadPanel.tsx`: compounds and measurements, potency
classes, the count of actives, potency per assay format, and each criterion
over all compounds, actives and the five most potent) above its records,
which carry their assay context, potency class, computed properties and
alerts. PAINS and reactive-metabolite atoms are highlighted on each
structure, and those compounds can be hidden.

**Structures.** `design-system/MoleculeView.tsx` draws 2D structures in the
browser with RDKit.js (RDKit compiled to WebAssembly, BSD-3). The module
(about 2.4 MB gzipped) is loaded lazily the first time a structure is shown,
by `chem/rdkit.ts`, and depictions are cached by SMILES and size. The
drawing is an SVG `<img>`, so it cannot run script. Until RDKit.js has
loaded — or if it cannot load or parse the SMILES — the SMILES text is shown
instead.

**Uploads.** The Run page's default source is a file: drag-and-drop or
choose a CSV, TSV, Excel, SD, SMILES or MOL file (`design-system/FileDrop.tsx`). The
upload's preview opens in `uploads/MappingEditor.tsx`, which shows the first
rows with structures drawn and a role selector per column, pre-set from the
server's suggestion. The mapping is checked in the browser with the same
rules as the server (`uploads/columnRoles.ts`) and can be saved as a named
template for future uploads. When a column is mapped to a lookup role, the
editor states that its values will be sent to PubChem or ChEMBL.

**Runs.** After a run starts, the Run page (`screens/RunTrigger.tsx`)
shows `runs/RunProgress.tsx`: a stepper of the stages with the counts so
far, polled every 2 s while the run is active, with a Cancel button. A run
returned to the queue by a clean stop shows "Waiting to resume" and
its stepper starts again at Queued, since it restarts from the beginning. The
Dashboard's run table has a Progress column: the stage while a run is
active, accepted of fetched records once it succeeded, and the error when
it failed. Stage labels are shared in `runs/stages.ts`.

**Theme.** Light and dark follow the operating system's colour scheme;
`<html data-theme="light|dark">` forces one. The Tailwind `dark:` variant
and the tokens in `design-system/tokens.css` use the same rule.

**Development and tests.** The app is built against a mock server (MSW)
that mirrors the real API contract, auth included, so it can be developed
without a backend. Its Playwright e2e test runs it against the real backend.
See `web/src/design-system/tokens.css` for the palette, type and spacing
system.
