"use client";

import * as React from "react";
import Link from "next/link";

import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Label,
  Numeric,
  ScrollRegion,
  type LabelElement,
} from "@/components/ui/primitives";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { AttentionPanel } from "@/components/cockpit/attention";
import { MetricTile, MetricTileSkeleton } from "@/components/cockpit/metric-tile";
import { SummaryDisclosure, useSummaryLayout } from "@/components/cockpit/mobile-summary";
import { PageHeader } from "@/components/cockpit/page-header";
import { PerformanceOverview } from "@/components/cockpit/performance-chart";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { WhatChangedPanel } from "@/components/cockpit/what-changed";
import { useScope } from "@/components/shell/use-scope";
import {
  useAttention,
  useExecutiveOverview,
  usePerformanceSeries,
  useQualificationStatus,
  useWhatChanged,
} from "@/data/client/hooks";
import type { MetricValue } from "@/contracts/values";
import type { DataProvenance } from "@/contracts/vocabularies";
import { METRIC_DEFINITION_VERSION, notImplemented } from "@/contracts/factories";
import { isValueBearing } from "@/contracts/validity";
import { prepareAttention } from "@/lib/attention";
import { formatDecimal, formatInstant, humanizeCode } from "@/lib/format";
import {
  disclosureAvailabilityStates,
  disclosureProvenances,
  pendingWidget,
  performancePresentedStates,
  settledWidget,
  whatChangedPresentedStates,
  type WidgetRead,
} from "@/lib/mobile-summary";
import { withScope, type PerformancePeriod } from "@/lib/scope";
import { ROUTES_BY_HREF } from "@/nav/registry";
import { cn } from "@/lib/utils";

/**
 * The Executive Overview — the composed landing page.
 *
 * THE TEN-SECOND TEST (`ui-ux-specification.md` §2) is an ACCEPTANCE CRITERION, not an
 * aspiration: the five questions are answered in the first viewport at 1440 × 900, and each
 * answer links to the area that owns it. Each tile is labelled with its QUESTION, so whether
 * the test passes is something a reader can check rather than something a designer asserts.
 *
 *   How are we doing?   Where is risk?   Is anything wrong?
 *   What changed?       What requires attention?
 *
 * THREE TIERS, and the tiering is the specification (§6):
 *
 *   TIER 1  the five ten-second answers -- large numerics, first viewport, no scrolling
 *   TIER 2  supporting context -- exposure, regime, freshness, active strategies
 *   TIER 3  What Changed, and the ranked Attention Required list
 *
 * Attention sits directly under tier 1 rather than after tier 2, because §6 also requires it
 * in the first viewport: "an attention list below the fold is a list nobody reads".
 *
 * BELOW 640 CSS PIXELS THE PAGE IS THE EXECUTIVE SUMMARY, AND NOTHING IS OMITTED (ADR-0033
 * §2, Decision M; `ui-ux-specification.md` §12.1). The shell, the header with its page-level
 * state badge, the six tier-1 tiles, Attention Required and — in the project scenario — the
 * explanation of the unavailable state render first; What Changed's detail, the performance
 * overview, the tier-2 supporting context and, in Operator mode, the response evidence stay
 * on this page behind labelled disclosures (`SummaryDisclosure`). No section moves to another
 * route, because no route owns What Changed or the tier-2 tiles. At 640 pixels and above
 * every section renders exactly as it always has, with no disclosure control.
 *
 * NO EQUITY, PERFORMANCE, EXPOSURE, INCIDENT, SYSTEM-HEALTH OR TRADE STATISTIC IS
 * FABRICATED. In the default project scope every operational read model reports that its
 * producing subsystem does not exist; the synthetic scenario is labelled unmissably.
 *
 * THREE DEPTHS OF READING, after the owner found the first cut slow to digest:
 *
 *   AT A GLANCE       the six answers -- a large figure, its unit, its availability, its
 *                     provenance, one line of context, and the area it belongs to
 *   ONE STEP DEEPER   Attention Required, What Changed, the performance overview with its
 *                     stated window, the supporting context
 *   ON DEMAND         each tile's "About …" disclosure with the contract explanation, the
 *                     chart's table alternative, and Operator mode's response evidence
 *
 * Nothing the reader must not miss is on demand: availability, provenance, freshness, the
 * page-level PARTIAL state, the health state and the no-baseline explanation stay visible.
 */

/**
 * One of the five answers.
 *
 * The QUESTION is the label. A tile headed "Return" answers a question the reader has to
 * infer; a tile headed "How are we doing?" answers the one §2 actually asks.
 *
 * THE READING ORDER IS THE HIERARCHY (§4.4: one primary number per tile, its comparison
 * secondary, its metadata tertiary). The owner found the first cut of this page "clumsy,
 * text-heavy and slow to digest", and each of the following was measured in the rendered
 * page rather than assumed: the figure was set at `numeric-l` under an uppercase subject of
 * near-equal weight, so nothing on a tile was the largest thing on it; every tile carried a
 * one-or-two-sentence caveat in the first viewport; six links read "Open the area that owns
 * this"; and the What Changed footer quoted a millisecond ISO instant. So now:
 *
 *   question        small, accent            what is being asked
 *   subject         secondary, sentence case what the figure is
 *   FIGURE          numeric-xl, primary      the answer, with its unit and its availability
 *   context         tertiary, one line       the comparison, the as-of, the basis
 *   link            the registered AREA      where to go next, named as the area is named
 *   details         collapsed by default     the contract explanations -- supporting prose,
 *                                            and never an availability state, a provenance,
 *                                            a warning or an action-blocking reason
 *
 * WHAT NEVER MOVES INTO THE DETAILS: the availability badge, the provenance badge, the
 * page-level PARTIAL state, the health state, the no-baseline explanation. A collapsed
 * disclosure may hide an explanation; it may never hide that something is wrong (ADR-0033 M4).
 */
