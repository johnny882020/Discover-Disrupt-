from pathlib import Path

from dndlabs.core.config import Settings
from dndlabs.core.schemas import Organization, RunStatus, SourceSpec, SourceType
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
        finished = await container.service.execute(org.id, run.id)
        assert finished.status is RunStatus.SUCCEEDED
        assert container.auth is not None
    finally:
        container.close()


def test_migrate(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    migrate(Settings(database_url=f"sqlite:///{db}"))
    assert db.exists()
