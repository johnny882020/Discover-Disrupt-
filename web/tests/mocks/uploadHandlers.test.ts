import { describe, expect, it } from "vitest";
import { createUploadPreview } from "../../src/mocks/uploadHandlers";

describe("createUploadPreview", () => {
  it("suggests roles for headers regardless of case, spacing and punctuation", () => {
    const preview = createUploadPreview(
      "org-1",
      "lab.csv",
      "Compound ID,Canonical SMILES,Activity Value,Notes\nC-1,CCO,12,ok\n",
    );
    expect(preview.suggested_mapping).toEqual({
      "Compound ID": "source_record_id",
      "Canonical SMILES": "smiles",
      "Activity Value": "activity_value",
    });
  });
});
