import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StructuralAlert } from "../../src/api/types";
import { AlertBadges } from "../../src/assessment/AlertBadges";
import { highlightedAtoms } from "../../src/assessment/alerts";

const ALERTS: StructuralAlert[] = [
  { family: "pains", name: "quinone_A(370)", atoms: [0, 1, 2] },
  { family: "reactive_metabolite", name: "Quinone", atoms: [2, 3] },
  { family: "brenk", name: "chinone_1", atoms: [7, 8] },
];

describe("structural alerts", () => {
  it("highlights PAINS and reactive-metabolite atoms, not Brenk's", () => {
    expect(highlightedAtoms(ALERTS)).toEqual([0, 1, 2, 3]);
    expect(highlightedAtoms([])).toEqual([]);
  });

  it("names every alert, grouped by family", () => {
    render(<AlertBadges alerts={ALERTS} />);
    expect(screen.getByText("PAINS: quinone_A(370)")).toBeInTheDocument();
    expect(screen.getByText("Reactive metabolite: Quinone")).toBeInTheDocument();
    expect(screen.getByText("Brenk: chinone_1")).toBeInTheDocument();
  });

  it("says when there are none", () => {
    render(<AlertBadges alerts={[]} />);
    expect(screen.getByText("None")).toBeInTheDocument();
  });
});
