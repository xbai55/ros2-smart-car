import { useCallback, useEffect, useState } from "react";

type QueryState<T> = { data: T | null; loading: boolean; error: string };

export function useData<T>(fetcher: () => Promise<T>, deps: readonly unknown[] = []) {
  const [state, setState] = useState<QueryState<T>>({ data: null, loading: true, error: "" });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let active = true;
    setState((prev) => ({ ...prev, loading: true, error: "" }));
    fetcher()
      .then((data) => { if (active) setState({ data, loading: false, error: "" }); })
      .catch((reason) => { if (active) setState({ data: null, loading: false, error: reason instanceof Error ? reason.message : String(reason) }); });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const refetch = useCallback(() => setTick((t) => t + 1), []);
  return { ...state, refetch };
}
