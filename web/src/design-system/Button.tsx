/** Primitive button with primary/secondary/ghost variants. */
import type { ButtonHTMLAttributes } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-fg hover:bg-accent/90",
  secondary:
    "border border-ink/20 bg-transparent text-ink hover:bg-ink/5 dark:border-paper/25 dark:text-paper dark:hover:bg-paper/10",
  ghost: "bg-transparent text-ink hover:bg-ink/5 dark:text-paper dark:hover:bg-paper/10",
  danger: "bg-danger text-paper hover:bg-danger/90",
};

export function Button({ variant = "primary", className = "", ...props }: ButtonProps): React.JSX.Element {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center rounded px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT_CLASSES[variant]} ${className}`}
    />
  );
}
