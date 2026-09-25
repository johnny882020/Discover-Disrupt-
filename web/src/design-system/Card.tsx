/** Primitive surface with a hairline border, used for panels and screens. */
import type { HTMLAttributes } from "react";

export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>): React.JSX.Element {
  return (
    <div
      {...props}
      className={`rounded-md border border-ink/10 bg-white p-6 dark:border-paper/15 dark:bg-[#1a1e25] ${className}`}
    />
  );
}
