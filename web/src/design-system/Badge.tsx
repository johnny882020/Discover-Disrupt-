/** Small status/label pill. No emoji icons — color + text only. */
import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "success" | "warning" | "danger" | "accent";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-ink/8 text-ink dark:bg-paper/10 dark:text-paper",
  success: "bg-success/10 text-success dark:text-success-bright",
  warning: "bg-warn/10 text-warn dark:text-warn-bright",
  danger: "bg-danger/10 text-danger dark:text-danger-bright",
  accent: "bg-accent/10 text-accent dark:text-accent-bright",
};

export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }): React.JSX.Element {
  return (
    <span
      className={`inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  );
}
