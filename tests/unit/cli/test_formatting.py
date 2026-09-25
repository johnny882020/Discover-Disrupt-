from dndlabs.cli.formatting import format_report
from dndlabs.core.schemas import QualityReport, Severity, ValidationIssue


def test_report_truncates_issue_list() -> None:
    issues = [
        ValidationIssue(
            rule="schema", severity=Severity.ERROR, source_record_id=str(i), message="m"
        )
        for i in range(5)
    ]
    report = QualityReport(
        run_id="r",
        total_records=5,
        accepted_records=0,
        rejected_records=5,
        duplicate_records=0,
        warning_count=0,
        error_count=5,
        issues_by_rule={"schema": 5},
        issues=issues,
        pass_rate=0.0,
    )
    text = format_report(report, max_issues=2)
    assert "schema=5" in text
    assert "... 3 more issue(s)" in text
