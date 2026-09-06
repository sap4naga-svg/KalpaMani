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
} from "@/components/ui/primitives";
import { AvailabilityBadge, UnavailableBody } from "@/components/cockpit/availability";
import { AttentionPanel } from "@/components/cockpit/attention";
import { MetricTile, MetricTileSkeleton } from "@/components/cockpit/metric-tile";
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
import { METRIC_DEFINITION_VERSION, notImplemented } from "@/contracts/factories";
import { isValueBearing } from "@/contracts/validity";
import { prepareAttention } from "@/lib/attention";
import { formatDecimal, humanizeCode } from "@/lib/format";
import { withScope, type PerformancePeriod } from "@/lib/scope";
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
 * NO EQUITY, PERFORMANCE, EXPOSURE, INCIDENT, SYSTEM-HEALTH OR TRADE STATISTIC IS
 * FABRICATED. In the default project scope every operational read model reports that its
 * producing subsystem does not exist; the synthetic scenario is labelled unmissably.
 */

/**
 * One of the five answers.
 *
 * The QUESTION is the label. A tile headed "Return" answers a question the reader has to
 * infer; a tile headed "How are we doing?" answers the one §2 actually asks.
 */
function AnswerTile({
  question,
  subject,
  children,
  footer,
  href,
  provenance,
  testId,
}: {
  question: string;
  subject: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  href?: string;
  provenance?: React.ReactNode;
  testId: string;
}) {
  return (
    <Card className="flex h-full flex-col" data-testid={testId}>
      <CardBody className="flex flex-1 flex-col gap-1 pt-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-label-s font-medium uppercase tracking-[0.09em] text-accent">
              {question}
            </p>
            <Label className="mt-0.5 block min-w-0 break-words">{subject}</Label>
          </div>
          {provenance}
        </div>
        <div className="flex flex-1 flex-col justify-center py-0.5">{children}</div>
        {footer !== undefined && (
          <div className="text-label-s leading-relaxed text-text-tertiary">{footer}</div>
        )}
        {href !== undefined && (
          <Link href={href} className="text-label-s text-accent underline underline-offset-2">
            Open the area that owns this →
          </Link>
        )}
      </CardBody>
    </Card>
  );
}

