"""Generic JSON connector for internal data-lake style uploads."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from dndlabs.core.exceptions import IngestionError
from dndlabs.core.logging import get_logger
from dndlabs.core.schemas import JsonScalar, RawRecord, SourceSpec, SourceType
from dndlabs.ingestion.fields import build_raw_record

logger = get_logger(__name__)

_Item = dict[str, JsonScalar]
_ITEMS = TypeAdapter(list[_Item])


class JsonEnvelope(BaseModel):
    """Accepted envelope: ``{"records": [...]}`` plus optional metadata."""

    model_config = ConfigDict(extra="allow")

    records: list[_Item]


class JsonConnector:
    """Reads flat compound objects from a JSON file.

    The file may be a top-level list of objects or an object with a
    ``records`` list. Values must be scalars; nested structures are rejected.

    Attributes:
        source: Always :attr:`SourceType.JSON`.
    """

    source = SourceType.JSON

    def fetch(self, spec: SourceSpec) -> list[RawRecord]:
        """Read all records from ``spec.path``.

        Args:
            spec: A JSON source spec.

        Returns:
            One raw record per object; ids fall back to ``item-<n>``.

        Raises:
            IngestionError: If the file is missing, not JSON, or has the wrong shape.
        """
        if spec.source is not SourceType.JSON or spec.path is None:
            raise IngestionError("JsonConnector requires a json spec with a path")
        items = _load_items(Path(spec.path))
        records = [
            build_raw_record(SourceType.JSON, item, fallback_id=f"item-{index + 1}")
            for index, item in enumerate(items)
        ]
        logger.info("json read", extra={"path": spec.path, "records": len(records)})
        return records


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
