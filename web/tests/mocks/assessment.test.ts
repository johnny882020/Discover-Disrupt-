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
});
