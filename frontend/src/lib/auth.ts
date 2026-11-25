// The shared access code is kept in this browser only. It is sent with every API call; the server only checks it on writes.
const KEY = "access-code";

export function getAccessCode(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(KEY);
  } catch {
    return null; // storage can be blocked (private mode); editing then just stays locked
  }
}

const listeners = new Set<() => void>();

/** For useSyncExternalStore: tells React when the stored code changes (here or in another tab). */
export function subscribeAccessCode(callback: () => void): () => void {
  listeners.add(callback);
  window.addEventListener("storage", callback);
  return () => {
    listeners.delete(callback);
    window.removeEventListener("storage", callback);
  };
}

export function setAccessCode(code: string | null): void {
  try {
    if (code) window.localStorage.setItem(KEY, code);
    else window.localStorage.removeItem(KEY);
  } catch {
    /* nothing to do: see above */
  }
  listeners.forEach((notify) => notify());
}
