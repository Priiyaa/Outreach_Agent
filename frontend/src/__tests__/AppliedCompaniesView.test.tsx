import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AppliedCompaniesView from "@/components/AppliedCompaniesView";

const companies = [
  { company_key: "zed", company: "Zed", boards: ["greenhouse:zed"], added_at: "2026-11-15T00:00:00", open_matches: 5, fresh_matches: 2 },
  { company_key: "homegrown", company: "Homegrown", boards: [], added_at: "2026-11-16T00:00:00", open_matches: 0, fresh_matches: 0 },
];

afterEach(() => vi.unstubAllGlobals());

it("lists applied companies with fresh matches and can stop checking one", async () => {
  const calls: { url: string; method?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, method: init?.method });
    return { ok: true, status: 200, json: async () => (init?.method === "DELETE" ? { saved: 1 } : companies) };
  }));
  render(<QueryClientProvider client={new QueryClient()}><AppliedCompaniesView /></QueryClientProvider>);
  expect(await screen.findByText("2 new matching postings this week at companies you applied to.")).toBeInTheDocument();
  expect(screen.getByText("Greenhouse")).toBeInTheDocument();
  expect(screen.getByText("Not automatically")).toBeInTheDocument();
  await userEvent.click(screen.getAllByRole("button", { name: "Stop checking" })[0]);
  expect(await screen.findByText("Stopped checking that company.")).toBeInTheDocument();
  expect(calls.find((c) => c.method === "DELETE")?.url).toMatch(/\/api\/watched\/zed$/);
});
