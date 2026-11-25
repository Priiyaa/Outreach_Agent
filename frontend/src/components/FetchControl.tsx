"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "@/lib/api";

/** Starts a background fetch on the server and polls it. The job list refreshes as soon as the new jobs are ranked
 * (before the slower LLM double-check finishes) and once more when the run ends. */
export default function FetchControl() {
  const queryClient = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const status = useQuery({
    queryKey: ["fetch"],
    queryFn: api.fetchStatus,
    refetchInterval: (query) => (query.state.data?.running ? 2000 : false),
  });
  const start = useMutation({
    mutationFn: api.startFetch,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["fetch"] }),
  });

  const running = status.data?.running ?? false;
  const ready = status.data?.results_ready ?? false;
  const wasRunning = useRef(false);
  const wasReady = useRef(false);
  useEffect(() => {
    const refresh = (wasRunning.current && !running) || (running && ready && !wasReady.current);
    if (refresh) queryClient.invalidateQueries({ queryKey: ["jobs"] });
    wasRunning.current = running;
    wasReady.current = running && ready;
  }, [running, ready, queryClient]);

  // Hosts that sleep fetch on a schedule instead, and tell us so.
  if (meta.data?.fetch_enabled === false) return null;

  return (
    <div className="flex items-center gap-3">
      <button
        onClick={() => start.mutate()}
        disabled={running || start.isPending}
        className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {running ? "Fetching…" : "Fetch new jobs"}
      </button>
      {running && status.data?.stage && (
        <span role="status" className={`max-w-md truncate text-sm ${ready ? "text-green-700 dark:text-green-400" : "text-zinc-500"}`}>
          {status.data.stage}
        </span>
      )}
      {!running && status.data?.error && <span className="text-sm text-red-600">{status.data.error}</span>}
      {!running && !status.data?.error && status.data?.output && (
        <span className="max-w-md truncate text-sm text-zinc-500" title={status.data.output}>
          {status.data.output.split("\n")[0]}
        </span>
      )}
    </div>
  );
}
