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

  it("serves repeated depictions from the cache", async () => {
    const rdkit = await loadRDKit();
    const getMol = vi.spyOn(rdkit, "get_mol");
    const first = depictSvg(rdkit, "c1ccncc1", SIZE);
    const again = depictSvg(rdkit, "c1ccncc1", SIZE);
    expect(again).toBe(first);
    expect(getMol).toHaveBeenCalledTimes(1);
  });
});