function AnswerTile({
  question,
  subject,
  children,
  context,
  details,
  detailsLabel,
  href,
  provenance,
  testId,
}: {
  question: string;
  subject: string;
  children: React.ReactNode;
  /** The one-line comparison or basis under the figure. Tertiary, and always visible. */
  context?: React.ReactNode;
  /** The contract explanation. Supporting prose, behind an accessible disclosure. */
  details?: React.ReactNode;
  /** The disclosure's own name -- distinct per tile, so six controls are six names. */
  detailsLabel?: string;
  href?: string;
  provenance?: React.ReactNode;
  testId: string;
}) {
  /*
   * THE LINK NAMES THE AREA, AND THE REGISTRY NAMES THE AREA. `ui-ux-specification.md` §3:
   * "Executive tile -> the area that owns the number", and an area control names the area
   * (ADR-0031). The label is read from the typed registry rather than typed here, so a tile
   * cannot name a destination that does not exist, and cannot name a record -- these are area
   * destinations, never a specific authorized target. A destination absent from the registry
   * is a defect, not a fallback: the tile renders no link rather than an unnamed one.
   */
  const destination = href === undefined ? undefined : ROUTES_BY_HREF.get(pathOf(href));
  return (
    <Card className="flex h-full flex-col" data-testid={testId}>
      <CardBody className="flex flex-1 flex-col gap-1.5 pt-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-label-s font-medium uppercase tracking-[0.09em] text-accent">
              {question}
            </p>
            <p className="mt-0.5 min-w-0 break-words text-label-m text-text-secondary">
              {subject}
            </p>
          </div>
          {provenance}
        </div>
        <div className="flex flex-1 flex-col justify-center py-1">{children}</div>
        {context !== undefined && (
          <div className="text-label-s leading-relaxed text-text-tertiary" data-tile-part="context">
            {context}
          </div>
        )}
        {/*
          * BOTH CONTROLS ARE AT LEAST 24 CSS PIXELS TALL. The first cut set the link at
          * `label-m` and the summary at `label-s`, stacked 6 px apart, and the axe sweep failed
          * WCAG 2.2 `target-size` on `/` at every width: two adjacent pointer targets of 18 and
          * 16 px. The text sizes stay; the boxes meet the minimum (§11, "target size").
          */}
        {href !== undefined && destination !== undefined && (
          <Link
            href={href}
            className="inline-flex min-h-6 items-center self-start text-label-m font-medium text-accent underline underline-offset-2"
            data-tile-part="destination"
          >
            {destination.label} →
          </Link>
        )}
        {details !== undefined && (
          <details className="group text-label-s text-text-tertiary" data-tile-part="details">
            <summary className="flex min-h-6 cursor-pointer select-none items-center text-text-tertiary hover:text-text-secondary">
              {detailsLabel ?? `About ${subject.charAt(0).toLowerCase()}${subject.slice(1)}`}
            </summary>
            <div className="mt-1 leading-relaxed">{details}</div>
          </details>
        )}
      </CardBody>
    </Card>
  );
}

/** The path of a scoped href, so a registry lookup ignores the query the scope appended. */
function pathOf(href: string): string {
  const cut = href.indexOf("?");
  return cut === -1 ? href : href.slice(0, cut);
}

/**
 * A large figure, or the availability state standing in place of one. Never both, never zero.
 *
 * `neutral` MARKS A MAGNITUDE, on the rule `MetricTile` already applies: a leading plus is a
 * claim about direction and green is the colour of a GAIN (§4.3 `--positive`: "gains and
 * healthy states"). Open planned risk is neither -- it is money at risk -- so `+757.15 USD`
 * in green read as a profit, which is the confusion the owner named. A neutral figure keeps a
 * minus where one belongs and is otherwise the primary text colour.
 */
function Figure({
  metric,
  dependency,
  neutral = false,
}: {
  metric: MetricValue;
  dependency: string;
  neutral?: boolean;
}) {
  if (!isValueBearing(metric.availability)) {
    return (
      <UnavailableBody
        state={metric.availability}
        reason={metric.reason}
        dependency={dependency}
      />
    );
  }
  const signed = !neutral && (metric.unit === "USD" || metric.unit === "PERCENT");
  const decimal =
    typeof metric.value === "string"
      ? formatDecimal(metric.value, { minimumFractionDigits: 2, signed })
      : null;
  const negative = typeof metric.value === "string" && metric.value.startsWith("-");
  const nonZero = /[1-9]/.test(String(metric.value));
  return (
    <div className="space-y-1.5">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <Numeric
          size="xl"
          className={cn(
            signed && nonZero
              ? negative
                ? "text-negative"
                : "text-positive"
              : "text-text-primary",
          )}
        >
          {decimal ?? String(metric.value)}
        </Numeric>
        <span className="text-label-m text-text-tertiary">
          {metric.unit === "USD" ? "USD" : metric.unit === "PERCENT" ? "%" : ""}
        </span>
      </div>
      {metric.availability !== "AVAILABLE" && (
        <AvailabilityBadge
          state={metric.availability}
          reason={metric.reason}
          className="self-start"
        />
      )}
    </div>
  );
}

