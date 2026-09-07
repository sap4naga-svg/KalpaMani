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
  AddPlannedRiskRecords,
  InitialPlannedRiskRecord,
  OpenPlannedRiskRecord,
  RiskSeparationNote,
} from "@/components/cockpit/risk-records";
import { TradePriceChart, type ChartLevel, type ChartMarker } from "@/components/cockpit/trade-chart";
import type { ExecutionQuality } from "@/contracts/execution-models";
import { isValueBearing } from "@/contracts/validity";
import { useScope } from "@/components/shell/use-scope";
import { useTradeDetail, useTradeLifecycle } from "@/data/client/hooks";
import type { TradeDetailPayload, TradeLifecyclePayload } from "@/contracts/portfolio-models";
import { humanizeCode } from "@/lib/format";
import { withScope } from "@/lib/scope";

/**
 * Trade Detail — Area 36.2, the complete lifecycle C6 owns.
 *
 * ```text
 * Candidate -> Brain Decision -> Risk Decision -> Order -> Fill(s) -> Protection
 *     -> Pyramid / Adds -> Exit -> Reconciliation -> Attribution
 * ```
 *
 * WHAT THIS PAGE RECONSTRUCTS, for a trade whose execution evidence was recorded: the
 * candidate and its thesis by reference, the orders and each of their fills, the reference
 * price each fill was measured against and the slippage that follows, protective-order
 * placement, amendment, correction and cancellation, adds, partial exits, the exit,
 * reconciliation, a declared attribution and a benchmark aligned to exactly this trade's
 * holding period.
 *
 * THE RISK DECISION IS CARRIED WHERE THE BOOK RECORDS ONE. It is a SEPARATELY OWNED
 * downstream fact (`COCKPIT_FEEDBACK_EXTENSION.md` §3) joined here by reference, and it says
 * what size was assigned, against which prices, under which policy version, and which
 * retained entry-stage record it reconciles with. **No risk engine exists**: these are
 * immutable repository-owned records, they authorize nothing, and a trade whose sizing
 * nobody wrote down still reports the absence rather than a number.
 *
 * WHAT IT STILL DOES NOT: the immutable audit events, which are Area 26's separate screen
 * and are named as a gap.
 *
 * **A MISSING EVENT RENDERS AS A GAP AND NEVER AS AN INFERENCE.** Most trades in the book
 * have no execution record at all, and theirs say so rather than being filled in from a
 * position size.
 *
 * **THE FOUR CONCEPTS STAY APART** (Area 36.3). This is one trade's story. Execution History
 * and the Audit Trail are separate destinations, and this page links to neither by pretending
 * a reference resolves when it does not.
 */
/**
 * The joined risk decision, or the absence where nobody recorded one.
 *
 * **The size is shown WITH the two prices it was assigned against**, because
 * `shares x |reference - invalidation|` is the risk it assigned and a reader given only the
 * share count cannot check it. A declined decision assigned nothing, and renders the reasons
 * rather than a size that was refused.
 */
