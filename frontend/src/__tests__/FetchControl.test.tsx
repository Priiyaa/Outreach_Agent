import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import FetchControl from "@/components/FetchControl";

afterEach(() => vi.unstubAllGlobals());

it("shows the stage while running and refreshes jobs once results are ready, before the run ends", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () =>
      url.includes("/api/meta")
        ? { fetch_enabled: true }
        : { running: true, output: "", error: null, stage: "New jobs are on the board. Double-checking unclear roles (3/21)", results_ready: true },
  })));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}><FetchControl /></QueryClientProvider>);
  expect(await screen.findByRole("status")).toHaveTextContent("Double-checking unclear roles (3/21)");
  expect(screen.getByRole("button", { name: "Fetching…" })).toBeDisabled();
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["jobs"] });
});

it("never shows the fetch button when the host has fetching off, not even while that answer loads", async () => {
  const meta = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ fetch_enabled: false }) }));
  vi.stubGlobal("fetch", meta);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><FetchControl /></QueryClientProvider>);
  expect(screen.queryByRole("button")).toBeNull(); // first paint, before the API answers
  await vi.waitFor(() => expect(meta).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 0));
  expect(screen.queryByRole("button")).toBeNull();
});
