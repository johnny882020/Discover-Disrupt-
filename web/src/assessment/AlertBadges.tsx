/** A compound's structural alerts as one badge per family, naming each alert. */
import type { StructuralAlert } from "../api/types";
import { Badge } from "../design-system/Badge";
import { ALERT_FAMILIES } from "./alerts";

export function AlertBadges({ alerts }: { alerts: readonly StructuralAlert[] }): React.JSX.Element {
  const groups = ALERT_FAMILIES.map((family) => ({
    ...family,
    names: alerts.filter((a) => a.family === family.family).map((a) => a.name),
  })).filter((group) => group.names.length > 0);
  if (groups.length === 0) {
    return <span className="text-ink/50 dark:text-paper/50">None</span>;
  }
  return (
    <ul className="flex flex-col gap-1">
      {groups.map((group) => (
        <li key={group.family} title={group.names.join(", ")}>
          <Badge tone={group.tone}>
            {group.label}: {group.names.join(", ")}
          </Badge>
        </li>
      ))}
    </ul>
  );
}
