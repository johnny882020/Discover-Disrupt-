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
    measurements: 5,
    controls: 1,
    potency_classes: { optimized: 1, lead: 1, hit: 1, inactive: 0, unknown: 1 },
    actives: 3,
    by_format: [
      {
        assay_format: "biochemical",
        compounds: 3,
        potency_classes: { optimized: 1, lead: 1, hit: 1, inactive: 0, unknown: 0 },
        actives: 3,
      },
      {
        assay_format: "cell_based",
        compounds: 2,
        potency_classes: { optimized: 0, lead: 0, hit: 1, inactive: 1, unknown: 0 },
        actives: 1,
      },
    ],
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

  it("shows compounds, measurements, controls and potency by assay format", () => {
    render(<HitLeadPanel assessment={assessment()} />);
    expect(screen.getByText(/4 compounds from 5 measurements; 1 control record is not assessed/)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Potency by assay format" });
    const cell = within(table).getByRole("row", { name: /Cell-based/ });
    expect(within(cell).getAllByRole("cell").map((c) => c.textContent)).toEqual(["2", "0", "0", "1", "1", "0", "1"]);
  });

  it("keeps a row for measurements without a format", () => {
    const withoutFormat = {
      assay_format: null,
      compounds: 1,
      potency_classes: { optimized: 0, lead: 0, hit: 0, inactive: 0, unknown: 1 },
      actives: 0,
    };
    render(<HitLeadPanel assessment={assessment({ by_format: [...assessment().by_format, withoutFormat] })} />);
    const table = screen.getByRole("table", { name: "Potency by assay format" });
    expect(within(table).getByRole("row", { name: /Not given/ })).toBeInTheDocument();
  });

  it("omits the format table when no assay format was given", () => {
    const withoutFormat = {
      assay_format: null,
      compounds: 4,
      potency_classes: { optimized: 1, lead: 1, hit: 1, inactive: 0, unknown: 1 },
      actives: 3,
    };
    render(<HitLeadPanel assessment={assessment({ by_format: [withoutFormat] })} />);
    expect(screen.queryByRole("table", { name: "Potency by assay format" })).not.toBeInTheDocument();
  });
});
