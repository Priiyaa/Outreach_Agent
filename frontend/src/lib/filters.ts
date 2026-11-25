export type Sort = "match" | "newest";

export type Filters = {
  sort: Sort;
  minScore: number;
  experience: string[];
  sponsorship: string[];
  status: string[];
  csOnly: boolean;
  usOnly: boolean;
  internships: boolean;
  closed: boolean;
  watched: boolean;
  yc: boolean;
  search: string;
  location: string;
  sinceDays: number;
};

// An empty list means "all" to the API. Best match first: the score already hides jobs too senior for the profile,
// so experience starts open; status starts narrowed to what you would act on.
export const DEFAULT_FILTERS: Filters = {
  sort: "match",
  minScore: 0,
  experience: [],
  sponsorship: [],
  status: ["new", "saved", "applied"],
  csOnly: true,
  usOnly: true,
  internships: false,
  closed: false,
  watched: false,
  yc: false,
  search: "",
  location: "",
  sinceDays: 0,
};

/** Query string for the API: repeatable params for lists, the rest as single values. */
export function toParams(f: Filters, paging?: { limit: number; offset: number }): string {
  const p = new URLSearchParams();
  for (const name of ["experience", "sponsorship", "status"] as const) {
    for (const value of f[name]) p.append(name, value);
  }
  p.set("cs_only", String(f.csOnly));
  p.set("us_only", String(f.usOnly));
  p.set("internships", String(f.internships));
  p.set("closed", String(f.closed));
  if (f.watched) p.set("watched", "true");
  if (f.yc) p.set("yc", "true");
  if (f.search.trim()) p.set("search", f.search.trim());
  if (f.location.trim()) p.set("location", f.location.trim());
  if (f.sinceDays > 0) p.set("since_days", String(f.sinceDays));
  p.set("sort", f.sort);
  if (f.minScore > 0) p.set("min_score", String(f.minScore));
  if (paging) {
    p.set("limit", String(paging.limit));
    p.set("offset", String(paging.offset));
  }
  return p.toString();
}
