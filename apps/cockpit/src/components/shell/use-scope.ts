"use client";

import * as React from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { parseScope, scopeToSearchParams, type ViewScope } from "@/lib/scope";

/**
 * The view scope, read from and written to the URL.
 *
 * Filters, range, mode and scoping survive navigation and a mode switch, and are
 * reproducible from the URL, so a link reproduces the view (U13). MODE SWITCHING PRESERVES
 * DRILL-DOWN CONTEXT AND DOES NOT RESET THE VIEW (U15): only the changed key is written,
 * and the path is untouched.
 */
export function useScope(): {
  scope: ViewScope;
  setScope: (next: Partial<ViewScope>) => void;
} {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();

  const scope = React.useMemo(
    () => parseScope(new URLSearchParams(searchParams.toString())),
    [searchParams],
  );

  const setScope = React.useCallback(
    (next: Partial<ViewScope>) => {
      const merged = { ...scope, ...next };
      // Preserve every unrelated query parameter, so a drill-down filter is not discarded.
      const params = new URLSearchParams(searchParams.toString());
      for (const [key, value] of scopeToSearchParams(merged)) {
        params.set(key, value);
      }
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, scope, searchParams],
  );

  return { scope, setScope };
}
