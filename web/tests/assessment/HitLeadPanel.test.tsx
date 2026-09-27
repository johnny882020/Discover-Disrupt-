import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CriterionSummary, DatasetAssessment } from "../../src/api/types";
import { HitLeadPanel } from "../../src/assessment/HitLeadPanel";

function summary(overrides: Partial<CriterionSummary> = {}): CriterionSummary {
  return {
    criterion: "mw_under_500",
    label: "MW < 500",
    all_compounds: { passing: 3, evaluated: 4 },
    actives: { passing: 1, evaluated: 3 },
    most_potent: { passing: 0, evaluated: 0 },
    ...overrides,
  };
}

function assessment(overrides: Partial<DatasetAssessment> = {}): DatasetAssessment {
  return {
    dataset_id: "d",
    compounds: 4,
    potency_classes: { optimized: 1, lead: 1, hit: 1, inactive: 0, unknown: 1 },
    actives: 3,
    most_potent_ids: [],
    criteria: [summary()],
    profiles: [],
    ...overrides,
  };
}

describe("HitLeadPanel", () => {
  it("counts compounds per potency class", () => {
    render(<HitLeadPanel assessment={assessment()} />);
    const classes = screen.getByRole("list", { name: "Potency classes" });
    expect(within(classes).getByText("Optimized (< 100 nM): 1")).toBeInTheDocument();
    expect(within(classes).getByText("No potency (no value, or open-ended): 1")).toBeInTheDocument();
  });

  it("says whether there are enough actives", () => {
    const { rerender } = render(<HitLeadPanel assessment={assessment()} />);
    expect(screen.getByText(/more than 10 actives give more confidence/)).toBeInTheDocument();
    rerender(<HitLeadPanel assessment={assessment({ actives: 12 })} />);
    expect(screen.getByText(/more than 10, enough to give confidence/)).toBeInTheDocument();
  });

  it("shows each criterion per group, with a dash for an empty group", () => {
    render(<HitLeadPanel assessment={assessment()} />);
    const row = screen.getByRole("row", { name: /MW < 500/ });
    expect(within(row).getByText("3 / 4 (75%)")).toBeInTheDocument();
    expect(within(row).getByText("1 / 3 (33%)")).toBeInTheDocument();
    expect(within(row).getByText("—")).toBeInTheDocument();
  });
});
