/** QualityReport: data-quality summary and issue list for one dataset. */
import { useParams } from "react-router-dom";
import { Badge } from "../design-system/Badge";
import { Card } from "../design-system/Card";
import { Table } from "../design-system/Table";
import { useQualityReport } from "../hooks/useQualityReport";

function StatTile({ label, value }: { label: string; value: string | number }): React.JSX.Element {
  return (
    <div className="flex flex-col gap-1 border-l border-ink/10 px-4 first:border-l-0 first:pl-0 dark:border-paper/15">
      <span className="text-xs uppercase tracking-wide text-ink/60 dark:text-paper/60">{label}</span>
      <span className="font-display text-2xl">{value}</span>
    </div>
  );
}

export function QualityReport(): React.JSX.Element {
  const { datasetId } = useParams<{ datasetId: string }>();
  const query = useQualityReport(datasetId);

  if (query.isLoading) {
    return <p className="text-sm text-ink/60 dark:text-paper/60">Loading quality report…</p>;
  }

  if (query.isError) {
    return (
      <p role="alert" className="text-sm text-danger">
        Could not load the quality report: {query.error.message}
      </p>
    );
  }

  const report = query.data;
  if (!report) {
    return <p className="text-sm text-ink/60 dark:text-paper/60">No quality report found.</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <h1 className="font-display text-3xl">Quality report</h1>

      <Card>
        <div className="flex flex-wrap gap-6">
          <StatTile label="Total records" value={report.total_records} />
          <StatTile label="Accepted" value={report.accepted_records} />
          <StatTile label="Rejected" value={report.rejected_records} />
          <StatTile label="Duplicates" value={report.duplicate_records} />
          <StatTile label="Pass rate" value={`${(report.pass_rate * 100).toFixed(1)}%`} />
        </div>
      </Card>

      <Card>
        <h2 className="mb-4 text-lg font-medium">Issues by rule</h2>
        {Object.keys(report.issues_by_rule).length === 0 ? (
          <p className="text-sm text-ink/60 dark:text-paper/60">No issues were found in this run.</p>
        ) : (
          <ul className="flex flex-col gap-2 text-sm">
            {Object.entries(report.issues_by_rule).map(([rule, count]) => (
              <li key={rule} className="flex items-center justify-between">
                <span className="font-mono">{rule}</span>
                <span className="text-ink/60 dark:text-paper/60">{count}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card>
        <h2 className="mb-4 text-lg font-medium">Issues</h2>
        {report.issues.length === 0 ? (
          <p className="text-sm text-ink/60 dark:text-paper/60">No issues to review.</p>
        ) : (
          <Table
            columns={[
              {
                key: "severity",
                header: "Severity",
                cell: (issue) => (
                  <Badge tone={issue.severity === "error" ? "danger" : "warning"}>{issue.severity}</Badge>
                ),
              },
              { key: "rule", header: "Rule", cell: (issue) => <span className="font-mono">{issue.rule}</span> },
              { key: "record", header: "Record", cell: (issue) => issue.source_record_id },
              { key: "field", header: "Field", cell: (issue) => issue.field ?? "—" },
              { key: "message", header: "Message", cell: (issue) => issue.message },
            ]}
            rows={report.issues}
            getRowKey={(issue) => `${issue.rule}-${issue.source_record_id}-${issue.field ?? ""}-${issue.message}`}
          />
        )}
      </Card>
    </div>
  );
}
