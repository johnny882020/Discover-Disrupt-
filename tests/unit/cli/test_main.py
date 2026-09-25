import json
import re
from pathlib import Path

from typer.testing import CliRunner

from dndlabs.cli import main as cli_main
from dndlabs.cli.main import app
from dndlabs.core.config import Settings

runner = CliRunner()


def _bootstrap(cli_env: Path) -> tuple[str, str]:
    result = runner.invoke(app, ["bootstrap-org", "Acme"])
    assert result.exit_code == 0, result.output
    org_id = re.search(r"org_id\s+(\S+)", result.output).group(1)  # type: ignore[union-attr]
    return org_id, result.output


def test_bootstrap_org(cli_env: Path) -> None:
    org_id, output = _bootstrap(cli_env)
    assert "api_key" in output
    assert len(org_id) == 36


def test_run_csv_then_query_commands(cli_env: Path) -> None:
    org_id, _ = _bootstrap(cli_env)
    csv_path = cli_env / "lab.csv"
    csv_path.write_text("smiles,name,mw\nCCO,ethanol,46.07\n", encoding="utf-8")

    result = runner.invoke(
        app, ["run", "--org-id", org_id, "--source", "csv", "--path", str(csv_path)]
    )
    assert result.exit_code == 0, result.output
    assert "status   succeeded" in result.output
    assert "Quality report" in result.output

    dataset_id = re.search(r"dataset\s+(\S+)", result.output).group(1)  # type: ignore[union-attr]

    listing = runner.invoke(app, ["datasets", "--org-id", org_id])
    assert dataset_id in listing.output

    report = runner.invoke(app, ["report", "--org-id", org_id, dataset_id, "--json"])
    assert json.loads(report.output)["accepted_records"] == 1

    exported = runner.invoke(
        app, ["export", "--org-id", org_id, dataset_id, "--output", str(cli_env / "out.csv")]
    )
    assert Path(exported.output.strip()).exists()


def test_empty_datasets(cli_env: Path) -> None:
    org_id, _ = _bootstrap(cli_env)
    assert "No datasets yet." in runner.invoke(app, ["datasets", "--org-id", org_id]).output


def test_missing_path_is_bad_parameter(cli_env: Path) -> None:
    org_id, _ = _bootstrap(cli_env)
    result = runner.invoke(app, ["run", "--org-id", org_id, "--source", "csv"])
    assert result.exit_code == 2


def test_missing_ids_is_bad_parameter(cli_env: Path) -> None:
    org_id, _ = _bootstrap(cli_env)
    result = runner.invoke(app, ["run", "--org-id", org_id, "--source", "pubchem"])
    assert result.exit_code == 2


def test_missing_chembl_target_is_bad_parameter(cli_env: Path) -> None:
    org_id, _ = _bootstrap(cli_env)
    result = runner.invoke(app, ["run", "--org-id", org_id, "--source", "chembl"])
    assert result.exit_code == 2


def test_init_db(cli_env: Path) -> None:
    result = runner.invoke(app, ["init-db"])
    assert result.exit_code == 0, result.output
    assert (cli_env / "cli.db").exists()
    assert runner.invoke(app, ["init-db"]).exit_code == 0


def test_init_db_failure(cli_env: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from dndlabs.core.exceptions import StorageError

    def boom(settings: Settings) -> None:
        raise StorageError("cannot connect")

    monkeypatch.setattr(cli_main, "migrate", boom)
    result = runner.invoke(app, ["init-db"])
    assert result.exit_code == 1
    assert "cannot connect" in result.output


def test_report_for_unknown_dataset_exits_nonzero(cli_env: Path) -> None:
    import uuid

    org_id, _ = _bootstrap(cli_env)
    result = runner.invoke(app, ["report", "--org-id", org_id, str(uuid.uuid4())])
    assert result.exit_code == 1


def test_default_container_factory(cli_env: Path) -> None:
    container = cli_main.default_container_factory(Settings(database_url="sqlite:///:memory:"))
    container.close()
