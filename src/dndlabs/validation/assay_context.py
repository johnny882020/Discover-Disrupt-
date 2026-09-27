"""Assay-context rule: normalizes a record's assay format and control role."""

import re

from dndlabs.core.schemas import (
    AssayFormat,
    ControlType,
    NormalizedRecord,
    RawRecord,
    RuleOutcome,
    ValidationIssue,
)
from dndlabs.validation.issues import warning

#: Accepted spellings (lower-case, separators collapsed to one space).
_FORMATS: dict[str, AssayFormat] = {
    **dict.fromkeys(
        ("biochemical", "biochem", "enzymatic", "enzyme", "binding", "cell free", "in vitro"),
        AssayFormat.BIOCHEMICAL,
    ),
    **dict.fromkeys(
        ("cell based", "cellular", "cell", "cells", "whole cell", "cell assay"),
        AssayFormat.CELL_BASED,
    ),
}
_CONTROLS: dict[str, ControlType | None] = {
    **dict.fromkeys(("positive", "positive control", "pos", "+", "pc"), ControlType.POSITIVE),
    **dict.fromkeys(("negative", "negative control", "neg", "-", "nc"), ControlType.NEGATIVE),
    # A test compound: explicitly not a control.
    **dict.fromkeys(("no", "none", "false", "0", "test", "sample", "compound"), None),
}
_SEPARATORS = re.compile(r"[\s_\-/]+")


def _normalize(text: str) -> str:
    """Lower-case and collapse separators, keeping a lone ``+`` or ``-``."""
    stripped = text.strip().lower()
    return stripped if stripped in {"+", "-"} else _SEPARATORS.sub(" ", stripped).strip()


class AssayContextRule:
    """Maps assay-format and control values onto their vocabularies.

    An unrecognized value is reported as a warning and left unset; the
    record is kept, since its measurement is still valid.

    Attributes:
        name: Rule name used in reports.
    """

    name = "assay_context"

    def apply(self, raw: RawRecord, record: NormalizedRecord) -> RuleOutcome:
        """Normalize the record's assay format and control role.

        Args:
            raw: The raw record.
            record: The record built so far.

        Returns:
            The record with ``assay_format`` and ``control`` set, plus any warnings.
        """
        issues: list[ValidationIssue] = []
        assay_format: AssayFormat | None = None
        control: ControlType | None = None
        if raw.assay_format:
            assay_format = _FORMATS.get(_normalize(raw.assay_format))
            if assay_format is None:
                issues.append(
                    warning(
                        self.name,
                        record,
                        f"unrecognized assay format {raw.assay_format!r}; use biochemical or "
                        "cell-based",
                        "assay_format",
                    )
                )
        if raw.control:
            key = _normalize(raw.control)
            if key in _CONTROLS:
                control = _CONTROLS[key]
            else:
                issues.append(
                    warning(
                        self.name,
                        record,
                        f"unrecognized control value {raw.control!r}; use positive, negative "
                        "or leave empty",
                        "control",
                    )
                )
        return RuleOutcome(
            record=record.model_copy(update={"assay_format": assay_format, "control": control}),
            issues=issues,
        )
