"use client";

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
import {
  AvailabilityBadge,
  UnavailableBody,
} from "@/components/cockpit/availability";
import { AttentionPanel } from "@/components/cockpit/attention";
import {
  MetricTile,
  MetricTileSkeleton,
} from "@/components/cockpit/metric-tile";
import { PageHeader } from "@/components/cockpit/page-header";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { WhatChangedPanel } from "@/components/cockpit/what-changed";
import { useScope } from "@/components/shell/use-scope";
import {
  useAttention,
  useExecutiveOverview,
  useQualificationStatus,
  useWhatChanged,
} from "@/data/client/hooks";
import { METRIC_DEFINITION_VERSION, notImplemented } from "@/contracts/factories";
import { formatDecimal } from "@/lib/format";
import { withScope } from "@/lib/scope";

/**
 * The Executive Overview -- the composed landing page.
 *
 * THE TEN-SECOND TEST (ui-ux-specification.md section 2): the default view answers five
 * questions -- how are we doing, is anything wrong, what changed, where is risk, what
 * requires attention -- and each links to the area that owns it.
 *
 * THREE TIERS, and the tiering is the specification:
 *   TIER 1  the five ten-second answers
 *   TIER 2  supporting context
 *   TIER 3  What Changed, and the ranked Attention Required list
 *
 * NO EQUITY, PERFORMANCE, EXPOSURE, INCIDENT, SYSTEM-HEALTH OR TRADE STATISTIC IS
 * FABRICATED. In the default project scope every operational read model reports that its
 * producing subsystem does not exist; the synthetic scenario is labelled unmissably.
 */
