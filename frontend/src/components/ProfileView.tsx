"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api, type Profile } from "@/lib/api";

const ROLE_LABELS: Record<string, string> = {
  ai: "AI / agentic / LLM",
  software: "Software (SWE, full-stack, backend, frontend)",
  ml: "Machine learning",
  research: "Research engineer / scientist",
  data: "Data engineer / scientist",
  other: "Other tech (DevOps, SRE, security, QA ...)",
};
const SKILL_LEVELS: Record<number, string> = { 1: "Nice to have", 2: "Strong", 3: "Core" };
const SOURCE_LABELS: Record<string, string> = {
  board: "Saved here",
  file: "From the config file (PROFILE_YAML or config/profile.yaml)",
  none: "No profile yet. Upload your resume to start.",
};

type FullProfile = Required<Profile>;

const EMPTY: FullProfile = {
  years_experience: 0,
  max_years_required: 2,
  needs_sponsorship: true,
  has_phd: false,
  preferred_locations: ["remote"],
  role_weights: { ai: 1, software: 1, ml: 0.8, research: 0.5, data: 0.5, other: 0.3 },
  skills: {},
};

const input = "rounded border border-zinc-300 bg-transparent px-2 py-1 text-sm dark:border-zinc-700";

export default function ProfileView() {
  const queryClient = useQueryClient();
  const state = useQuery({ queryKey: ["profile"], queryFn: api.profile });
  const [draft, setDraft] = useState<Profile | null>(null);
  const [locations, setLocations] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const saved = state.data?.profile ?? null;
  const profile: FullProfile = { ...EMPTY, ...(draft ?? saved ?? {}) } as FullProfile;
  const dirty = draft !== null;

  const edit = (changes: Partial<Profile>) => setDraft({ ...profile, ...changes });

  const upload = useMutation({
    mutationFn: api.readResume,
    onSuccess: (fromResume) => {
      setDraft(fromResume);
      setLocations(null);
      const n = Object.keys(fromResume.skills ?? {}).length;
      setNotice({
        ok: true,
        text: `Read your resume: ${n} skills, ${fromResume.years_experience} year(s) of experience. Check them below, then save. The file itself wasn't kept.`,
      });
    },
    onError: (err) => setNotice({ ok: false, text: `Could not read the resume: ${err.message}` }),
    onSettled: () => {
      if (fileInput.current) fileInput.current.value = "";
    },
  });

  const save = useMutation({
    mutationFn: () => api.saveProfile(profile),
    onSuccess: (res) => {
      setDraft(null);
      setLocations(null);
      setNotice({
        ok: true,
        text: `Saved. ${res.scored.toLocaleString()} jobs fit your profile, ${res.strong.toLocaleString()} of them score 70 or more. "Best match" on the Jobs page is updated.`,
      });
      queryClient.invalidateQueries({ queryKey: ["profile"] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => setNotice({ ok: false, text: `Nothing saved: ${err.message}` }),
  });

  const skills = Object.entries(profile.skills).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const unused = (state.data?.known_skills ?? []).filter((s) => !(s in profile.skills));
  const families = state.data?.role_families ?? Object.keys(ROLE_LABELS);

  return (
    <div className="max-w-3xl space-y-6">
      <section className="space-y-2">
        <p className="text-sm text-zinc-500">
          &ldquo;Best match&rdquo; on the Jobs page ranks every job against this profile. Upload your resume to fill it in, adjust
          anything it got wrong, then save to re-rank.
        </p>
        {state.data && <p className="text-sm">Current profile: {SOURCE_LABELS[state.data.source] ?? state.data.source}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,.pdf"
            aria-label="Resume PDF"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload.mutate(file);
            }}
          />
          <button
            onClick={() => fileInput.current?.click()}
            disabled={upload.isPending}
            className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
          >
            {upload.isPending ? "Reading resume…" : "Upload resume (PDF)"}
          </button>
          <button
            onClick={() => save.mutate()}
            disabled={(!dirty && state.data?.source === "board") || save.isPending}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {save.isPending ? "Re-ranking jobs (about 10 s)…" : "Save and re-rank"}
          </button>
          {dirty && !save.isPending && (
            <button
              onClick={() => {
                setDraft(null);
                setLocations(null);
                setNotice(null);
              }}
              className="text-sm text-zinc-500 underline hover:text-foreground"
            >
              Discard changes
            </button>
          )}
        </div>
        {notice && (
          <p role="status" className={`rounded-md px-3 py-2 text-sm ${notice.ok ? "bg-green-100 dark:bg-green-950/40" : "bg-red-100 dark:bg-red-950/40"}`}>
            {notice.text}
          </p>
        )}
        {state.isError && <p role="alert">Could not load the profile: {state.error.message}</p>}
      </section>

      <section className="space-y-3">
        <h2 className="font-semibold">Eligibility</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex items-center justify-between gap-3 text-sm">
            Years of full-time experience
            <input
              type="number" min={0} max={40} value={profile.years_experience} className={`${input} w-20`}
              onChange={(e) => edit({ years_experience: Math.max(0, Number(e.target.value) || 0) })}
            />
          </label>
          <label className="flex items-center justify-between gap-3 text-sm">
            Hide jobs asking for more than (years)
            <input
              type="number" min={0} max={40} value={profile.max_years_required} className={`${input} w-20`}
              onChange={(e) => edit({ max_years_required: Math.max(0, Number(e.target.value) || 0) })}
            />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={profile.needs_sponsorship} onChange={(e) => edit({ needs_sponsorship: e.target.checked })} />
            I need visa sponsorship (hides no-sponsor, clearance and citizens-only jobs)
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={profile.has_phd} onChange={(e) => edit({ has_phd: e.target.checked })} />
            I have a PhD
          </label>
        </div>
        <label className="block space-y-1 text-sm">
          <span>Preferred locations (comma separated; these rank a little higher, the rest of the US still counts)</span>
          <input
            value={locations ?? profile.preferred_locations.join(", ")}
            className={`${input} w-full`}
            onChange={(e) => {
              setLocations(e.target.value);
              edit({ preferred_locations: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) });
            }}
          />
        </label>
      </section>

      <section className="space-y-3">
        <h2 className="font-semibold">Roles you want</h2>
        <div className="space-y-2">
          {families.map((f) => {
            const value = profile.role_weights[f] ?? 0;
            return (
              <label key={f} className="flex items-center gap-3 text-sm">
                <span className="w-72">{ROLE_LABELS[f] ?? f}</span>
                <input
                  type="range" min={0} max={1} step={0.05} value={value} aria-label={`Weight for ${ROLE_LABELS[f] ?? f}`}
                  className="flex-1"
                  onChange={(e) => edit({ role_weights: { ...profile.role_weights, [f]: Number(e.target.value) } })}
                />
                <span className="w-10 text-right tabular-nums">{Math.round(value * 100)}%</span>
              </label>
            );
          })}
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="font-semibold">Skills ({skills.length})</h2>
        <p className="text-sm text-zinc-500">Jobs whose description names more of your core skills rank higher.</p>
        <ul className="flex flex-wrap gap-2">
          {skills.map(([name, level]) => (
            <li key={name} className="flex items-center gap-1 rounded-full border border-zinc-300 py-0.5 pl-3 pr-1 text-sm dark:border-zinc-700">
              {name}
              <select
                aria-label={`Level of ${name}`}
                value={level}
                className="rounded bg-transparent text-xs text-zinc-500"
                onChange={(e) => edit({ skills: { ...profile.skills, [name]: Number(e.target.value) } })}
              >
                {[3, 2, 1].map((l) => (
                  <option key={l} value={l}>
                    {SKILL_LEVELS[l]}
                  </option>
                ))}
              </select>
              <button
                aria-label={`Remove ${name}`}
                className="rounded-full px-1.5 text-zinc-400 hover:text-red-600"
                onClick={() => {
                  const rest = { ...profile.skills };
                  delete rest[name];
                  edit({ skills: rest });
                }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
        {unused.length > 0 && (
          <select
            aria-label="Add a skill"
            value=""
            className={input}
            onChange={(e) => e.target.value && edit({ skills: { ...profile.skills, [e.target.value]: 2 } })}
          >
            <option value="">+ Add a skill</option>
            {unused.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        )}
      </section>
    </div>
  );
}
