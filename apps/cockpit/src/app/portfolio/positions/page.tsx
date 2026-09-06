"use client";

import * as React from "react";

import { Badge, Button, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { columnsFor, DataTable, RowCount } from "@/components/cockpit/data-table";
import { FilterBar, SearchField, SelectField } from "@/components/cockpit/filters";
import { MetricText, MoneyText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel, ReferenceChip } from "@/components/cockpit/read-model-panel";
import {
  GapEventRiskRecord,
  InitialPlannedRiskRecord,
  OpenPlannedRiskRecord,
  PermittedRiskRecord,
  RiskSeparationNote,
} from "@/components/cockpit/risk-records";
import { usePageFilters } from "@/components/shell/use-page-filters";
import { useScope } from "@/components/shell/use-scope";
import { useExposure, usePositions } from "@/data/client/hooks";
import type {
  ExposureAggregate,
  ExposureAggregatePayload,
  PositionSnapshot,
} from "@/contracts/portfolio-models";
import { humanizeCode } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * Positions & Exposure — Area 3.
 *
 * "Show what is owned, why, and what it is exposed to."
 *
 *   THE TWO RISK QUANTITIES ARE SEPARATE COLUMNS   initial planned risk is the immutable entry
 *                                                  record; current open planned risk is an
 *                                                  assessment with its own as-of. **A moving
 *                                                  stop changes only the second**, and two
 *                                                  positions in this book demonstrate it
 *   BORROW COMES FROM A RECORD                     one short has one and one does not, and the
 *                                                  one that does not renders UNKNOWN. Nothing
 *                                                  here reads a price to decide it
 *   A GROUPING IS DISPLAYED, NEVER COMPUTED        the exposure views are seven views of one
 *                                                  set of positions. **A position contributes
 *                                                  to each axis exactly once**, and no view
 *                                                  computes a permitted exposure
 *   SORTING AND FILTERING ARE PRESENTATION         they narrow what is shown. They change no
 *                                                  total, no population and no permission
 */

const FILTER_KEYS = ["q", "dir", "sector", "strategy", "borrow"] as const;

const columns = columnsFor<PositionSnapshot>();

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const positions = usePositions(scope);
  const exposure = useExposure(scope);
  const { filters, setFilter, clearFilter, clearAll } = usePageFilters(FILTER_KEYS);

  const items = React.useMemo(
    () => positions.data?.payload?.items ?? [],
    [positions.data],
  );

  const sectors = React.useMemo(
    () => [...new Set(items.map((row) => row.groupings.sector.code))].sort(),
    [items],
  );
  const strategies = React.useMemo(
    () => [...new Set(items.map((row) => row.groupings.strategy_module.code))].sort(),
    [items],
  );
  const borrowStates = React.useMemo(
    () =>
      [
        ...new Set(
          items
            .map((row) => row.borrow_state?.code)
            .filter((code): code is string => code !== undefined),
        ),
      ].sort(),
    [items],
  );

  /**
   * The typed filters, applied over the DELIVERED page.
   *
   * They are presentation: the population every figure on this page was computed over is the
   * whole delivered page, and narrowing the view does not narrow that.
   */
  const filtered = React.useMemo(
    () =>
      items.filter((row) => {
        if (filters.dir !== "" && row.direction !== filters.dir) return false;
        if (filters.sector !== "" && row.groupings.sector.code !== filters.sector) return false;
        if (filters.strategy !== "" && row.groupings.strategy_module.code !== filters.strategy)
          return false;
        if (filters.borrow !== "" && row.borrow_state?.code !== filters.borrow) return false;
        return true;
      }),
    [filters, items],
  );

  const tableColumns = React.useMemo(
    () =>
      columns.columns([
        columns.accessor((row) => `${row.security.symbol} ${row.security.display_name}`, {
          id: "security",
          header: () => "Security",
          cell: (info) => {
            const row = info.row.original;
            return (
              <span className="flex flex-col">
                <span className="font-mono text-text-primary">{row.security.symbol}</span>
                <span className="text-label-s text-text-tertiary">
                  {row.security.display_name}
                </span>
              </span>
            );
          },
        }),
        columns.accessor((row) => row.direction, {
          id: "direction",
          header: () => "Side",
          cell: (info) => (
            <Badge tone={info.row.original.direction === "LONG" ? "info" : "warning"}>
              <span aria-hidden="true">
                {info.row.original.direction === "LONG" ? "▲" : "▼"}
              </span>
              <span>{info.row.original.direction}</span>
            </Badge>
          ),
        }),
        columns.accessor((row) => row.quantity, {
          id: "quantity",
          header: () => "Shares",
          cell: (info) => (
            <span className="font-mono tabular-nums">
              {info.row.original.quantity.toLocaleString("en-US")}
            </span>
          ),
        }),
        columns.accessor((row) => Number(row.entry_price.value ?? 0), {
          id: "entry",
          header: () => "Entry",
          cell: (info) => <MetricText metric={info.row.original.entry_price} neutral />,
        }),
        columns.accessor((row) => Number(row.current_price.value ?? 0), {
          id: "mark",
          header: () => "Mark",
          cell: (info) => <MetricText metric={info.row.original.current_price} neutral />,
        }),
        columns.accessor((row) => Number(row.unrealized.amount), {
          id: "unrealized",
          header: () => "Unrealized",
          cell: (info) => (
            <MoneyText amount={info.row.original.unrealized.amount} signed />
          ),
        }),
        columns.accessor(
          (row) => Number(row.initial_planned_risk.record?.risk_money.amount ?? 0),
          {
            id: "initialRisk",
            header: () => "Initial planned risk",
            cell: (info) => {
              const wrapper = info.row.original.initial_planned_risk;
              return wrapper.record === undefined ? (
                <AvailabilityBadge state={wrapper.availability} reason={wrapper.reason} />
              ) : (
                <MoneyText amount={wrapper.record.risk_money.amount} />
              );
            },
          },
        ),
        columns.accessor(
          (row) => Number(row.open_planned_risk.record?.risk_money.value ?? 0),
          {
            id: "openRisk",
            header: () => "Current open planned risk",
            cell: (info) => {
              const wrapper = info.row.original.open_planned_risk;
              return wrapper.record === undefined ? (
                <AvailabilityBadge state={wrapper.availability} reason={wrapper.reason} />
              ) : (
                <span className="flex flex-col gap-0.5">
                  <MetricText metric={wrapper.record.risk_money} neutral />
                  <span className="font-mono text-label-s text-text-tertiary">
                    as of {wrapper.record.as_of.slice(0, 10)}
                  </span>
                </span>
              );
            },
          },
        ),
        columns.accessor((row) => Number(row.holding_duration.value ?? 0), {
          id: "holding",
          header: () => "Held",
          cell: (info) => <MetricText metric={info.row.original.holding_duration} neutral />,
        }),
        columns.accessor((row) => row.groupings.strategy_module.code, {
          id: "strategy",
          header: () => "Strategy",
          cell: (info) => {
            const row = info.row.original;
            const version = row.pins.strategy_version;
            return (
              <span className="flex flex-col">
                <span>{humanizeCode(row.groupings.strategy_module.code)}</span>
                <span className="font-mono text-label-s text-text-tertiary">
                  {typeof version === "string" ? version : "version not applicable"}
                </span>
              </span>
            );
          },
        }),
        columns.accessor((row) => row.groupings.sector.code, {
          id: "sector",
          header: () => "Sector",
          cell: (info) => (
            <span className="flex flex-col">
              <span>{humanizeCode(info.row.original.groupings.sector.code)}</span>
              <span className="text-label-s text-text-tertiary">
                {humanizeCode(info.row.original.groupings.industry.code)}
              </span>
            </span>
          ),
        }),
        columns.accessor((row) => row.borrow_state?.code ?? "", {
          id: "borrow",
          header: () => "Borrow",
          cell: (info) => {
            const state = info.row.original.borrow_state;
            if (state === undefined) {
              return (
                <span className="text-label-s text-text-tertiary">
                  Not applicable to a long
                </span>
              );
            }
            const unknown = state.code.includes("UNKNOWN");
            return (
              <Badge tone={unknown ? "warning" : "neutral"} data-borrow={state.code}>
                <span aria-hidden="true">{unknown ? "◌" : "●"}</span>
                <span>{humanizeCode(state.code)}</span>
              </Badge>
            );
          },
        }),
      ]),
    [],
  );

  const chips = FILTER_KEYS.filter((key) => filters[key] !== "").map((key) => ({
    key,
    label:
      key === "q"
        ? "Search"
        : key === "dir"
          ? "Side"
          : key === "borrow"
            ? "Borrow"
            : humanizeCode(key.toUpperCase()),
    value: filters[key],
  }));

  const degraded =
    positions.data !== undefined &&
    (positions.data.completeness === "PARTIAL" || positions.data.payload === undefined);

  return (
    <>
      <PageHeader
        title="Positions & Exposure"
        summary="What is owned, the two planned-risk quantities kept apart, and what the book is exposed to across every recorded grouping."
        pageState={degraded ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 3</Badge>
          <Badge tone="neutral">Read-only</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadModelPanel
          title="Open positions"
          description="Every open position, with its entry basis, its latest recorded mark, and its two risk quantities as separate facts."
          envelope={positions.data}
          dependency="the portfolio runtime and its recorded positions and lots"
          operator={operator}
          testId="positions-panel"
          always={
            <FilterBar
              chips={chips}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
              basis="Marks are recorded at the session close on the named market calendar, stored in UTC."
            >
              <SearchField
                id="position-search"
                label="Search"
                value={filters.q}
                onChange={(next) => setFilter("q", next)}
                placeholder="Symbol, name, sector…"
              />
              <SelectField
                id="position-direction"
                label="Side"
                value={filters.dir}
                onChange={(next) => setFilter("dir", next)}
                options={[
                  { value: "LONG", label: "Long" },
                  { value: "SHORT", label: "Short" },
                ]}
              />
              <SelectField
                id="position-sector"
                label="Sector"
                value={filters.sector}
                onChange={(next) => setFilter("sector", next)}
                options={sectors.map((code) => ({ value: code, label: humanizeCode(code) }))}
              />
              <SelectField
                id="position-strategy"
                label="Strategy"
                value={filters.strategy}
                onChange={(next) => setFilter("strategy", next)}
                options={strategies.map((code) => ({
                  value: code,
                  label: humanizeCode(code),
                }))}
              />
              <SelectField
                id="position-borrow"
                label="Borrow"
                value={filters.borrow}
                onChange={(next) => setFilter("borrow", next)}
                options={borrowStates.map((code) => ({
                  value: code,
                  label: humanizeCode(code),
                }))}
              />
            </FilterBar>
          }
        >
          {(payload) => (
            <div className="space-y-3">
              <RiskSeparationNote />
              <DataTable
                caption="Open positions, with entry basis, mark, unrealized result and both planned-risk quantities"
                columns={tableColumns}
                data={filtered}
                getRowId={(row) => row.position_id}
                globalFilter={filters.q}
                initialSorting={[{ id: "unrealized", desc: true }]}
                testId="positions-table"
                /*
                 * COLUMN PRIORITY, DECLARED AND MEASURED.
                 *
                 * Identity, side, quantity, the mark, the unrealized result and BOTH risk
                 * quantities stay at every width — they are what this screen is for. The
                 * borrow state stays as far down as it fits, because an unknown borrow is a
                 * fact a reader must not have to hunt for; the holding period, the sector and
                 * the strategy attribution appear where there is room, and the row detail
                 * carries every one of them at every width.
                 */
                columnClasses={{
                  entry: "hidden md:table-cell",
                  borrow: "hidden xl:table-cell",
                  strategy: "hidden 2xl:table-cell",
                  sector: "hidden 2xl:table-cell",
                  holding: "hidden 2xl:table-cell",
                }}
                empty={
                  <span>
                    No position matches the filters above. The population every figure on this
                    page was computed over is unchanged.
                  </span>
                }
                renderDetail={(row) => <PositionDetail row={row} operator={operator} />}
              />
              <RowCount shown={filtered.length} total={payload.items.length} noun="positions" />
              <p className="text-label-s text-text-tertiary">
                Snapshot as of{" "}
                <span className="font-mono text-text-secondary">{payload.as_of}</span> · page
                sorted by{" "}
                <span className="text-text-secondary">
                  {humanizeCode(payload.page.sort.code)}
                </span>{" "}
                with tiebreak{" "}
                <span className="text-text-secondary">
                  {humanizeCode(payload.page.tiebreak.code)}
                </span>{" "}
                · strategy capital{" "}
                <MoneyText amount={payload.strategy_capital.amount} />
              </p>
            </div>
          )}
        </ReadModelPanel>

        <ExposurePanel exposure={exposure.data} operator={operator} />
      </div>
    </>
  );
}

/** Everything the row knows that the table cannot show without becoming unreadable. */
function PositionDetail({
  row,
  operator,
}: {
  row: PositionSnapshot;
  operator: boolean;
}) {
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <PanelSection
        title="Initial planned risk — immutable"
        note="The entry-time record, and the only denominator an R multiple may use. A moving stop does not move it."
      >
        <InitialPlannedRiskRecord wrapper={row.initial_planned_risk} operator={operator} />
      </PanelSection>
      <PanelSection
        title="Current open planned risk — an assessment"
        note="The risk engine's assessment of the remaining exposure, always shown with the instant it was true at."
      >
        <OpenPlannedRiskRecord wrapper={row.open_planned_risk} operator={operator} />
      </PanelSection>
      <PanelSection
        title="Gap and event risk — a separate model"
        note="Never added into either planned-risk figure: a modelled scenario and a recorded plan are different kinds of claim."
      >
        <GapEventRiskRecord
          wrapper={
            row.gap_event_risk ?? {
              availability: "NOT_APPLICABLE",
              reason: "NOT_DEFINED_FOR_SUBJECT",
            }
          }
        />
      </PanelSection>
      <PanelSection
        title="Borrow"
        note="Read from a borrow record, and never inferred from price behaviour. A position whose record is missing renders unknown rather than available."
        testId="position-borrow-detail"
      >
        {row.borrow_state === undefined ? (
          <p className="text-label-m text-text-tertiary">
            Not applicable to a long position: there is nothing to borrow.
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              tone={row.borrow_state.code.includes("UNKNOWN") ? "warning" : "neutral"}
              data-borrow-detail={row.borrow_state.code}
            >
              <span aria-hidden="true">
                {row.borrow_state.code.includes("UNKNOWN") ? "◌" : "●"}
              </span>
              <span>{humanizeCode(row.borrow_state.code)}</span>
            </Badge>
          </div>
        )}
      </PanelSection>
      <PanelSection title="Groupings and references">
        <dl className="grid gap-2 sm:grid-cols-2">
          {(
            [
              ["Sector", row.groupings.sector.code],
              ["Industry", row.groupings.industry.code],
              ["Strategy module", row.groupings.strategy_module.code],
              ["Alpha family", row.groupings.alpha_family.code],
              ["Factor bucket", row.groupings.factor_bucket.code],
              ["Correlation cluster", row.groupings.correlation_cluster.code],
            ] as const
          ).map(([term, code]) => (
            <div key={term} className="flex flex-col gap-0.5">
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                {term}
              </dt>
              <dd className="text-label-m text-text-secondary">{humanizeCode(code)}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-2 flex flex-wrap gap-2">
          <ReferenceChip reference={row.invalidation_ref} label="Invalidation level" />
          <ReferenceChip reference={row.trade_ref} label="Trade" />
          <ReferenceChip reference={row.security_ref} label="Security" />
        </div>
        {operator && (
          <ScrollRegion label="Version pins" className="mt-2">
            <dl className="grid min-w-[28rem] grid-cols-2 gap-x-6 gap-y-1 font-mono text-label-s sm:grid-cols-3">
              {Object.entries(row.pins).map(([key, pin]) => (
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
      </PanelSection>
    </div>
  );
}

/**
 * The exposure aggregates.
 *
 * Seven axes over one set of positions. Every axis reconciles to the SAME portfolio totals,
 * which is what "a position contributes to each axis exactly once" means in practice — and
 * the panel prints both so a reader can check it rather than trust it.
 */
function ExposurePanel({
  exposure,
  operator,
}: {
  exposure: ReturnType<typeof useExposure>["data"];
  operator: boolean;
}) {
  const [axis, setAxis] = React.useState<string | null>(null);
  const payload = exposure?.payload;
  const aggregates = payload?.items ?? [];
  const selected =
    aggregates.find((entry) => entry.grouping.code === axis) ?? aggregates[0];

  return (
    <Card data-testid="exposure-panel">
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>Exposure</Label>
          <p className="mt-0.5 max-w-3xl text-label-m leading-relaxed text-text-secondary">
            Long, short, gross and net across every recorded grouping. Each magnitude carries a
            direction and never a profit sign, and <strong>a grouping is displayed, never
            computed as a permitted exposure</strong>.
          </p>
        </div>
        {aggregates.length > 0 && (
          <div role="group" aria-label="Grouping axis" className="flex flex-wrap gap-1">
            {aggregates.map((entry) => (
              <Button
                key={entry.grouping.code}
                size="sm"
                variant={entry.grouping.code === selected?.grouping.code ? "primary" : "subtle"}
                aria-pressed={entry.grouping.code === selected?.grouping.code}
                onClick={() => setAxis(entry.grouping.code)}
              >
                {humanizeCode(entry.grouping.code)}
              </Button>
            ))}
          </div>
        )}
      </CardHeader>
      <CardBody className="space-y-3">
        {exposure === undefined ? (
          <>
            <div className="skeleton-shape h-24 w-full" data-testid="skeleton" />
            <span className="sr-only">Loading exposure</span>
          </>
        ) : payload === undefined || selected === undefined ? (
          <AvailabilityBadge
            state={exposure.availability}
            reason={exposure.availability_reason}
          />
        ) : (
          <>
            <PortfolioTotals totals={payload.totals} />
            <ExposureTable aggregate={selected} />
            <div className="grid gap-3 sm:grid-cols-2">
              <PanelSection
                title="Concentration"
                note="The largest bucket's gross exposure as a share of the portfolio's gross. A measurement of the displayed grouping — not a limit, and not a permission."
              >
                <MetricText metric={selected.concentration} neutral />
              </PanelSection>
              <PanelSection
                title="Permitted limits on this axis"
                note="A permitted value is a separately governed policy value carried with its policy reference."
              >
                <div className="space-y-2">
                  {selected.permitted.map((entry) => (
                    <PermittedRiskRecord
                      key={entry.scope}
                      scope={entry.scope}
                      wrapper={entry.value}
                    />
                  ))}
                </div>
              </PanelSection>
            </div>
            {selected.correlation_ref !== undefined && (
              <p className="flex flex-wrap items-center gap-2 text-label-s text-text-tertiary">
                <span>Correlation evidence</span>
                <ReferenceChip reference={selected.correlation_ref} label="Correlation matrix" />
                <span>
                  A cluster label is a recorded grouping.{" "}
                  <strong className="text-text-secondary">
                    Diversification is not inferred from it.
                  </strong>
                </span>
              </p>
            )}
            {operator && (
              <p className="font-mono text-label-s text-text-tertiary">
                base: {selected.base.code} · as_of: {payload.as_of}
              </p>
            )}
          </>
        )}
      </CardBody>
    </Card>
  );
}

function PortfolioTotals({
  totals,
}: {
  totals: ExposureAggregatePayload["totals"];
}) {
  return (
    <dl
      className="grid gap-3 rounded-sm border border-border-subtle bg-surface-sunken p-3 sm:grid-cols-5"
      data-testid="exposure-totals"
    >
      {(
        [
          ["Long", totals.long],
          ["Short", totals.short],
          ["Gross", totals.gross],
          ["Net", totals.net],
        ] as const
      ).map(([label, magnitude]) => (
        <div key={label} className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            {label}
          </dt>
          <dd>
            <MoneyText amount={magnitude.amount} />
            <span className="ml-1 text-label-s text-text-tertiary">{magnitude.direction}</span>
          </dd>
        </div>
      ))}
      <div className="flex flex-col gap-0.5">
        <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
          Positions
        </dt>
        <dd>
          <MetricText metric={totals.position_count} neutral />
        </dd>
      </div>
    </dl>
  );
}

/** One axis, as a table with proportional bars. Colour is never the only carrier of size. */
function ExposureTable({ aggregate }: { aggregate: ExposureAggregate }) {
  const widest = Math.max(
    1,
    ...aggregate.buckets.map((bucket) => Number(bucket.gross.amount)),
  );
  return (
    <ScrollRegion
      label={`Exposure by ${humanizeCode(aggregate.grouping.code)}`}
      className="rounded-sm border border-border-subtle"
    >
      <table className="w-full min-w-[46rem] border-collapse text-label-m" data-testid="exposure-table">
        <caption className="sr-only">
          Long, short, gross and net exposure for each bucket of the{" "}
          {humanizeCode(aggregate.grouping.code)} axis, with the number of positions and the
          assessed open planned risk in each.
        </caption>
        <thead className="bg-surface-sunken">
          <tr className="border-b border-border-subtle text-left text-text-tertiary">
            <th scope="col" className="px-3 py-2 font-medium">
              {humanizeCode(aggregate.grouping.code)}
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Long
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Short
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Gross
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Net
            </th>
            <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
              Open planned risk
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Positions
            </th>
          </tr>
        </thead>
        <tbody>
          {aggregate.buckets.map((bucket) => (
            <tr
              key={bucket.bucket.code}
              className="border-b border-border-subtle last:border-0"
              data-bucket={bucket.bucket.code}
            >
              <th scope="row" className="px-3 py-1.5 text-left font-normal text-text-secondary">
                <span className="flex flex-col gap-1">
                  <span>{humanizeCode(bucket.bucket.code)}</span>
                  <span className="h-1.5 w-32 overflow-hidden rounded-sm bg-surface-sunken">
                    <span
                      className="block h-full bg-accent"
                      style={{ width: `${(Number(bucket.gross.amount) / widest) * 100}%` }}
                      aria-hidden="true"
                    />
                  </span>
                </span>
              </th>
              <td className="px-3 py-1.5">
                <MoneyText amount={bucket.long.amount} />
              </td>
              <td className="px-3 py-1.5">
                <MoneyText amount={bucket.short.amount} />
              </td>
              <td className="px-3 py-1.5">
                <MoneyText amount={bucket.gross.amount} />
              </td>
              <td className="px-3 py-1.5">
                <span className="flex items-baseline gap-1">
                  <MoneyText amount={bucket.net.amount} />
                  <span
                    className={cn(
                      "text-label-s",
                      bucket.net.direction === "LONG" ? "text-info" : "text-warning",
                    )}
                  >
                    {bucket.net.direction}
                  </span>
                </span>
              </td>
              <td className="hidden px-3 py-1.5 lg:table-cell">
                {bucket.open_planned_risk.record === undefined ? (
                  <AvailabilityBadge
                    state={bucket.open_planned_risk.availability}
                    reason={bucket.open_planned_risk.reason}
                  />
                ) : (
                  <span className="flex flex-col gap-0.5">
                    <MetricText metric={bucket.open_planned_risk.record.risk_money} neutral />
                    {bucket.open_planned_risk.availability !== "AVAILABLE" && (
                      <AvailabilityBadge
                        state={bucket.open_planned_risk.availability}
                        reason={bucket.open_planned_risk.reason}
                      />
                    )}
                  </span>
                )}
              </td>
              <td className="px-3 py-1.5">
                <MetricText metric={bucket.position_count} neutral />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}
