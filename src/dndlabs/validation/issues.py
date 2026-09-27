"""Helpers shared by validation rules: building issues and parsing numbers.

A record is rejected when any rule reports an error-severity issue for it;
warnings are recorded in the quality report and the record is kept.
"""

import re

from dndlabs.core.schemas import NormalizedRecord, Severity, ValidationIssue

# Commas are accepted only as thousands separators in full groups of three
# ("1,200", "12,500.5"). Anything else ("1,5", "1,2,3") is ambiguous: in many
# locales the comma is the decimal separator, and dropping it would silently
# read "1,5" as 15 instead of 1.5.
_GROUPED = re.compile(r"[+-]?\d{1,3}(,\d{3})+(\.\d*)?")


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
    if isinstance(value, str):
        text = value.strip()
        if "," in text:
            if not _GROUPED.fullmatch(text):
                raise ValueError(f"{value!r} has an ambiguous comma")
            text = text.replace(",", "")
        number = float(text)
    else:
        number = float(value)
    # float() accepts "nan" and "inf"; neither is a usable measurement.
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{value!r} is not a finite number")
    return number
