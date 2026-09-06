"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText, MoneyText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel, ReferenceChip } from "@/components/cockpit/read-model-panel";
import {
  InitialPlannedRiskRecord,
  OpenPlannedRiskRecord,
  RiskSeparationNote,
} from "@/components/cockpit/risk-records";
import { TradePriceChart, type ChartLevel, type ChartMarker } from "@/components/cockpit/trade-chart";
import { useScope } from "@/components/shell/use-scope";
import { useTradeDetail, useTradeLifecycle } from "@/data/client/hooks";
import type { TradeDetailPayload, TradeLifecyclePayload } from "@/contracts/portfolio-models";
import { humanizeCode } from "@/lib/format";
import { withScope } from "@/lib/scope";

/**
 * Trade Detail — Area 36.2, in the **basic** form C5 owns.
 *
 * WHAT THIS CYCLE IMPLEMENTS: the trade's identity, its recorded reasons, the economics and
 * both risk records, the trade-level timeline a recorded trade actually has, the recorded
 * price marks with entry, add, partial-exit and exit markers, and the references to every
 * downstream fact.
 *
 * WHAT IT DELIBERATELY DOES NOT: the candidate and its thesis, the Brain decision, the risk
 * decision, order and fill mechanics, protective-order events, reconciliation, execution
 * quality and finalized attribution. **The producers do not exist**, and the complete
 * lifecycle and the chart drill-down belong to C6. Every one of them is listed as a gap.
 *
 * **A MISSING EVENT RENDERS AS A GAP AND NEVER AS AN INFERENCE.** Nothing on this page fills
 * a stage in from the stages around it.
 */
