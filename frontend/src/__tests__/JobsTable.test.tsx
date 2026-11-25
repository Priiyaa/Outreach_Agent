import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import JobsTable from "@/components/JobsTable";
import type { Job, Meta } from "@/lib/api";

const meta: Meta = {
  writes_locked: false,
  fetch_enabled: true,
  experience: ["New grad", "Experienced", "Unclear"],
  sponsorship: ["Yes", "No", "Unknown"],
  status: { new: "New", saved: "Saved", applied: "Applied", skipped: "Skipped" },
};

const job: Job = {
  id: "j1", company: "Acme", title: "Software Engineer, New Grad", location: "Chicago, IL",
  cs_role_evidence: "title: Software", role_family: "", experience: "New grad",
  sponsorship: "Unknown", sponsorship_note: "", status: "new", url: "https://example.com/1",
  first_seen: "2026-10-15T18:34:49+00:00", match_score: null, match_reasons: "",
};

describe("JobsTable", () => {
  it("shows the job with a link that opens safely in a new tab", () => {
    render(<JobsTable rows={[job]} meta={meta} edits={{}} onSave={() => {}} onDraft={() => {}} />);
    const link = screen.getByRole("link", { name: job.title });
    expect(link).toHaveAttribute("href", job.url);
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("2026-10-15")).toHaveAttribute("title", "Tracker first saw it on 2026-10-15");
  });

  it("reports an edit with just the changed field", async () => {
    const onSave = vi.fn();
    render(<JobsTable rows={[job]} meta={meta} edits={{}} onSave={onSave} onDraft={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText(/Status for/), "applied");
    expect(onSave).toHaveBeenCalledWith("j1", { status: "applied" });
  });

  it("shows pending edits instead of the saved value", () => {
    render(<JobsTable rows={[job]} meta={meta} edits={{ j1: { sponsorship: "Yes" } }} onSave={() => {}} onDraft={() => {}} />);
    expect(screen.getByLabelText(/Sponsors visas for/)).toHaveValue("Yes");
  });

  it("shows the match score with its reasons, and a dash for jobs that are not a fit", () => {
    const scored = { ...job, id: "j2", match_score: 87, match_reasons: "AI/agentic role; skills: python, react" };
    render(<JobsTable rows={[scored, job]} meta={meta} edits={{}} onSave={() => {}} onDraft={() => {}} />);
    expect(screen.getByText("87")).toHaveAttribute("title", scored.match_reasons);
    expect(screen.getByText(scored.match_reasons)).toBeInTheDocument();
    expect(screen.getByTitle(/Not a fit/)).toHaveTextContent("-");
  });

  it("shows the posting date, with the date the tracker first saw it on hover", () => {
    render(<JobsTable rows={[{ ...job, posted_at: "2026-09-02" }]} meta={meta} edits={{}} onSave={() => {}} onDraft={() => {}} />);
    expect(screen.getByText("2026-09-02")).toHaveAttribute("title", "Tracker first saw it on 2026-10-15");
  });

  it("colours rows by status: applied green, skipped yellow, saved blue", () => {
    const rows = ["applied", "skipped", "saved", "new"].map((status, i) => ({ ...job, id: `s${i}`, status }));
    const { container } = render(<JobsTable rows={rows} meta={meta} edits={{ s3: { status: "applied" } }} onSave={() => {}} onDraft={() => {}} />);
    const cls = (status: string) => [...container.querySelectorAll(`tr[data-status="${status}"]`)].map((r) => r.className);
    expect(cls("applied")).toEqual([expect.stringContaining("bg-green-50"), expect.stringContaining("bg-green-50")]); // s3's pending edit counts
    expect(cls("skipped")[0]).toContain("bg-yellow-50");
    expect(cls("saved")[0]).toContain("bg-sky-50");
  });

  it("saves the note when you leave the box, not on every keystroke", async () => {
    const onSave = vi.fn();
    const onDraft = vi.fn();
    const { rerender } = render(<JobsTable rows={[job]} meta={meta} edits={{}} onSave={onSave} onDraft={onDraft} />);
    await userEvent.type(screen.getByLabelText(/Sponsorship note for/), "E");
    expect(onDraft).toHaveBeenCalledWith("j1", { sponsorship_note: "E" });
    expect(onSave).not.toHaveBeenCalled();
    rerender(<JobsTable rows={[job]} meta={meta} edits={{ j1: { sponsorship_note: "E-Verify" } }} onSave={onSave} onDraft={onDraft} />);
    await userEvent.keyboard("{Enter}");
    expect(onSave).toHaveBeenCalledWith("j1", { sponsorship_note: "E-Verify" });
  });
});
