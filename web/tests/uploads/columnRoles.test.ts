import { describe, expect, it } from "vitest";
import { ROLE_OPTIONS, lookupColumns, mappingProblem } from "../../src/uploads/columnRoles";

describe("mappingProblem", () => {
  it("accepts a mapping with one structure column", () => {
    expect(mappingProblem({ a: "smiles", b: "ignore", c: "ignore", d: "activity_value" })).toBeNull();
    expect(mappingProblem({ a: "inchi" })).toBeNull();
  });

  it.each(["mol_block", "inchikey", "pubchem_cid", "chembl_id", "lookup_name"] as const)(
    "accepts %s as the structure column",
    (role) => {
      expect(mappingProblem({ a: role })).toBeNull();
    },
  );

  it("requires a structure column and one column per role", () => {
    expect(mappingProblem({})).toMatch(/identifies each structure/);
    expect(mappingProblem({ a: "name", b: "ignore" })).toMatch(/identifies each structure/);
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
        "chembl_id",
        "inchi",
        "inchikey",
        "lookup_name",
        "mol_block",
        "pubchem_cid",
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

describe("lookupColumns", () => {
  it("lists the columns whose values leave the platform", () => {
    expect(lookupColumns({ Key: "inchikey", Struct: "mol_block", Code: "chembl_id", Label: "name" })).toEqual([
      "Key",
      "Code",
    ]);
    expect(lookupColumns({ Struct: "smiles" })).toEqual([]);
  });
});
