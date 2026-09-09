"use client";

import * as React from "react";

import { Badge, Card, CardBody, CardHeader, Label, Numeric } from "@/components/ui/primitives";
import {
  AvailabilityBadge,
  STATE_PRESENTATION,
  UnavailableBody,
} from "@/components/cockpit/availability";
import { MetricTile, MetricTileSkeleton } from "@/components/cockpit/metric-tile";
import { PageHeader } from "@/components/cockpit/page-header";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { useLiveFreshness } from "@/components/cockpit/freshness";
import { useClock } from "@/components/shell/clock-provider";
import { useScope } from "@/components/shell/use-scope";
import { available, absent, instantOf, qualified } from "@/contracts/factories";
import type { FreshnessReport } from "@/contracts/freshness";
import { AVAILABILITY_STATES, DATA_PROVENANCES } from "@/contracts/vocabularies";
import { PERMITTED_REASONS, isValueBearing } from "@/contracts/validity";
import type { MetricValue } from "@/contracts/values";

/**
 * The contract and state reference -- a local foundation review surface.
 *
 * It exists so every availability state, every provenance badge and the freshness deadline
 * rule can be inspected DETERMINISTICALLY and REPEATABLY, at any viewport, by a person or a
 * test. It is NOT a product area, and it claims to implement none.
 *
 * Every figure here is a repository-owned demonstration value.
 */
const DEMO_AS_OF = "2026-09-05T12:00:00.000Z";

function demoMetric(state: (typeof AVAILABILITY_STATES)[number]): MetricValue {
  const reason = PERMITTED_REASONS[state][0];
  const args = {
    metricId: `reference.${state.toLowerCase()}`,
    unit: "USD" as const,
    value: state === "EMPTY_VERIFIED" ? 0 : "1234.50",
    asOf: DEMO_AS_OF,
  };
  if (state === "AVAILABLE") return available(args);
  if (isValueBearing(state)) {
    return qualified(state as "STALE" | "PARTIAL" | "EMPTY_VERIFIED", reason, args);
  }
  return absent(
    state as Exclude<
      (typeof AVAILABILITY_STATES)[number],
      "AVAILABLE" | "STALE" | "PARTIAL" | "EMPTY_VERIFIED"
    >,
    reason,
    args.metricId,
    "USD",
  );
}

/**
 * A short freshness budget, so the deadline is OBSERVABLE within a review pass.
 *
 * The demonstration clock below is LABELLED as one and is never presented as the current
 * source time.
 */
const REFERENCE_BUDGET_SECONDS = 5;

function useReferenceFreshness(): { report: FreshnessReport; startedAt: number } {
  const clock = useClock();
  const [startedAt] = React.useState(() => clock.now());
  const report = React.useMemo<FreshnessReport>(() => {
    const effective = instantOf(startedAt);
    const evaluation = instantOf(startedAt);
    return {
      inputs: [
        {
          input_id: "reference.short_budget",
          required: true,
          source_effective_time: effective,
          source_age: available({
            metricId: "freshness.source_age",
            unit: "SECONDS",
            value: 0,
            asOf: evaluation,
          }),
          contract_max_age: REFERENCE_BUDGET_SECONDS,
          state: "AVAILABLE",
          reason: "NONE",
        },
      ],
      oldest_required: "reference.short_budget",
      source_age: available({
        metricId: "freshness.source_age",
        unit: "SECONDS",
        value: 0,
        asOf: evaluation,
      }),
      projection_lag: available({
        metricId: "freshness.projection_lag",
        unit: "SECONDS",
        value: 0,
        asOf: evaluation,
      }),
      build_age: available({
        metricId: "freshness.build_age",
        unit: "SECONDS",
        value: 0,
        asOf: evaluation,
      }),
      composite_state: "AVAILABLE",
      evaluation_time: evaluation,
    };
  }, [startedAt]);
  return { report, startedAt };
}

function FreshnessDemonstration() {
  const clock = useClock();
  const { report } = useReferenceFreshness();
  const live = useLiveFreshness(report);
  return (
    <Card data-testid="freshness-demo">
      <CardHeader>
        <Label as="h2">Freshness deadline, live</Label>
        <p className="mt-1 max-w-2xl text-label-m leading-relaxed text-text-secondary">
          One required input with a {REFERENCE_BUDGET_SECONDS}-second contract. The deadline is
          absolute — <span className="font-mono">source_effective_time + contract_max_age</span>{" "}
          — so this tile degrades to <strong>Stale</strong> while the page stays mounted, with
          no navigation and no refetch. A refetch over the same source fact would renew nothing.
        </p>
      </CardHeader>
      <CardBody className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <AvailabilityBadge state={live.state} reason={live.reason} />
          <span
            data-testid="freshness-remaining"
            className="font-mono text-numeric-m text-text-primary"
          >
            {live.remainingSeconds ?? 0}s
          </span>
          <span className="text-label-m text-text-tertiary">remaining budget</span>
        </div>
        <p className="text-label-s text-text-tertiary">
          At equality the entry is expired: <span className="font-mono">serve_time &lt; fresh_until</span>{" "}
          permits available, and <span className="font-mono">serve_time &gt;= fresh_until</span>{" "}
          means expired. A configured cache TTL may only shorten this, never extend it.
        </p>
        <p className="text-label-s text-text-tertiary">
          Clock:{" "}
          <Badge tone={clock.kind === "fixed" ? "warning" : "neutral"}>
            {clock.kind === "fixed" ? "FIXED DEMONSTRATION CLOCK" : "system clock"}
          </Badge>
        </p>
      </CardBody>
    </Card>
  );
}

