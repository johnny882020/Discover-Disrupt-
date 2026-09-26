/**
 * Drag-and-drop file picker. The whole zone is a labelled file input, so it
 * works by drop, click, or keyboard (Enter/Space on the focused button).
 */
import { useId, useRef, useState, type DragEvent } from "react";

interface FileDropProps {
  /** Accepted file extensions, e.g. `.csv,.xlsx`. */
  accept: string;
  /** Short description of what can be dropped. */
  hint: string;
  disabled?: boolean;
  onFile: (file: File) => void;
}

export function FileDrop({ accept, hint, disabled = false, onFile }: FileDropProps): React.JSX.Element {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function handleDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file && !disabled) {
      onFile(file);
    }
  }

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`flex flex-col items-center gap-2 rounded-md border-2 border-dashed px-6 py-10 text-center transition-colors ${
        dragging ? "border-accent bg-accent/5" : "border-ink/20 dark:border-paper/25"
      } ${disabled ? "opacity-50" : ""}`}
    >
      <p className="text-sm font-medium">Drag a file here, or</p>
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        className="rounded border border-ink/20 px-3 py-1.5 text-sm hover:bg-ink/5 disabled:cursor-not-allowed dark:border-paper/25 dark:hover:bg-paper/10"
      >
        Choose a file
      </button>
      <label htmlFor={inputId} className="text-xs text-ink/60 dark:text-paper/60">
        {hint}
      </label>
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={accept}
        disabled={disabled}
        className="sr-only"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) {
            onFile(file);
          }
          event.target.value = "";
        }}
      />
    </div>
  );
}
