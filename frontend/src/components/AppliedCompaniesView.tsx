"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";

const SOURCE_NAMES: Record<string, string> = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", workday: "Workday" };

/** Companies you applied to. Their careers pages are checked on every fetch; new matching postings are counted here. */
export default function AppliedCompaniesView() {
  const queryClient = useQueryClient();
  const companies = useQuery({ queryKey: ["watched"], queryFn: api.watched });
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const stop = useMutation({
    mutationFn: api.unwatch,
    onSuccess: () => {
      setNotice({ ok: true, text: "Stopped checking that company." });
      queryClient.invalidateQueries({ queryKey: ["watched"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => setNotice({ ok: false, text: `Not changed: ${err.message}` }),
  });

  const rows = companies.data ?? [];
  const fresh = rows.reduce((n, c) => n + c.fresh_matches, 0);

  return (
    <div className="max-w-4xl space-y-4">
      <p className="text-sm text-zinc-500">
        Marking a job <strong>Applied</strong> adds its company here. Every fetch checks these companies&rsquo; careers
        pages for new postings, and the Jobs page tags their roles &ldquo;Applied here&rdquo; (filter: &ldquo;Only
        companies I applied to&rdquo;).
      </p>
      {rows.length > 0 && (
        <p className="text-sm font-medium">
          {fresh > 0
            ? `${fresh} new matching posting${fresh === 1 ? "" : "s"} this week at companies you applied to.`
            : "No new matching postings this week at these companies."}
        </p>
      )}
      {notice && (
        <p role="status" className={`rounded-md px-3 py-2 text-sm ${notice.ok ? "bg-green-100 dark:bg-green-950/40" : "bg-red-100 dark:bg-red-950/40"}`}>
          {notice.text}
        </p>
      )}
      {companies.isError && <p role="alert">Could not load companies: {companies.error.message}</p>}
      {companies.data && rows.length === 0 && (
        <p className="py-8 text-center text-zinc-500">No companies yet. Mark a job Applied on the Jobs page to add its company.</p>
      )}
      {rows.length > 0 && (
        <div className="overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-zinc-100 text-xs uppercase tracking-wide text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
              <tr>
                {["Company", "Careers page checked", "Open matches", "New this week", "Since", ""].map((h) => (
                  <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
              {rows.map((c) => (
                <tr key={c.company_key}>
                  <td className="px-3 py-2 font-medium">{c.company}</td>
                  <td className="px-3 py-2">
                    {c.boards.length ? (
                      c.boards.map((b) => SOURCE_NAMES[b.split(":")[0]] ?? b.split(":")[0]).join(", ")
                    ) : (
                      <span className="text-zinc-500" title="Its careers site isn't one the app can read (Greenhouse, Lever, Ashby or Workday).">
                        Not automatically
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 tabular-nums">{c.open_matches}</td>
                  <td className="px-3 py-2 tabular-nums">
                    {c.fresh_matches > 0 ? (
                      <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-semibold text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300">
                        {c.fresh_matches} new
                      </span>
                    ) : (
                      "0"
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-zinc-500">{c.added_at.slice(0, 10)}</td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => stop.mutate(c.company_key)}
                      disabled={stop.isPending}
                      className="text-xs text-zinc-500 underline hover:text-red-600 disabled:opacity-50"
                    >
                      Stop checking
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
