"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";

const GUESSED = new Set(["default", "unknown", "claude", "openings", "unsized"]);

export default function CompaniesView() {
  const queryClient = useQueryClient();
  const [onlyGuessed, setOnlyGuessed] = useState(false);
  const [edits, setEdits] = useState<Record<string, { size: string }>>({});
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);

  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const companies = useQuery({ queryKey: ["companies"], queryFn: api.companies });
  const save = useMutation({
    mutationFn: () => api.editCompanies(edits),
    onSuccess: (res) => {
      setNotice({ ok: true, text: `Saved size for ${res.saved} company(ies). Their jobs moved bucket.` });
      setEdits({});
      queryClient.invalidateQueries({ queryKey: ["companies"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => setNotice({ ok: false, text: `Nothing saved: ${err.message}` }),
  });

  const rows = (companies.data ?? []).filter((c) => !onlyGuessed || GUESSED.has(c.size_source));
  const pending = Object.keys(edits).length;

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500">
        Sizes come from the known-company list, headcount in job text, then Claude, then default to Startup/Small. Change one
        here and it sticks; its jobs move bucket immediately.
      </p>
      <div className="flex items-center gap-4">
        <button
          onClick={() => save.mutate()}
          disabled={pending === 0 || save.isPending}
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {pending ? `Save company sizes (${pending})` : "Save company sizes"}
        </button>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={onlyGuessed} onChange={(e) => setOnlyGuessed(e.target.checked)} />
          Only show defaults and guesses
        </label>
      </div>
      {notice && (
        <p role="status" className={`rounded-md px-3 py-2 text-sm ${notice.ok ? "bg-green-100 dark:bg-green-950/40" : "bg-red-100 dark:bg-red-950/40"}`}>
          {notice.text}
        </p>
      )}
      {companies.isError && <p role="alert">Could not load companies: {companies.error.message}</p>}
      <div className="max-h-[70vh] overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-zinc-100 text-xs uppercase tracking-wide text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
            <tr>
              {["Company", "Size", "Source", "Employees", "Open jobs"].map((h) => (
                <th key={h} className="px-3 py-2 font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {rows.map((c) => (
              <tr key={c.key} className={edits[c.key] ? "bg-blue-50 dark:bg-blue-950/30" : undefined}>
                <td className="px-3 py-2 font-medium">{c.company}</td>
                <td className="px-3 py-2">
                  <select
                    aria-label={`Size of ${c.company}`}
                    value={edits[c.key]?.size ?? c.size}
                    onChange={(e) => setEdits((prev) => ({ ...prev, [c.key]: { size: e.target.value } }))}
                    className="rounded border border-zinc-300 bg-transparent px-1.5 py-1 dark:border-zinc-700"
                  >
                    {(meta.data?.size ?? [c.size]).map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </td>
                <td className="px-3 py-2 text-zinc-500">{c.size_source}</td>
                <td className="px-3 py-2">{c.employees ?? ""}</td>
                <td className="px-3 py-2">{c.open_jobs}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