export default function Page() {
  const params = useParams<{ tradeId: string }>();
  const tradeId = typeof params.tradeId === "string" ? params.tradeId : "";
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const detail = useTradeDetail(scope, tradeId);
  const lifecycle = useTradeLifecycle(scope, tradeId);

  const summary = detail.data?.payload?.summary;

  return (
    <>
      <PageHeader
        title={
          summary === undefined
            ? "Trade Detail"
            : `${summary.security.symbol} — ${humanizeCode(summary.direction)}`
        }
        summary="One trade's story, joined from separately owned records by reference. Every stage this cycle does not carry is named rather than filled in."
        pageState="PARTIAL"
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 36 — basic detail</Badge>
          <Badge tone="unavailable">Full lifecycle: C6</Badge>
          <Link
            href={withScope("/portfolio/trades", scope)}
            className="text-label-m text-accent underline underline-offset-2"
          >
            Back to the trade ledger
          </Link>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadModelPanel
          title="Identity and economics"
          description="What the trade is, what it did, and the versions that produced it."
          envelope={detail.data}
          dependency="the portfolio and execution runtimes and their recorded trades"
          operator={operator}
          testId="trade-detail-panel"
        >
          {(payload) => <TradeIdentity payload={payload} operator={operator} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Recorded price marks"
          description="The trade's own mark path, with the events that were recorded on it."
          envelope={detail.data}
          dependency="a qualified market-data provider — G1 is OPEN and no provider is selected"
          testId="trade-chart-panel"
        >
          {(payload) =>
            payload.chart_series === undefined ? (
              <AvailabilityBadge state="NOT_YET_AVAILABLE" reason="UPSTREAM_INPUT_MISSING" />
            ) : (
              <TradePriceChart
                series={payload.chart_series}
                markers={markersFrom(lifecycle.data?.payload)}
                levels={levelsFrom(payload)}
                direction={payload.summary.direction}
                caption={`${payload.summary.security.symbol} recorded marks`}
              />
            )
          }
        </ReadModelPanel>

        <ReadModelPanel
          title="Trade timeline"
          description="The trade-level stages this book records: entry, adds, partial exits and the exit."
          envelope={lifecycle.data}
          dependency="the execution runtime and its recorded order and fill events"
          operator={operator}
          testId="trade-lifecycle-panel"
        >
          {(payload) => <Lifecycle payload={payload} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="What this detail does not carry"
          description="Each stage the complete story would include, with the state that explains its absence."
          envelope={detail.data}
          dependency="the Brain, risk, execution and audit runtimes"
          testId="trade-gaps-panel"
        >
          {(payload) => <Gaps payload={payload} />}
        </ReadModelPanel>
      </div>
    </>
  );
}

/** The markers a chart may draw. **Only recorded events produce one.** */
function markersFrom(lifecycle: TradeLifecyclePayload | undefined): ChartMarker[] {
  if (lifecycle === undefined) {
    return [];
  }
  return lifecycle.events.map((event) => {
    const code = event.event_kind.code;
    const kind: ChartMarker["kind"] = code.startsWith("ENTRY")
      ? "ENTRY"
      : code.startsWith("PYRAMID")
        ? "ADD"
        : code.startsWith("PARTIAL")
          ? "PARTIAL_EXIT"
          : "EXIT";
    return {
      day: event.event_time.slice(0, 10),
      /** The RECORDED kind, in full. The plot's own short text is the chart's concern. */
      label: humanizeCode(code),
      kind,
      price: typeof event.price.value === "string" ? event.price.value : "",
      quantity: event.quantity,
    };
  });
}

/**
 * The levels a chart may draw.
 *
 * The invalidation level is carried as a REFERENCE, never an order, and the entry-time record
 * is the only one this page has a number for. A current protective level belongs to the
 * protective-order record, which does not exist.
 */
function levelsFrom(payload: TradeDetailPayload): ChartLevel[] {
  const record = payload.summary.initial_planned_risk.record;
  if (record === undefined) {
    return [];
  }
  return [
    {
      label: "Entry reference",
      price: record.reference_price.amount,
      note: "the price the entry-time risk was set against",
    },
  ];
}

function TradeIdentity({
  payload,
  operator,
}: {
  payload: TradeDetailPayload;
  operator: boolean;
}) {
  const summary = payload.summary;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={summary.direction === "LONG" ? "info" : "warning"}>
          <span aria-hidden="true">{summary.direction === "LONG" ? "▲" : "▼"}</span>
          <span>{summary.direction}</span>
        </Badge>
        <Badge tone="neutral" data-trade-status={summary.trade_status}>
          Status: {humanizeCode(summary.trade_status)}
        </Badge>
        <Badge
          tone={summary.data_completeness === "COMPLETE" ? "neutral" : "warning"}
          data-completeness={summary.data_completeness}
        >
          Data: {humanizeCode(summary.data_completeness)}
        </Badge>
        <Badge tone="neutral">{humanizeCode(summary.strategy_module.code)}</Badge>
        <Badge tone="neutral">{humanizeCode(summary.alpha_family.code)}</Badge>
        <Badge tone="neutral">{humanizeCode(summary.trade_template.code)}</Badge>
      </div>
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        <strong className="text-text-secondary">Trade status and data completeness are
        two facts.</strong>{" "}
        A complete trade with a missing bar is complete in status and partial in completeness,
        and neither is inferred from the other.
      </p>

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(
          [
            ["Security", `${summary.security.symbol} · ${summary.security.display_name}`],
            ["Trade identity", summary.trade_id],
            ["Entry", summary.entry_time],
            ["Shares at entry", summary.shares_at_entry.toLocaleString("en-US")],
            ["Shares open", summary.shares_open.toLocaleString("en-US")],
            ["Environment", summary.environment],
          ] as const
        ).map(([term, value]) => (
          <div key={term} className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              {term}
            </dt>
            <dd className="break-words font-mono text-numeric-s text-text-secondary">
              {value}
            </dd>
          </div>
        ))}
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Initial position value
          </dt>
          <dd>
            <MoneyText amount={summary.initial_position_value.amount} />
          </dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Holding period
          </dt>
          <dd>
            <MetricText metric={summary.holding_period} neutral />
          </dd>
        </div>
      </dl>

      <dl className="grid gap-3 border-t border-border-subtle pt-3 sm:grid-cols-2 lg:grid-cols-4">
        {(
          [
            ["Realized", summary.realized_pnl, undefined],
            ["Unrealized", summary.unrealized_pnl, undefined],
            ["Return", summary.return_pct, "initial position value"],
            ["R multiple", summary.r_multiple, "initial planned risk"],
            ["Maximum favourable", summary.mfe, undefined],
            ["Maximum adverse", summary.mae, undefined],
            ["Capture ratio", summary.capture_ratio, "maximum favourable"],
            ["Exit price", summary.exit_price, undefined],
          ] as const
        ).map(([term, metric, denominator]) => (
          <div key={term} className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              {term}
            </dt>
            <dd>
              <MetricText metric={metric} denominator={denominator} operator={operator} />
            </dd>
          </div>
        ))}
      </dl>

      <div className="grid gap-5 border-t border-border-subtle pt-3 lg:grid-cols-2">
        <PanelSection
          title="Initial planned risk — immutable"
          note="Recorded at entry. A moving stop, a replaced protective order and a partial exit each move the OTHER figure and never this one."
        >
          <InitialPlannedRiskRecord
            wrapper={summary.initial_planned_risk}
            operator={operator}
          />
        </PanelSection>
        <PanelSection
          title="Current open planned risk — an assessment"
          note="Present only while remaining exposure exists, and always shown with its own as-of."
        >
          <OpenPlannedRiskRecord wrapper={summary.open_planned_risk} operator={operator} />
        </PanelSection>
      </div>
      <RiskSeparationNote />

      <PanelSection
        title="Recorded reasons"
        note="Closed vocabulary codes from the record. There is no free text anywhere in this payload."
      >
        <dl className="grid gap-3 sm:grid-cols-3">
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Entry reason
            </dt>
            <dd className="text-label-m text-text-secondary">
              {humanizeCode(summary.entry_reason.code)}
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Exit reason
            </dt>
            <dd>
              <MetricText metric={summary.exit_reason} neutral />
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Stop outcome
            </dt>
            <dd className="text-label-m text-text-secondary">
              {humanizeCode(summary.stop_outcome.code)}
            </dd>
          </div>
        </dl>
      </PanelSection>

      <PanelSection
        title="The thesis, and where it lives"
        note="The original thesis belongs to the candidate the Brain journaled. The Brain runtime does not exist, so the reference is carried and resolves to an availability state rather than to a payload."
      >
        <div className="flex flex-wrap gap-2">
          <ReferenceChip reference={payload.candidate_ref} label="Candidate and thesis" />
          <ReferenceChip reference={payload.brain_decision_ref} label="Brain decision" />
          <ReferenceChip reference={payload.risk_decision_ref} label="Risk decision" />
          <ReferenceChip
            reference={payload.execution_quality_ref}
            label="Execution quality"
          />
          <ReferenceChip reference={payload.benchmark_series_ref} label="Benchmark series" />
          <ReferenceChip reference={payload.chart_series_ref} label="Price marks" />
        </div>
        <p className="mt-2 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
          Order, fill, protective-order, reconciliation and audit references are carried as
          empty lists rather than omitted:{" "}
          <span className="font-mono">{String(payload.order_refs.total.value ?? 0)}</span>{" "}
          orders,{" "}
          <span className="font-mono">{String(payload.fill_refs.total.value ?? 0)}</span>{" "}
          fills,{" "}
          <span className="font-mono">
            {String(payload.protection_refs.total.value ?? 0)}
          </span>{" "}
          protective events,{" "}
          <span className="font-mono">
            {String(payload.reconciliation_refs.total.value ?? 0)}
          </span>{" "}
          reconciliations and{" "}
          <span className="font-mono">{String(payload.audit_refs.total.value ?? 0)}</span>{" "}
          audit events. The producers do not exist, and these are the screens that own them —
          Execution History and the Audit Trail.
        </p>
      </PanelSection>

      <PanelSection
        title="Attribution and benchmark"
        note="Strategy, factor, regime, execution and cost attribution each need a producer that does not exist. A provisional zero would be a decomposition nobody computed."
        state={{ availability: "NOT_IMPLEMENTED", reason: "PRODUCER_NOT_IMPLEMENTED" }}
      >
        <dl className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {(
            [
              ["Strategy", payload.attribution.strategy],
              ["Factor", payload.attribution.factor],
              ["Regime", payload.attribution.regime],
              ["Execution", payload.attribution.execution],
              ["Cost", payload.attribution.cost],
              ["Benchmark move", payload.benchmark_movement],
            ] as const
          ).map(([term, metric]) => (
            <div key={term} className="flex flex-col gap-0.5">
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                {term}
              </dt>
              <dd>
                <MetricText metric={metric} />
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-label-s text-text-tertiary">
          Attribution state:{" "}
          <span className="font-mono text-text-secondary">{payload.attribution.state}</span> ·
          benchmark basis:{" "}
          <span className="font-mono text-text-secondary">{payload.benchmark_basis}</span>. A
          price-return benchmark is never compared against a total-return portfolio, so the
          basis travels with the figure.
        </p>
      </PanelSection>

      {operator && (
        <ScrollRegion label="Lineage pins">
          <dl className="grid min-w-[30rem] grid-cols-2 gap-x-6 gap-y-1 font-mono text-label-s sm:grid-cols-3">
            {Object.entries(payload.lineage).map(([key, pin]) => (
              <div key={key} className="flex flex-col">
                <dt className="text-text-tertiary">{key}</dt>
                <dd className="truncate text-text-secondary">
                  {typeof pin === "string" ? pin : "not applicable"}
                </dd>
              </div>
            ))}
          </dl>
        </ScrollRegion>
      )}
    </div>
  );
}

/** The trade-level timeline, and the event kinds it does not carry. */
function Lifecycle({ payload }: { payload: TradeLifecyclePayload }) {
  return (
    <div className="space-y-3">
      <ol className="space-y-2" data-testid="lifecycle-events">
        {payload.events.map((event) => (
          <li
            key={event.event_id}
            className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-sm border border-border-subtle bg-surface-sunken px-3 py-2"
            data-event-kind={event.event_kind.code}
          >
            <span className="font-mono text-label-s text-text-tertiary">
              {event.event_time.slice(0, 10)}
            </span>
            <span className="text-label-m font-medium text-text-primary">
              {humanizeCode(event.event_kind.code)}
            </span>
            <span className="font-mono text-label-m text-text-secondary">
              {event.quantity.toLocaleString("en-US")} sh
            </span>
            <MetricText metric={event.price} neutral />
            <Badge tone="neutral" data-downstream-stage={event.downstream_stage}>
              {humanizeCode(event.downstream_stage)}
            </Badge>
            {event.correction_of !== undefined && (
              <ReferenceChip reference={event.correction_of} label="Corrects" />
            )}
          </li>
        ))}
      </ol>

      {payload.gaps.length > 0 && (
        <div
          className="rounded-sm border border-warning/40 bg-warning/10 p-2.5"
          data-testid="lifecycle-gaps"
        >
          <p className="text-label-s leading-relaxed text-warning">
            <strong>Intervals nothing observed.</strong> A gap is shown as a gap; nothing is
            interpolated across it and no event is inferred from the ones around it.
          </p>
          <ul className="mt-1 space-y-0.5">
            {payload.gaps.map((gap) => (
              <li key={gap.between[0]} className="font-mono text-label-s text-text-secondary">
                {gap.between[0].slice(0, 10)} → {gap.between[1].slice(0, 10)} · {gap.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      <PanelSection
        title="Event kinds this timeline does not carry"
        note="Order and fill mechanics, protective-order events and reconciliation belong to Execution History, and this cycle implements none of them."
      >
        <ul className="flex flex-wrap gap-2" data-testid="absent-event-kinds">
          {payload.absent_kinds.map((absent) => (
            <li key={absent.kind.code}>
              <span className="inline-flex items-center gap-2 rounded-sm border border-border-subtle bg-surface-sunken px-2 py-1">
                <span className="text-label-s text-text-secondary">
                  {humanizeCode(absent.kind.code)}
                </span>
                <AvailabilityBadge state={absent.availability} reason={absent.reason} />
              </span>
            </li>
          ))}
        </ul>
      </PanelSection>
    </div>
  );
}

function Gaps({ payload }: { payload: TradeDetailPayload }) {
  return (
    <Card className="border-0 shadow-none">
      <CardHeader className="px-0 pt-0">
        <Label>Missing stages</Label>
      </CardHeader>
      <CardBody className="px-0 pb-0">
        <ScrollRegion label="Stages this trade detail does not carry">
          <table className="w-full min-w-[30rem] border-collapse text-label-m" data-testid="trade-gaps">
            <caption className="sr-only">
              Each stage of the complete trade story that this cycle does not carry, with the
              availability state and closed reason code that explain its absence.
            </caption>
            <thead>
              <tr className="border-b border-border-subtle text-left text-text-tertiary">
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  Stage
                </th>
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  State
                </th>
                <th scope="col" className="py-1.5 font-medium">
                  Reason
                </th>
              </tr>
            </thead>
            <tbody>
              {payload.gaps.map((gap) => (
                <tr
                  key={gap.expected.code}
                  className="border-b border-border-subtle last:border-0"
                  data-gap={gap.expected.code}
                >
                  <th
                    scope="row"
                    className="py-1.5 pr-4 text-left font-normal text-text-secondary"
                  >
                    {humanizeCode(gap.expected.code)}
                  </th>
                  <td className="py-1.5 pr-4">
                    <AvailabilityBadge state={gap.availability} reason={gap.reason} />
                  </td>
                  <td className="py-1.5 font-mono text-label-s text-unavailable">
                    {gap.reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
        <p className="mt-3 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
          <strong className="text-text-secondary">
            The complete Candidate → Brain → Risk → Execution → Reconciliation → Attribution
            workflow is C6&rsquo;s
          </strong>
          , and this cycle implements the history and a basic detail only. Naming the stages
          here is not a claim that any of them exists.
        </p>
      </CardBody>
    </Card>
  );
}
