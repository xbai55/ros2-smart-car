import { useSyncExternalStore } from "react";

function currentPath(): string {
  const raw = window.location.hash.replace(/^#/, "").split("?")[0];
  return raw || "/";
}

const subs = new Set<() => void>();
if (typeof window !== "undefined") {
  window.addEventListener("hashchange", () => subs.forEach((fn) => fn()));
}

export function usePath(): string {
  return useSyncExternalStore(
    (cb) => {
      subs.add(cb);
      return () => subs.delete(cb);
    },
    currentPath
  );
}

export function navigate(path: string): void {
  if (currentPath() === path) return;
  window.location.hash = path;
}

export function matchRoute(pattern: string, path: string): Record<string, string> | null {
  const patternParts = pattern.split("/").filter(Boolean);
  const pathParts = path.split("/").filter(Boolean);
  if (patternParts.length !== pathParts.length) return null;
  const params: Record<string, string> = {};
  for (let i = 0; i < patternParts.length; i += 1) {
    if (patternParts[i].startsWith(":")) params[patternParts[i].slice(1)] = decodeURIComponent(pathParts[i]);
    else if (patternParts[i] !== pathParts[i]) return null;
  }
  return params;
}

type LinkProps = {
  to: string;
  className?: string;
  children: React.ReactNode;
  onClick?: () => void;
  title?: string;
  "aria-label"?: string;
};

export function Link({ to, children, ...rest }: LinkProps) {
  return (
    <a href={`#${to}`} {...rest}>
      {children}
    </a>
  );
}
