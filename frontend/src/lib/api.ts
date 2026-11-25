import type { components } from "./api-types";
import { getAccessCode } from "./auth";
import { type Filters, toParams } from "./filters";

type Schemas = components["schemas"];
export type Job = Schemas["Job"];
export type JobsPage = Schemas["JobsPage"];
export type JobEdit = Schemas["JobEdit"];
export type Meta = Schemas["Meta"];
export type FetchStatus = Schemas["FetchStatus"];
export type Profile = Schemas["Profile"];
export type ProfileState = Schemas["ProfileState"];
export type ProfileSaved = Schemas["ProfileSaved"];
export type WatchedCompany = Schemas["WatchedCompany"];

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const code = getAccessCode();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(code ? { Authorization: `Bearer ${code}` } : {}), ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : res.statusText;
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

const send = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) });

export const api = {
  meta: () => request<Meta>("/api/meta"),
  checkAccess: (code: string) => request<{ ok: boolean }>("/api/auth/check", { headers: { Authorization: `Bearer ${code}` } }),
  jobs: (filters: Filters, limit: number, offset: number) =>
    request<JobsPage>(`/api/jobs?${toParams(filters, { limit, offset })}`),
  csvUrl: (filters: Filters) => `${API_URL}/api/jobs.csv?${toParams(filters)}`,
  editJobs: (edits: Record<string, JobEdit>) => request<{ saved: number }>("/api/jobs", send("PATCH", edits)),
  bulkSponsorship: (filters: Filters, value: string) =>
    request<{ saved: number }>(`/api/jobs/bulk-sponsorship?${toParams(filters)}`, send("POST", { value })),
  startFetch: () => request<FetchStatus>("/api/fetch", { method: "POST" }),
  fetchStatus: () => request<FetchStatus>("/api/fetch"),
  profile: () => request<ProfileState>("/api/profile"),
  watched: () => request<WatchedCompany[]>("/api/watched"),
  labelJob: (id: string, label: "good" | "bad" | null) =>
    request<{ good: number; bad: number }>(`/api/jobs/${encodeURIComponent(id)}/label`, send("PUT", { label })),
  unwatch: (companyKey: string) =>
    request<{ saved: number }>(`/api/watched/${encodeURIComponent(companyKey)}`, { method: "DELETE" }),
  /** Sends the PDF's bytes; the server returns a draft profile and keeps nothing. */
  readResume: (file: File) =>
    request<Profile>("/api/profile/resume", { method: "POST", body: file, headers: { "Content-Type": "application/pdf" } }),
  saveProfile: (profile: Profile) => request<ProfileSaved>("/api/profile", send("PUT", profile)),
};
