"""Helpers for building validation issues."""

from dndlabs.core.schemas import NormalizedRecord, Severity, ValidationIssue


def error(
    rule: str, record: NormalizedRecord, message: str, field: str | None = None
) -> ValidationIssue:
    """Build an error-severity issue (the record will be rejected).

    Args:
        rule: Rule name.
        record: Record the issue is about.
        message: Human-readable description.
        field: Offending field, if any.

    Returns:
        The issue.
    """
    return ValidationIssue(
        rule=rule,
        severity=Severity.ERROR,
        source_record_id=record.source_record_id,
        field=field,
        message=message,
    )


def warning(
    rule: str, record: NormalizedRecord, message: str, field: str | None = None
) -> ValidationIssue:
    """Build a warning-severity issue (the record is kept).

    Args:
        rule: Rule name.
        record: Record the issue is about.
        message: Human-readable description.
        field: Offending field, if any.

    Returns:
        The issue.
    """
    return ValidationIssue(
        rule=rule,
        severity=Severity.WARNING,
        source_record_id=record.source_record_id,
        field=field,
        message=message,
    )


def parse_number(value: str | float | None) -> float | None:
    """Parse a numeric value that may arrive as a string.

    Args:
        value: Raw value.

    Returns:
        The float, or ``None`` when the value is missing.

    Raises:
        ValueError: If the value is present but not a finite number.
    """
    if value is None:
        return None
    number = float(value.strip().replace(",", "") if isinstance(value, str) else value)
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{value!r} is not a finite number")
    return number
