import { useCallback, useEffect, useRef, useState } from "react";

import { fetchJobs, type Job } from "@/lib/api";

/**
 * Loads the conversion history and polls it every 1.5s while any job is still
 * queued or processing. Polling stops automatically once everything settles.
 */
export function useJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      setJobs(await fetchJobs());
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const active = jobs.some((j) => j.status === "queued" || j.status === "processing");

  useEffect(() => {
    if (!active) return;
    timer.current = setInterval(() => void refresh(), 1500);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [active, refresh]);

  return { jobs, error, loading, refresh };
}
