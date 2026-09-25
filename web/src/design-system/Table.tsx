/** Primitive data table: hairline row dividers, no heavy shadows. */
import type { ReactNode } from "react";

export interface TableColumn<T> {
  header: string;
  cell: (row: T) => ReactNode;
  key: string;
  align?: "left" | "right";
}

interface TableProps<T> {
  columns: TableColumn<T>[];
  rows: T[];
  getRowKey: (row: T) => string;
}

export function Table<T>({ columns, rows, getRowKey }: TableProps<T>): React.JSX.Element {
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-ink/15 dark:border-paper/20">
          {columns.map((col) => (
            <th
              key={col.key}
              scope="col"
              className={`py-2 pr-4 text-xs font-medium uppercase tracking-wide text-ink/60 dark:text-paper/60 ${
                col.align === "right" ? "text-right" : "text-left"
              }`}
            >
              {col.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={getRowKey(row)} className="border-b border-ink/8 dark:border-paper/10">
            {columns.map((col) => (
              <td
                key={col.key}
                className={`py-2 pr-4 ${col.align === "right" ? "text-right" : "text-left"}`}
              >
                {col.cell(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
