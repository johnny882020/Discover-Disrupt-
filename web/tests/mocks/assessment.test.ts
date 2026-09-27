import { describe, expect, it } from "vitest";
import type { NormalizedRecord } from "../../src/api/types";
import { buildAssessment } from "../../src/mocks/assessment";
import { RECORDS_ASPIRIN } from "../../src/mocks/data";

function withActivity(value: number | null, relation: string | null): NormalizedRecord {
  return { ...RECORDS_ASPIRIN[0], id: `${value}${relation}`, activity_value_nm: value, activity_relation: relation };
}

describe("mock assessment", () => {
  it("classifies potency like the API", () => {
    const records = [
      withActivity(100, "="),
      withActivity(100, "<"),
      withActivity(10_000, "="),
      withActivity(50, ">"),
      withActivity(null, null),
    ];
    expect(buildAssessment("d", records).profiles.map((p) => p.potency_class)).toEqual([
      "lead",
      "optimized",
      "inactive",
      "unknown",
      "unknown",
    ]);
  });

  it("summarizes the seeded dataset", () => {
    const result = buildAssessment("d", RECORDS_ASPIRIN);
    expect(result.actives).toBe(RECORDS_ASPIRIN.length);
    expect(result.most_potent_ids).toHaveLength(5);
  });

  it("classes a compound by the majority of its measurements, per format, without controls", () => {
    const base = RECORDS_ASPIRIN[0];
    const records: NormalizedRecord[] = [
      { ...base, id: "a1", record_key: "A", activity_value_nm: 50, assay_format: "biochemical" },
      { ...base, id: "a2", record_key: "A", activity_value_nm: 20_000, assay_format: "cell_based" },
      { ...base, id: "c1", record_key: "C", activity_value_nm: 1, assay_format: "biochemical", control: "positive" },
    ];
    const result = buildAssessment("d", records);
    expect([result.compounds, result.measurements, result.controls]).toEqual([1, 2, 1]);
    expect(result.potency_classes.inactive).toBe(1);
    expect(result.by_format.map((f) => [f.assay_format, f.actives])).toEqual([
      ["biochemical", 1],
      ["cell_based", 0],
    ]);
  });
});
