/** Potency classes: labels and badge tones, most potent first. */
import type { PotencyClass } from "../api/types";
import type { BadgeTone } from "../design-system/Badge";

export const POTENCY_CLASSES: { potency: PotencyClass; label: string; range: string; tone: BadgeTone }[] = [
  { potency: "optimized", label: "Optimized", range: "< 100 nM", tone: "success" },
  { potency: "lead", label: "Lead", range: "< 1 µM", tone: "success" },
  { potency: "hit", label: "Hit", range: "< 10 µM", tone: "accent" },
  { potency: "inactive", label: "Inactive", range: "≥ 10 µM", tone: "neutral" },
  { potency: "unknown", label: "No potency", range: "no value, or open-ended", tone: "neutral" },
];

export function potencyInfo(potency: PotencyClass) {
  return POTENCY_CLASSES.find((p) => p.potency === potency) ?? POTENCY_CLASSES[POTENCY_CLASSES.length - 1];
}
