"""In-memory fakes of the core protocols for unit tests."""

import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import datetime

from dndlabs.core.exceptions import (
    ConflictError,
    IngestionError,
    InvitationInvalidError,
    NotFoundError,
)
from dndlabs.core.protocols import Repositories
from dndlabs.core.schemas import (
    ApiKeyRecord,
    Dataset,
    DatasetFilter,
    DatasetWithRecords,
    EnrichmentResult,
    FeatureVector,
    Invitation,
    InvitationPurpose,
    MappingTemplate,
    NormalizedRecord,
    Organization,
    PipelineRun,
    QualityReport,
    RawRecord,
    Role,
    SourceSpec,
    SourceType,
    Upload,
    User,
    UserCredentials,
    UserSession,
)


class FakeOrganizations:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, Organization] = {}

    def create(self, org: Organization) -> Organization:
        self.items[org.id] = org
        return org

    def get(self, org_id: uuid.UUID) -> Organization:
        if org_id not in self.items:
            raise NotFoundError(f"organization {org_id} not found")
        return self.items[org_id]

    def ping(self) -> None:
        pass


class FakeApiKeys:
    def __init__(self) -> None:
        self.records: dict[str, ApiKeyRecord] = {}
        self.hashes: dict[str, str] = {}

    def create(self, org_id: uuid.UUID, prefix: str, hashed_key: str) -> ApiKeyRecord:
        record = ApiKeyRecord(id=uuid.uuid4(), org_id=org_id, prefix=prefix, created_at=_now())
        self.records[prefix] = record
        self.hashes[prefix] = hashed_key
        return record

    def get_by_prefix(self, prefix: str) -> ApiKeyRecord | None:
        return self.records.get(prefix)

    def get_hash(self, prefix: str) -> str | None:
        return self.hashes.get(prefix)

    def touch_last_used(self, key_id: uuid.UUID) -> None:
        for prefix, record in self.records.items():
            if record.id == key_id:
                self.records[prefix] = record.model_copy(update={"last_used_at": _now()})

    def revoke(self, org_id: uuid.UUID, key_id: uuid.UUID) -> None:
        for prefix, record in self.records.items():
            if record.id == key_id and record.org_id == org_id:
                self.records[prefix] = record.model_copy(update={"revoked_at": _now()})
                return
        raise NotFoundError(f"api key {key_id} not found for org {org_id}")


def _now():  # type: ignore[no-untyped-def]
    from dndlabs.core.schemas import utcnow

    return utcnow()


