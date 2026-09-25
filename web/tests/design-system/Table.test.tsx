import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Table } from "../../src/design-system/Table";

interface Row {
  id: string;
  name: string;
}

describe("Table", () => {
  it("renders headers and row cells", () => {
    const rows: Row[] = [{ id: "1", name: "Aspirin" }];
    render(
      <Table<Row>
        columns={[{ key: "name", header: "Name", cell: (r) => r.name }]}
        rows={rows}
        getRowKey={(r) => r.id}
      />,
    );

    expect(screen.getByText("Name")).toBeInTheDocument();
    expect(screen.getByText("Aspirin")).toBeInTheDocument();
  });
});
