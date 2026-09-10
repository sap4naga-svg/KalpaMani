"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_GROUPS, resolveRoute, routesInGroup, type NavRoute } from "@/nav/registry";
import { withScope, type ViewScope } from "@/lib/scope";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/primitives";

function statusBadge(route: NavRoute) {
  if (route.status === "implemented") return null;
  return (
    <Badge tone="unavailable" className="ml-auto shrink-0">
      {route.status === "inert" ? "inert" : "planned"}
    </Badge>
  );
}

/**
 * `page` is the entry a reader is ON. `true` is the entry that OWNS where they are.
 *
 * A drill-down screen is not its sidebar entry — `/portfolio/trades/<id>` is Trade Detail,
 * reached from Trade History — so marking Trade History `aria-current="page"` there would tell
 * a screen reader the reader is on the ledger. It is highlighted as the owning section instead,
 * which is the true statement and still restores the sense of place that was missing.
 */
type CurrentKind = "page" | "section" | null;

function NavLink({
  route,
  scope,
  current,
  onNavigate,
}: {
  route: NavRoute;
  scope: ViewScope;
  current: CurrentKind;
  onNavigate?: () => void;
}) {
  const active = current !== null;
  return (
    <Link
      href={withScope(route.href, scope)}
      onClick={onNavigate}
      aria-current={current === "page" ? "page" : current === "section" ? true : undefined}
      className={cn(
        "flex items-center gap-2 rounded-sm px-3 py-1.5 text-label-m transition-colors",
        active
          ? "bg-surface-sunken text-text-primary"
          : "text-text-secondary hover:bg-surface-sunken hover:text-text-primary",
      )}
    >
      <span className="truncate">{route.label}</span>
      {statusBadge(route)}
    </Link>
  );
}

/**
 * Grouped navigation. Thirty-six areas are not thirty-six equal-weight sidebar links, so
 * the grouping is part of the specification rather than a layout preference.
 */
export function NavTree({
  scope,
  onNavigate,
}: {
  scope: ViewScope;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  /*
   * THE CURRENT ENTRY IS THE ONE THAT OWNS THE PATH, NOT THE ONE WHOSE HREF EQUALS IT.
   *
   * Comparing `pathname` to `href` marked NOTHING current on `/portfolio/trades/<id>` and
   * `/signals/candidates/<id>`, so a reader who had drilled into a trade or a candidate saw a
   * sidebar with no position in it at all. `resolveRoute` maps a deep destination back to the
   * sidebar entry it is reached from, and returns `null` for an unregistered path rather than
   * choosing a nearest entry.
   */
  const currentOwner = resolveRoute(pathname)?.owner ?? null;
  return (
    <nav aria-label="Cockpit areas" className="space-y-5">
      {NAV_GROUPS.map((group) => {
        const routes = routesInGroup(group.id);
        if (routes.length === 0) return null;
        return (
          <div key={group.id}>
            <h2 className="px-3 pb-1.5 text-label-s font-semibold uppercase tracking-[0.09em] text-text-tertiary">
              {group.label}
            </h2>
            <div className="space-y-0.5">
              {routes.map((route) => (
                <NavLink
                  key={route.href}
                  route={route}
                  scope={scope}
                  current={
                    currentOwner !== null && currentOwner.href === route.href
                      ? pathname === route.href
                        ? "page"
                        : "section"
                      : null
                  }
                  onNavigate={onNavigate}
                />
              ))}
            </div>
          </div>
        );
      })}
    </nav>
  );
}
