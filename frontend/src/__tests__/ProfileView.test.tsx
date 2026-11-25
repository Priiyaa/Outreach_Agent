import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProfileView from "@/components/ProfileView";

const state = {
  source: "file",
  known_skills: ["go", "python", "react"],
  role_families: ["ai", "software"],
  profile: {
    years_experience: 2,
    max_years_required: 3,
    needs_sponsorship: true,
    has_phd: false,
    preferred_locations: ["chicago", "remote"],
    role_weights: { ai: 1, software: 0.5 },
    skills: { python: 3 },
  },
};
const draft = { ...state.profile, years_experience: 4, skills: { react: 3, go: 1 } };

function setup() {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const body = url.endsWith("/api/profile/resume") ? draft : init?.method === "PUT" ? { scored: 120, strong: 9, ineligible: 5 } : state;
      return { ok: true, status: 200, json: async () => body };
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ProfileView />
    </QueryClientProvider>,
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("ProfileView", () => {
  it("fills the form from an uploaded resume and saves the reviewed profile", async () => {
    const calls = setup();
    expect(await screen.findByText("python")).toBeInTheDocument();

    const pdf = new File(["%PDF"], "resume.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Resume PDF"), pdf);
    expect(await screen.findByText(/2 skills, 4 year\(s\)/)).toBeInTheDocument();
    const upload = calls.find((c) => c.url.endsWith("/api/profile/resume"))!;
    expect(upload.init?.body).toBe(pdf);
    expect((upload.init?.headers as Record<string, string>)["Content-Type"]).toBe("application/pdf");

    await userEvent.click(screen.getByRole("button", { name: "Remove go" }));
    await userEvent.click(screen.getByRole("button", { name: "Save and re-rank" }));
    expect(await screen.findByText(/120 jobs fit your profile, 9 of them/)).toBeInTheDocument();
    const saved = JSON.parse(calls.find((c) => c.init?.method === "PUT")!.init!.body as string);
    expect(saved.skills).toEqual({ react: 3 });
    expect(saved.years_experience).toBe(4);
  });
});
