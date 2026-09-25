import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Button } from "../../src/design-system/Button";

describe("Button", () => {
  it("renders its label and responds to clicks", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<Button onClick={onClick}>Save</Button>);

    const button = screen.getByRole("button", { name: "Save" });
    await user.click(button);

    expect(onClick).toHaveBeenCalledOnce();
  });

  it("can be disabled", () => {
    render(<Button disabled>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});