export default function ExecutiveOverviewPage() {
  const { scope, setScope } = useScope();
  const overview = useExecutiveOverview(scope);
  const attention = useAttention(scope);
  const whatChanged = useWhatChanged(scope);
  const qualification = useQualificationStatus(scope);
  const performance = usePerformanceSeries(scope);
  const operator = scope.mode === "operator";
  /*
   * Below the breakpoint each deferred panel's title renders as a span: the disclosure
   * control's `h2` is the section's one listing in heading navigation (ADR-0033 M5), and a
   * second heading with the same or a near-identical name inside the revealed content would
   * list it twice. The visual treatment is identical either way.
   */
  const panelTitle: LabelElement = useSummaryLayout() === "summary" ? "span" : "h2";

  const envelope = overview.data;
  const payload = envelope?.payload;
  const degraded =
    envelope !== undefined &&
    (envelope.availability !== "AVAILABLE" ||
      (payload?.tile_availability ?? []).some((tile) => tile.availability !== "AVAILABLE"));

  const qualificationEnvelope = qualification.data;
  const qualificationPayload = qualificationEnvelope?.payload;
  /*
   * The qualification read model is unavailable outside the RESEARCH environment, because
   * no Paper or Live governance record exists. A settled response with no payload is an
   * ABSENCE and must render as one: a perpetual loading skeleton implies data is coming,
   * and `0 of 0` open gates is a fabricated measurement of a thing nobody read.
   */
  const qualificationAbsent =
    qualificationEnvelope !== undefined && qualificationPayload === undefined;
  const gates = qualificationPayload?.gates ?? [];
  // A tracked governance constant, read from the enumerated governance read model rather
  // than hardcoded into a component (CLAUDE.md section 6).
  const strategyCapital = qualificationPayload?.facts.find(
    (fact) => fact.fact_id === "strategy-capital",
  )?.state.code;
  const openGates = gates.filter((gate) => gate.state === "OPEN").length;

  /*
   * The attention and change SUMMARIES come from the same pipelines the panels below use, so
   * the count in the first viewport and the list under it cannot disagree.
   */
  const attentionPayload = attention.data?.payload;
  const rankedAttention =
    attentionPayload === undefined ? undefined : prepareAttention(attentionPayload.items);
  const topAttention = rankedAttention?.visible[0];
  const changesPayload = whatChanged.data?.payload;
  const noBaseline = changesPayload?.baseline_state !== undefined;

  const onPeriodChange = React.useCallback(
    (period: PerformancePeriod) => setScope({ period }),
    [setScope],
  );

  /*
   * THE TIER-2 METRICS, stated once so the tiles and the mobile disclosure that defers them
   * read the same values: a control's badge that disagreed with the tile behind it would
   * report one state on the outside and another within.
   */
  const brokerEquityMetric: MetricValue =
    payload?.broker_reported_equity ?? notImplemented("portfolio.broker_reported_equity", "USD");
  const drawdownMetric: MetricValue =
    payload?.drawdown ?? notImplemented("drawdown.current", "PERCENT");
  const permittedRiskMetric: MetricValue = {
    value: payload?.permitted_open_risk.record?.limit_money.value,
    unit: "USD",
    availability: payload?.permitted_open_risk.availability ?? "NOT_IMPLEMENTED",
    reason: payload?.permitted_open_risk.reason ?? "PRODUCER_NOT_IMPLEMENTED",
    as_of: payload?.permitted_open_risk.as_of,
    metric_id: "risk.permitted",
    metric_definition_version: METRIC_DEFINITION_VERSION,
  };
  const tileProvenance: DataProvenance = envelope?.provenance ?? "SYNTHETIC";

  /*
   * WHAT EACH DEFERRED SECTION'S CONTROL CARRIES BELOW THE BREAKPOINT (ADR-0033 M5, M6).
   *
   * Every widget inside a deferred section is listed with the states it PRESENTS and the
   * provenance it DISPLAYS, from the same values it renders from. A pending read is listed
   * as pending and contributes nothing; a settled widget contributes every state it shows
   * as its own -- the last-runs tile shows two absent records, so it contributes both. The
   * rule that turns these into badges is the vocabulary's own order, and it is local to the
   * disclosure: every widget inside keeps its own badge exactly as before.
   */
  const metricWidget = (metric: MetricValue): WidgetRead =>
    settledWidget(
      metric.availability,
      isValueBearing(metric.availability) ? tileProvenance : undefined,
    );
  const whatChangedWidgets: readonly WidgetRead[] = [
    whatChanged.data === undefined
      ? pendingWidget()
      : settledWidget(
          whatChangedPresentedStates(whatChanged.data),
          changesPayload === undefined ? undefined : whatChanged.data.provenance,
        ),
  ];
  const performanceWidgets: readonly WidgetRead[] = [
    performance.data === undefined
      ? pendingWidget()
      : settledWidget(
          performancePresentedStates(performance.data),
          performance.data.payload === undefined ? undefined : performance.data.provenance,
        ),
  ];
  const supportingContextWidgets: readonly WidgetRead[] = [
    // The gates tile: a tracked governance fact, so its provenance is known before its value.
    qualificationEnvelope === undefined
      ? pendingWidget("REPOSITORY_TRACKED")
      : qualificationAbsent
        ? settledWidget(qualificationEnvelope.availability, "REPOSITORY_TRACKED")
        : settledWidget("AVAILABLE", "REPOSITORY_TRACKED"),
    ...(envelope === undefined
      ? [pendingWidget(), pendingWidget(), pendingWidget(), pendingWidget(), pendingWidget()]
      : [
          metricWidget(brokerEquityMetric),
          metricWidget(drawdownMetric),
          metricWidget(permittedRiskMetric),
          // Exposure: the payload's own figures, or the envelope's state standing in for them.
          payload === undefined
            ? settledWidget(envelope.availability)
            : settledWidget("AVAILABLE", envelope.provenance),
          // Regime and the two last-run records: each record's own state, both reported.
          payload === undefined
            ? settledWidget(envelope.availability)
            : settledWidget([
                payload.last_decision.at.availability,
                payload.last_scout_run.at.availability,
              ]),
        ]),
  ];
  const responseEvidenceWidgets: readonly WidgetRead[] =
    envelope === undefined
      ? [pendingWidget()]
      : [settledWidget(envelope.availability, envelope.provenance)];

  return (
    <>
      <PageHeader
        title={operator ? "Executive Overview — Operator" : "Executive Overview"}
        summary={
          operator
            ? "The same read models, with reason codes, metric identities, contract versions, watermarks, pins and provenance exposed for evidence."
            : "Status, attention and change, answered before detail. Every figure carries its source and its availability."
        }
        pageState={degraded ? "PARTIAL" : "COMPLETE"}
      />

      {/* TIER 1 -- the five ten-second answers, in the first viewport. */}
      <section aria-labelledby="tier-one" className="mb-2">
        <h2 id="tier-one" className="sr-only">
          The five ten-second answers
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {/* Strategy capital is AUTHORITATIVE and is never broker-reported equity. */}
          <AnswerTile
            question="What are we risking against?"
            subject="Strategy capital"
            testId="tile-strategy-capital"
            provenance={<ProvenanceBadge provenance="REPOSITORY_TRACKED" className="shrink-0" />}
            href={withScope("/governance/qualification", scope)}
            context="Authoritative. Not broker-reported equity."
            detailsLabel="About strategy capital"
            details={
              <>
                A tracked governance fact, read from the repository&apos;s enumerated governance
                record. Broker-reported equity is <strong>observed</strong> for reconciliation
                and is never substituted for it: the broker may report USD 1,000,000 while the
                capital every risk figure is measured against stays this number.
              </>
            }
          >
            {qualificationAbsent ? (
              <UnavailableBody
                state={qualificationEnvelope.availability}
                reason={qualificationEnvelope.availability_reason}
                dependency="the tracked governance record for this environment"
              />
            ) : strategyCapital === undefined ? (
              <div className="skeleton-shape h-9 w-2/3" data-testid="skeleton" />
            ) : (
              <div className="flex flex-wrap items-baseline gap-x-2">
                <Numeric size="xl" className="text-text-primary">
                  {formatDecimal(strategyCapital, { minimumFractionDigits: 2 })}
                </Numeric>
                <span className="text-label-m text-text-tertiary">USD</span>
              </div>
            )}
          </AnswerTile>

          {/*
            * THE HEADLINE RETURN STATES ITS AS-OF AND SAYS ITS WINDOW IS NOT STATED. The
            * overview read model carries `return_pct` with its method and its as-of and NO
            * window (read-model-contracts, "Executive"); the performance overview below
            * carries a declared window and the period the reader selects. Labelling this
            * figure with the chart's period would assert that two metrics share a window
            * their contracts never established, and computing one to reconcile them would
            * be a period-adjusted figure nobody produced. So each says what it is.
            */}
          <AnswerTile
            question="How are we doing?"
            subject="Total return, time-weighted"
            testId="answer-performance"
            provenance={
              payload !== undefined && envelope !== undefined ? (
                <ProvenanceBadge provenance={envelope.provenance} className="shrink-0" />
              ) : undefined
            }
            href={withScope("/portfolio/performance", scope)}
            context={
              payload === undefined || envelope === undefined ? undefined : (
                <>
                  <span data-tile-part="day-realized">
                    Day realized{" "}
                    <span className="font-mono text-text-secondary">
                      {(() => {
                        const day = payload.pnl.find((entry) => entry.window === "DAY")?.realized;
                        return day !== undefined && isValueBearing(day.availability)
                          ? `${formatDecimal(String(day.value), {
                              minimumFractionDigits: 2,
                              signed: true,
                            })} USD`
                          : "unavailable";
                      })()}
                    </span>
                  </span>
                  <br />
                  <span data-tile-part="window-note">
                    As of {formatInstant(payload.return_pct.as_of ?? envelope.as_of_time)}.
                    Window: not stated by this read model — the chart below states its own.
                  </span>
                </>
              )
            }
            detailsLabel="About the return figure"
            details={
              <>
                Chain-linked across every external cash flow, so a deposit is never a profit.
                Realized and unrealized are separate figures and are never summed into one.
                This figure and the performance chart are two separate measurements: the
                chart is drawn over the period you select and says so; this one carries its
                own as-of and no declared window.
              </>
            }
          >
            {overview.isPending ? (
              <div className="skeleton-shape h-9 w-2/3" data-testid="skeleton" />
            ) : (
              <Figure
                metric={payload?.return_pct ?? notImplemented("return.time_weighted", "PERCENT")}
                dependency="the portfolio valuation projection"
              />
            )}
          </AnswerTile>

          <AnswerTile
            question="Where is risk?"
            subject="Current open planned risk"
            testId="answer-risk"
            provenance={
              payload !== undefined && envelope !== undefined ? (
                <ProvenanceBadge provenance={envelope.provenance} className="shrink-0" />
              ) : undefined
            }
            href={withScope("/risk", scope)}
            context={
              payload?.open_planned_risk.record === undefined ? undefined : (
                <>
                  {isValueBearing(
                    payload.open_planned_risk.record.risk_pct_of_capital.availability,
                  ) &&
                  typeof payload.open_planned_risk.record.risk_pct_of_capital.value ===
                    "string" ? (
                    <span data-tile-part="risk-pct">
                      <span className="font-mono text-text-secondary">
                        {formatDecimal(
                          payload.open_planned_risk.record.risk_pct_of_capital.value,
                          { minimumFractionDigits: 2 },
                        )}
                        {" %"}
                      </span>{" "}
                      of strategy capital ·{" "}
                    </span>
                  ) : null}
                  assessed {formatInstant(payload.open_planned_risk.record.as_of)}
                </>
              )
            }
            detailsLabel="About open planned risk"
            details={
              <>
                The risk engine&apos;s assessment of the remaining planned exposure, as of the
                instant shown. It is a magnitude, not a gain. Permitted open risk is a{" "}
                <strong>separate</strong> policy fact, and drawdown a third; neither is derived
                from this one.
              </>
            }
          >
            {overview.isPending ? (
              <div className="skeleton-shape h-9 w-2/3" data-testid="skeleton" />
            ) : (
              <Figure
                neutral
                metric={
                  payload?.open_planned_risk.record !== undefined
                    ? {
                        value: payload.open_planned_risk.record.risk_money.value,
                        unit: "USD",
                        availability: payload.open_planned_risk.availability,
                        reason: payload.open_planned_risk.reason,
                        as_of: payload.open_planned_risk.as_of,
                        metric_id: "risk.open_planned",
                        metric_definition_version: METRIC_DEFINITION_VERSION,
                      }
                    : {
                        unit: "USD",
                        availability:
                          payload?.open_planned_risk.availability ?? "NOT_IMPLEMENTED",
                        reason: payload?.open_planned_risk.reason ?? "PRODUCER_NOT_IMPLEMENTED",
                        metric_id: "risk.open_planned",
                        metric_definition_version: METRIC_DEFINITION_VERSION,
                      }
                }
                dependency="the risk engine and a versioned risk-policy reference"
              />
            )}
          </AnswerTile>

          <AnswerTile
            question="Is anything wrong?"
            subject="System health and open incidents"
            testId="answer-health"
            href={withScope("/system/operations", scope)}
            detailsLabel="About system health"
            details="Health is a recorded state, never inferred from the absence of an alert. An open-incident count is a completed query, and an empty one is a verified empty answer rather than a measured zero."
          >
            {overview.isPending ? (
              <div className="skeleton-shape h-9 w-2/3" data-testid="skeleton" />
            ) : payload === undefined ? (
              <UnavailableBody
                state={envelope?.availability ?? "NOT_IMPLEMENTED"}
                reason={envelope?.availability_reason ?? "PRODUCER_NOT_IMPLEMENTED"}
                dependency="the alerting subsystem and the operations projection"
              />
            ) : (
              <div className="space-y-2">
                <Badge tone="warning">{humanizeCode(payload.system_health.code)}</Badge>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-label-m text-text-tertiary">Open incidents:</span>
                  {isValueBearing(payload.open_incidents.availability) ? (
                    <>
                      <Numeric size="m" className="text-text-primary">
                        {String(payload.open_incidents.value)}
                      </Numeric>
                      {payload.open_incidents.availability !== "AVAILABLE" && (
                        <AvailabilityBadge
                          state={payload.open_incidents.availability}
                          reason={payload.open_incidents.reason}
                        />
                      )}
                    </>
                  ) : (
                    <AvailabilityBadge
                      state={payload.open_incidents.availability}
                      reason={payload.open_incidents.reason}
                    />
                  )}
                </div>
              </div>
            )}
          </AnswerTile>

          {/*
            * THE BASELINE IS NAMED AND DATED, READABLY. The read model's own `baseline_label`
            * is the subject where one exists; the baseline instant renders to the minute with
            * its timezone, and its full-precision form stays in the What Changed panel below.
            * The no-baseline explanation is never deferred: it is what the count would
            * otherwise be misread as.
            */}
          <AnswerTile
            question="What changed?"
            subject={changesPayload?.baseline_label ?? "Since the stated baseline"}
            testId="answer-changed"
            href={withScope("/governance/audit", scope)}
            context={
              changesPayload === undefined
                ? undefined
                : noBaseline
                  ? "No prior endpoint exists, so no change is listed and none is inferred."
                  : `Baseline ${
                      changesPayload.baseline_as_of === undefined
                        ? "absent"
                        : formatInstant(changesPayload.baseline_as_of)
                    }.`
            }
            detailsLabel="About this comparison"
            details="A comparison needs a stated baseline, and this one says it on the screen: both endpoints carry their as-of, an appearance or a disappearance is a change, and an unavailable endpoint reports its state instead of a delta. The audit trail is where the recorded events live; it does not own this comparison."
          >
            {whatChanged.data === undefined ? (
              <div className="skeleton-shape h-9 w-2/3" data-testid="skeleton" />
            ) : changesPayload === undefined ? (
              <UnavailableBody
                state={whatChanged.data.availability}
                reason={whatChanged.data.availability_reason}
                dependency="a baseline endpoint and a comparison endpoint"
              />
            ) : noBaseline && changesPayload.baseline_state !== undefined ? (
              <AvailabilityBadge
                state={changesPayload.baseline_state.availability}
                reason={changesPayload.baseline_state.reason}
              />
            ) : changesPayload.entries.length === 0 ? (
              <div className="space-y-1.5">
                <Numeric size="xl" className="text-text-primary">
                  0
                </Numeric>
                <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
              </div>
            ) : (
              <div className="flex flex-wrap items-baseline gap-x-2">
                <Numeric size="xl" className="text-text-primary">
                  {changesPayload.entries.length}
                </Numeric>
                <span className="text-label-m text-text-tertiary">
                  change{changesPayload.entries.length === 1 ? "" : "s"}
                </span>
              </div>
            )}
          </AnswerTile>

          <AnswerTile
            question="What requires attention?"
            subject="Open items, ranked"
            testId="answer-attention"
            href={withScope("/attention", scope)}
            context={
              topAttention === undefined
                ? undefined
                : `Highest: ${humanizeCode(topAttention.what_happened.code)}.`
            }
            detailsLabel="About the attention list"
            details="Ranked by materiality then severity, and deduplicated against the alert feed. Every item shows what happened, why it matters, its impact, its evidence and a permitted governance action for a person; the Cockpit performs none of them."
          >
            {attention.data === undefined ? (
              <div className="skeleton-shape h-9 w-2/3" data-testid="skeleton" />
            ) : attentionPayload === undefined ? (
              <UnavailableBody
                state={attention.data.availability}
                reason={attention.data.availability_reason}
                dependency="the attention projection and the alert feed"
              />
            ) : rankedAttention !== undefined && rankedAttention.rankedTotal === 0 ? (
              <div className="space-y-1.5">
                <Numeric size="xl" className="text-text-primary">
                  0
                </Numeric>
                <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
              </div>
            ) : (
              <div className="flex flex-wrap items-baseline gap-x-2">
                <Numeric size="xl" className="text-text-primary">
                  {rankedAttention?.rankedTotal ?? 0}
                </Numeric>
                <span className="text-label-m text-text-tertiary">
                  item{rankedAttention?.rankedTotal === 1 ? "" : "s"}
                </span>
                {topAttention !== undefined && (
                  <Badge
                    tone={
                      topAttention.severity.code === "HIGH"
                        ? "negative"
                        : topAttention.severity.code === "MEDIUM"
                          ? "warning"
                          : "neutral"
                    }
                    className="ml-1"
                  >
                    {topAttention.severity.code}
                  </Badge>
                )}
              </div>
            )}
          </AnswerTile>
        </div>
      </section>

      {/*
        * ATTENTION AND CHANGE, in the first viewport at the reference desktop width. §6 puts
        * them in tier 3 of the hierarchy and still requires attention above the fold, because
        * "an attention list below the fold is a list nobody reads".
        */}
      <section
        aria-labelledby="attention-and-change"
        className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-2"
      >
        <h2 id="attention-and-change" className="sr-only">
          Attention and change
        </h2>
        {attention.data === undefined ? (
          <Card>
            <CardHeader>
              <Label as="h2">Attention required</Label>
            </CardHeader>
            <CardBody>
              <div className="skeleton-shape h-16 w-full" data-testid="skeleton" />
            </CardBody>
          </Card>
        ) : (
          <AttentionPanel
            envelope={attention.data}
            scope={scope}
            operator={operator}
            limit={2}
          />
        )}

        {/*
          * THE PANEL'S DETAIL IS DEFERRED BELOW THE BREAKPOINT; THE TILE ABOVE IT IS NOT. The
          * disclosure wraps the panel's card and not this section, which the attention panel
          * shares and which stays visible. Its label is the panel's heading with a suffix, so
          * the deferred detail is never confused with the tier-1 "What changed?" answer.
          */}
        <SummaryDisclosure
          id="what-changed"
          headingId="what-changed-details"
          fullWidthHeading={null}
          availability={disclosureAvailabilityStates(whatChangedWidgets)}
          provenance={disclosureProvenances(whatChangedWidgets)}
        >
          {whatChanged.data === undefined ? (
            <Card className="h-full">
              <CardHeader>
                <Label as={panelTitle}>What changed</Label>
              </CardHeader>
              <CardBody>
                <div className="skeleton-shape h-16 w-full" data-testid="skeleton" />
              </CardBody>
            </Card>
          ) : (
            <WhatChangedPanel
              envelope={whatChanged.data}
              scope={scope}
              operator={operator}
              withVariants={scope.scenario === "demo"}
              className="h-full"
              titleElement={panelTitle}
            />
          )}
        </SummaryDisclosure>
      </section>

      {/* The performance overview. Below the ten-second answers, and above the detail. */}
      <section aria-labelledby="performance" className="mb-6">
        <SummaryDisclosure
          id="performance-overview"
          headingId="performance"
          fullWidthHeading={{ className: "sr-only" }}
          availability={disclosureAvailabilityStates(performanceWidgets)}
          provenance={disclosureProvenances(performanceWidgets)}
        >
          <PerformanceOverview
            envelope={performance.data}
            scope={scope}
            operator={operator}
            onPeriodChange={onPeriodChange}
            titleElement={panelTitle}
            summary="Equity, return and drawdown over the period selected here. An overview, not the full portfolio performance analysis."
            statedWindow
          />
        </SummaryDisclosure>
      </section>

      {/* TIER 2 -- supporting context. */}
      <section aria-labelledby="tier-two" className="mb-6">
        <SummaryDisclosure
          id="supporting-context"
          headingId="tier-two"
          fullWidthHeading={{ className: "mb-2 text-label-m font-semibold text-text-secondary" }}
          availability={disclosureAvailabilityStates(supportingContextWidgets)}
          provenance={disclosureProvenances(supportingContextWidgets)}
        >
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Card data-testid="tile-open-gates">
            <CardBody className="space-y-2 pt-4">
              <div className="flex items-start justify-between gap-2">
                <Label className="min-w-0 break-words">Open decision gates</Label>
                <ProvenanceBadge provenance="REPOSITORY_TRACKED" className="shrink-0" />
              </div>
              {qualification.isPending ? (
                <div className="skeleton-shape h-8 w-16" data-testid="skeleton" />
              ) : qualificationAbsent ? (
                <UnavailableBody
                  state={qualificationEnvelope.availability}
                  reason={qualificationEnvelope.availability_reason}
                  dependency="the tracked governance record for this environment"
                />
              ) : (
                <>
                  <div className="flex items-baseline gap-1.5">
                    <Numeric size="l" className="text-text-primary">
                      {openGates}
                    </Numeric>
                    <span className="text-label-m text-text-tertiary">of {gates.length}</span>
                  </div>
                  <Link
                    href={withScope("/governance/qualification", scope)}
                    className="inline-block text-label-s text-accent underline underline-offset-2"
                  >
                    Each gate is read on its own →
                  </Link>
                </>
              )}
            </CardBody>
          </Card>

          {overview.isPending ? (
            <>
              <MetricTileSkeleton label="Broker-reported equity" />
              <MetricTileSkeleton label="Drawdown" />
              <MetricTileSkeleton label="Permitted open risk" />
            </>
          ) : (
            <>
              {/*
                * OBSERVED BALANCES AND POLICY LIMITS ARE MAGNITUDES. A broker balance of
                * +1,000,000.00 in green read as a gain; it is an observed, informational
                * figure that never participates in sizing. Permitted open risk is what policy
                * allows, not a profit. Drawdown stays directional: it measures a loss.
                */}
              <MetricTile
                label="Broker-reported equity"
                metric={brokerEquityMetric}
                provenance={tileProvenance}
                dependency="an authorized brokerage session"
                operator={operator}
                size="m"
                neutral
              />
              <MetricTile
                label="Drawdown"
                metric={drawdownMetric}
                provenance={tileProvenance}
                dependency="the portfolio valuation projection"
                operator={operator}
                size="m"
                denominator="running peak equity"
              />
              <MetricTile
                label="Permitted open risk"
                metric={permittedRiskMetric}
                provenance={tileProvenance}
                dependency="a versioned risk-policy reference"
                operator={operator}
                size="m"
                neutral
              />
            </>
          )}
        </div>

        {/* Exposure, regime and the two last-run records. */}
        <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-2">
          <Card data-testid="tile-exposure">
            <CardHeader className="flex items-center justify-between gap-2">
              <Label as="h3">Exposure</Label>
              {payload !== undefined && envelope !== undefined && (
                <ProvenanceBadge provenance={envelope.provenance} />
              )}
            </CardHeader>
            <CardBody>
              {payload === undefined ? (
                <UnavailableBody
                  state={envelope?.availability ?? "NOT_IMPLEMENTED"}
                  reason={envelope?.availability_reason ?? "PRODUCER_NOT_IMPLEMENTED"}
                  dependency="the positions projection"
                />
              ) : (
                <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
                  {(["long", "short", "gross", "net"] as const).map((leg) => (
                    <div key={leg}>
                      <dt>
                        <Label>{leg}</Label>
                      </dt>
                      <dd className="mt-0.5 flex items-baseline gap-1">
                        <Numeric size="m" className="text-text-primary">
                          {formatDecimal(payload.exposure[leg].amount, {
                            minimumFractionDigits: 2,
                          })}
                        </Numeric>
                        <span className="text-label-s text-text-tertiary">
                          {payload.exposure[leg].direction}
                        </span>
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
              <p className="mt-3 text-label-s text-text-tertiary">
                Exposure carries magnitude and direction; it never carries a profit sign.
              </p>
            </CardBody>
          </Card>

          <Card data-testid="tile-last-runs">
            <CardHeader>
              <Label as="h3">Regime, last decision and last scout run</Label>
            </CardHeader>
            <CardBody className="space-y-3">
              {payload === undefined ? (
                <UnavailableBody
                  state={envelope?.availability ?? "NOT_IMPLEMENTED"}
                  reason={envelope?.availability_reason ?? "PRODUCER_NOT_IMPLEMENTED"}
                  dependency="the market-regime projection and the Strategy Brain runtime"
                />
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <Label>Market regime</Label>
                    <Badge tone="unavailable">{payload.regime_ref.resolution}</Badge>
                    <span className="font-mono text-label-s text-text-tertiary">
                      {payload.regime_ref.ref_kind} · {payload.regime_ref.ref_id}
                    </span>
                  </div>
                  {(
                    [
                      ["Last decision", payload.last_decision],
                      ["Last scout run", payload.last_scout_run],
                    ] as const
                  ).map(([label, record]) => (
                    <div key={label} className="flex flex-wrap items-center gap-2">
                      <Label>{label}</Label>
                      {isValueBearing(record.at.availability) ? (
                        <span className="font-mono text-numeric-s text-text-primary">
                          {String(record.at.value)}
                        </span>
                      ) : (
                        <AvailabilityBadge
                          state={record.at.availability}
                          reason={record.at.reason}
                        />
                      )}
                      <span className="font-mono text-label-s text-text-tertiary">
                        {record.ref.ref_kind} · {record.ref.resolution}
                      </span>
                    </div>
                  ))}
                  <p className="text-label-s leading-relaxed text-text-tertiary">
                    The Strategy Brain runtime is{" "}
                    <strong>not implemented and not authorized</strong>, so no decision and no
                    scout run has ever happened. A plausible date here would be the one figure
                    on this page implying otherwise.
                  </p>
                </>
              )}
            </CardBody>
          </Card>
        </div>
        </SummaryDisclosure>
      </section>

      {operator && envelope !== undefined && (
        <section aria-labelledby="operator-evidence" className="mt-6">
        <SummaryDisclosure
          id="response-evidence"
          headingId="operator-evidence"
          fullWidthHeading={{ className: "mb-2 text-label-m font-semibold text-text-secondary" }}
          availability={disclosureAvailabilityStates(responseEvidenceWidgets)}
          provenance={disclosureProvenances(responseEvidenceWidgets)}
        >
          <Card>
            <CardBody className="space-y-4 pt-4">
              <ScrollRegion label="Response evidence fields">
                <dl className="grid min-w-[36rem] grid-cols-2 gap-x-6 gap-y-1.5 font-mono text-label-s sm:grid-cols-3">
                  {(
                    [
                      ["schema_version", envelope.schema_version],
                      ["api_version", envelope.api_version],
                      ["entity_id", envelope.entity_id],
                      ["environment", envelope.environment],
                      ["maturity_stage", envelope.maturity_stage ?? "absent"],
                      ["provenance", envelope.provenance],
                      ["classification", envelope.classification],
                      ["access_scope", envelope.access_scope],
                      ["availability", envelope.availability],
                      ["availability_reason", envelope.availability_reason],
                      ["completeness", envelope.completeness],
                      [
                        "coverage",
                        `${envelope.coverage.present}/${envelope.coverage.requested}`,
                      ],
                      ["snapshot_version", envelope.snapshot_version],
                      ["watermark", envelope.watermark ?? "absent"],
                      ["as_of_time", envelope.as_of_time],
                      ["projected_time", envelope.projected_time],
                      ["evaluation_time", envelope.freshness.evaluation_time],
                      ["oldest_required", envelope.freshness.oldest_required ?? "absent"],
                      [
                        "source_age",
                        isValueBearing(envelope.freshness.source_age.availability)
                          ? `${String(envelope.freshness.source_age.value)}s`
                          : envelope.freshness.source_age.availability,
                      ],
                      [
                        "projection_lag",
                        isValueBearing(envelope.freshness.projection_lag.availability)
                          ? `${String(envelope.freshness.projection_lag.value)}s`
                          : envelope.freshness.projection_lag.availability,
                      ],
                      [
                        "build_age",
                        isValueBearing(envelope.freshness.build_age.availability)
                          ? `${String(envelope.freshness.build_age.value)}s`
                          : envelope.freshness.build_age.availability,
                      ],
                      ["composite_state", envelope.freshness.composite_state],
                      ["source_refs.total", String(envelope.source_refs.total.value ?? "—")],
                      ["metric_definition_version", envelope.metric_definition_version],
                    ] as const
                  ).map(([key, value]) => (
                    <div key={key} className="flex flex-col">
                      <dt className="text-text-tertiary">{key}</dt>
                      <dd className="truncate text-text-secondary">{value}</dd>
                    </div>
                  ))}
                </dl>
              </ScrollRegion>

              {/* Required inputs, each against ITS OWN contract (§3.1). */}
              <div>
                <Label>Required inputs and their own freshness contracts</Label>
                <ScrollRegion label="Freshness inputs" className="mt-2">
                  <table className="w-full min-w-[34rem] border-collapse text-label-s">
                    <caption className="sr-only">
                      Each required input, its own age, its own contract and its resulting
                      state.
                    </caption>
                    <thead>
                      <tr className="border-b border-border-subtle text-left">
                        {["Input", "Required", "Age", "Contract", "State", "Reason"].map(
                          (heading) => (
                            <th
                              key={heading}
                              scope="col"
                              className="py-1.5 pr-3 font-medium text-text-tertiary"
                            >
                              {heading}
                            </th>
                          ),
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {envelope.freshness.inputs.map((input) => (
                        <tr
                          key={input.input_id}
                          className="border-b border-border-subtle last:border-0"
                        >
                          <th
                            scope="row"
                            className="py-1.5 pr-3 text-left font-mono font-normal text-text-secondary"
                          >
                            {input.input_id}
                            {input.clock_skew_flagged === true && (
                              <Badge tone="warning" className="ml-2">
                                clock skew
                              </Badge>
                            )}
                          </th>
                          <td className="py-1.5 pr-3 font-mono text-text-tertiary">
                            {input.required ? "yes" : "no"}
                          </td>
                          <td className="py-1.5 pr-3 font-mono text-text-secondary">
                            {isValueBearing(input.source_age.availability)
                              ? `${String(input.source_age.value)}s`
                              : "unknown"}
                          </td>
                          <td className="py-1.5 pr-3 font-mono text-text-tertiary">
                            {input.contract_max_age}s
                          </td>
                          <td className="py-1.5 pr-3">
                            <AvailabilityBadge state={input.state} reason={input.reason} />
                          </td>
                          <td className="py-1.5 font-mono text-text-tertiary">{input.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollRegion>
              </div>

              {/* Version pins — a pin that does not apply SAYS SO (§4.2). */}
              {envelope.pins !== undefined && (
                <div>
                  <Label>Version pins</Label>
                  <ScrollRegion label="Version pins" className="mt-2">
                    <dl className="grid min-w-[34rem] grid-cols-2 gap-x-6 gap-y-1 font-mono text-label-s sm:grid-cols-3">
                      {Object.entries(envelope.pins).map(([pin, value]) => (
                        <div key={pin} className="flex flex-col">
                          <dt className="text-text-tertiary">{pin}</dt>
                          <dd className="truncate text-text-secondary">
                            {typeof value === "string" ? value : value.availability}
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </ScrollRegion>
                </div>
              )}
            </CardBody>
          </Card>
        </SummaryDisclosure>
        </section>
      )}

      {!operator && envelope !== undefined && envelope.payload === undefined && (
        <section className="mt-6">
          <Card>
            <CardBody className="pt-5">
              <Label>Why these tiles are empty</Label>
              <div className="mt-2">
                <UnavailableBody
                  state={envelope.availability}
                  reason={envelope.availability_reason}
                  dependency="the portfolio, risk and execution projections"
                />
              </div>
              <p className="mt-3 max-w-2xl text-label-m leading-relaxed text-text-tertiary">
                Nothing is estimated in their place. To see how the populated states render,
                switch the scenario to <Badge tone="synthetic">SYNTHETIC</Badge> in the header,
                or open the{" "}
                <Link
                  href={withScope("/foundation/states", scope)}
                  className="text-accent underline underline-offset-2"
                >
                  contract and state reference
                </Link>
                .
              </p>
            </CardBody>
          </Card>
        </section>
      )}

      <p className="mt-6 flex flex-wrap items-center gap-2 text-label-s text-text-tertiary">
        <AvailabilityBadge state="NOT_IMPLEMENTED" reason="PRODUCER_NOT_IMPLEMENTED" />
        <span>
          No production read API, projection or metric engine exists, and none is authorized.
          Every operational figure here is either a labelled synthetic fixture or an explicit
          absence.
        </span>
      </p>
    </>
  );
}
