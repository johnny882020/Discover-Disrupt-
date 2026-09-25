"""Unit-normalization rule: activity concentrations to nanomolar."""

from dndlabs.core.schemas import NormalizedRecord, RawRecord, RuleOutcome, ValidationIssue
from dndlabs.validation.issues import error, parse_number, warning

#: Multiplier converting a (lower-cased, micro-sign-normalized) unit to nM.
_TO_NANOMOLAR: dict[str, float] = {
    "mm": 1e6,
    "um": 1e3,
    "nm": 1.0,
    "pm": 1e-3,
    "mol/l": 1e9,
    "mmol/l": 1e6,
    "umol/l": 1e3,
    "nmol/l": 1.0,
    "pmol/l": 1e-3,
}


def nanomolar_factor(unit: str) -> float | None:
    """Return the factor converting ``unit`` to nM.

    ``M`` (molar) is only accepted upper-case because a bare lower-case ``m``
    is ambiguous. Micro may be written ``u``, ``µ`` (U+00B5) or ``μ`` (U+03BC).

    Args:
        unit: Unit as written in the source.

    Returns:
        The multiplier, or ``None`` if the unit is not a supported concentration.
    """
    text = unit.strip().replace("µ", "u").replace("μ", "u")
    if text == "M":
        return 1e9
    return _TO_NANOMOLAR.get(text.lower())


class UnitNormalizationRule:
    """Converts activity values to nanomolar.

    Attributes:
        name: Rule name used in reports.
    """

    name = "unit_normalization"

    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome:
        """Normalize the activity value, if any.

        Args:
            raw: The raw record.
            record: The record built so far.

        Returns:
            The record with ``activity_value_nm`` set, plus any issues.
        """
        issues: list[ValidationIssue] = []
        try:
            value = parse_number(raw.activity_value)
        except ValueError:
            issues.append(
                error(
                    self.name,
                    record,
                    f"activity value {raw.activity_value!r} is not numeric",
                    "activity_value",
                )
            )
            return RuleOutcome(record=record, issues=issues)
        if value is None:
            if raw.activity_unit:
                issues.append(
                    warning(self.name, record, "unit given without a value", "activity_value")
                )
            return RuleOutcome(record=record, issues=issues)
        if value < 0:
            issues.append(
                error(self.name, record, f"concentration {value} is negative", "activity_value")
            )
            return RuleOutcome(record=record, issues=issues)
        if not raw.activity_unit:
            issues.append(error(self.name, record, "activity value has no unit", "activity_unit"))
            return RuleOutcome(record=record, issues=issues)
        factor = nanomolar_factor(raw.activity_unit)
        if factor is None:
            issues.append(
                error(
                    self.name,
                    record,
                    f"unsupported concentration unit {raw.activity_unit!r}",
                    "activity_unit",
                )
            )
            return RuleOutcome(record=record, issues=issues)
        normalized = record.model_copy(update={"activity_value_nm": value * factor})
        return RuleOutcome(record=normalized, issues=issues)
