"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_GROUPS, routesInGroup, type NavRoute } from "@/nav/registry";
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

function NavLink({
  route,
  scope,
  active,
  onNavigate,
}: {
  route: NavRoute;
  scope: ViewScope;
  active: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={withScope(route.href, scope)}
      onClick={onNavigate}
      aria-current={active ? "page" : undefined}
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
                  active={pathname === route.href}
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
