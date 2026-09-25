"""Connector registry keyed by source type."""

from collections.abc import Iterable

from dndlabs.core.exceptions import ConnectorNotFoundError
from dndlabs.core.protocols import Connector
from dndlabs.core.schemas import SourceType

#: Sources on the roadmap but intentionally not implemented in the MVP.
PLANNED_SOURCES: dict[str, str] = {
    "chembl": "ChEMBL bioactivity (REST API) - planned",
    "uniprot": "UniProt protein targets (REST API) - planned",
    "pdb": "RCSB PDB structures (Search/Data API) - planned",
}


class ConnectorRegistry:
    """Maps each :class:`SourceType` to a connector instance."""

    def __init__(self, connectors: Iterable[Connector]) -> None:
        """Register connectors.

        Args:
            connectors: Connector instances; later ones override earlier ones.
        """
        self._connectors: dict[SourceType, Connector] = {c.source: c for c in connectors}

    def get(self, source: SourceType | str) -> Connector:
        """Look up the connector for ``source``.

        Args:
            source: Source type or its string value.

        Returns:
            The connector.

        Raises:
            ConnectorNotFoundError: If the source is planned or unknown.
        """
        key = str(source.value if isinstance(source, SourceType) else source).lower()
        for source_type, connector in self._connectors.items():
            if source_type.value == key:
                return connector
        if key in PLANNED_SOURCES:
            raise ConnectorNotFoundError(f"{key}: {PLANNED_SOURCES[key]}")
        raise ConnectorNotFoundError(f"no connector registered for source {key!r}")

    @property
    def sources(self) -> list[SourceType]:
        """Registered source types."""
        return list(self._connectors)
