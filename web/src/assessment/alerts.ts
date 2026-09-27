/** Structural alert families: labels, badge tones, and which are highlighted. */
import type { AlertFamily, StructuralAlert } from "../api/types";
import type { BadgeTone } from "../design-system/Badge";

export const ALERT_FAMILIES: { family: AlertFamily; label: string; tone: BadgeTone; highlight: boolean }[] = [
  { family: "pains", label: "PAINS", tone: "danger", highlight: true },
  { family: "reactive_metabolite", label: "Reactive metabolite", tone: "danger", highlight: true },
  // Brenk flags broad "unwanted" groups (e.g. aspirin's phenol ester): listed, not highlighted.
  { family: "brenk", label: "Brenk", tone: "warning", highlight: false },
];

/** Atoms to highlight on a structure: those matched by PAINS and reactive-metabolite alerts. */
export function highlightedAtoms(alerts: readonly StructuralAlert[]): number[] {
  const highlighted = new Set(ALERT_FAMILIES.filter((f) => f.highlight).map((f) => f.family));
  const atoms = new Set<number>();
  for (const alert of alerts) {
    if (highlighted.has(alert.family)) alert.atoms.forEach((atom) => atoms.add(atom));
  }
  return [...atoms].sort((a, b) => a - b);
}
