import { describe, expect, it } from "vitest";
import { ROLE_OPTIONS, mappingProblem } from "../../src/uploads/columnRoles";

describe("mappingProblem", () => {
  it("accepts a mapping with one structure column", () => {
    expect(mappingProblem({ a: "smiles", b: "ignore", c: "ignore", d: "activity_value" })).toBeNull();
    expect(mappingProblem({ a: "inchi" })).toBeNull();
  });

  it("requires a structure column and one column per role", () => {
    expect(mappingProblem({})).toMatch(/SMILES or InChI/);
    expect(mappingProblem({ a: "name", b: "ignore" })).toMatch(/SMILES or InChI/);
    expect(mappingProblem({ a: "smiles", b: "name", c: "name" })).toBe("Each role can be used for one column only: Name.");
  });

  it("offers every role the API accepts", () => {
    expect(ROLE_OPTIONS.map((o) => o.role).sort()).toEqual(
      [
        "activity_relation",
        "activity_unit",
        "activity_value",
        "assay_type",
        "ignore",
        "inchi",
        "inchikey",
        "molecular_formula",
        "molecular_weight",
        "name",
        "smiles",
        "source_record_id",
        "target",
      ].sort(),
    );
  });
});
