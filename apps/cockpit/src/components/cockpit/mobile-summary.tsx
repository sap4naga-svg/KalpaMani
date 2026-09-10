"use client";

import * as React from "react";

import { AvailabilityBadge } from "@/components/cockpit/availability";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import type { AvailabilityState, DataProvenance } from "@/contracts/vocabularies";
import { SUMMARY_MEDIA_QUERY } from "@/lib/mobile-summary";
import { cn } from "@/lib/utils";

/**
 * The mobile executive summary's disclosures — ADR-0033 §2 (Decision M).
 *
 * Below 640 CSS pixels of VIEWPORT width, on `/` only, every section of the Executive
 * Overview that is not part of the accepted summary is deferred behind one of these: a
 * native `<details>`/`<summary>` control whose summary CONTAINS THE SECTION'S `h2`, so
 * heading navigation lists the deferred section exactly once whether it is collapsed or not.
 *
 * THE SAME DOM CONTENT EXISTS AT EVERY WIDTH (M1, M7). The `<details>` element is the
 * PERMANENT wrapper of the section's content: above the breakpoint it is held open and its
 * summary carries the `hidden` attribute, so the section renders exactly as it did before
 * this decision — no disclosure control, every section visible. Because the wrapper never
 * changes element type, the children keep their DOM nodes across a breakpoint crossing,
 * which is what lets an element focused inside a section keep focus when the viewport is
 * resized across 640 pixels in either direction (M8.10).
 *
 * WHAT A CONTROL CARRIES, AND NOTHING ELSE (M5): the fixed label, the section's provenance
 * badge or badges, and one availability badge per distinct settled non-`AVAILABLE` state
 * among the section's widgets, in vocabulary order. Never a metric value, never a delta,
 * never a count and never a skeleton — a pending read contributes nothing.
 *
 * EXPANSION STATE LIVES FOR THE PAGE INSTANCE ONLY (M7): component state, so it is written
 * neither to the URL nor to storage, survives a mode switch and a breakpoint crossing on the
 * same page, and returns to collapsed on a reload or a navigation away and back. A section
 * that holds focus is never collapsed by a resize.
 */

type SummaryLayout = "unknown" | "summary" | "full";

/**
 * The breakpoint, as an external store the server cannot see.
 *
 * `matchMedia` does not exist on the server, so the server snapshot is `unknown`, and the
 * client switches to the real answer only after it subscribes — `useSyncExternalStore` is
 * the primitive for a value the server render and the first client render must agree on.
 */
const summaryLayoutStore = (() => {
  let query: MediaQueryList | null = null;
  const listeners = new Set<() => void>();
  const notify = () => {
    for (const listener of listeners) listener();
  };
  const resolve = (): MediaQueryList | null => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return null;
    query ??= window.matchMedia(SUMMARY_MEDIA_QUERY);
    return query;
  };
  return {
    subscribe(listener: () => void): () => void {
      const list = resolve();
      if (list !== null && listeners.size === 0) list.addEventListener("change", notify);
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
        if (list !== null && listeners.size === 0) list.removeEventListener("change", notify);
      };
    },
    getSnapshot(): SummaryLayout {
      const list = resolve();
      if (list === null) return "unknown";
      return list.matches ? "summary" : "full";
    },
    getServerSnapshot(): SummaryLayout {
      return "unknown";
    },
  };
})();

export function useSummaryLayout(): SummaryLayout {
  return React.useSyncExternalStore(
    summaryLayoutStore.subscribe,
    summaryLayoutStore.getSnapshot,
    summaryLayoutStore.getServerSnapshot,
  );
}

/** The four fixed labels (M5). A label is never a number and never carries one. */
export type SummaryDisclosureId =
  | "what-changed"
  | "performance-overview"
  | "supporting-context"
  | "response-evidence";

export const SUMMARY_DISCLOSURE_LABEL: Readonly<Record<SummaryDisclosureId, string>> = {
  "what-changed": "What changed — details",
  "performance-overview": "Performance overview",
  "supporting-context": "Supporting context",
  "response-evidence": "Response evidence",
};

/** The `h2` inside the control is visible, whatever its full-width treatment is. */
const CONTROL_HEADING = "text-label-m font-semibold text-text-secondary";

export interface SummaryDisclosureProps {
  readonly id: SummaryDisclosureId;
  /** The `id` of the section's `h2`, which the enclosing `section` is labelled by. */
  readonly headingId: string;
  /**
   * How the `h2` renders at and above the breakpoint, where it stands outside the control
   * exactly as it did before this decision. `null` renders no heading there — the What
   * Changed panel carries its own heading inside its card.
   */
  readonly fullWidthHeading: { readonly className?: string } | null;
  /** The distinct settled non-`AVAILABLE` states, already in vocabulary order. */
  readonly availability: readonly AvailabilityState[];
  /** Every distinct provenance the section's widgets display. */
  readonly provenance: readonly DataProvenance[];
  readonly className?: string;
  readonly children: React.ReactNode;
}

