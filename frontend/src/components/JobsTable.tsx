"use client";

import type { Job, JobEdit, Meta } from "@/lib/api";

type Props = {
  rows: Job[];
  meta: Meta | undefined;
  /** Values typed or picked but not yet confirmed by the server, shown over the saved ones. */
  edits: Record<string, JobEdit>;
  /** Save this change now (dropdowns, and the note when you leave the box). */
  onSave: (id: string, change: JobEdit) => void;
  /** The note while you type; saved on blur or Enter. */
  onDraft: (id: string, change: JobEdit) => void;
  /** Mark the match good or bad for you (null clears it); used to tune the ranking. */
  onLabel?: (id: string, label: "good" | "bad" | null) => void;
};

const labelButton = (on: boolean, tone: string) =>
  `rounded px-1 text-sm leading-none ${on ? tone : "opacity-40 grayscale hover:opacity-100 hover:grayscale-0"}`;

const cell = "px-3 py-2 align-top";

/** Row colour by status, so applied / skipped / saved jobs stand out at a glance. */
export const STATUS_ROW: Record<string, string> = {
  applied: "bg-green-50 dark:bg-green-950/30",
  skipped: "bg-yellow-50 dark:bg-yellow-950/30",
  saved: "bg-sky-50 dark:bg-sky-950/30",
};

function scoreClass(score: number): string {
  if (score >= 80) return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300";
  if (score >= 60) return "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300";
  return "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400";
}
const control = "rounded border border-zinc-300 bg-transparent px-1.5 py-1 text-sm dark:border-zinc-700";

export default function JobsTable({ rows, meta, edits, onSave, onDraft, onLabel }: Props) {
  return (
    <div className="overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full min-w-[1000px] text-left text-sm">
        <thead className="sticky top-0 bg-zinc-100 text-xs uppercase tracking-wide text-zinc-600 dark:bg-zinc-900 dark:text-zinc-400">
          <tr>
            {["Match", "Company and title", "Location", "Role", "Experience", "Sponsors?", "Sponsorship note", "Status", "Posted"].map((h) => (
              <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {rows.map((job) => {
            const edit = edits[job.id] ?? {};
            const status = edit.status ?? job.status;
            const note = edit.sponsorship_note ?? job.sponsorship_note;
            const posted = (job.posted_at || job.first_seen).slice(0, 10);
            return (
              <tr key={job.id} data-status={status} className={STATUS_ROW[status]}>
                <td className={cell}>
                  {job.match_score == null ? (
                    <span className="text-zinc-400" title="Not a fit for your profile (too senior, no sponsorship ...)">-</span>
                  ) : (
                    <div className="flex flex-col items-start gap-1">
                      <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${scoreClass(job.match_score)}`} title={job.match_reasons}>
                        {job.match_score}
                      </span>
                      {onLabel && (
                        <span className="flex gap-0.5">
                          <button
                            aria-label={`Good match: ${job.title}`}
                            aria-pressed={job.match_label === "good"}
                            title="A good match for me"
                            className={labelButton(job.match_label === "good", "bg-emerald-100 dark:bg-emerald-900/40")}
                            onClick={() => onLabel(job.id, job.match_label === "good" ? null : "good")}
                          >
                            👍
                          </button>
                          <button
                            aria-label={`Bad match: ${job.title}`}
                            aria-pressed={job.match_label === "bad"}
                            title="Not a good match for me"
                            className={labelButton(job.match_label === "bad", "bg-red-100 dark:bg-red-900/40")}
                            onClick={() => onLabel(job.id, job.match_label === "bad" ? null : "bad")}
                          >
                            👎
                          </button>
                        </span>
                      )}
                    </div>
                  )}
                </td>
                <td className={`${cell} min-w-[280px]`}>
                  <div className="flex items-center gap-2 font-semibold">
                    {job.company}
                    {job.yc_batch && (
                      <span
                        className="rounded bg-orange-100 px-1.5 py-0.5 text-[11px] font-medium text-orange-800 dark:bg-orange-900/40 dark:text-orange-300"
                        title={`Y Combinator company, batch ${job.yc_batch}`}
                      >
                        YC {job.yc_batch}
                      </span>
                    )}
                    {job.watched && (
                      <span
                        className="rounded bg-violet-100 px-1.5 py-0.5 text-[11px] font-medium text-violet-800 dark:bg-violet-900/40 dark:text-violet-300"
                        title="You applied here before. This company's careers page is checked on every fetch."
                      >
                        Applied here
                      </span>
                    )}
                  </div>
                  <a href={job.url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline dark:text-blue-400">
                    {job.title}
                  </a>
                  {job.match_reasons && <p className="mt-0.5 text-xs text-zinc-500">{job.match_reasons}</p>}
                </td>
                <td className={cell}>{job.location || "-"}</td>
                <td className={cell} title={job.cs_role_evidence}>
                  {job.role_family || <span className="text-zinc-400">rules</span>}
                </td>
                <td className={`${cell} whitespace-nowrap`}>{job.experience}</td>
                <td className={cell}>
                  <select
                    aria-label={`Sponsors visas for ${job.title}`}
                    className={control}
                    value={edit.sponsorship ?? job.sponsorship}
                    onChange={(e) => onSave(job.id, { sponsorship: e.target.value })}
                  >
                    {(meta?.sponsorship ?? [job.sponsorship]).map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </td>
                <td className={cell}>
                  <input
                    aria-label={`Sponsorship note for ${job.title}`}
                    className={`${control} w-44`}
                    value={note}
                    onChange={(e) => onDraft(job.id, { sponsorship_note: e.target.value })}
                    onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
                    onBlur={() => note !== job.sponsorship_note && onSave(job.id, { sponsorship_note: note })}
                  />
                </td>
                <td className={cell}>
                  <select
                    aria-label={`Status for ${job.title}`}
                    className={control}
                    value={status}
                    onChange={(e) => onSave(job.id, { status: e.target.value })}
                  >
                    {Object.entries(meta?.status ?? { [job.status]: job.status }).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </td>
                <td className={`${cell} whitespace-nowrap text-zinc-500`} title={`Tracker first saw it on ${job.first_seen.slice(0, 10)}`}>
                  {posted}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
