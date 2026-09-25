"""``dnd-pipeline`` command-line interface."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import typer

from dndlabs.cli.formatting import format_datasets, format_report, format_result, format_run
from dndlabs.core.config import Settings, get_settings
from dndlabs.core.exceptions import DndLabsError
from dndlabs.core.logging import configure_logging
from dndlabs.core.schemas import ExportFormat, IdentifierType, SourceSpec, SourceType
from dndlabs.pipeline.factory import Container, build_container, migrate

app = typer.Typer(
    name="dnd-pipeline",
    help="Ingest, validate and export model-ready drug-discovery datasets.",
    no_args_is_help=True,
)

ContainerFactory = Callable[[Settings, ExportFormat], Container]


def default_container_factory(settings: Settings, fmt: ExportFormat) -> Container:
    """Build the production container.

    Args:
        settings: Application settings.
        fmt: Export format for pipeline runs.

    Returns:
        The wired container.
    """
    return build_container(settings, export_format=fmt)


#: Builds the service container; replaced in tests.
container_factory: ContainerFactory = default_container_factory


@contextmanager
def _container(
    fmt: ExportFormat = ExportFormat.CSV, export_dir: Path | None = None
) -> Iterator[Container]:
    """Yield a container, translating domain errors into a clean exit."""
    settings = get_settings()
    if export_dir is not None:
        settings = settings.model_copy(update={"export_dir": export_dir})
    configure_logging(settings.log_level, settings.log_json)
    container = container_factory(settings, fmt)
    try:
        yield container
    except DndLabsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        container.close()


def _split(values: str | None) -> list[str]:
    """Split a comma-separated option into trimmed, non-empty items."""
    return [v.strip() for v in (values or "").split(",") if v.strip()]


def _build_spec(
    source: SourceType,
    ids: str | None,
    names: str | None,
    path: Path | None,
    dataset_name: str | None,
) -> SourceSpec:
    """Translate CLI options into a :class:`SourceSpec`."""
    if source is SourceType.PUBCHEM:
        if bool(ids) == bool(names):
            raise typer.BadParameter("pass exactly one of --ids or --names for pubchem")
        return SourceSpec(
            source=source,
            identifiers=_split(ids or names),
            identifier_type=IdentifierType.CID if ids else IdentifierType.NAME,
            dataset_name=dataset_name,
        )
    if path is None:
        raise typer.BadParameter(f"--path is required for {source.value}")
    return SourceSpec(source=source, path=str(path), dataset_name=dataset_name)


@app.command()
def run(
    source: Annotated[SourceType, typer.Option(help="Source connector.")],
    ids: Annotated[str | None, typer.Option(help="Comma-separated PubChem CIDs.")] = None,
    names: Annotated[str | None, typer.Option(help="Comma-separated PubChem names.")] = None,
    path: Annotated[Path | None, typer.Option(help="Input file for csv/json.")] = None,
    name: Annotated[str | None, typer.Option(help="Dataset name.")] = None,
    fmt: Annotated[ExportFormat, typer.Option("--format", help="Export format.")] = (
        ExportFormat.CSV
    ),
    output_dir: Annotated[
        Path | None, typer.Option(help="Export directory (default: DNDLABS_EXPORT_DIR).")
    ] = None,
) -> None:
    """Ingest, validate, store and export a dataset, then print its quality report."""
    try:
        spec = _build_spec(source, ids, names, path, name)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    with _container(fmt, output_dir) as container:
        result = container.service.run(spec)
        typer.echo(format_result(result))


@app.command()
def status(run_id: str) -> None:
    """Show the status of a pipeline run."""
    with _container() as container:
        typer.echo(format_run(container.repositories.runs.get(run_id)))


@app.command()
def datasets() -> None:
    """List stored datasets, newest first."""
    with _container() as container:
        typer.echo(format_datasets(container.repositories.datasets.list()))


@app.command()
def show(
    dataset_id: str,
    limit: Annotated[int, typer.Option(min=1, help="Rows to print.")] = 20,
) -> None:
    """Print a dataset's records as JSON lines."""
    with _container() as container:
        dataset = container.repositories.datasets.get(dataset_id)
        typer.echo(dataset.dataset.model_dump_json())
        for record in dataset.records[:limit]:
            typer.echo(record.model_dump_json())


@app.command()
def report(
    dataset_id: str,
    as_json: Annotated[bool, typer.Option("--json", help="Print raw JSON.")] = False,
) -> None:
    """Print a dataset's quality report."""
    with _container() as container:
        quality = container.repositories.reports.get_for_dataset(dataset_id)
        typer.echo(quality.model_dump_json(indent=2) if as_json else format_report(quality, 50))


@app.command()
def export(
    dataset_id: str,
    fmt: Annotated[ExportFormat, typer.Option("--format", help="Export format.")] = (
        ExportFormat.CSV
    ),
    output_dir: Annotated[Path, typer.Option(help="Target directory.")] = Path("."),
) -> None:
    """Export a stored dataset to a file."""
    with _container() as container:
        dataset = container.repositories.datasets.get(dataset_id)
        typer.echo(str(container.exporter.write(dataset, fmt, output_dir)))


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