class FakeUsers:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, UserCredentials] = {}
        self.sessions: FakeSessions | None = None  # wired by fake_repositories

    def create(self, user: User, password_hash: str) -> User:
        if self.email_exists(user.email):
            raise ConflictError("an account with this email already exists")
        self.items[user.id] = UserCredentials(user=user, password_hash=password_hash)
        return user

    def get_credentials(self, email: str) -> UserCredentials | None:
        return next((c for c in self.items.values() if c.user.email == email), None)

    def get(self, org_id: uuid.UUID, user_id: uuid.UUID) -> UserCredentials:
        found = self.items.get(user_id)
        if found is None or found.user.org_id != org_id:
            raise NotFoundError(f"user {user_id} not found for org {org_id}")
        return found

    def email_exists(self, email: str) -> bool:
        return self.get_credentials(email) is not None

    def record_login_failure(
        self, user_id: uuid.UUID, max_attempts: int, lock_until: datetime
    ) -> None:
        creds = self.items[user_id]
        count = creds.failed_login_count + 1
        update: dict[str, object] = {"failed_login_count": count}
        if count >= max_attempts:
            update = {"failed_login_count": 0, "locked_until": lock_until}
        self.items[user_id] = creds.model_copy(update=update)

    def record_login_success(self, user_id: uuid.UUID) -> None:
        self.items[user_id] = self.items[user_id].model_copy(
            update={"failed_login_count": 0, "locked_until": None}
        )

    def list_members(self, org_id: uuid.UUID) -> list[User]:
        members = [c.user for c in self.items.values() if c.user.org_id == org_id]
        return sorted(members, key=lambda u: u.created_at)

    def set_role(self, org_id: uuid.UUID, user_id: uuid.UUID, role: Role) -> User:
        creds = self.get(org_id, user_id)
        user = creds.user.model_copy(update={"role": role})
        self.items[user_id] = creds.model_copy(update={"user": user})
        return user

    def delete(self, org_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.get(org_id, user_id)
        del self.items[user_id]
        if self.sessions is not None:
            self.sessions.items = {
                d: s for d, s in self.sessions.items.items() if s.user_id != user_id
            }

    def set_password(self, org_id: uuid.UUID, user_id: uuid.UUID, password_hash: str) -> None:
        creds = self.get(org_id, user_id)
        self.items[user_id] = creds.model_copy(update={"password_hash": password_hash})


class FakeSessions:
    def __init__(self) -> None:
        self.items: dict[str, UserSession] = {}

    def create(self, session: UserSession, token_hash: str) -> UserSession:
        self.items[token_hash] = session
        return session

    def get_by_token_hash(self, token_hash: str) -> UserSession | None:
        return self.items.get(token_hash)

    def revoke(self, org_id: uuid.UUID, session_id: uuid.UUID) -> None:
        for digest, s in self.items.items():
            if s.id == session_id and s.org_id == org_id and s.revoked_at is None:
                self.items[digest] = s.model_copy(update={"revoked_at": _now()})

    def revoke_all_for_user(
        self, org_id: uuid.UUID, user_id: uuid.UUID, except_session_id: uuid.UUID | None = None
    ) -> int:
        revoked = 0
        for digest, s in self.items.items():
            if (
                s.org_id == org_id
                and s.user_id == user_id
                and s.id != except_session_id
                and s.revoked_at is None
            ):
                self.items[digest] = s.model_copy(update={"revoked_at": _now()})
                revoked += 1
        return revoked

    def delete_expired(self, before: datetime) -> int:
        expired = [d for d, s in self.items.items() if s.expires_at < before]
        for digest in expired:
            del self.items[digest]
        return len(expired)


class FakeInvitations:
    def __init__(self, users: FakeUsers) -> None:
        self.items: dict[str, Invitation] = {}
        self._users = users

    def create(self, invitation: Invitation, token_hash: str) -> Invitation:
        self.items[token_hash] = invitation
        return invitation

    def get_by_token_hash(self, token_hash: str) -> Invitation | None:
        return self.items.get(token_hash)

    def list_pending(
        self, org_id: uuid.UUID, purpose: InvitationPurpose, now: datetime
    ) -> list[Invitation]:
        pending = [
            i
            for i in self.items.values()
            if i.org_id == org_id
            and i.purpose is purpose
            and i.accepted_at is None
            and i.revoked_at is None
            and i.expires_at > now
        ]
        return sorted(pending, key=lambda i: i.created_at, reverse=True)

    def revoke(self, org_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
        for digest, i in self.items.items():
            if (
                i.id == invitation_id
                and i.org_id == org_id
                and i.accepted_at is None
                and i.revoked_at is None
            ):
                self.items[digest] = i.model_copy(update={"revoked_at": _now()})
                return
        raise NotFoundError(f"pending invitation {invitation_id} not found for org {org_id}")

    def redeem_password_reset(self, invitation: Invitation, password_hash: str) -> User:
        digest = self._claimable(invitation)
        creds = next(
            (
                c
                for c in self._users.items.values()
                if c.user.org_id == invitation.org_id and c.user.email == invitation.email
            ),
            None,
        )
        if creds is None:
            raise InvitationInvalidError("invitation is invalid, expired or already used")
        self._users.items[creds.user.id] = creds.model_copy(
            update={"password_hash": password_hash, "failed_login_count": 0, "locked_until": None}
        )
        if self._users.sessions is not None:
            self._users.sessions.items = {
                d: s for d, s in self._users.sessions.items.items() if s.user_id != creds.user.id
            }
        self.items[digest] = self.items[digest].model_copy(update={"accepted_at": _now()})
        return creds.user

    def accept(self, invitation: Invitation, user: User, password_hash: str) -> User:
        digest = self._claimable(invitation)
        created = self._users.create(user, password_hash)
        self.items[digest] = self.items[digest].model_copy(update={"accepted_at": _now()})
        return created

    def _claimable(self, invitation: Invitation) -> str:
        digest = next(d for d, i in self.items.items() if i.id == invitation.id)
        current = self.items[digest]
        if current.accepted_at is not None or current.revoked_at is not None:
            raise InvitationInvalidError("invitation is invalid, expired or already used")
        return digest


class FakeUploads:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, tuple[Upload, bytes]] = {}

    def create(self, upload: Upload, data: bytes) -> Upload:
        self.items[upload.id] = (upload, data)
        return upload

    def get(self, org_id: uuid.UUID, upload_id: uuid.UUID) -> Upload:
        found = self.items.get(upload_id)
        if found is None or found[0].org_id != org_id:
            raise NotFoundError(f"upload {upload_id} not found for org {org_id}")
        return found[0]

    def get_data(self, org_id: uuid.UUID, upload_id: uuid.UUID) -> bytes:
        self.get(org_id, upload_id)
        return self.items[upload_id][1]


class FakeMappingTemplates:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, MappingTemplate] = {}

    def create(self, template: MappingTemplate) -> MappingTemplate:
        self.items = {
            k: t
            for k, t in self.items.items()
            if not (t.org_id == template.org_id and t.name == template.name)
        }
        self.items[template.id] = template
        return template

    def list_templates(self, org_id: uuid.UUID) -> list[MappingTemplate]:
        return sorted((t for t in self.items.values() if t.org_id == org_id), key=lambda t: t.name)

    def delete(self, org_id: uuid.UUID, template_id: uuid.UUID) -> None:
        found = self.items.get(template_id)
        if found is None or found.org_id != org_id:
            raise NotFoundError(f"mapping template {template_id} not found for org {org_id}")
        del self.items[template_id]


