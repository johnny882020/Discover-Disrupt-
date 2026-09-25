import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Card } from "../../src/design-system/Card";

describe("Card", () => {
  it("renders its children inside a surface", () => {
    render(
      <Card>
        <p>Panel content</p>
      </Card>,
    );
    expect(screen.getByText("Panel content")).toBeInTheDocument();
  });
});
