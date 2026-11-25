import { api, ApiError } from "@/lib/api";
import { setAccessCode } from "@/lib/auth";
import { DEFAULT_FILTERS } from "@/lib/filters";

const reply = (status: number, body: unknown) =>
  vi.fn().mockResolvedValue({ ok: status < 400, status, statusText: "err", json: async () => body });

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessCode(null);
});

describe("api client", () => {
  it("surfaces the server's detail message as an ApiError", async () => {
    vi.stubGlobal("fetch", reply(422, { detail: "invalid status: 'nope'" }));
    await expect(api.editJobs({ a: { status: "nope" } })).rejects.toMatchObject({
      name: "Error",
      status: 422,
      message: "invalid status: 'nope'",
    });
    await expect(api.editJobs({})).rejects.toBeInstanceOf(ApiError);
  });

  it("sends edits as a PATCH with a JSON body", async () => {
    const fetchMock = reply(200, { saved: 1 });
    vi.stubGlobal("fetch", fetchMock);
    await expect(api.editJobs({ j1: { status: "applied" } })).resolves.toEqual({ saved: 1 });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/api\/jobs$/);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ j1: { status: "applied" } });
  });

  it("builds the jobs URL from filters and paging", async () => {
    const fetchMock = reply(200, { rows: [], stats: {} });
    vi.stubGlobal("fetch", fetchMock);
    await api.jobs({ ...DEFAULT_FILTERS, search: "ml" }, 100, 100);
    const url = new URL(fetchMock.mock.calls[0][0]);
    expect(url.pathname).toBe("/api/jobs");
    expect(url.searchParams.get("search")).toBe("ml");
    expect(url.searchParams.get("offset")).toBe("100");
  });

  it("sends the stored access code, and nothing when there is none", async () => {
    const fetchMock = reply(200, { ok: true });
    vi.stubGlobal("fetch", fetchMock);
    await api.meta();
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBeUndefined();
    setAccessCode("s3cret");
    await api.meta();
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe("Bearer s3cret");
  });

  it("checks a typed code without storing it first", async () => {
    const fetchMock = reply(200, { ok: true });
    vi.stubGlobal("fetch", fetchMock);
    await api.checkAccess("typed");
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer typed");
  });
});
