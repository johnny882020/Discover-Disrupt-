/** Labelled text input with an optional hint, sharing the app's form styling. */
import { useId, type InputHTMLAttributes } from "react";

interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id"> {
  label: string;
  hint?: string;
}

export function TextField({ label, hint, className = "", ...props }: TextFieldProps): React.JSX.Element {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <div className="flex flex-col gap-1.5 text-sm">
      <label htmlFor={id} className="font-medium">
        {label}
      </label>
      <input
        {...props}
        id={id}
        aria-describedby={hintId}
        className={`rounded border border-ink/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-accent dark:border-paper/20 ${className}`}
      />
      {hint ? (
        <p id={hintId} className="text-xs text-ink/60 dark:text-paper/60">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
