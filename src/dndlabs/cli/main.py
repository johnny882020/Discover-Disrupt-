"""``dnd-pipeline`` command-line interface.

Operates directly against the configured database (like an operator tool),
not over HTTP — it is a thin wrapper over the same services the API uses.
"""

import asyncio
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from dndlabs.cli.formatting import format_datasets, format_report, format_run
from dndlabs.core.config import Settings, get_settings
from dndlabs.core.exceptions import DndLabsError
from dndlabs.core.logging import configure_logging
from dndlabs.core.schemas import Organization, SourceSpec, SourceType
from dndlabs.pipeline.factory import Container, build_container, migrate

app = typer.Typer(
    name="dnd-pipeline",
    help="D&D Labs Platform operator CLI: bootstrap orgs, run pipelines, inspect data.",
    no_args_is_help=True,
)

ContainerFactory = Callable[[Settings], Container]


def default_container_factory(settings: Settings) -> Container:
    """Build the production container.

    Args:
        settings: Application settings.

    Returns:
        The wired container.
    """
    return build_container(settings)


#: Builds the service container; replaced in tests.
container_factory: ContainerFactory = default_container_factory


@contextmanager
def _container() -> Iterator[Container]:
    """Yield a container, translating domain errors into a clean exit."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    container = container_factory(settings)
    try:
        yield container
    except DndLabsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        container.close()


@app.command("bootstrap-org")
def bootstrap_org(name: str) -> None:
    """Create an organization and print its first API key (shown once)."""
    with _container() as container:
        org = container.repositories.organizations.create(Organization(name=name))
        key = container.auth.issue_key(org)
        typer.echo(f"org_id   {org.id}")
        typer.echo(f"api_key  {key.raw_key}")
        typer.echo("Save this key now — it will not be shown again.")


@app.command()
def run(
    org_id: Annotated[str, typer.Option(help="Organization UUID.")],
    source: Annotated[SourceType, typer.Option(help="Source connector.")],
    ids: Annotated[str | None, typer.Option(help="Comma-separated PubChem CIDs.")] = None,
    path: Annotated[Path | None, typer.Option(help="Input file for csv/json.")] = None,
    chembl_target: Annotated[str | None, typer.Option(help="ChEMBL target id.")] = None,
    name: Annotated[str | None, typer.Option(help="Dataset name.")] = None,
) -> None:
    """Ingest, validate, store, feature-ize and enrich a dataset."""
    spec = _build_spec(source, ids, path, chembl_target, name)
    with _container() as container:
        run_record = container.service.submit(uuid.UUID(org_id), spec)
        finished = asyncio.run(container.service.execute(uuid.UUID(org_id), run_record.id))
        typer.echo(format_run(finished))
        if finished.dataset_id:
            report = container.repositories.reports.get_for_dataset(
                uuid.UUID(org_id), finished.dataset_id
            )
            typer.echo("")
            typer.echo(format_report(report))


def _build_spec(
    source: SourceType,
    ids: str | None,
    path: Path | None,
    chembl_target: str | None,
    name: str | None,
) -> SourceSpec:
    """Translate CLI options into a :class:`SourceSpec`."""
    if source is SourceType.PUBCHEM:
        if not ids:
            raise typer.BadParameter("--ids is required for pubchem")
        return SourceSpec(source=source, identifiers=_split(ids), dataset_name=name)
    if source is SourceType.CHEMBL:
        if not chembl_target:
            raise typer.BadParameter("--chembl-target is required for chembl")
        return SourceSpec(source=source, chembl_target=chembl_target, dataset_name=name)
    if path is None:
        raise typer.BadParameter(f"--path is required for {source.value}")
    kwargs = {"csv_path": str(path)} if source is SourceType.CSV else {"json_path": str(path)}
    return SourceSpec(source=source, dataset_name=name, **kwargs)


def _split(values: str) -> list[str]:
    """Split a comma-separated option into trimmed, non-empty items."""
    return [v.strip() for v in values.split(",") if v.strip()]


@app.command()
def datasets(org_id: Annotated[str, typer.Option(help="Organization UUID.")]) -> None:
    """List stored datasets for an organization, newest first."""
    with _container() as container:
        typer.echo(format_datasets(container.repositories.datasets.list_for_org(uuid.UUID(org_id))))


@app.command()
def report(
    org_id: Annotated[str, typer.Option(help="Organization UUID.")],
    dataset_id: str,
    as_json: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    """Print a dataset's quality report."""
    with _container() as container:
        quality = container.repositories.reports.get_for_dataset(
            uuid.UUID(org_id), uuid.UUID(dataset_id)
        )
        typer.echo(quality.model_dump_json(indent=2) if as_json else format_report(quality, 50))


@app.command()
def export(
    org_id: Annotated[str, typer.Option(help="Organization UUID.")],
    dataset_id: str,
    fmt: Annotated[str, typer.Option("--format")] = "csv",
    output: Annotated[Path | None, typer.Option(help="Output file path.")] = None,
) -> None:
    """Export a stored dataset to a file."""
    from dndlabs.core.schemas import ExportFormat

    with _container() as container:
        dataset = container.repositories.datasets.get(uuid.UUID(org_id), uuid.UUID(dataset_id))
        body = container.exporter.export(dataset.records, ExportFormat(fmt))
        out_path = output or Path(f"{dataset_id}.{fmt}")
        out_path.write_bytes(body)
        typer.echo(str(out_path))


@app.command("init-db")
def init_db() -> None:
    """Apply database migrations (idempotent)."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    try:
        migrate(settings)
    except DndLabsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Database is up to date.")


if __name__ == "__main__":  # pragma: no cover
    app()
