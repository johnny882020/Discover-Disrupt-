import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Badge } from "../../src/design-system/Badge";

describe("Badge", () => {
  it("renders its children", () => {
    render(<Badge tone="danger">error</Badge>);
    expect(screen.getByText("error")).toBeInTheDocument();
  });
});
