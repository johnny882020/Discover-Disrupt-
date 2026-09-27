/**
 * HitLeadPanel: a dataset against common hit-to-lead criteria — potency
 * classes, the count of actives, and computed-property criteria over all
 * compounds, the actives and the five most potent.
 */
import type { CriterionShare, DatasetAssessment } from "../api/types";
import { Badge } from "../design-system/Badge";
import { Card } from "../design-system/Card";
import { POTENCY_CLASSES } from "./potency";

/** The guide's bar for confidence that a candidate can be found. */
const ENOUGH_ACTIVES = 10;

function ShareCell({ share }: { share: CriterionShare }): React.JSX.Element {
  if (share.evaluated === 0) {
    return <span className="text-ink/50 dark:text-paper/50">—</span>;
  }
  const majority = share.passing * 2 > share.evaluated;
  const percent = Math.round((share.passing / share.evaluated) * 100);
  return (
    <Badge tone={majority ? "success" : "danger"}>
      {share.passing} / {share.evaluated} ({percent}%)
    </Badge>
  );
}

export function HitLeadPanel({ assessment }: { assessment: DatasetAssessment }): React.JSX.Element {
  const { actives } = assessment;
  return (
    <Card>
      <h2 className="text-lg font-medium">Hit/lead criteria</h2>
      <p className="mt-1 text-sm text-ink/60 dark:text-paper/60">
        Potency from activity values (IC50, Ki, …). Properties computed with RDKit from the standardized
        structures.
      </p>

      <ul className="mt-4 flex flex-wrap gap-2" aria-label="Potency classes">
        {POTENCY_CLASSES.map(({ potency, label, range, tone }) => (
          <li key={potency}>
            <Badge tone={tone}>
              {label} ({range}): {assessment.potency_classes[potency] ?? 0}
            </Badge>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-sm">
        <strong>{actives}</strong> {actives === 1 ? "active" : "actives"} below 10 µM
        {actives > ENOUGH_ACTIVES
          ? " — more than 10, enough to give confidence a candidate can be found."
          : " — more than 10 actives give more confidence that a candidate can be found."}
      </p>

      <div className="mt-4 overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-ink/15 dark:border-paper/20">
              {["Criterion", "All compounds", "Actives", "5 most potent"].map((header) => (
                <th
                  key={header}
                  scope="col"
                  className="py-2 pr-4 text-left text-xs font-medium uppercase tracking-wide text-ink/60 dark:text-paper/60"
                >
                  {header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {assessment.criteria.map((row) => (
              <tr key={row.criterion} className="border-b border-ink/8 dark:border-paper/10">
                <th scope="row" className="py-2 pr-4 text-left font-normal">
                  {row.label}
                </th>
                <td className="py-2 pr-4">
                  <ShareCell share={row.all_compounds} />
                </td>
                <td className="py-2 pr-4">
                  <ShareCell share={row.actives} />
                </td>
                <td className="py-2 pr-4">
                  <ShareCell share={row.most_potent} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-ink/60 dark:text-paper/60">
        Green: met by the majority of the group. Compounds without a computed structure are not counted.
      </p>
    </Card>
  );
}
