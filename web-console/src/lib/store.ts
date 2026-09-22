import { useSyncExternalStore } from "react";

type Listener = () => void;

export function createStore<T extends object>(initial: T) {
  let state = initial;
  const listeners = new Set<Listener>();
  const get = () => state;
  const set = (next: Partial<T> | ((s: T) => Partial<T>)) => {
    const patch = typeof next === "function" ? next(state) : next;
    state = { ...state, ...patch };
    listeners.forEach((fn) => fn());
  };
  const subscribe = (fn: Listener) => {
    listeners.add(fn);
    return () => listeners.delete(fn);
  };
  const use = () => useSyncExternalStore(subscribe, get);
  return { get, set, subscribe, use };
}