export default function StateReferencePage() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";

  return (
    <>
      <PageHeader
        title="Contract & State Reference"
        summary="Every availability state, every provenance badge and the freshness deadline rule, rendered deterministically for repeatable review. This is a foundation review surface, not a product area."
      >
        <Badge tone="unavailable">Foundation surface — implements no product area</Badge>
      </PageHeader>

      <section aria-labelledby="states-heading" className="mb-6">
        <h2 id="states-heading" className="mb-2 text-label-m font-semibold text-text-secondary">
          The eleven availability states
        </h2>
        <p className="mb-3 max-w-3xl text-label-m text-text-tertiary">
          Each renders distinctly, and none renders as zero, healthy or passed. A value-bearing
          state keeps its value <em>and</em> its qualification; an absence carries no value at
          all.
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {AVAILABILITY_STATES.map((state) => (
            <MetricTile
              key={state}
              label={STATE_PRESENTATION[state].label}
              metric={demoMetric(state)}
              provenance="SYNTHETIC"
              dependency="a demonstration dependency"
              operator={operator}
              size="m"
            />
          ))}
        </div>
      </section>

      <section aria-labelledby="zero-heading" className="mb-6">
        <h2 id="zero-heading" className="mb-2 text-label-m font-semibold text-text-secondary">
          A zero is a measurement, and never an availability state
        </h2>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <Card data-testid="measured-zero">
            <CardBody className="space-y-2 pt-4">
              <div className="flex items-start justify-between gap-2">
                <Label>Zero winners among ten closed trades</Label>
                <ProvenanceBadge provenance="SYNTHETIC" />
              </div>
              <Numeric size="l">0.00</Numeric>
              <span className="text-label-m text-text-tertiary"> % win rate</span>
              <AvailabilityBadge state="AVAILABLE" reason="NONE" />
              <p className="text-label-s text-text-tertiary">
                A measured zero over a <strong>non-empty</strong> population. The producer ran
                and measured zero, so this is a finding a screen must show.
              </p>
            </CardBody>
          </Card>
          <Card data-testid="empty-population">
            <CardBody className="space-y-2 pt-4">
              <div className="flex items-start justify-between gap-2">
                <Label>Zero closed trades in the window</Label>
                <ProvenanceBadge provenance="SYNTHETIC" />
              </div>
              <Numeric size="l">0</Numeric>
              <span className="text-label-m text-text-tertiary"> trades</span>
              <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
              <p className="text-label-s text-text-tertiary">
                An <strong>empty population</strong>. The query ran and there is nothing in it.
                The count of an empty population is zero; the converse does not hold.
              </p>
            </CardBody>
          </Card>
        </div>
      </section>

      <section aria-labelledby="freshness-heading" className="mb-6">
        <h2
          id="freshness-heading"
          className="mb-2 text-label-m font-semibold text-text-secondary"
        >
          Freshness
        </h2>
        <FreshnessDemonstration />
      </section>

      <section aria-labelledby="provenance-heading" className="mb-6">
        <h2
          id="provenance-heading"
          className="mb-2 text-label-m font-semibold text-text-secondary"
        >
          Provenance
        </h2>
        <Card>
          <CardBody className="space-y-3 pt-4">
            <ul className="flex flex-wrap gap-2">
              {DATA_PROVENANCES.map((provenance) => (
                <li key={provenance}>
                  <ProvenanceBadge provenance={provenance} />
                </li>
              ))}
            </ul>
            <p className="max-w-3xl text-label-m leading-relaxed text-text-tertiary">
              <strong className="text-text-secondary">SYNTHETIC</strong> and{" "}
              <strong className="text-text-secondary">TRACKED FACT</strong> are never rendered
              under one another&apos;s badge. This deployment admits only PUBLIC_SAFE payloads
              with synthetic or repository-tracked provenance; system-recorded,
              backtest-simulated and broker-reported payloads are refused at admission, as are
              unclassified and CONTROL payloads.
            </p>
          </CardBody>
        </Card>
      </section>

      <section aria-labelledby="loading-heading" className="mb-6">
        <h2
          id="loading-heading"
          className="mb-2 text-label-m font-semibold text-text-secondary"
        >
          Loading
        </h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricTileSkeleton label="Shape only" />
          <MetricTileSkeleton label="No digits" />
          <Card>
            <CardBody className="pt-4">
              <Label>Widget failure isolation</Label>
              <div className="mt-2">
                <UnavailableBody
                  state="ERROR"
                  reason="PROJECTION_ERROR"
                  dependency="a demonstration projection"
                />
              </div>
            </CardBody>
          </Card>
          <Card>
            <CardBody className="pt-4">
              <Label>The rest of the page is unaffected</Label>
              <p className="mt-2 text-label-m text-text-tertiary">
                A failing widget renders its own availability. The page reports itself partial
                and stays usable.
              </p>
            </CardBody>
          </Card>
        </div>
      </section>
    </>
  );
}