function RiskDecisionRecord({
  decision,
  operator,
}: {
  decision: TradeDetailPayload["risk_decision"];
  operator: boolean;
}) {
  if (decision === undefined) {
    return (
      <div className="space-y-1" data-testid="trade-risk-decision-absent">
        <AvailabilityBadge state="NOT_IMPLEMENTED" reason="PRODUCER_NOT_IMPLEMENTED" />
        <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
          No risk decision was recorded for this trade, so nothing here says why this size
          rather than another. The absence is reported and never filled in from the position.
        </p>
      </div>
    );
  }
  const declined = decision.outcome === "REJECTED";
  return (
    <div className="space-y-3" data-testid="trade-risk-decision">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={declined ? "warning" : "neutral"} data-testid="risk-decision-outcome">
          {humanizeCode(decision.outcome_reason.code)}
        </Badge>
        <span className="text-label-s text-text-tertiary">{decision.decided_at}</span>
      </div>
      {declined ? (
        <ul className="space-y-1" data-testid="risk-decision-rejection-reasons">
          {decision.rejection_reasons.map((reason) => (
            <li key={reason.code} className="text-label-s text-text-secondary">
              {humanizeCode(reason.code)}
            </li>
          ))}
        </ul>
      ) : (
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="risk-decision-sizing">
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">Shares assigned</dt>
            <dd>
              <MetricText metric={decision.sizing.shares} neutral operator={operator} />
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">Reference price</dt>
            <dd>
              <MetricText metric={decision.sizing.reference_price} neutral operator={operator} />
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">Invalidation level</dt>
            <dd>
              <MetricText metric={decision.sizing.invalidation_price} neutral operator={operator} />
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">Risk assigned</dt>
            <dd>
              <MetricText metric={decision.assigned_risk} neutral operator={operator} />
            </dd>
          </div>
        </dl>
      )}
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        {declined
          ? "Declined at the recorded size. No shares were assigned, no risk was committed and no order was produced."
          : "Shares times the distance from the reference price to the invalidation level is the risk this decision assigned, and it reconciles with the entry stage's retained record."}
      </p>
      {operator && (
        <dl className="grid gap-3 sm:grid-cols-3" data-testid="risk-decision-operator">
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">Decision id</dt>
            <dd className="font-mono text-label-s text-text-secondary">{decision.decision_id}</dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">Risk policy version</dt>
            <dd className="font-mono text-label-s text-text-secondary">
              {decision.risk_policy_ref.policy_version}
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">Traceable to</dt>
            <dd>
              <ReferenceChip reference={decision.initial_risk_ref} label="Initial risk record" />
            </dd>
          </div>
        </dl>
      )}
    </div>
  );
}

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
        summary="One trade's story, from the candidate that produced it to the reconciliation that closed it, joined from separately owned records by reference. Every stage without a recorded fact is named rather than filled in."
        pageState="PARTIAL"
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 36 — complete lifecycle</Badge>
          <Badge tone="unavailable">No risk engine exists</Badge>
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
          title="Execution quality"
          description="Each fill against the named reference price it was measured on, with the side convention that makes an adverse buy and an adverse sell both read positive."
          envelope={detail.data}
          dependency="the execution runtime and its recorded reference prices"
          operator={operator}
          testId="trade-execution-panel"
        >
          {(payload) => <Execution payload={payload} operator={operator} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Attribution and benchmark"
          description="A declared decomposition of the trade's outcome, and the benchmark's movement over exactly this trade's holding period."
          envelope={detail.data}
          dependency="a factor model, a regime model and a cost model — none exists"
          operator={operator}
          testId="trade-attribution-panel"
        >
          {(payload) => <Attribution payload={payload} operator={operator} />}
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
  /*
   * ONLY POSITION EVENTS PRODUCE A MARKER.
   *
   * The complete lifecycle now carries order submissions, acknowledgements, individual fills,
   * protective-order events and a reconciliation. Drawing a marker for each would put eleven
   * glyphs on a session that had one entry, and an acknowledgement is not a price the trade
   * transacted at. The table below the plot carries the whole timeline.
   */
  const POSITION_KINDS = [
    "ENTRY_RECORDED",
    "PYRAMID_ADD_RECORDED",
    "PARTIAL_EXIT_RECORDED",
    "EXIT_RECORDED",
  ];
  return lifecycle.events
    .filter((event) => POSITION_KINDS.includes(event.event_kind.code))
    .map((event) => {
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
 * The invalidation level is carried as a REFERENCE, never an order, and the retained risk
 * records are the only ones this page has a number for. A current protective level belongs to
 * the protective-order record, which does not exist.
 *
 * A pyramided trade draws one line per retained record, at each stage's OWN reference price:
 * the entry's line is the price the entry actually filled at, and the add's is its own. One
 * blended line would draw a price no stage was ever recorded against.
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
    ...(payload.summary.add_planned_risk ?? []).map((add) => ({
      label: `Add ${add.stage_ordinal} reference`,
      price: add.record.reference_price.amount,
      note: "the price that add's own risk record was set against",
    })),
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
    <div className="space-y-4" data-testid="trade-identity">
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

      {summary.shares_acquired !== undefined && (
        <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
          <strong className="text-text-secondary">This trade added to its position.</strong>{" "}
          The entry quantity and entry price below are the original entry&apos;s and are not
          restated by the add; what the trade went on to hold is carried separately, with the
          basis that add produced. Each stage keeps its own retained risk record.
        </p>
      )}

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {(
          [
            ["Security", `${summary.security.symbol} · ${summary.security.display_name}`],
            ["Trade identity", summary.trade_id],
            ["Entry", summary.entry_time],
            ["Shares at entry", summary.shares_at_entry.toLocaleString("en-US")],
            ...(summary.shares_acquired === undefined
              ? []
              : ([
                  [
                    "Shares acquired — entry plus adds",
                    summary.shares_acquired.toLocaleString("en-US"),
                  ],
                ] as const)),
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
            Entry price
          </dt>
          <dd>
            <MetricText metric={summary.entry_price} neutral operator={operator} />
          </dd>
        </div>
        {summary.current_basis !== undefined && (
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Current basis — after adds
            </dt>
            <dd>
              <MetricText metric={summary.current_basis} neutral operator={operator} />
            </dd>
          </div>
        )}
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
            [
              "R multiple",
              summary.r_multiple,
              /* The retained records: this trade's one, or the sum of its stages' (§12.4). */
              summary.r_denominator === undefined
                ? "initial planned risk"
                : "the retained stage risks, summed",
            ],
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

      <div
        className="grid gap-5 border-t border-border-subtle pt-3 lg:grid-cols-2"
        data-testid="trade-risk"
      >
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
        {summary.add_planned_risk !== undefined && (
          <PanelSection
            title="Each add's retained record — and the summed R denominator"
            note="An add carries its own record at its own reference price and as-of. It never edits the entry's."
          >
            <AddPlannedRiskRecords
              adds={summary.add_planned_risk}
              denominator={summary.r_denominator}
              operator={operator}
            />
          </PanelSection>
        )}
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
        title="The risk decision — why this size"
        note="A separately owned downstream record, joined by reference. It assigned the size; it did not decide the opportunity, and it authorized no order."
      >
        <RiskDecisionRecord decision={payload.risk_decision} operator={operator} />
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

/* ---------------------------------------------------------------- execution */

/** The four order sides, in words. **A short OPENS with a sell and CLOSES with a buy.** */
const SIDE_LABEL: Readonly<Record<string, string>> = {
  BUY_TO_OPEN: "Buy to open",
  BUY_TO_COVER: "Buy to cover",
  SELL_TO_CLOSE: "Sell to close",
  SELL_TO_OPEN: "Sell to open",
};

function Execution({
  payload,
  operator,
}: {
  payload: TradeDetailPayload;
  operator: boolean;
}) {
  if (payload.execution_quality === undefined) {
    return (
      <div className="space-y-2" data-testid="trade-execution-absent">
        <AvailabilityBadge state="NOT_YET_AVAILABLE" reason="UPSTREAM_INPUT_MISSING" />
        <p className="max-w-3xl text-label-m leading-relaxed text-text-secondary">
          <strong>No order or fill evidence was recorded for this trade.</strong> The ledger row
          says how many shares it acquired; it does not say whether that was one fill or four,
          what reference price the order was measured against, or whether anybody reconciled
          it. Deriving those from a quantity would manufacture an execution history out of a
          position size.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-4" data-testid="trade-execution">
      <ScrollRegion label="Per-fill execution quality">
        <table
          className="w-full min-w-[46rem] border-collapse text-label-m"
          data-testid="fill-quality"
        >
          <caption className="sr-only">
            Each recorded fill, its order side, the quantity it filled, the price it filled at,
            the named reference price it was measured against and the resulting slippage in
            basis points.
          </caption>
          <thead>
            <tr className="border-b border-border-subtle text-left text-text-tertiary">
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Side
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Quantity
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Reference
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Fill
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Slippage
              </th>
              <th scope="col" className="py-1.5 font-medium">
                Order filled
              </th>
            </tr>
          </thead>
          <tbody>
            {payload.fill_quality.map((record) => (
              <tr
                key={record.subject_ref.ref_id}
                className="border-b border-border-subtle last:border-0"
                data-side={record.side}
              >
                <th scope="row" className="py-1.5 pr-4 text-left font-normal text-text-secondary">
                  {SIDE_LABEL[record.side] ?? record.side}
                </th>
                <td className="py-1.5 pr-4">
                  <MetricText metric={record.quantity} neutral />
                </td>
                <td className="py-1.5 pr-4">
                  <MetricText metric={record.reference_price.price} neutral operator={operator} />
                </td>
                <td className="py-1.5 pr-4">
                  <MetricText metric={record.fill_price} neutral operator={operator} />
                </td>
                <td className="py-1.5 pr-4">
                  <MetricText metric={record.slippage} operator={operator} />
                </td>
                <td className="py-1.5">
                  <MetricText metric={record.fill_rate} neutral />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollRegion>

      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        <strong className="text-text-secondary">Positive slippage is adverse, on both
        sides.</strong>{" "}
        A buy filled above its reference and a sell filled below its reference are the same
        cost, and the side convention is what makes both report a positive figure — without it
        a book of adverse buys and adverse sells averages to zero and reports perfect
        execution. <strong className="text-text-secondary">The order side is not the
        position&rsquo;s direction</strong>: a short opens with a sell and closes with a buy.
      </p>

      <AggregateQuality record={payload.execution_quality} operator={operator} />
    </div>
  );
}

function AggregateQuality({
  record,
  operator,
}: {
  record: ExecutionQuality;
  operator: boolean;
}) {
  return (
    <PanelSection
      title="The trade-level aggregate"
      note="Quantity-weighted over fills with a resolvable reference, under the named aggregation method."
      testId="aggregate-quality"
    >
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Aggregate slippage
          </dt>
          <dd>
            <MetricText metric={record.slippage} operator={operator} />
          </dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Fill rate
          </dt>
          <dd>
            <MetricText metric={record.fill_rate} neutral />
          </dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Signal to order
          </dt>
          <dd>
            <MetricText metric={record.signal_to_order_latency} neutral />
          </dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Order to first fill
          </dt>
          <dd>
            <MetricText metric={record.order_to_fill_latency} neutral />
          </dd>
        </div>
      </dl>
      <p className="mt-2 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        Observations:{" "}
        <span className="font-mono text-text-secondary">
          {String(record.observation_count.value ?? "—")}
        </span>{" "}
        against a declared minimum of{" "}
        <span className="font-mono text-text-secondary">
          {String(record.minimum_observations.value ?? "—")}
        </span>
        .{" "}
        {!isValueBearing(record.slippage.availability) && (
          <>
            <strong className="text-text-secondary">
              Below its minimum, so it is not computed.
            </strong>{" "}
            A quantity-weighted average over four fills is a number whose own rule says it is
            not meaningful; the per-fill values above stay available, because their declared
            minimum is one fill.
          </>
        )}{" "}
        Excluded fills:{" "}
        <span className="font-mono text-text-secondary">
          {String(record.excluded_fills?.value ?? "—")}
        </span>{" "}
        — a fill with no resolvable reference is excluded and counted, because an average over a
        silently reduced population is a different metric.
      </p>
      <p className="mt-1.5 text-label-s text-text-tertiary">
        Clock: <span className="font-mono">{humanizeCode(record.clock_source.code)}</span>,
        accurate to <MetricText metric={record.clock_accuracy} neutral />. Reference:{" "}
        <span className="font-mono">{humanizeCode(record.reference_price.name.code)}</span> at{" "}
        <span className="font-mono">{record.reference_price.at}</span>.
      </p>
    </PanelSection>
  );
}

/* -------------------------------------------------------------- attribution */

function Attribution({
  payload,
  operator,
}: {
  payload: TradeDetailPayload;
  operator: boolean;
}) {
  const attributed = isValueBearing(payload.attribution.strategy.availability);
  return (
    <div className="space-y-4" data-testid="trade-attribution">
      <PanelSection
        title="Attribution"
        note={
          attributed
            ? "A DECLARED decomposition of this trade's combined result. The five components sum to the outcome exactly, because a decomposition that does not add up to the thing it decomposes is five numbers rather than an attribution."
            : "Strategy, factor, regime, execution and cost attribution each need a producer that does not exist. A provisional zero would be a decomposition nobody computed."
        }
        state={
          attributed
            ? undefined
            : { availability: "NOT_YET_AVAILABLE", reason: "UPSTREAM_INPUT_MISSING" }
        }
      >
        <dl className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {(
            [
              ["Strategy", payload.attribution.strategy],
              ["Factor", payload.attribution.factor],
              ["Regime", payload.attribution.regime],
              ["Execution", payload.attribution.execution],
              ["Cost", payload.attribution.cost],
            ] as const
          ).map(([term, metric]) => (
            <div key={term} className="flex flex-col gap-0.5">
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                {term}
              </dt>
              <dd>
                <MetricText metric={metric} operator={operator} />
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-label-s text-text-tertiary">
          Attribution state:{" "}
          <Badge tone={payload.attribution.state === "FINAL" ? "neutral" : "warning"}>
            {payload.attribution.state}
          </Badge>{" "}
          — a provisional decomposition is labelled, and finalization is a recorded event.
        </p>
      </PanelSection>

      <PanelSection
        title="Benchmark over this trade's holding period"
        note="Aligned to exactly the boundaries the trade used, and stating its return basis so a price-return benchmark is never read against a total-return subject."
        testId="trade-benchmark"
      >
        <div className="flex flex-wrap items-baseline gap-3">
          <MetricText metric={payload.benchmark_movement} />
          <Badge tone="neutral">{payload.benchmark_basis}</Badge>
          {payload.benchmark_label !== undefined && (
            <Badge tone="unavailable">{humanizeCode(payload.benchmark_label.code)}</Badge>
          )}
        </div>
        {payload.benchmark_window !== undefined && (
          <p className="mt-1.5 font-mono text-label-s text-text-tertiary">
            {payload.benchmark_window.from} → {payload.benchmark_window.to}
          </p>
        )}
        <p className="mt-2 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
          <strong className="text-text-secondary">
            The index is a synthetic demonstration series, not a real benchmark.
          </strong>{" "}
          No provider is selected, G1 is OPEN, and no benchmark price history is requested from
          anywhere. It pays no dividend and reinvests nothing — and neither do the demonstration
          securities beside it — so both sides of the comparison are price returns.
        </p>
        {payload.benchmark_series !== undefined && (
          <ScrollRegion
            label="Benchmark movement since this trade's entry"
            className="mt-2"
          >
            <table className="w-full min-w-[24rem] border-collapse text-label-s">
              <caption className="sr-only">
                The benchmark&rsquo;s movement since this trade&rsquo;s entry, one point per
                session over exactly the trade&rsquo;s holding period.
              </caption>
              <thead>
                <tr className="border-b border-border-subtle text-left text-text-tertiary">
                  <th scope="col" className="py-1 pr-4 font-medium">
                    Session
                  </th>
                  <th scope="col" className="py-1 font-medium">
                    Since entry
                  </th>
                </tr>
              </thead>
              <tbody>
                {payload.benchmark_series.points.map((point) => (
                  <tr key={String(point.t)} className="border-b border-border-subtle last:border-0">
                    <th
                      scope="row"
                      className="py-1 pr-4 text-left font-mono font-normal text-text-tertiary"
                    >
                      {String(point.t)}
                    </th>
                    <td className="py-1">
                      <MetricText metric={point.v} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
        )}
      </PanelSection>
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
            {event.observed_time !== event.event_time && (
              <Badge tone="warning" data-testid="late-observation">
                observed {event.observed_time.slice(11, 16)}Z — later than it happened
              </Badge>
            )}
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

      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        <strong className="text-text-secondary">Ordered by when each event happened.</strong>{" "}
        An event that reached this system late is retained at the instant it occurred, with its
        observation time shown beside it — a late event advances no watermark it did not cover.
        <strong className="text-text-secondary"> A correction appends.</strong> The event it
        corrects stays in this list, unchanged, and the correction points at it.
      </p>

      <PanelSection
        title="Event kinds this timeline does not carry"
        note="Each with the state that explains it. A kind absent because nobody recorded it for THIS trade is not the same as a kind no producer can write."
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
