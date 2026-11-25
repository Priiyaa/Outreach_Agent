"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useSyncExternalStore } from "react";
import { api, type Job, type JobEdit, type JobsPage } from "@/lib/api";
import { DEFAULT_FILTERS, type Filters } from "@/lib/filters";
import { useDebounced } from "@/lib/useDebounced";
import FilterPanel from "./FilterPanel";
import JobsTable from "./JobsTable";

const PAGE_SIZE = 100;
const FILTERS_KEY = "show-filters";

// Whether the filter sidebar is open, remembered in this browser (open when storage is blocked).
const filterListeners = new Set<() => void>();
let memoryShown: boolean | null = null; // used when storage is blocked
function filtersShown(): boolean {
  if (memoryShown !== null) return memoryShown;
  try {
    return window.localStorage.getItem(FILTERS_KEY) !== "0";
  } catch {
    return true;
  }
}
function setFiltersShown(shown: boolean): void {
  try {
    window.localStorage.setItem(FILTERS_KEY, shown ? "1" : "0");
  } catch {
    /* not remembered, but still toggled below */
  }
  memoryShown = shown;
  filterListeners.forEach((notify) => notify());
}
function subscribeFilters(callback: () => void): () => void {
  filterListeners.add(callback);
  return () => filterListeners.delete(callback);
}

function Stat({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="rounded-lg border border-zinc-200 px-4 py-2 dark:border-zinc-800">
      <div className="text-xl font-semibold">{value?.toLocaleString() ?? "–"}</div>
      <div className="text-xs text-zinc-500">{label}</div>
    </div>
  );
}

