"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useSyncExternalStore } from "react";
import { api } from "@/lib/api";
import { getAccessCode, setAccessCode, subscribeAccessCode } from "@/lib/auth";

/** Shown only when the server has an access code set. Reading is open; editing needs the code. */
export default function UnlockControl() {
  const queryClient = useQueryClient();
  const meta = useQuery({ queryKey: ["meta"], queryFn: api.meta, staleTime: Infinity });
  const unlocked = useSyncExternalStore(subscribeAccessCode, () => getAccessCode() !== null, () => false);
  const [error, setError] = useState<string | null>(null);

  if (!meta.data?.writes_locked) return null;

  const unlock = async () => {
    const code = window.prompt("Access code for editing:");
    if (!code) return;
    try {
      await api.checkAccess(code);
      setAccessCode(code);
      setError(null);
      queryClient.invalidateQueries();
    } catch {
      setError("Wrong code");
    }
  };
  const lock = () => {
    setAccessCode(null);
  };

  return (
    <div className="flex items-center gap-2 text-sm">
      {error && <span className="text-red-600">{error}</span>}
      {unlocked ? (
        <button onClick={lock} className="rounded-md border border-zinc-300 px-3 py-1.5 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900">
          Editing unlocked · Lock
        </button>
      ) : (
        <button onClick={unlock} className="rounded-md border border-zinc-300 px-3 py-1.5 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900">
          Unlock editing
        </button>
      )}
    </div>
  );
}
