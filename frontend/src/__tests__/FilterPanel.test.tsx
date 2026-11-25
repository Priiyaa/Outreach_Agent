import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FilterPanel from "@/components/FilterPanel";
import type { Meta } from "@/lib/api";
import { DEFAULT_FILTERS } from "@/lib/filters";

const meta: Meta = {
  writes_locked: false,
  fetch_enabled: true,
  experience: ["New grad", "Experienced", "Unclear"],
  sponsorship: ["Yes", "No", "Unknown"],
  status: { new: "New", saved: "Saved" },
};

describe("FilterPanel", () => {
  it("shows an empty list (meaning all) as every box checked", () => {
    render(<FilterPanel meta={meta} filters={{ ...DEFAULT_FILTERS, experience: [] }} onChange={() => {}} />);
    for (const name of meta.experience) expect(screen.getByRole("checkbox", { name })).toBeChecked();
  });

  it("unchecking one box from 'all' selects the others", async () => {
    const onChange = vi.fn();
    render(<FilterPanel meta={meta} filters={{ ...DEFAULT_FILTERS, experience: [] }} onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Unclear" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ experience: ["New grad", "Experienced"] }));
  });

  it("checking the last missing box goes back to 'all' (empty list)", async () => {
    const onChange = vi.fn();
    render(<FilterPanel meta={meta} filters={{ ...DEFAULT_FILTERS, experience: ["New grad", "Experienced"] }} onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Unclear" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ experience: [] }));
  });

  it("ignores unchecking the only selected box", async () => {
    const onChange = vi.fn();
    render(<FilterPanel meta={meta} filters={{ ...DEFAULT_FILTERS, experience: ["Unclear"] }} onChange={onChange} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Unclear" }));
    expect(onChange).not.toHaveBeenCalled();
  });
});
