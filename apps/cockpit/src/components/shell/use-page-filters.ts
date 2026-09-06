"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

/**
 * Page-local filters, kept in the URL beside the view scope.
 *
 * U13: "filters, date range, mode and scoping survive a mode switch and are reproducible from
 * the URL". The view scope — mode, environment, scenario, period, granularity — is global and
 * lives in `useScope`. THESE are the filters of ONE screen: a search term, a status, a
 * direction, a date range. Both live in the same query string, and neither clears the other,
 * so a mode switch preserves a drill-down filter and a shared link reproduces the whole view.
 *
 * **A FILTER THAT IS APPLIED AND INVISIBLE IS HOW A READER MISREADS A SUBSET AS THE WHOLE**
 * (§8), which is why every active filter is rendered as a removable chip by `FilterChips`.
 */
export function usePageFilters<K extends string>(
  keys: readonly K[],
): {
  filters: Readonly<Record<K, string>>;
  setFilter: (key: K, value: string) => void;
  clearFilter: (key: K) => void;
  clearAll: () => void;
  activeKeys: readonly K[];
} {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const serialized = searchParams.toString();

  const filters = React.useMemo(() => {
    const params = new URLSearchParams(serialized);
    const next = {} as Record<K, string>;
    for (const key of keys) {
      next[key] = params.get(key) ?? "";
    }
    return next;
    // `keys` is a stable literal tuple at every call site; `serialized` is what changes.
  }, [serialized, keys]);

  const write = React.useCallback(
    (mutate: (params: URLSearchParams) => void) => {
      const params = new URLSearchParams(serialized);
      mutate(params);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, serialized],
  );

  const setFilter = React.useCallback(
    (key: K, value: string) => {
      write((params) => {
        if (value === "") {
          params.delete(key);
        } else {
          params.set(key, value);
        }
      });
    },
    [write],
  );

  const clearFilter = React.useCallback(
    (key: K) => {
      write((params) => params.delete(key));
    },
    [write],
  );

  const clearAll = React.useCallback(() => {
    write((params) => {
      for (const key of keys) {
        params.delete(key);
      }
    });
  }, [keys, write]);

  const activeKeys = React.useMemo(
    () => keys.filter((key) => filters[key] !== ""),
    [filters, keys],
  );

  return { filters, setFilter, clearFilter, clearAll, activeKeys };
}