class FakeRuns:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, PipelineRun] = {}

    def create(self, run: PipelineRun) -> PipelineRun:
        self.items[run.id] = run
        return run

    def update(self, org_id: uuid.UUID, run: PipelineRun) -> PipelineRun:
        existing = self.items.get(run.id)
        if existing is None or existing.org_id != org_id:
            raise NotFoundError(f"run {run.id} not found for org {org_id}")
        self.items[run.id] = run
        return run

    def get(self, org_id: uuid.UUID, run_id: uuid.UUID) -> PipelineRun:
        run = self.items.get(run_id)
        if run is None or run.org_id != org_id:
            raise NotFoundError(f"run {run_id} not found for org {org_id}")
        return run

    def list_for_org(self, org_id: uuid.UUID) -> list[PipelineRun]:
        return [r for r in self.items.values() if r.org_id == org_id]


class FakeDatasets:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, DatasetWithRecords] = {}

    def create(self, dataset: Dataset, records: Sequence[NormalizedRecord]) -> Dataset:
        self.items[dataset.id] = DatasetWithRecords(dataset=dataset, records=list(records))
        return dataset

    def get(self, org_id: uuid.UUID, dataset_id: uuid.UUID) -> DatasetWithRecords:
        item = self.items.get(dataset_id)
        if item is None or item.dataset.org_id != org_id:
            raise NotFoundError(f"dataset {dataset_id} not found for org {org_id}")
        return item

    def list_for_org(self, org_id: uuid.UUID) -> list[Dataset]:
        return [i.dataset for i in self.items.values() if i.dataset.org_id == org_id]

    def filter_records(
        self, org_id: uuid.UUID, dataset_id: uuid.UUID, filters: DatasetFilter
    ) -> list[NormalizedRecord]:
        item = self.get(org_id, dataset_id)
        records = item.records
        if filters.mw_min is not None:
            records = [
                r for r in records if r.molecular_weight and r.molecular_weight >= filters.mw_min
            ]
        if filters.mw_max is not None:
            records = [
                r for r in records if r.molecular_weight and r.molecular_weight <= filters.mw_max
            ]
        if filters.target is not None:
            records = [r for r in records if r.target == filters.target]
        return records[filters.offset : filters.offset + filters.limit]

    def delete_org_data(self, org_id: uuid.UUID) -> int:
        ids = [i for i, d in self.items.items() if d.dataset.org_id == org_id]
        for i in ids:
            del self.items[i]
        return len(ids)


class FakeReports:
    def __init__(self) -> None:
        self.items: dict[uuid.UUID, QualityReport] = {}

    def save(self, org_id: uuid.UUID, report: QualityReport) -> QualityReport:
        assert report.dataset_id
        self.items[report.dataset_id] = report
        return report

    def get_for_dataset(self, org_id: uuid.UUID, dataset_id: uuid.UUID) -> QualityReport:
        if dataset_id not in self.items:
            raise NotFoundError(f"report for {dataset_id} not found")
        return self.items[dataset_id]


class FakeFeatures:
    def __init__(self) -> None:
        self.items: list[FeatureVector] = []
        self.owners: dict[uuid.UUID, uuid.UUID] = {}

    def save_many(self, org_id: uuid.UUID, vectors: Sequence[FeatureVector]) -> int:
        self.items.extend(vectors)
        self.owners.update({v.record_id: org_id for v in vectors})
        return len(vectors)

    def descriptors_for(
        self, org_id: uuid.UUID, record_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, float]]:
        wanted = set(record_ids)
        return {
            v.record_id: dict(v.descriptors)
            for v in self.items
            if v.record_id in wanted and self.owners.get(v.record_id) == org_id
        }


class FakeEnrichments:
    def __init__(self) -> None:
        self.items: list[EnrichmentResult] = []

    def save_many(self, org_id: uuid.UUID, results: Sequence[EnrichmentResult]) -> int:
        self.items.extend(results)
        return len(results)

    def get_for_dataset(self, org_id: uuid.UUID, dataset_id: uuid.UUID) -> list[EnrichmentResult]:
        return list(self.items)


def fake_repositories() -> Repositories:
    users = FakeUsers()
    sessions = FakeSessions()
    users.sessions = sessions
    return Repositories(
        organizations=FakeOrganizations(),
        api_keys=FakeApiKeys(),
        users=users,
        sessions=sessions,
        invitations=FakeInvitations(users),
        uploads=FakeUploads(),
        mapping_templates=FakeMappingTemplates(),
        runs=FakeRuns(),
        datasets=FakeDatasets(),
        reports=FakeReports(),
        features=FakeFeatures(),
        enrichments=FakeEnrichments(),
    )


class StaticConnector:
    """Returns canned records, or raises if ``error`` is set."""

    def __init__(
        self, source: SourceType, records: list[RawRecord], error: str | None = None
    ) -> None:
        self.source = source
        self.records = records
        self.error = error
        self.calls: list[SourceSpec] = []

    async def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]:
        self.calls.append(spec)
        if self.error:
            raise IngestionError(self.error)
        for record in self.records:
            yield record


class DictProvider:
    def __init__(self, *connectors: object) -> None:
        self._by_source = {c.source: c for c in connectors}  # type: ignore[attr-defined]

    def get(self, source: SourceType) -> object:
        return self._by_source[source]
