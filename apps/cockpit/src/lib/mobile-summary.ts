import type { EnvelopeOf } from "@/contracts/envelope";
import type { PerformanceSeriesPayload } from "@/contracts/read-models";
import type { WhatChangedPayload } from "@/data/client/read-client";
import {
  AVAILABILITY_STATES,
  DATA_PROVENANCES,
  type AvailabilityState,
  type DataProvenance,
} from "@/contracts/vocabularies";

/**
 * The mobile executive summary — ADR-0033 §2 (Decision M), `ui-ux-specification.md` §12.1.
 *
 * Below the breakpoint the Executive Overview renders the accepted summary first and DEFERS
 * every other section behind a labelled disclosure on the same page. This module holds the
 * two rules a collapsed control's badges obey, as pure functions a unit test can hold to the
 * contract, and the derivations that say what state a deferred widget PRESENTS.
 *
 * THE BREAKPOINT IS A VIEWPORT RULE (M1): the summary behaviour applies when the viewport is
 * narrower than 640 CSS pixels — the `sm` breakpoint the page already lays its tiers out
 * against — and nowhere else. 390 × 844 is below it; 768 × 1024 is above it and keeps its
 * single-column stacking with no disclosure.
 */
export const SUMMARY_BREAKPOINT_PX = 640;

/** The media query the breakpoint is detected with. A viewport rule, never a container one. */
export const SUMMARY_MEDIA_QUERY = `(width < ${SUMMARY_BREAKPOINT_PX}px)`;

/**
 * What one widget inside a deferred section contributes to its control.
 *
 * A PENDING READ CONTRIBUTES NOTHING (M5, M6): a widget whose read has not settled has no
 * availability state, is excluded from the set, and never suppresses a settled state beside
 * it. A settled widget contributes every state it renders as its own — a composite tile
 * that shows two absent records contributes both — and the provenance badge it displays,
 * where it displays one.
 */
export type WidgetRead =
  | { readonly settled: false; readonly provenance?: DataProvenance }
  | {
      readonly settled: true;
      readonly states: readonly AvailabilityState[];
      readonly provenance?: DataProvenance;
    };

export function pendingWidget(provenance?: DataProvenance): WidgetRead {
  return provenance === undefined ? { settled: false } : { settled: false, provenance };
}

export function settledWidget(
  states: AvailabilityState | readonly AvailabilityState[],
  provenance?: DataProvenance,
): WidgetRead {
  const list = typeof states === "string" ? [states] : states;
  return provenance === undefined
    ? { settled: true, states: list }
    : { settled: true, states: list, provenance };
}

/**
 * ONE BADGE PER DISTINCT SETTLED NON-`AVAILABLE` STATE, IN VOCABULARY ORDER — and not a
 * precedence policy.
 *
 * The read-model contract fixes no ordering between availability states and refuses a
 * composite that picks one (`contracts/freshness.ts`: no precedence policy is invented
 * there), so none is invented here either. The order is `AVAILABILITY_STATES`' own and fixes
 * the DISPLAY SEQUENCE only; it asserts nothing about severity. `ERROR` is therefore never
 * omitted, never outranked and never merged into another state, and two different absences
 * in one section are never reported as one. A section whose settled widgets are all
 * `AVAILABLE` carries no badge.
 */
export function disclosureAvailabilityStates(
  widgets: readonly WidgetRead[],
): readonly AvailabilityState[] {
  const present = new Set<AvailabilityState>();
  for (const widget of widgets) {
    if (!widget.settled) continue;
    for (const state of widget.states) {
      if (state !== "AVAILABLE") present.add(state);
    }
  }
  return AVAILABILITY_STATES.filter((state) => present.has(state));
}

/**
 * EVERY DISTINCT PROVENANCE THE SECTION'S WIDGETS CARRY (M5), in the vocabulary's order.
 *
 * §5 requires a page carrying both kinds of provenance to badge each component individually
 * rather than choose one badge for the whole page, and one badge on a mixed control would
 * choose — so a section grouping a `REPOSITORY_TRACKED` tile beside `SYNTHETIC` ones carries
 * both. A widget that displays no provenance badge — an absence carries no number, so it
 * carries no provenance — contributes none; a pending widget whose provenance is already
 * known (a tracked governance tile) still contributes it, because the label is known before
 * the value is.
 */
export function disclosureProvenances(widgets: readonly WidgetRead[]): readonly DataProvenance[] {
  const present = new Set<DataProvenance>();
  for (const widget of widgets) {
    if (widget.provenance !== undefined) present.add(widget.provenance);
  }
  return DATA_PROVENANCES.filter((provenance) => present.has(provenance));
}

/**
 * The states the What Changed panel PRESENTS for a settled read — the same decision tree
 * `WhatChangedPanel` renders from, stated once so the collapsed control and the expanded
 * panel cannot disagree.
 *
 *   no payload                        the envelope's own state, and its named dependency
 *   no baseline endpoint              the baseline's state (NOT_YET_AVAILABLE) — an absence
 *   nothing renderable, sound         EMPTY_VERIFIED — a measurement that nothing changed
 *   nothing renderable, unsound       PARTIAL, or the envelope's own non-available state
 *   entries over a partial extent     the envelope's state, and PARTIAL for the extent
 */
export function whatChangedPresentedStates(
  envelope: EnvelopeOf<WhatChangedPayload>,
): readonly AvailabilityState[] {
  const payload = envelope.payload;
  if (payload === undefined) {
    return [envelope.availability];
  }
  if (payload.baseline_state !== undefined) {
    return [payload.baseline_state.availability];
  }
  const renderable = payload.entries.filter((entry) => entry.evidence_refs.items.length > 0);
  const populationComplete = envelope.completeness === "COMPLETE";
  if (renderable.length === 0) {
    const sound = populationComplete && envelope.availability === "AVAILABLE";
    if (sound) return ["EMPTY_VERIFIED"];
    return [envelope.availability === "AVAILABLE" ? "PARTIAL" : envelope.availability];
  }
  return envelope.completeness === "PARTIAL"
    ? [envelope.availability, "PARTIAL"]
    : [envelope.availability];
}

/**
 * The states the performance overview PRESENTS for a settled read: the envelope's own
 * state, and `PARTIAL` where any of its three series did not cover its whole extent — the
 * panel badges a gapped series `PARTIAL` rather than drawing through the gap.
 */
export function performancePresentedStates(
  envelope: EnvelopeOf<PerformanceSeriesPayload>,
): readonly AvailabilityState[] {
  const payload = envelope.payload;
  if (payload === undefined) {
    return [envelope.availability];
  }
  const gapped = [payload.equity, payload.return_series, payload.drawdown_series].some(
    (series) => series.completeness !== "COMPLETE",
  );
  return gapped ? [envelope.availability, "PARTIAL"] : [envelope.availability];
}
