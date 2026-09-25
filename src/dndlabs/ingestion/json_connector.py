"""Generic JSON connector for internal data-lake style uploads."""

import json
from collections.abc import AsyncIterator
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.logging import get_logger
from dndlabs.core.schemas import RawRecord, SourceSpec, SourceType
from dndlabs.ingestion.fields import build_raw_record

logger = get_logger(__name__)

JsonScalar = str | int | float | bool | None
_Item = dict[str, JsonScalar]
_ITEMS = TypeAdapter(list[_Item])


class JsonEnvelope(BaseModel):
    """Accepted envelope: ``{"records": [...]}`` plus optional metadata."""

    model_config = ConfigDict(extra="allow")

    records: list[_Item]


class JsonConnector:
    """Reads flat compound objects from a JSON file.

    Attributes:
        source: Always :attr:`SourceType.JSON`.
    """

    source = SourceType.JSON

    async def fetch(self, spec: SourceSpec) -> AsyncIterator[RawRecord]:
        """Read all records from ``spec.json_path``.

        Args:
            spec: A JSON source spec.

        Yields:
            One raw record per object; ids fall back to ``item-<n>``.

        Raises:
            IngestionError: If the file is missing, not JSON, or has the wrong shape.
        """
        if spec.source is not SourceType.JSON or spec.json_path is None:
            raise IngestionError("JsonConnector requires a json spec with json_path")
        items = _load_items(Path(spec.json_path))
        for index, item in enumerate(items):
            yield build_raw_record(SourceType.JSON, item, fallback_id=f"item-{index + 1}")
        logger.info("json read", extra={"path": spec.json_path, "records": len(items)})


def _load_items(path: Path) -> list[_Item]:
    """Parse and shape-check the JSON document."""
    if not path.is_file():
        raise IngestionError(f"JSON file not found: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IngestionError(f"invalid JSON in {path}: {exc}") from exc
    try:
        if isinstance(document, list):
            return _ITEMS.validate_python(document)
        return JsonEnvelope.model_validate(document).records
    except ValidationError as exc:
        raise IngestionError(
            f"{path}: expected a list of flat objects or {{'records': [...]}}: {exc}"
        ) from exc