/** A large figure, or the availability state standing in place of one. Never both, never zero. */
function Figure({
  metric,
  dependency,
  denominator,
}: {
  metric: MetricValue;
  dependency: string;
  denominator?: string;
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
  const signed = metric.unit === "USD" || metric.unit === "PERCENT";
  const decimal =
    typeof metric.value === "string"
      ? formatDecimal(metric.value, { minimumFractionDigits: 2, signed })
      : null;
  const negative = typeof metric.value === "string" && metric.value.startsWith("-");
  const nonZero = /[1-9]/.test(String(metric.value));
  return (
    <div className="space-y-1">
      <div className="flex items-baseline gap-1.5">
        <Numeric
          size="l"
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
      {denominator !== undefined && (
        <p className="text-label-s text-text-tertiary">per {denominator}</p>
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
            footer={
              <>
                Authoritative. Broker-reported equity is <strong>observed</strong> and never
                substituted for it.
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
              <div className="flex items-baseline gap-1.5">
                <Numeric size="l" className="text-text-primary">
                  {formatDecimal(strategyCapital, { minimumFractionDigits: 2 })}
                </Numeric>
                <span className="text-label-m text-text-tertiary">USD</span>
              </div>
            )}
          </AnswerTile>

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
            footer={
              payload === undefined ? undefined : (
                <>
                  Day realized{" "}
                  <span className="font-mono">
                    {(() => {
                      const day = payload.pnl.find((entry) => entry.window === "DAY")?.realized;
                      return day !== undefined && isValueBearing(day.availability)
                        ? `${formatDecimal(String(day.value), {
                            minimumFractionDigits: 2,
                            signed: true,
                          })} USD`
                        : "unavailable";
                    })()}
                  </span>{" "}
                  · realized and unrealized are never summed into one figure.
                </>
              )
            }
          >
            {overview.isPending ? (
              <div className="skeleton-shape h-9 w-2/3" data-testid="skeleton" />
            ) : (
              <Figure
                metric={payload?.return_pct ?? notImplemented("return.time_weighted", "PERCENT")}
                dependency="the portfolio valuation projection"
                denominator="time-weighted, cash-flow adjusted"
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
            footer={
              <>
                Permitted open risk is a <strong>separate fact</strong>, and drawdown a third.
                Neither is derived from this one.
              </>
            }
          >
            {overview.isPending ? (
              <div className="skeleton-shape h-9 w-2/3" data-testid="skeleton" />
            ) : (
              <Figure
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
            footer="Health is a recorded state, never inferred from the absence of an alert."
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

          <AnswerTile
            question="What changed?"
            subject="Since the stated baseline"
            testId="answer-changed"
            href={withScope("/governance/audit", scope)}
            footer={
              changesPayload === undefined
                ? undefined
                : noBaseline
                  ? "No prior endpoint exists, so no change is listed and none is inferred."
                  : `Baseline as-of ${changesPayload.baseline_as_of ?? "absent"}.`
            }
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
                <Numeric size="l" className="text-text-primary">
                  0
                </Numeric>
                <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
              </div>
            ) : (
              <div className="flex items-baseline gap-1.5">
                <Numeric size="l" className="text-text-primary">
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
            subject="Ranked and deduplicated"
            testId="answer-attention"
            href={withScope("/attention", scope)}
            footer={
              topAttention === undefined
                ? undefined
                : `Highest: ${humanizeCode(topAttention.what_happened.code)}.`
            }
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
                <Numeric size="l" className="text-text-primary">
                  0
                </Numeric>
                <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
              </div>
            ) : (
              <div className="flex flex-wrap items-baseline gap-1.5">
                <Numeric size="l" className="text-text-primary">
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
              <Label>Attention required</Label>
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

        {whatChanged.data === undefined ? (
          <Card>
            <CardHeader>
              <Label>What changed</Label>
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
          />
        )}
      </section>

      {/* The performance overview. Below the ten-second answers, and above the detail. */}
      <section aria-labelledby="performance" className="mb-6">
        <h2 id="performance" className="sr-only">
          Performance overview
        </h2>
        <PerformanceOverview
          envelope={performance.data}
          scope={scope}
          operator={operator}
          onPeriodChange={onPeriodChange}
        />
      </section>

      {/* TIER 2 -- supporting context. */}
      <section aria-labelledby="tier-two" className="mb-6">
        <h2 id="tier-two" className="mb-2 text-label-m font-semibold text-text-secondary">
          Supporting context
        </h2>
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
              <MetricTile
                label="Broker-reported equity"
                metric={
                  payload?.broker_reported_equity ??
                  notImplemented("portfolio.broker_reported_equity", "USD")
                }
                provenance={envelope?.provenance ?? "SYNTHETIC"}
                dependency="an authorized brokerage session"
                operator={operator}
                size="m"
              />
              <MetricTile
                label="Drawdown"
                metric={payload?.drawdown ?? notImplemented("drawdown.current", "PERCENT")}
                provenance={envelope?.provenance ?? "SYNTHETIC"}
                dependency="the portfolio valuation projection"
                operator={operator}
                size="m"
                denominator="running peak equity"
              />
              <MetricTile
                label="Permitted open risk"
                metric={{
                  value: payload?.permitted_open_risk.record?.limit_money.value,
                  unit: "USD",
                  availability: payload?.permitted_open_risk.availability ?? "NOT_IMPLEMENTED",
                  reason: payload?.permitted_open_risk.reason ?? "PRODUCER_NOT_IMPLEMENTED",
                  as_of: payload?.permitted_open_risk.as_of,
                  metric_id: "risk.permitted",
                  metric_definition_version: METRIC_DEFINITION_VERSION,
                }}
                provenance={envelope?.provenance ?? "SYNTHETIC"}
                dependency="a versioned risk-policy reference"
                operator={operator}
                size="m"
              />
            </>
          )}
        </div>

        {/* Exposure, regime and the two last-run records. */}
        <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-2">
          <Card data-testid="tile-exposure">
            <CardHeader className="flex items-center justify-between gap-2">
              <Label>Exposure</Label>
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
              <Label>Regime, last decision and last scout run</Label>
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
      </section>

      {operator && envelope !== undefined && (
        <section aria-labelledby="operator-evidence" className="mt-6">
          <h2
            id="operator-evidence"
            className="mb-2 text-label-m font-semibold text-text-secondary"
          >
            Response evidence
          </h2>
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
