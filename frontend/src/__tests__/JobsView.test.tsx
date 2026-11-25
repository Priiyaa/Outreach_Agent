import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import JobsView from "@/components/JobsView";

const meta = {
  writes_locked: false, fetch_enabled: true, experience: ["New grad"],
  sponsorship: ["Yes", "No", "Unknown"], status: { new: "New", saved: "Saved", applied: "Applied", skipped: "Skipped" },
};
const job = {
  id: "j1", company: "Acme", title: "Software Engineer", location: "Chicago, IL", cs_role_evidence: "", role_family: "software",
  experience: "New grad", sponsorship: "Unknown", sponsorship_note: "", status: "new", url: "https://x/1",
  first_seen: "2026-11-01T00:00:00+00:00", posted_at: "2026-10-30", match_score: 80, match_reasons: "",
};

afterEach(() => vi.unstubAllGlobals());

it("saves a status change straight away, with no save button, and keeps the row coloured", async () => {
  const patches: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "PATCH") patches.push(JSON.parse(init.body as string));
    const body = url.includes("/api/meta") ? meta : init?.method === "PATCH" ? { saved: 1 }
      : { stats: { total: 1, new_grad: 1, sponsor_yes: 0, not_applied: 1 }, limit: 100, offset: 0, rows: [job] };
    return { ok: true, status: 200, json: async () => body };
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(<QueryClientProvider client={client}><JobsView /></QueryClientProvider>);

  const status = await screen.findByLabelText(/Status for/);
  expect(screen.queryByRole("button", { name: /Save changes/ })).toBeNull();
  await userEvent.selectOptions(status, "applied");
  expect(await screen.findByText("Saved.")).toBeInTheDocument();
  expect(patches).toEqual([{ j1: { status: "applied" } }]);
  expect(container.querySelector("tr[data-status='applied']")).not.toBeNull();

  await userEvent.click(screen.getByRole("button", { name: "Hide filters" }));
  expect(screen.getByRole("button", { name: "Show filters" })).toHaveAttribute("aria-expanded", "false");
});
