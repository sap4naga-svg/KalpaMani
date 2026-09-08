"use client";

import * as React from "react";

import { Badge, Label } from "@/components/ui/primitives";
import { DataTable, RowCount, columnsFor, type TableColumns } from "@/components/cockpit/data-table";
import { FilterBar, SearchField, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { MetricTile } from "@/components/cockpit/metric-tile";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import {
  ComparisonChart,
  ReasonList,
  ReferenceRow,
  SectionState,
  type ComparisonRow,
} from "@/components/cockpit/research";
import {
  Fact,
  FactGrid,
  OperationsReadOnlyNotice,
  StateBadge,
  WindowStatement,
} from "@/components/cockpit/operations";
import { useScope } from "@/components/shell/use-scope";
import { usePageFilters } from "@/components/shell/use-page-filters";
import type { ExecutionQualityRecord } from "@/contracts/execution-quality-page";
import { ORDER_LIFECYCLE_STATES } from "@/contracts/execution-quality-page";
import { useExecutionQuality } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";
import type { ViewScope } from "@/lib/scope";

/**
 * Execution Quality — Area 9.
 *
 * "Show what the order machinery did, and what it cost."
 *
 *   DISPLAYING AN ORDER LIFECYCLE IS NOT     nothing on this screen submits, cancels, amends
 *   PARTICIPATING IN ONE                     or retries anything, and no such control exists
 *   NO BROKER-NATIVE IDENTIFIER APPEARS      every identity rendered here is a safe internal
 *                                            one; there is no account, no session and no
 *                                            broker order id anywhere in the payload
 *   SLIPPAGE CARRIES ITS WHOLE DEFINITION    the named reference price, its timestamp, the
 *                                            side convention and the signed basis-point scale
 *                                            travel with every figure
 *   A SAMPLE BELOW ITS MINIMUM IS A STATE    the window aggregate reports
 *                                            INSUFFICIENT_OBSERVATIONS rather than an average
 *                                            over a population its own rule calls too small
 *   AN ORDER ROW IS NOT A TRADE              a fill is never counted as a trade, a cancel is
 *                                            never an exit, and a submitted protective order
 *                                            is never proof of active protection
 */

const FILTER_KEYS = ["state", "module", "q"] as const;

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const quality = useExecutionQuality(scope);
  const payload = quality.data?.payload;
  const { filters, setFilter, clearFilter, clearAll, activeKeys } =
    usePageFilters(FILTER_KEYS);

  const rows = React.useMemo(() => {
    if (payload === undefined) {
      return [];
    }
    return payload.items.filter((row) => {
      if (filters.state !== "" && row.lifecycle_state !== filters.state) {
        return false;
      }
      if (filters.module !== "" && row.strategy_module.code !== filters.module) {
        return false;
      }
      return true;
    });
  }, [payload, filters.state, filters.module]);

  const modules = React.useMemo(() => {
    const seen = new Set((payload?.items ?? []).map((row) => row.strategy_module.code));
    return [...seen].sort().map((code) => ({ value: code, label: humanizeCode(code) }));
  }, [payload]);

  return (
    <>
      <PageHeader
        title="Execution Quality"
        summary="Recorded order and fill mechanics, and what they cost against a named reference price. Slippage is signed basis points, latency states its clock, and the window aggregate reports its rule rather than a number it is not entitled to."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 9</Badge>
          <Badge tone="unavailable">Execution runtime: NOT IMPLEMENTED</Badge>
          <Badge tone="neutral">No broker-native identifier is rendered</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <OperationsReadOnlyNotice
          subject="recorded order and fill events"
          actions={["submit", "cancel", "amend", "retry", "route"]}
          producer="No automated execution runtime exists beyond the certified Phase 2 scope, and the broker is flat"
        />

        <ReadModelPanel
          title="The window, and what every figure was measured against"
          description="Slippage without a named reference price, its timestamp and a side convention is not a number this contract admits."
          envelope={quality.data}
          dependency="the execution runtime — no automated execution runtime exists"
          operator={operator}
          testId="execution-basis"
        >
          {(loaded) => (
            <div className="space-y-3">
              <WindowStatement window={loaded.window} label="Recorded events from" />
              <FactGrid>
                <Fact label="Reference price" testId="reference-name">
                  {humanizeCode(loaded.reference_basis.name.code)}
                </Fact>
                <Fact label="Side convention" testId="side-convention">
                  {humanizeCode(loaded.reference_basis.side_convention.code)}
                </Fact>
                <Fact label="Clock source" testId="clock-source">
                  {humanizeCode(loaded.reference_basis.clock_source.code)}
                </Fact>
              </FactGrid>
              <SectionState
                availability={loaded.runtime_state.availability}
                reason={loaded.runtime_state.reason}
                note={humanizeCode(loaded.runtime_state.note.code)}
                testId="runtime-state"
              />
              <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                <strong className="text-text-secondary">
                  Positive is adverse cost; negative is a favourable fill.
                </strong>{" "}
                A buy ten basis points above its reference and a sell ten below it are the same
                cost, and the side convention is what makes both report <code>+10</code>.
              </p>
            </div>
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="The window aggregate"
          description="Quantity-weighted over the fills that have a resolvable reference. Fills with no reference are excluded and counted."
          envelope={quality.data}
          dependency="the execution runtime — no automated execution runtime exists"
          operator={operator}
          testId="execution-aggregate"
        >
          {(loaded) => (
            <div className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <MetricTile
                  label="Slippage, aggregate"
                  metric={loaded.aggregate.slippage}
                  provenance="SYNTHETIC"
                  dependency="twenty fills with a resolvable reference price"
                  operator={operator}
                  denominator="reference price"
                />
                <MetricTile
                  label="Fill rate"
                  metric={loaded.aggregate.fill_rate}
                  provenance="SYNTHETIC"
                  operator={operator}
                  denominator="ordered quantity"
                />
                <MetricTile
                  label="Signal to order"
                  metric={loaded.aggregate.signal_to_order_latency}
                  provenance="SYNTHETIC"
                  operator={operator}
                />
                <MetricTile
                  label="Order to first fill"
                  metric={loaded.aggregate.order_to_fill_latency}
                  provenance="SYNTHETIC"
                  operator={operator}
                />
              </div>

              <PanelSection
                title="The population this aggregate was computed over"
                note="A value below its declared minimum reports the state, not a number — and an average over a silently reduced population is a different metric."
                testId="aggregate-population"
              >
                <FactGrid columns={3}>
                  <Fact label="Observations" testId="aggregate-observed">
                    <MetricText metric={loaded.aggregate_population.observed} neutral />
                  </Fact>
                  <Fact label="Declared minimum" testId="aggregate-minimum">
                    <MetricText metric={loaded.aggregate_population.minimum} neutral />
                  </Fact>
                  <Fact label="Excluded, no reference" testId="aggregate-excluded">
                    <MetricText metric={loaded.aggregate_population.excluded} neutral />
                  </Fact>
                </FactGrid>
                <div className="mt-2">
                  <Label>Why an observation was excluded</Label>
                  <div className="mt-1">
                    <ReasonList
                      codes={loaded.aggregate_population.exclusion_reasons}
                      tone="warning"
                      empty="No observation was excluded from this aggregate."
                      testId="exclusion-reasons"
                    />
                  </div>
                </div>
                <p className="mt-2 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                  Aggregated by{" "}
                  <strong className="text-text-secondary">
                    {humanizeCode(loaded.aggregate.aggregation_method.code)}
                  </strong>
                  . The clock is {humanizeCode(loaded.aggregate.clock_source.code)}, accurate to{" "}
                  <MetricText metric={loaded.aggregate.clock_accuracy} neutral />.
                </p>
              </PanelSection>
            </div>
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="Recorded lifecycle outcomes"
          description="Fills, partial fills, rejects, cancels, duplicate suppressions and missed fills — each counted separately, and an unmeasured one stated as unmeasured."
          envelope={quality.data}
          dependency="the execution runtime — no automated execution runtime exists"
          operator={operator}
          testId="execution-outcomes"
        >
          {(loaded) => (
            <div className="space-y-3">
              <ComparisonChart
                caption="Recorded lifecycle outcomes in the window"
                rows={loaded.outcomes.map(
                  (entry): ComparisonRow => ({
                    label: entry.outcome.code,
                    value: entry.count,
                  }),
                )}
                unitLabel="observations"
                testId="outcome-chart"
              />
              <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                <strong className="text-text-secondary">A cancellation is not an exit</strong>{" "}
                and a fill is not a trade. These are order events; the position they touched is
                a different record, on a different screen.
              </p>
            </div>
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="Recorded orders and fills"
          description="One row per recorded fill, plus the illustrative rows this page names explicitly."
          envelope={quality.data}
          dependency="the execution runtime — no automated execution runtime exists"
          operator={operator}
          testId="execution-rows"
          always={
            <FilterBar
              chips={activeKeys.map((key) => ({
                key,
                label: key === "q" ? "Search" : key === "state" ? "Lifecycle" : "Module",
                value: filters[key],
              }))}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
            >
              <SelectField
                id="execution-state"
                label="Lifecycle"
                value={filters.state}
                options={ORDER_LIFECYCLE_STATES.map((state) => ({
                  value: state,
                  label: humanizeCode(state),
                }))}
                onChange={(next) => setFilter("state", next)}
              />
              <SelectField
                id="execution-module"
                label="Strategy module"
                value={filters.module}
                options={modules}
                onChange={(next) => setFilter("module", next)}
              />
              <SearchField
                id="execution-search"
                label="Search"
                value={filters.q}
                placeholder="Record, order or trade"
                onChange={(next) => setFilter("q", next)}
              />
            </FilterBar>
          }
        >
          {(loaded) => (
            <div className="space-y-3">
              <ExecutionTable
                rows={rows}
                globalFilter={filters.q}
                scope={scope}
                operator={operator}
                illustrative={loaded.illustrative_record_ids}
              />
              <RowCount shown={rows.length} total={loaded.items.length} noun="records" />
              <IllustrativeNote ids={loaded.illustrative_record_ids} />
            </div>
          )}
        </ReadModelPanel>
      </div>
    </>
  );
}

/** What the illustrative rows are, named by identifier rather than left indistinguishable. */
function IllustrativeNote({ ids }: { ids: readonly string[] }) {
  if (ids.length === 0) {
    return null;
  }
  return (
    <p
      className="max-w-3xl rounded-sm border border-warning/40 bg-surface-sunken px-3 py-2 text-label-s leading-relaxed text-text-tertiary"
      data-testid="illustrative-note"
    >
      <strong className="text-warning">
        {ids.length} of these rows are illustrative rather than projected from the recorded
        book.
      </strong>{" "}
      The recorded execution evidence contains no rejected order, no cancelled order and no
      fill whose reference price went unrecorded, so three lifecycle outcomes this area exists
      to show have no row to render. They are named here —{" "}
      <span className="font-mono text-text-secondary">{ids.join(", ")}</span> — and the
      aggregate above was computed over the recorded fills only, so an illustrative row cannot
      move a headline.
    </p>
  );
}

const LIFECYCLE_TONE: Readonly<
  Record<string, React.ComponentProps<typeof Badge>["tone"]>
> = {
  FILLED: "positive",
  PARTIALLY_FILLED: "warning",
  SUBMITTED: "neutral",
  ACKNOWLEDGED: "neutral",
  REJECTED: "negative",
  CANCELLED: "warning",
};

const helper = columnsFor<ExecutionQualityRecord>();

function ExecutionTable({
  rows,
  globalFilter,
  scope,
  operator,
  illustrative,
}: {
  rows: readonly ExecutionQualityRecord[];
  globalFilter: string;
  scope: ViewScope;
  operator: boolean;
  illustrative: readonly string[];
}) {
  const columns = React.useMemo<TableColumns<ExecutionQualityRecord>>(
    () =>
      helper.columns([
        helper.accessor((row) => row.record_id, {
          id: "record",
          header: () => "Record",
          cell: ({ row }) => (
            <span className="inline-flex flex-wrap items-center gap-1.5">
              <span className="font-mono text-label-s text-text-secondary">
                {row.original.record_id}
              </span>
              {illustrative.includes(row.original.record_id) && (
                <Badge tone="warning" data-testid="illustrative-row">
                  Illustrative
                </Badge>
              )}
            </span>
          ),
        }),
        helper.accessor((row) => row.lifecycle_state, {
          id: "lifecycle",
          header: () => "Lifecycle",
          cell: ({ row }) => (
            <Badge
              tone={LIFECYCLE_TONE[row.original.lifecycle_state] ?? "neutral"}
              data-lifecycle={row.original.lifecycle_state}
            >
              {humanizeCode(row.original.lifecycle_state)}
            </Badge>
          ),
        }),
        helper.accessor((row) => row.side, {
          id: "side",
          header: () => "Side",
          cell: ({ row }) => (
            <span className="font-mono text-label-s" data-side={row.original.side}>
              {humanizeCode(row.original.side)}
            </span>
          ),
        }),
        helper.accessor((row) => row.strategy_module.code, {
          id: "module",
          header: () => "Module",
          cell: ({ row }) => humanizeCode(row.original.strategy_module.code),
        }),
        helper.accessor(
          (row) =>
            typeof row.quality.slippage.value === "string"
              ? Number(row.quality.slippage.value)
              : Number.NEGATIVE_INFINITY,
          {
            id: "slippage",
            header: () => "Slippage",
            cell: ({ row }) => (
              <MetricText metric={row.original.quality.slippage} operator={operator} />
            ),
          },
        ),
        helper.accessor(
          (row) =>
            typeof row.quality.order_to_fill_latency.value === "number"
              ? row.quality.order_to_fill_latency.value
              : Number.NEGATIVE_INFINITY,
          {
            id: "latency",
            header: () => "Order to fill",
            cell: ({ row }) => (
              <MetricText metric={row.original.quality.order_to_fill_latency} neutral />
            ),
          },
        ),
        helper.accessor((row) => row.protective_order_state.code, {
          id: "protection",
          header: () => "Protection",
          cell: ({ row }) => (
            <StateBadge
              state={row.original.protective_order_state}
              tone={
                row.original.protective_order_state.code === "CONFIRMED_WORKING"
                  ? "positive"
                  : "warning"
              }
              attribute="protection-state"
            />
          ),
        }),
      ]),
    [illustrative, operator],
  );

  return (
    <DataTable
      caption="Recorded execution-quality records, one per fill or order"
      columns={columns}
      data={rows}
      getRowId={(row) => row.record_id}
      globalFilter={globalFilter}
      initialSorting={[{ id: "slippage", desc: true }]}
      columnClasses={{
        module: "hidden lg:table-cell",
        latency: "hidden md:table-cell",
        protection: "hidden lg:table-cell",
        side: "hidden sm:table-cell",
      }}
      empty="No recorded execution row matches this filter. Every row this read delivered is still part of the population the aggregate was computed over."
      testId="execution-table"
      renderDetail={(row) => <ExecutionDetail row={row} scope={scope} operator={operator} />}
    />
  );
}

function ExecutionDetail({
  row,
  scope,
  operator,
}: {
  row: ExecutionQualityRecord;
  scope: ViewScope;
  operator: boolean;
}) {
  return (
    <div className="space-y-3" data-testid={`execution-detail-${row.record_id}`}>
      <FactGrid columns={4}>
        <Fact label="Ordered">
          <MetricText metric={row.ordered_quantity} neutral />
        </Fact>
        <Fact label="Filled">
          <MetricText metric={row.filled_quantity} neutral />
        </Fact>
        <Fact label="Fill rate">
          <MetricText metric={row.quality.fill_rate} neutral />
        </Fact>
        <Fact label="Signal to order">
          <MetricText metric={row.quality.signal_to_order_latency} neutral />
        </Fact>
      </FactGrid>

      <PanelSection
        title="The reference this fill was measured against"
        note="A reference price that cannot be placed in time is not a reference."
      >
        <FactGrid columns={3}>
          <Fact label="Named reference">
            {humanizeCode(row.quality.reference_price.name.code)}
          </Fact>
          <Fact label="Reference at">
            <span className="font-mono text-label-s">{row.quality.reference_price.at}</span>
          </Fact>
          <Fact label="Reference price">
            <MetricText metric={row.quality.reference_price.price} neutral />
          </Fact>
          <Fact label="Fill price">
            <MetricText metric={row.quality.fill_price} neutral />
          </Fact>
          <Fact label="Side convention">
            {humanizeCode(row.quality.reference_price.side_convention.code)}
          </Fact>
          <Fact label="Clock accuracy">
            <MetricText metric={row.quality.clock_accuracy} neutral />
          </Fact>
        </FactGrid>
      </PanelSection>

      <PanelSection
        title="Cost, reported twice and never combined"
        note="An actual fill price already incorporates the spread crossed and the slippage realized, so a modelled cost is reported beside it and is never subtracted from it."
        testId={`cost-${row.record_id}`}
      >
        <FactGrid columns={3}>
          <Fact label="Modelled cost">
            <MetricText metric={row.modelled_cost} neutral />
          </Fact>
          <Fact label="Recorded cost">
            <MetricText metric={row.recorded_cost} neutral />
          </Fact>
          <Fact label="Cost treatment">{humanizeCode(row.cost_treatment.code)}</Fact>
        </FactGrid>
        <p className="mt-1 text-label-s text-text-tertiary">
          {humanizeCode(row.cost_comparison_basis.code)}
        </p>
      </PanelSection>

      <PanelSection
        title="Protection and duplicate-order protection"
        note="A submitted protective order is a submission. Cover is what a recorded confirmation establishes."
      >
        <FactGrid columns={2}>
          <Fact label="Protective order state">
            <StateBadge state={row.protective_order_state} attribute="protection-state" />
          </Fact>
          <Fact label="Confirmed at">
            <MetricText metric={row.protection_confirmed_at} neutral />
          </Fact>
          <Fact label="Duplicate protection">
            {humanizeCode(row.duplicate_protection.code)}
          </Fact>
          <Fact label="Recorded events">
            <MetricText metric={row.protective_order_refs.total} neutral /> protective
            references
          </Fact>
        </FactGrid>
      </PanelSection>

      <PanelSection title="Where this row belongs">
        <ul className="space-y-1">
          <li>
            <ReferenceRow reference={row.trade_ref} label="Trade" scope={scope} />
          </li>
          <li>
            <ReferenceRow reference={row.order_ref} label="Order" scope={scope} />
          </li>
          <li>
            <ReferenceRow
              reference={row.quality.subject_ref}
              label="Measured over"
              scope={scope}
            />
          </li>
        </ul>
      </PanelSection>

      {operator && (
        <p className="font-mono text-label-s text-text-tertiary">
          event_time={row.event_time} · observed_time={row.observed_time} · scope=
          {row.quality.scope}
        </p>
      )}
    </div>
  );
}
