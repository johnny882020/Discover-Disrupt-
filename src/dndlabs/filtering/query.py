"""Translates a :class:`DatasetFilter` into a SQL predicate.

Kept separate from ``validation`` (which decides whether a record is
correct) and from ``storage`` (which owns the session) — this module only
knows how to turn filter criteria into `WHERE` clauses against the ORM
column objects it's given.
"""

from typing import Any

from sqlalchemy import Select

from dndlabs.core.schemas import DatasetFilter


def build_predicate(
    stmt: Select[Any], record_row: type[Any], filters: DatasetFilter
) -> Select[Any]:
    """Apply a :class:`DatasetFilter` to a SELECT statement.

    Args:
        stmt: The statement to filter (already scoped to org/dataset).
        record_row: The ``NormalizedRecordRow`` class (passed in rather than
            imported, so this module has no dependency on ``storage``).
        filters: Filter criteria; unset fields are no-ops.

    Returns:
        The filtered statement.
    """
    if filters.mw_min is not None:
        stmt = stmt.where(record_row.molecular_weight >= filters.mw_min)
    if filters.mw_max is not None:
        stmt = stmt.where(record_row.molecular_weight <= filters.mw_max)
    if filters.target is not None:
        stmt = stmt.where(record_row.target == filters.target)
    if filters.source is not None:
        stmt = stmt.where(record_row.source == filters.source.value)
    if filters.activity_min_nm is not None:
        stmt = stmt.where(record_row.activity_value_nm >= filters.activity_min_nm)
    if filters.activity_max_nm is not None:
        stmt = stmt.where(record_row.activity_value_nm <= filters.activity_max_nm)
    return stmt
