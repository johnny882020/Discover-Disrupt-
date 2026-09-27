// @vitest-environment node
// Loads the real RDKit.js WebAssembly module from disk (Node reads it with fs).
import path from "node:path";
import { describe, expect, it, vi } from "vitest";
import { depictSvg, loadRDKit } from "../../src/chem/rdkit";

vi.mock("@rdkit/rdkit/RDKit_minimal.wasm?url", () => ({
  default: path.resolve("node_modules/@rdkit/rdkit/dist/RDKit_minimal.wasm"),
}));

const SIZE = { width: 160, height: 100 };

describe("RDKit.js depiction", () => {
  it("loads once and draws a valid structure as SVG", async () => {
    const [first, second] = await Promise.all([loadRDKit(), loadRDKit()]);
    expect(first).toBe(second);

    const svg = depictSvg(first, "CC(=O)Oc1ccccc1C(=O)O", SIZE);
    expect(svg).toMatch(/^<\?xml[\s\S]*<svg[\s\S]*<\/svg>/);
    expect(svg).toContain("width='160px'");
  });

  it("returns null for SMILES RDKit cannot parse", async () => {
    const rdkit = await loadRDKit();
    expect(depictSvg(rdkit, "C1CC(", SIZE)).toBeNull();
  });

  it("highlights the requested atoms", async () => {
    const rdkit = await loadRDKit();
    const plain = depictSvg(rdkit, "Nc1ccccc1", SIZE) ?? "";
    const flagged = depictSvg(rdkit, "Nc1ccccc1", SIZE, [0, 1]) ?? "";
    // The highlight colour (0.93, 0.55, 0.55) as RDKit writes it.
    expect(flagged.toUpperCase()).toContain("#ED8C8C");
    expect(plain.toUpperCase()).not.toContain("#ED8C8C");
  });

  it("serves repeated depictions from the cache", async () => {
    const rdkit = await loadRDKit();
    const getMol = vi.spyOn(rdkit, "get_mol");
    const first = depictSvg(rdkit, "c1ccncc1", SIZE);
    const again = depictSvg(rdkit, "c1ccncc1", SIZE);
    expect(again).toBe(first);
    expect(getMol).toHaveBeenCalledTimes(1);
  });
});