export function SummaryDisclosure({
  id,
  headingId,
  fullWidthHeading,
  availability,
  provenance,
  className,
  children,
}: SummaryDisclosureProps) {
  const layout = useSummaryLayout();
  const [expanded, setExpanded] = React.useState(false);
  const [focusWithin, setFocusWithin] = React.useState(false);
  const label = SUMMARY_DISCLOSURE_LABEL[id];
  const controlId = `summary-disclosure-${id}-control`;
  const contentId = `summary-disclosure-${id}-content`;

  /*
   * A SECTION HOLDING FOCUS IS NEVER COLLAPSED BY A RESIZE (M7). Whether the focused element
   * is inside this section's CONTENT is tracked as it happens, because once a `<details>`
   * closes the browser has already moved focus to the body and nothing can read the loss it
   * was meant to prevent. Focus on the control itself is not focus inside the content and
   * does not hold the section open.
   */
  const onFocus = React.useCallback((event: React.FocusEvent<HTMLDetailsElement>) => {
    setFocusWithin(event.target.id !== controlId);
  }, [controlId]);
  const onBlur = React.useCallback((event: React.FocusEvent<HTMLDetailsElement>) => {
    const next = event.relatedTarget;
    if (!(next instanceof Node) || !event.currentTarget.contains(next)) setFocusWithin(false);
  }, []);

  /*
   * A section holding focus when the viewport crosses downward is EXPANDED by that crossing,
   * as a section the reader expanded would be: the reader is inside it, and it must neither
   * close under them nor snap shut when focus later moves out. The crossing is detected from
   * the previous render's layout -- the pattern for adjusting state when an input changes --
   * and the adjustment lands in the same render, before the `<details>` could close.
   */
  const [previousLayout, setPreviousLayout] = React.useState(layout);
  if (previousLayout !== layout) {
    setPreviousLayout(layout);
    if (layout === "summary" && focusWithin && !expanded) setExpanded(true);
  }

  const open = layout !== "summary" || expanded;

  /*
   * ONLY THE READER EXPANDS A SECTION. The `toggle` event also fires when a breakpoint
   * crossing opens or closes the element, and recording that as the reader's choice would
   * leave a section the reader never opened expanded after a rotate-and-back. Above the
   * breakpoint the event is therefore ignored; it is dispatched after the render that
   * changed `open` committed, so the handler sees the layout that caused it.
   */
  const onToggle = React.useCallback(
    (event: React.SyntheticEvent<HTMLDetailsElement>) => {
      if (layout === "summary") setExpanded(event.currentTarget.open);
    },
    [layout],
  );

  const collapsedControl = layout !== "full" && !expanded;

  /*
   * BEFORE THE BREAKPOINT IS KNOWN the markup carries a CSS fallback instead of a guess:
   * below `sm` the control shows and the content hides, above `sm` the control hides and
   * the heading stands outside it — so a phone's first paint is already the collapsed
   * summary and a desktop's is already the full page, and neither shifts on hydration. The
   * control's label is a plain span in that state so the heading's `id` exists exactly once.
   */
  const unknown = layout === "unknown";

  return (
    <details
      open={open}
      onToggle={onToggle}
      onFocus={onFocus}
      onBlur={onBlur}
      data-testid={`disclosure-${id}`}
      data-summary-disclosure={id}
      data-summary-layout={layout}
      className={cn("group", className)}
    >
      {/*
        * THE CONTROL, BELOW THE BREAKPOINT ONLY. At and above it the summary carries the
        * `hidden` attribute — not rendered, not focusable, not in the accessibility tree —
        * and the `<details>` is simply open, so the section is the section it always was.
        */}
      <summary
        hidden={layout === "full"}
        id={controlId}
        aria-controls={contentId}
        data-testid={`disclosure-${id}-control`}
        data-expanded={collapsedControl ? "false" : "true"}
        className={cn(
          "flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1.5 rounded-md",
          "border border-border-subtle bg-surface-raised px-4 py-3 shadow-elevation-1",
          "marker:content-none [&::-webkit-details-marker]:hidden",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent",
          unknown && "sm:hidden",
        )}
      >
        <span
          aria-hidden="true"
          className={cn(
            "inline-flex h-5 w-5 shrink-0 items-center justify-center text-text-tertiary transition-transform",
            !collapsedControl && "rotate-90",
          )}
        >
          ▸
        </span>
        {layout === "summary" ? (
          <h2 id={headingId} className={CONTROL_HEADING}>
            {label}
          </h2>
        ) : (
          <span className={CONTROL_HEADING}>{label}</span>
        )}
        {/*
          * THE SECTION'S PROVENANCE, EVERY DISTINCT ONE (M5, U3): a collapsed synthetic
          * section is still labelled SYNTHETIC, and a section mixing a tracked fact with
          * synthetic tiles carries both rather than choosing one.
          */}
        {provenance.map((source) => (
          <ProvenanceBadge key={source} provenance={source} className="shrink-0" />
        ))}
        {/*
          * ONE BADGE PER DISTINCT SETTLED NON-AVAILABLE STATE, IN VOCABULARY ORDER (M4, M5):
          * glyph and label, never colour alone, never a number, never a skeleton, and never
          * a precedence the contract does not define.
          */}
        {availability.map((state) => (
          <AvailabilityBadge key={state} state={state} className="shrink-0" />
        ))}
      </summary>
      {layout !== "summary" && fullWidthHeading !== null && (
        <h2
          id={headingId}
          className={cn(fullWidthHeading.className, unknown && "max-sm:hidden")}
        >
          {label}
        </h2>
      )}
      <div
        id={contentId}
        data-testid={`disclosure-${id}-content`}
        className={cn(layout === "summary" && "mt-3", unknown && "max-sm:hidden")}
      >
        {children}
      </div>
    </details>
  );
}