export default function JobsView() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [page, setPage] = useState(0);
  const [edits, setEdits] = useState<Record<string, JobEdit>>({});
  const [bulkValue, setBulkValue] = useState("Yes");
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  // Text boxes are debounced so typing does not send a request per keystroke.
  const debounced = useDebounced(filters);
  const meta = useQuery({
    queryKey: ["meta"],
    queryFn: api.meta,
    staleTime: Infinity,
  });
  const jobs = useQuery({
    queryKey: ["jobs", debounced, page],
    queryFn: () => api.jobs(debounced, PAGE_SIZE, page * PAGE_SIZE),
    placeholderData: keepPreviousData,
  });

  // Edits save as soon as they are made. The row keeps the new value on screen while the request runs.
  const save = useMutation({
    mutationFn: ({ id, change }: { id: string; change: JobEdit }) => api.editJobs({ [id]: change }),
    onSuccess: (_res, { id, change }) => {
      // Update the rows already on screen instead of refetching, so a row doesn't jump or vanish under the cursor.
      queryClient.setQueriesData<JobsPage>(
        { queryKey: ["jobs"] },
        (old) =>
          old && {
            ...old,
            rows: old.rows.map((r) => (r.id === id ? ({ ...r, ...change } as Job) : r)),
          },
      );
      setEdits((prev) => dropSaved(prev, id, change));
      setNotice({ ok: true, text: "Saved." });
    },
    onError: (err, { id, change }) => {
      setEdits((prev) => dropSaved(prev, id, change));
      setNotice({ ok: false, text: `Not saved: ${err.message}` });
    },
  });
  const bulk = useMutation({
    mutationFn: () => api.bulkSponsorship(debounced, bulkValue),
    onSuccess: (res) => {
      setNotice({
        ok: true,
        text: `Set Sponsors? to ${bulkValue} for ${res.saved} jobs.`,
      });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => setNotice({ ok: false, text: err.message }),
  });

  const total = jobs.data?.stats.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const showFilters = useSyncExternalStore(subscribeFilters, filtersShown, () => true);

  const changeFilters = (next: Filters) => {
    setFilters(next);
    setPage(0);
  };
  const draft = (id: string, change: JobEdit) => setEdits((prev) => ({ ...prev, [id]: { ...prev[id], ...change } }));
  const label = useMutation({
    mutationFn: ({ id, value }: { id: string; value: "good" | "bad" | null }) => api.labelJob(id, value),
    onSuccess: (counts, { id, value }) => {
      queryClient.setQueriesData<JobsPage>(
        { queryKey: ["jobs"] },
        (old) => old && { ...old, rows: old.rows.map((r) => (r.id === id ? { ...r, match_label: value } : r)) },
      );
      const total = counts.good + counts.bad;
      const next =
        total < 20
          ? ` About ${20 - total} more (at least 5 of each) and the ranking can be tuned to you.`
          : " Enough to tune: run `python -m app.cli tune`.";
      setNotice({ ok: true, text: `Labels: ${counts.good} good, ${counts.bad} bad.${next}` });
    },
    onError: (err) => setNotice({ ok: false, text: `Label not saved: ${err.message}` }),
  });
  const saveNow = (id: string, change: JobEdit) => {
    draft(id, change);
    save.mutate({ id, change });
  };

  return (
    <div className="space-y-3">
      <button
        onClick={() => setFiltersShown(!showFilters)}
        aria-expanded={showFilters}
        aria-controls="filter-panel"
        aria-label={showFilters ? "Hide filters" : "Show filters"}
        title={showFilters ? "Hide filters" : "Show filters"}
        className="rounded-md p-1.5 text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-900"
      >
        <svg
          width="22"
          height="22"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
      <div className="flex flex-col gap-6 md:flex-row">
        {showFilters && (
          <div id="filter-panel" className="contents">
            <FilterPanel meta={meta.data} filters={filters} onChange={changeFilters} />
          </div>
        )}
        <section className="min-w-0 flex-1 space-y-4">
          <div className="flex flex-wrap gap-3">
            <Stat label="Jobs shown" value={jobs.data?.stats.total} />
            <Stat label="New grad" value={jobs.data?.stats.new_grad} />
            <Stat label="Sponsor: Yes" value={jobs.data?.stats.sponsor_yes} />
            <Stat label="Not yet applied" value={jobs.data?.stats.not_applied} />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <a
              href={api.csvUrl(debounced)}
              className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              Download filtered CSV
            </a>
            <span className="flex-1" />
            <select
              aria-label="Value for bulk sponsorship"
              value={bulkValue}
              onChange={(e) => setBulkValue(e.target.value)}
              className="rounded border border-zinc-300 bg-transparent px-1.5 py-1 text-sm dark:border-zinc-700"
            >
              {(meta.data?.sponsorship ?? ["Yes", "No", "Unknown"]).map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
            <button
              onClick={() => {
                if (
                  window.confirm(
                    `Set Sponsors? to '${bulkValue}' for all ${total.toLocaleString()} matching jobs? This locks them as manual.`,
                  )
                )
                  bulk.mutate();
              }}
              disabled={total === 0 || bulk.isPending}
              className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              Set Sponsors? for all matching
            </button>
          </div>

          {notice && (
            <p
              role="status"
              className={`rounded-md px-3 py-2 text-sm ${notice.ok ? "bg-green-100 dark:bg-green-950/40" : "bg-red-100 dark:bg-red-950/40"}`}
            >
              {notice.text}
            </p>
          )}
          {jobs.isError && (
            <p role="alert" className="rounded-md bg-red-100 px-3 py-2 text-sm dark:bg-red-950/40">
              Could not load jobs: {jobs.error.message}. Is the API running?
            </p>
          )}

          {jobs.data && jobs.data.rows.length === 0 ? (
            <p className="py-10 text-center text-zinc-500">
              No jobs match. Loosen the filters, or fetch new jobs if the database is empty.
            </p>
          ) : (
            <div className={jobs.isPlaceholderData ? "opacity-60 transition-opacity" : undefined}>
              <JobsTable
                rows={jobs.data?.rows ?? []}
                meta={meta.data}
                edits={edits}
                onSave={saveNow}
                onDraft={draft}
                onLabel={(id, value) => label.mutate({ id, value })}
              />
            </div>
          )}

          <nav className="flex items-center justify-between text-sm" aria-label="Pagination">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="rounded-md border border-zinc-300 px-3 py-1 disabled:opacity-40 dark:border-zinc-700"
            >
              Previous
            </button>
            <span className="text-zinc-500">
              Page {page + 1} of {pages.toLocaleString()}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(pages - 1, p + 1))}
              disabled={page >= pages - 1}
              className="rounded-md border border-zinc-300 px-3 py-1 disabled:opacity-40 dark:border-zinc-700"
            >
              Next
            </button>
          </nav>
        </section>
      </div>
    </div>
  );
}

/** Edits left once `change` is saved (or failed): a field the person has changed again since stays. */
function dropSaved(edits: Record<string, JobEdit>, id: string, change: JobEdit): Record<string, JobEdit> {
  const left = { ...edits[id] } as Record<string, unknown>;
  for (const [key, value] of Object.entries(change)) if (left[key] === value) delete left[key];
  const next = { ...edits };
  if (Object.keys(left).length) next[id] = left as JobEdit;
  else delete next[id];
  return next;
}
