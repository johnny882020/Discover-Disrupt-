import json
import re
from pathlib import Path

from typer.testing import CliRunner

from dndlabs.cli import main as cli_main
from dndlabs.cli.main import app
from dndlabs.core.config import Settings
from dndlabs.core.schemas import ExportFormat
from tests.conftest import FIXTURES

runner = CliRunner()


def _dataset_id(output: str) -> str:
    match = re.search(r"dataset\s+([0-9a-f-]{36})", output)
    assert match, output
    return match.group(1)


def test_run_pubchem_prints_report(cli_env: Path) -> None:
    result = runner.invoke(app, ["run", "--source", "pubchem", "--ids", "2244,3672,5090"])
    assert result.exit_code == 0, result.output
    assert "status   succeeded" in result.output
    assert "Quality report" in result.output
    assert "pass rate          100.0%" in result.output
    assert list((cli_env / "exports").glob("*.csv"))


def test_run_csv_then_query_commands(cli_env: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run", "--source", "csv", "--path", str(FIXTURES / "lab_export_malformed.csv"),
            "--name", "lab", "--format", "jsonl", "--output-dir", str(cli_env / "out"),
        ],
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "rejected (errors)  6" in result.output
    assert list((cli_env / "out").glob("*.jsonl"))
    dataset_id = _dataset_id(result.output)
    run_id = re.search(r"Run ([0-9a-f-]{36})", result.output).group(1)  # type: ignore[union-attr]

    status = runner.invoke(app, ["status", run_id])
    assert "succeeded" in status.output

    listing = runner.invoke(app, ["datasets"])
    assert dataset_id in listing.output and "lab" in listing.output

    shown = runner.invoke(app, ["show", dataset_id, "--limit", "2"])
    lines = shown.output.strip().splitlines()
    assert len(lines) == 3
    assert json.loads(lines[0])["name"] == "lab"

    report = runner.invoke(app, ["report", dataset_id, "--json"])
    assert json.loads(report.output)["accepted_records"] == 5
    assert "more issue" not in runner.invoke(app, ["report", dataset_id]).output

    exported = runner.invoke(app, ["export", dataset_id, "--output-dir", str(cli_env / "x")])
    assert Path(exported.output.strip()).exists()


def test_run_by_names(cli_env: Path) -> None:
    result = runner.invoke(app, ["run", "--source", "pubchem", "--names", "aspirin,unobtainium"])
    assert result.exit_code == 0, result.output
    assert "records  1" in result.output


def test_empty_datasets(cli_env: Path) -> None:
    assert "No datasets yet." in runner.invoke(app, ["datasets"]).output


def test_errors_exit_nonzero(cli_env: Path) -> None:
    missing = runner.invoke(app, ["status", "nope"])
    assert missing.exit_code == 1
    assert "not found" in missing.output

    bad_file = runner.invoke(app, ["run", "--source", "csv", "--path", "/no/such.csv"])
    assert bad_file.exit_code == 1
    assert "CSV file not found" in bad_file.output


def test_bad_parameters(cli_env: Path) -> None:
    assert runner.invoke(app, ["run", "--source", "pubchem"]).exit_code == 2
    assert (
        runner.invoke(app, ["run", "--source", "pubchem", "--ids", "1", "--names", "a"]).exit_code
        == 2
    )
    assert runner.invoke(app, ["run", "--source", "csv"]).exit_code == 2
    assert runner.invoke(app, ["run", "--source", "pubchem", "--ids", "abc"]).exit_code == 2


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


def test_default_container_factory(cli_env: Path) -> None:
    container = cli_main.default_container_factory(
        Settings(database_url="sqlite:///:memory:"), ExportFormat.CSV
    )
    container.close()
