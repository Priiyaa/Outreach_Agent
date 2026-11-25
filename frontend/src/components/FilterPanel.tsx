"use client";

import type { Meta } from "@/lib/api";
import type { Filters } from "@/lib/filters";

type ListKey = "experience" | "sponsorship" | "status";
type Props = { meta: Meta | undefined; filters: Filters; onChange: (next: Filters) => void };

function CheckGroup({
  legend,
  options,
  selected,
  onToggle,
}: {
  legend: string;
  options: [value: string, label: string][];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <fieldset className="space-y-1">
      <legend className="mb-1 text-sm font-semibold">{legend}</legend>
      {options.map(([value, label]) => (
        <label key={value} className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={selected.includes(value)} onChange={() => onToggle(value)} />
          {label}
        </label>
      ))}
    </fieldset>
  );
}

const input =
  "w-full rounded-md border border-zinc-300 bg-transparent px-2 py-1.5 text-sm dark:border-zinc-700";

export default function FilterPanel({ meta, filters, onChange }: Props) {
  const set = <K extends keyof Filters>(key: K, value: Filters[K]) => onChange({ ...filters, [key]: value });
  const same = (values: string[]): [string, string][] => values.map((v) => [v, v]);
  const all = (key: ListKey): string[] => (meta ? (key === "status" ? Object.keys(meta.status) : meta[key]) : []);
  // An empty list means "all" to the API, so show it as every box checked.
  const shown = (key: ListKey): string[] => (filters[key].length ? filters[key] : all(key));
  const toggle = (key: ListKey) => (value: string) => {
    const current = shown(key);
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
    if (next.length === 0) return; // unchecking the last box would mean "nothing", which has no use
    set(key, next.length === all(key).length ? [] : next);
  };

  return (
    <aside className="w-full shrink-0 space-y-5 md:w-64">
      <div className="space-y-2">
        <label className="flex items-center justify-between gap-2 text-sm font-semibold">
          Sort
          <select
            className={`${input} w-40`}
            value={filters.sort}
            onChange={(e) => set("sort", e.target.value as Filters["sort"])}
          >
            <option value="match">Best match for me</option>
            <option value="newest">Newest first</option>
          </select>
        </label>
        <label className="flex items-center justify-between gap-2 text-sm">
          Minimum match
          <select
            className={`${input} w-40`}
            value={filters.minScore}
            onChange={(e) => set("minScore", Number(e.target.value))}
          >
            <option value={0}>Any</option>
            <option value={60}>60+ (decent)</option>
            <option value={70}>70+ (strong)</option>
            <option value={80}>80+ (best)</option>
          </select>
        </label>
        <input
          className={input}
          placeholder="Search title or company"
          value={filters.search}
          onChange={(e) => set("search", e.target.value)}
        />
        <input
          className={input}
          placeholder="Location: seattle, chicago, remote"
          value={filters.location}
          onChange={(e) => set("location", e.target.value)}
        />
        <label className="flex items-center justify-between gap-2 text-sm">
          Posted in the last N days (0 = any)
          <input
            type="number"
            min={0}
            className={`${input} w-16`}
            value={filters.sinceDays}
            onChange={(e) => set("sinceDays", Math.max(0, Number(e.target.value) || 0))}
          />
        </label>
      </div>
      {meta && (
        <>
          <CheckGroup legend="Experience" options={same(meta.experience)} selected={shown("experience")} onToggle={toggle("experience")} />
          <CheckGroup legend="Sponsors visas?" options={same(meta.sponsorship)} selected={shown("sponsorship")} onToggle={toggle("sponsorship")} />
          <CheckGroup legend="Status" options={Object.entries(meta.status)} selected={shown("status")} onToggle={toggle("status")} />
        </>
      )}
      <div className="space-y-1 text-sm">
        {(
          [
            ["csOnly", "CS-related roles only"],
            ["usOnly", "US jobs only"],
            ["internships", "Include internships"],
            ["closed", "Include closed postings"],
            ["watched", "Only companies I applied to"],
            ["yc", "YC startups only"],
          ] as const
        ).map(([key, label]) => (
          <label key={key} className="flex items-center gap-2">
            <input type="checkbox" checked={filters[key]} onChange={(e) => set(key, e.target.checked)} />
            {label}
          </label>
        ))}
      </div>
    </aside>
  );
}
