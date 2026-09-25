"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api-client";

export interface AsyncState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** Minimal data-fetching hook: loading/error/data plus reload. Ignores
 *  results from stale requests so fast re-renders can't show old data. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const callId = useRef(0);

  useEffect(() => {
    const id = ++callId.current;
    setLoading(true);
    fn()
      .then((result) => {
        if (id !== callId.current) return;
        setData(result);
        setError(null);
      })
      .catch((err: unknown) => {
        if (id !== callId.current) return;
        setError(err instanceof ApiError ? err : new ApiError(String(err), "UNKNOWN", 0, null));
      })
      .finally(() => id === callId.current && setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}
