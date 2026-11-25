import { DEFAULT_FILTERS, toParams } from "@/lib/filters";

describe("toParams", () => {
  it("repeats list params and sends booleans as strings", () => {
    const p = new URLSearchParams(toParams({ ...DEFAULT_FILTERS, experience: ["New grad", "Experienced"], sponsorship: ["Yes"] }));
    expect(p.getAll("experience")).toEqual(["New grad", "Experienced"]);
    expect(p.getAll("sponsorship")).toEqual(["Yes"]);
    expect(p.get("cs_only")).toBe("true");
    expect(p.get("internships")).toBe("false");
  });

  it("leaves out empty lists (meaning all) and blank text", () => {
    const p = new URLSearchParams(toParams({ ...DEFAULT_FILTERS, sponsorship: [], search: "  ", location: "" }));
    expect(p.has("sponsorship")).toBe(false);
    expect(p.has("search")).toBe(false);
    expect(p.has("location")).toBe(false);
    expect(p.has("since_days")).toBe(false);
  });

  it("trims text, sends since_days only when set, and adds paging last", () => {
    const p = new URLSearchParams(toParams({ ...DEFAULT_FILTERS, search: " ml ", sinceDays: 7 }, { limit: 100, offset: 200 }));
    expect(p.get("search")).toBe("ml");
    expect(p.get("since_days")).toBe("7");
    expect([p.get("limit"), p.get("offset")]).toEqual(["100", "200"]);
  });

  it("sorts by best match by default and sends min_score only when set", () => {
    const p = new URLSearchParams(toParams(DEFAULT_FILTERS));
    expect(p.get("sort")).toBe("match");
    expect(p.has("min_score")).toBe(false);
    expect(new URLSearchParams(toParams({ ...DEFAULT_FILTERS, sort: "newest", minScore: 70 })).get("min_score")).toBe("70");
  });
});
