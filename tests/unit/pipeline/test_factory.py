from pathlib import Path

from dndlabs.core.config import Settings
from dndlabs.core.schemas import Organization, RunStatus, SourceSpec, SourceType
from dndlabs.ingestion.pubchem import PubChemConnector
from dndlabs.ingestion.resolution import LookupStructureResolver
from dndlabs.pipeline.factory import build_container, migrate


async def test_container_runs_csv_end_to_end(tmp_path: Path) -> None:
    csv_path = tmp_path / "x.csv"
    csv_path.write_text("smiles,name\nCCO,ethanol\n", encoding="utf-8")
    settings = Settings(database_url="sqlite:///:memory:")
    container = build_container(settings)
    try:
        org = container.repositories.organizations.create(Organization(name="Acme"))
        run = container.service.submit(
            org.id, SourceSpec(source=SourceType.CSV, csv_path=str(csv_path))
        )
        finished = await container.worker.run_now(run)
        assert finished.status is RunStatus.SUCCEEDED
        assert container.auth is not None
    finally:
        container.close()


def test_migrate(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    migrate(Settings(database_url=f"sqlite:///{db}"))
    assert db.exists()


def test_pubchem_interval_setting_reaches_connector_and_resolver() -> None:
    settings = Settings(database_url="sqlite:///:memory:", pubchem_min_interval_seconds=1.25)
    container = build_container(settings)
    try:
        # Private attributes: the container exposes no other view of how its
        # services were configured, and a wrong wiring is otherwise silent.
        connector = container.service._connectors.get(SourceType.PUBCHEM)
        resolver = container.service._resolver
        assert isinstance(connector, PubChemConnector)
        assert isinstance(resolver, LookupStructureResolver)
        assert connector._min_interval == 1.25
        assert resolver._min_interval == 1.25
    finally:
        container.close()


def test_rate_limit_settings_reach_the_auth_policy() -> None:
    from datetime import timedelta

    from dndlabs.pipeline.factory import auth_policy

    policy = auth_policy(
        Settings(
            rate_limit_window_seconds=600,
            signin_limit_per_ip=7,
            signin_limit_per_email_and_ip=3,
            signin_limit_per_email=11,
            auth_failure_limit_per_ip=13,
        )
    )
    assert policy.rate_limit_window == timedelta(minutes=10)
    assert (
        policy.signin_limit_per_ip,
        policy.signin_limit_per_email_and_ip,
        policy.signin_limit_per_email,
        policy.auth_failure_limit_per_ip,
    ) == (7, 3, 11, 13)
