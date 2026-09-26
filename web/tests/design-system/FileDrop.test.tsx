import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { FileDrop } from "../../src/design-system/FileDrop";

const file = new File(["smiles\nCCO\n"], "lab.csv", { type: "text/csv" });

describe("FileDrop", () => {
  it("accepts a chosen file through its labelled input", async () => {
    const onFile = vi.fn();
    const user = userEvent.setup();
    render(<FileDrop accept=".csv" hint="CSV only" onFile={onFile} />);
    await user.upload(screen.getByLabelText("CSV only"), file);
    expect(onFile).toHaveBeenCalledWith(file);
  });

  it("accepts a dropped file", () => {
    const onFile = vi.fn();
    render(<FileDrop accept=".csv" hint="CSV only" onFile={onFile} />);
    const zone = screen.getByText("Drag a file here, or").parentElement as HTMLElement;
    const drop = createEvent.drop(zone, { dataTransfer: { files: [file] } });
    fireEvent(zone, drop);
    expect(onFile).toHaveBeenCalledWith(file);
  });

  it("ignores drops while disabled", () => {
    const onFile = vi.fn();
    render(<FileDrop accept=".csv" hint="CSV only" disabled onFile={onFile} />);
    const zone = screen.getByText("Drag a file here, or").parentElement as HTMLElement;
    fireEvent(zone, createEvent.drop(zone, { dataTransfer: { files: [file] } }));
    expect(onFile).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Choose a file" })).toBeDisabled();
  });
});