export default function ExecutiveOverviewPage() {
  const { scope } = useScope();
  const overview = useExecutiveOverview(scope);
  const attention = useAttention(scope);
  const whatChanged = useWhatChanged(scope);
  const qualification = useQualificationStatus(scope);
  const operator = scope.mode === "operator";

  const envelope = overview.data;
  const payload = envelope?.payload;
  const degraded =
    envelope !== undefined &&
    (envelope.availability !== "AVAILABLE" ||
      (payload?.tile_availability ?? []).some(
        (tile) => tile.availability !== "AVAILABLE",
      ));

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

  return (
    <>
      <PageHeader
        title={
          operator ? "Executive Overview — Operator" : "Executive Overview"
        }
        summary={
          operator
            ? "The same read models, with reason codes, metric identities, contract versions and provenance exposed for evidence."
            : "Status, attention and change, answered before detail. Every figure carries its source and its availability."
        }
        pageState={degraded ? "PARTIAL" : "COMPLETE"}
      />

      {/* TIER 1 -- the five ten-second answers, in the first viewport. */}
      <section aria-labelledby="tier-one" className="mb-6">
        <h2 id="tier-one" className="sr-only">
          Primary status
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {/* Strategy capital is AUTHORITATIVE and is never broker-reported equity. */}
          <Card data-testid="tile-strategy-capital">
            <CardBody className="space-y-2 pt-4">
              <div className="flex items-start justify-between gap-2">
                <Label className="min-w-0 break-words">Strategy capital</Label>
                <ProvenanceBadge provenance="REPOSITORY_TRACKED" className="shrink-0" />
              </div>
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
                  <Numeric size="xl" className="text-text-primary">
                    {formatDecimal(strategyCapital, { minimumFractionDigits: 2 })}
                  </Numeric>
                  <span className="text-label-m text-text-tertiary">USD</span>
                </div>
              )}
              <p className="text-label-s text-text-tertiary">
                Authoritative. Broker-reported equity is observed and never
                substituted for it.
              </p>
            </CardBody>
          </Card>

          {overview.isPending ? (
            <>
              <MetricTileSkeleton label="Day realized P/L" />
              <MetricTileSkeleton label="Open planned risk" />
              <MetricTileSkeleton label="Drawdown" />
            </>
          ) : (
            <>
              <MetricTile
                label="Day realized P/L"
                metric={
                  payload?.pnl.find((window) => window.window === "DAY")
                    ?.realized ?? notImplemented("pnl.realized", "USD")
                }
                provenance={envelope?.provenance ?? "SYNTHETIC"}
                dependency="the portfolio projection"
                operator={operator}
              />
              <MetricTile
                label="Open planned risk"
                metric={
                  payload?.open_planned_risk.record !== undefined
                    ? {
                        value: payload.open_planned_risk.record.amount.amount,
                        unit: "USD",
                        availability: payload.open_planned_risk.availability,
                        reason: payload.open_planned_risk.reason,
                        as_of: payload.open_planned_risk.as_of,
                        metric_id: "risk.open_planned",
                        metric_definition_version: METRIC_DEFINITION_VERSION,
                      }
                    : notImplemented("risk.open_planned", "USD")
                }
                provenance={envelope?.provenance ?? "SYNTHETIC"}
                dependency="the risk engine"
                operator={operator}
              />
              <MetricTile
                label="Drawdown"
                metric={
                  payload?.drawdown ??
                  notImplemented("drawdown.current", "PERCENT")
                }
                provenance={envelope?.provenance ?? "SYNTHETIC"}
                dependency="the portfolio projection"
                operator={operator}
                denominator="peak equity"
              />
            </>
          )}
        </div>
      </section>

      {/* TIER 2 -- supporting context. */}
      <section aria-labelledby="tier-two" className="mb-6">
        <h2
          id="tier-two"
          className="mb-2 text-label-m font-semibold text-text-secondary"
        >
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
                <div
                  className="skeleton-shape h-8 w-16"
                  data-testid="skeleton"
                />
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
                    <span className="text-label-m text-text-tertiary">
                      of {gates.length}
                    </span>
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
              <MetricTileSkeleton label="Active strategies" />
              <MetricTileSkeleton label="Open incidents" />
              <MetricTileSkeleton label="Permitted open risk" />
            </>
          ) : (
            <>
              <MetricTile
                label="Active strategies"
                metric={
                  payload?.active_strategies ??
                  notImplemented("strategy.active_count", "COUNT")
                }
                provenance={envelope?.provenance ?? "SYNTHETIC"}
                dependency="the Strategy Brain runtime"
                operator={operator}
                size="m"
              />
              <MetricTile
                label="Open incidents"
                metric={
                  payload?.open_incidents ??
                  notImplemented("operations.open_incidents", "COUNT")
                }
                provenance={envelope?.provenance ?? "SYNTHETIC"}
                dependency="the alerting subsystem"
                operator={operator}
                size="m"
              />
              <MetricTile
                label="Permitted open risk"
                metric={{
                  value: payload?.permitted_open_risk.record?.amount.amount,
                  unit: "USD",
                  availability:
                    payload?.permitted_open_risk.availability ??
                    "NOT_IMPLEMENTED",
                  reason:
                    payload?.permitted_open_risk.reason ??
                    "PRODUCER_NOT_IMPLEMENTED",
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
      </section>

      {/* TIER 3 -- What Changed and Attention Required. */}
      <section
        aria-labelledby="tier-three"
        className="grid grid-cols-1 gap-4 xl:grid-cols-2"
      >
        <h2 id="tier-three" className="sr-only">
          Change and attention
        </h2>
        {attention.data === undefined ? (
          <Card>
            <CardHeader>
              <Label>Attention required</Label>
            </CardHeader>
            <CardBody>
              <div
                className="skeleton-shape h-16 w-full"
                data-testid="skeleton"
              />
            </CardBody>
          </Card>
        ) : (
          <AttentionPanel
            envelope={attention.data}
            scope={scope}
            operator={operator}
          />
        )}

        {whatChanged.data === undefined ? (
          <Card>
            <CardHeader>
              <Label>What changed</Label>
            </CardHeader>
            <CardBody>
              <div
                className="skeleton-shape h-16 w-full"
                data-testid="skeleton"
              />
            </CardBody>
          </Card>
        ) : (
          <WhatChangedPanel envelope={whatChanged.data} operator={operator} />
        )}
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
            <CardBody className="pt-4">
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
                      ["snapshot_version", envelope.snapshot_version],
                      ["as_of_time", envelope.as_of_time],
                      ["projected_time", envelope.projected_time],
                      ["evaluation_time", envelope.freshness.evaluation_time],
                      [
                        "oldest_required",
                        envelope.freshness.oldest_required ?? "absent",
                      ],
                      [
                        "metric_definition_version",
                        envelope.metric_definition_version,
                      ],
                    ] as const
                  ).map(([key, value]) => (
                    <div key={key} className="flex flex-col">
                      <dt className="text-text-tertiary">{key}</dt>
                      <dd className="truncate text-text-secondary">{value}</dd>
                    </div>
                  ))}
                </dl>
              </ScrollRegion>
            </CardBody>
          </Card>
        </section>
      )}

      {!operator &&
        envelope !== undefined &&
        envelope.payload === undefined && (
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
                  Nothing is estimated in their place. To see how the populated
                  states render, switch the scenario to{" "}
                  <Badge tone="synthetic">SYNTHETIC</Badge> in the header, or
                  open the{" "}
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
        <AvailabilityBadge
          state="NOT_IMPLEMENTED"
          reason="PRODUCER_NOT_IMPLEMENTED"
        />
        <span>
          This is the C3 foundation, not the C4 dashboard. No production read
          API, projection or metric engine exists, and none is authorized.
        </span>
      </p>
    </>
  );
}
