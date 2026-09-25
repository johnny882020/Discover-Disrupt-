"""Plain-text rendering of results for the terminal."""

from dndlabs.core.schemas import Dataset, PipelineRun, QualityReport


def format_report(report: QualityReport, max_issues: int = 10) -> str:
    """Render a quality-report summary.

    Args:
        report: The report.
        max_issues: Maximum individual issues to list.

    Returns:
        Multi-line text.
    """
    lines = [
        "Quality report",
        f"  total records      {report.total_records}",
        f"  accepted           {report.accepted_records}",
        f"  rejected (errors)  {report.rejected_records}",
        f"  duplicates         {report.duplicate_records}",
        f"  warnings / errors  {report.warning_count} / {report.error_count}",
        f"  pass rate          {report.pass_rate:.1%}",
    ]
    if report.issues_by_rule:
        lines.append(
            "  issues by rule     "
            + ", ".join(f"{rule}={count}" for rule, count in report.issues_by_rule.items())
        )
    for issue in report.issues[:max_issues]:
        lines.append(
            f"    [{issue.severity.value}] {issue.source_record_id} {issue.rule}: {issue.message}"
        )
    hidden = len(report.issues) - max_issues
    if hidden > 0:
        lines.append(f"    ... {hidden} more issue(s)")
    return "\n".join(lines)


def format_run(run: PipelineRun) -> str:
    """Render run status.

    Args:
        run: The run.

    Returns:
        Multi-line text.
    """
    lines = [
        f"Run {run.id}",
        f"  status   {run.status.value}",
        f"  source   {run.spec.source.value}",
    ]
    if run.dataset_id:
        lines.append(f"  dataset  {run.dataset_id}")
    if run.error:
        lines.append(f"  error    {run.error}")
    return "\n".join(lines)


def format_datasets(datasets: list[Dataset]) -> str:
    """Render a dataset listing.

    Args:
        datasets: Datasets to list.

    Returns:
        One line per dataset, or a placeholder when empty.
    """
    if not datasets:
        return "No datasets yet."
    return "\n".join(
        f"{d.id}  {d.created_at:%Y-%m-%d %H:%M}  {d.source.value:<7}  {d.record_count:>6}  {d.name}"
        for d in datasets
    )
