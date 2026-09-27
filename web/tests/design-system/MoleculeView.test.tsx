import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { depictSvg, loadRDKit } from "../../src/chem/rdkit";
import { MoleculeView } from "../../src/design-system/MoleculeView";

vi.mock("../../src/chem/rdkit", () => ({
  loadRDKit: vi.fn(),
  depictSvg: vi.fn(),
}));

const ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O";
const mockedLoad = vi.mocked(loadRDKit);
const mockedDepict = vi.mocked(depictSvg);

describe("MoleculeView", () => {
  beforeEach(() => {
    mockedLoad.mockReset();
    mockedDepict.mockReset();
  });

  it("draws the structure once RDKit.js is loaded", async () => {
    mockedLoad.mockResolvedValue({} as Awaited<ReturnType<typeof loadRDKit>>);
    mockedDepict.mockReturnValue("<svg xmlns='http://www.w3.org/2000/svg'></svg>");
    render(<MoleculeView smiles={ASPIRIN} size="md" />);

    expect(screen.getByText(ASPIRIN)).toBeInTheDocument(); // text while loading
    const img = await screen.findByRole("img", { name: ASPIRIN });
    expect(img).toHaveAttribute("src", expect.stringMatching(/^data:image\/svg\+xml;charset=utf-8,/));
    expect(img).toHaveAttribute("width", "260");
    expect(mockedDepict).toHaveBeenCalledWith(expect.anything(), ASPIRIN, { width: 260, height: 180 }, []);
  });

  it("passes the atoms to highlight to the depiction", async () => {
    mockedLoad.mockResolvedValue({} as Awaited<ReturnType<typeof loadRDKit>>);
    mockedDepict.mockReturnValue("<svg xmlns='http://www.w3.org/2000/svg'></svg>");
    render(<MoleculeView smiles={ASPIRIN} highlightAtoms={[4, 5]} />);
    await screen.findByRole("img", { name: ASPIRIN });
    expect(mockedDepict).toHaveBeenCalledWith(expect.anything(), ASPIRIN, { width: 160, height: 100 }, [4, 5]);
  });

  it("keeps the SMILES text when RDKit.js cannot load", async () => {
    mockedLoad.mockRejectedValue(new Error("wasm blocked"));
    render(<MoleculeView smiles={ASPIRIN} />);
    await waitFor(() => expect(mockedLoad).toHaveBeenCalled());
    expect(screen.getByText(ASPIRIN)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("keeps the SMILES text when RDKit.js cannot parse it", async () => {
    mockedLoad.mockResolvedValue({} as Awaited<ReturnType<typeof loadRDKit>>);
    mockedDepict.mockReturnValue(null);
    render(<MoleculeView smiles="C1CC(" />);
    await waitFor(() => expect(mockedDepict).toHaveBeenCalled());
    expect(screen.getByText("C1CC(")).toBeInTheDocument();
  });

  it("shows a fallback when there is no structure", () => {
    render(<MoleculeView smiles={null} />);
    expect(screen.getByText(/no structure/i)).toBeInTheDocument();
    expect(mockedLoad).not.toHaveBeenCalled();
  });
});
