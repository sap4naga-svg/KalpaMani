"use client";

import * as React from "react";
import Link from "next/link";
import * as Dialog from "@radix-ui/react-dialog";
import { Menu, Search, X } from "lucide-react";

import { Badge, Button } from "@/components/ui/primitives";
import { FreshnessIndicator } from "@/components/cockpit/freshness";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { CommandPalette, useCommandPalette } from "@/components/palette/command-palette";
import { useExecutiveOverview } from "@/data/client/hooks";
import { DATA_SCENARIOS, VIEW_MODES, withScope, type ViewMode } from "@/lib/scope";
import { ENVIRONMENTS } from "@/contracts/vocabularies";
import { humanizeCode } from "@/lib/format";
import { cn } from "@/lib/utils";

import { NavTree } from "./nav";
import { useScope } from "./use-scope";

function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
  testId,
}: {
  label: string;
  value: T;
  options: readonly T[];
  onChange: (next: T) => void;
  testId: string;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">{label}</span>
      <div
        role="radiogroup"
        aria-label={label}
        data-testid={testId}
        className="flex rounded-sm border border-border-subtle bg-surface-sunken p-0.5"
      >
        {options.map((option) => (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={value === option}
            data-value={option}
            onClick={() => onChange(option)}
            className={cn(
              "rounded-[3px] px-2 py-1 text-label-s font-medium capitalize transition-colors",
              value === option
                ? "bg-accent text-text-inverse"
                : "text-text-secondary hover:text-text-primary",
            )}
          >
            {option.toLowerCase()}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * The persistent environment, source and freshness context.
 *
 * Present on EVERY route, in the header, at ALL times (U2). Five things are kept apart:
 * deployment identity, runtime environment, strategy maturity, source provenance and data
 * availability.
 */
function ContextBar() {
  const { scope, setScope } = useScope();
  const overview = useExecutiveOverview(scope);
  return (
    <div
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border-subtle px-4 py-2"
      data-testid="context-bar"
    >
      <SegmentedControl
        label="Mode"
        value={scope.mode}
        options={VIEW_MODES}
        onChange={(mode: ViewMode) => setScope({ mode })}
        testId="mode-switch"
      />
      <SegmentedControl
        label="Environment"
        value={scope.environment}
        options={ENVIRONMENTS}
        onChange={(environment) => setScope({ environment })}
        testId="environment-switch"
      />
      <SegmentedControl
        label="Scenario"
        value={scope.scenario}
        options={DATA_SCENARIOS}
        onChange={(scenario) => setScope({ scenario })}
        testId="scenario-switch"
      />
      {/*
        * Both provenances are shown, because this deployment carries both kinds and a page
        * carrying both badges EACH COMPONENT INDIVIDUALLY rather than choosing one badge
        * for the whole page. Governance facts are tracked; operational read models are
        * fixture-adapter output.
        */}
      <div className="flex items-center gap-2" data-testid="source-context">
        <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
          Source
        </span>
        <ProvenanceBadge provenance="REPOSITORY_TRACKED" />
        {scope.scenario === "demo" && <ProvenanceBadge provenance="SYNTHETIC" />}
      </div>
      <div className="flex items-center gap-2">
        <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
          Freshness
        </span>
        {overview.data === undefined ? (
          <Badge tone="unavailable">◌ evaluating</Badge>
        ) : (
          <FreshnessIndicator
            report={overview.data.freshness}
            showDetail={scope.mode === "operator"}
          />
        )}
      </div>
      {/*
        * Maturity is a governance property of a strategy version, and a filter is a filter.
        * It is READ FROM THE RESPONSE rather than hardcoded: a scope that carries no facts
        * carries no maturity stage either, and a header that always said "Research" would
        * assert a governance position for a response that states none.
        */}
      <div className="flex items-center gap-2">
        <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
          Maturity
        </span>
        <Badge tone="unavailable">
          {overview.data?.maturity_stage === undefined
            ? "not applicable"
            : humanizeCode(overview.data.maturity_stage)}
        </Badge>
      </div>
    </div>
  );
}

/**
 * A synthetic deployment is labelled at PAGE level as well as at component level, because
 * screenshots travel (U3).
 */
function ScenarioBanner() {
  const { scope } = useScope();
  if (scope.scenario === "demo") {
    return (
      <div
        role="note"
        data-testid="page-provenance-banner"
        className="border-b border-warning/50 bg-warning/12 px-4 py-2 text-label-m text-warning"
      >
        <strong className="font-semibold">SYNTHETIC DEMONSTRATION DATA.</strong> Every figure
        on this page is a repository-owned deterministic fixture. It is not a result, not a
        measurement and not evidence of anything.
      </div>
    );
  }
  return (
    <div
      role="note"
      data-testid="page-provenance-banner"
      className="border-b border-info/40 bg-info/10 px-4 py-2 text-label-m text-info"
    >
      <strong className="font-semibold">PROJECT READINESS.</strong> Governance facts are read
      from tracked repository authority at a recorded commit and carry their as-of dates.
      Operational read models are shown as unavailable, because their producing subsystems do
      not exist.
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { scope } = useScope();
  const palette = useCommandPalette();
  const [drawerOpen, setDrawerOpen] = React.useState(false);

  return (
    <div className="min-h-dvh bg-surface-base">
      <a
        href="#main-content"
        className={cn(
          "sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50",
          "focus:rounded-sm focus:bg-accent focus:px-3 focus:py-2 focus:text-text-inverse",
        )}
      >
        Skip to main content
      </a>

      <header className="sticky top-0 z-30 border-b border-border-subtle bg-surface-raised">
        <div className="flex items-center gap-3 px-4 py-2.5">
          <Dialog.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
            <Dialog.Trigger asChild>
              <Button variant="ghost" size="sm" className="lg:hidden" aria-label="Open navigation">
                <Menu size={16} aria-hidden="true" />
              </Button>
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Overlay className="fixed inset-0 z-40 bg-black/60" />
              <Dialog.Content
                className={cn(
                  "fixed inset-y-0 left-0 z-50 w-[19rem] max-w-[86vw] overflow-y-auto",
                  "border-r border-border-subtle bg-surface-raised p-3 shadow-elevation-2",
                )}
              >
                <div className="mb-3 flex items-center justify-between px-2">
                  <Dialog.Title className="text-label-m font-semibold text-text-primary">
                    Navigation
                  </Dialog.Title>
                  <Dialog.Close asChild>
                    <Button variant="ghost" size="sm" aria-label="Close navigation">
                      <X size={15} aria-hidden="true" />
                    </Button>
                  </Dialog.Close>
                </div>
                <Dialog.Description className="sr-only">
                  Grouped navigation across the Cockpit product areas.
                </Dialog.Description>
                <NavTree scope={scope} onNavigate={() => setDrawerOpen(false)} />
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>

          <Link
            href={withScope("/", scope)}
            className="flex items-baseline gap-2 rounded-sm text-text-primary"
          >
            <span className="text-numeric-m font-semibold tracking-tight">KalpaMani</span>
            <span className="text-label-s uppercase tracking-[0.14em] text-text-tertiary">
              Cockpit
            </span>
          </Link>

          <Button
            variant="subtle"
            size="sm"
            className="ml-auto gap-2"
            onClick={(event) => palette.open(event.currentTarget)}
            aria-keyshortcuts="Meta+K Control+K"
            // The visible label is hidden below the `sm` breakpoint, so the accessible
            // name is stated explicitly rather than left to disappear with it.
            aria-label="Search"
          >
            <Search size={14} aria-hidden="true" />
            <span className="hidden sm:inline">Search</span>
            <kbd className="hidden font-mono text-label-s text-text-tertiary sm:inline">
              ⌘K
            </kbd>
          </Button>
        </div>
        <ContextBar />
      </header>

      <ScenarioBanner />

      <div className="mx-auto flex w-full max-w-[110rem] gap-6 px-4 py-6">
        <aside className="hidden w-60 shrink-0 lg:block">
          <div className="sticky top-[9.5rem]">
            <NavTree scope={scope} />
          </div>
        </aside>
        <main id="main-content" className="min-w-0 flex-1">
          {children}
        </main>
      </div>

      <CommandPalette controller={palette} />
    </div>
  );
}
