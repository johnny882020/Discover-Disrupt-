import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from dndlabs.core.schemas import DatasetFilter, SourceType
from dndlabs.filtering.query import build_predicate
from dndlabs.storage.database import create_db_engine, create_schema
from dndlabs.storage.models import DatasetRow, NormalizedRecordRow, OrganizationRow, RunRow
from dndlabs.storage.repositories import SessionFactory


def _seed_dataset(sessions: SessionFactory, org_id: uuid.UUID, dataset_id: uuid.UUID) -> None:
    """Insert the minimal org/run/dataset rows a normalized_record row's FKs need.

    Each entity commits in its own transaction (matching how the real
    repositories work), since these plain-FK rows have no mapped
    ``relationship()`` for SQLAlchemy's flush to order by dependency.
    """
    run_id = uuid.uuid4()
    with sessions.transaction() as session:
        session.add(OrganizationRow(id=org_id, name="Acme", created_at=datetime.now(UTC)))
    with sessions.transaction() as session:
        session.add(
            RunRow(
                id=run_id,
                org_id=org_id,
                source="csv",
                status="succeeded",
                request_payload={},
                created_at=datetime.now(UTC),
            )
        )
    with sessions.transaction() as session:
        session.add(
            DatasetRow(
                id=dataset_id,
                org_id=org_id,
                run_id=run_id,
                name="d",
                source="csv",
                created_at=datetime.now(UTC),
            )
        )


def _row(session: object, org_id: uuid.UUID, dataset_id: uuid.UUID, **kwargs: object) -> None:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        org_id=org_id,
        dataset_id=dataset_id,
        source="csv",
        source_record_id="1",
        record_key=str(uuid.uuid4())[:27],
    )
    defaults.update(kwargs)
    session.add(NormalizedRecordRow(**defaults))  # type: ignore[attr-defined]


def test_build_predicate_filters_by_all_fields() -> None:
    engine = create_db_engine("sqlite:///:memory:")
    create_schema(engine)
    sessions = SessionFactory(engine)
    org_id, dataset_id = uuid.uuid4(), uuid.uuid4()
    _seed_dataset(sessions, org_id, dataset_id)
    with sessions.transaction() as session:
        _row(
            session,
            org_id,
            dataset_id,
            source_record_id="light",
            molecular_weight=50.0,
            target="EGFR",
            source="csv",
            activity_value_nm=5.0,
        )
        _row(
            session,
            org_id,
            dataset_id,
            source_record_id="heavy",
            molecular_weight=500.0,
            target="COX-1",
            source="pubchem",
            activity_value_nm=5000.0,
        )

    with sessions.transaction() as session:
        stmt = select(NormalizedRecordRow).where(NormalizedRecordRow.dataset_id == dataset_id)

        results = session.scalars(
            build_predicate(stmt, NormalizedRecordRow, DatasetFilter(mw_min=100))
        ).all()
        assert [r.source_record_id for r in results] == ["heavy"]

        results = session.scalars(
            build_predicate(stmt, NormalizedRecordRow, DatasetFilter(mw_max=100))
        ).all()
        assert [r.source_record_id for r in results] == ["light"]

        results = session.scalars(
            build_predicate(stmt, NormalizedRecordRow, DatasetFilter(target="EGFR"))
        ).all()
        assert [r.source_record_id for r in results] == ["light"]

        results = session.scalars(
            build_predicate(stmt, NormalizedRecordRow, DatasetFilter(source=SourceType.PUBCHEM))
        ).all()
        assert [r.source_record_id for r in results] == ["heavy"]

        results = session.scalars(
            build_predicate(
                stmt, NormalizedRecordRow, DatasetFilter(activity_min_nm=100, activity_max_nm=10000)
            )
        ).all()
        assert [r.source_record_id for r in results] == ["heavy"]


def test_no_filters_returns_everything() -> None:
    engine = create_db_engine("sqlite:///:memory:")
    create_schema(engine)
    sessions = SessionFactory(engine)
    org_id, dataset_id = uuid.uuid4(), uuid.uuid4()
    _seed_dataset(sessions, org_id, dataset_id)
    with sessions.transaction() as session:
        _row(session, org_id, dataset_id, source_record_id="a")
        _row(session, org_id, dataset_id, source_record_id="b")
    with sessions.transaction() as session:
        stmt = select(NormalizedRecordRow).where(NormalizedRecordRow.dataset_id == dataset_id)
        assert (
            len(session.scalars(build_predicate(stmt, NormalizedRecordRow, DatasetFilter())).all())
            == 2
        )
