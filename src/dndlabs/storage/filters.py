"""Translates a :class:`~dndlabs.core.schemas.DatasetFilter` into SQL predicates.

Lives in ``storage`` because it builds SQLAlchemy expressions against the
ORM's ``normalized_records`` columns, and SQLAlchemy stays inside
``storage/``. (It used to be a separate ``filtering`` package, which made
``storage`` import a sibling package — a layering violation: ``storage`` may
import only ``core``.) Pagination and ordering are applied by the
repository, not here.
"""

from typing import Any

from sqlalchemy import Select

from dndlabs.core.schemas import DatasetFilter
from dndlabs.storage.models import NormalizedRecordRow


def apply_filters(stmt: Select[Any], filters: DatasetFilter) -> Select[Any]:
    """Apply a :class:`DatasetFilter` to a SELECT over normalized records.

    Args:
        stmt: The statement to filter (already scoped to org/dataset).
        filters: Filter criteria; unset fields are no-ops.

    Returns:
        The filtered statement.
    """
    row = NormalizedRecordRow
    # A bound excludes records with no value for that column: a SQL
    # comparison with NULL is never true.
    if filters.mw_min is not None:
        stmt = stmt.where(row.molecular_weight >= filters.mw_min)
    if filters.mw_max is not None:
        stmt = stmt.where(row.molecular_weight <= filters.mw_max)
    if filters.target is not None:
        stmt = stmt.where(row.target == filters.target)
    if filters.source is not None:
        stmt = stmt.where(row.source == filters.source.value)
    # Activity bounds compare the nM-normalized value, so records reported
    # in different units are comparable.
    if filters.activity_min_nm is not None:
        stmt = stmt.where(row.activity_value_nm >= filters.activity_min_nm)
    if filters.activity_max_nm is not None:
        stmt = stmt.where(row.activity_value_nm <= filters.activity_max_nm)
    return stmt
