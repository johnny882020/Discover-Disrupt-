import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MoleculeView } from "../../src/design-system/MoleculeView";

describe("MoleculeView", () => {
  it("renders the SMILES string as text", () => {
    render(<MoleculeView smiles="CC(=O)Oc1ccccc1C(=O)O" />);
    expect(screen.getByText("CC(=O)Oc1ccccc1C(=O)O")).toBeInTheDocument();
  });

  it("shows a fallback when there is no structure", () => {
    render(<MoleculeView smiles={null} />);
    expect(screen.getByText(/no structure/i)).toBeInTheDocument();
  });
});
