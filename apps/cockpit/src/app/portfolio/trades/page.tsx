"use client";

import * as React from "react";
import Link from "next/link";

import { Badge, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { columnsFor, DataTable, RowCount } from "@/components/cockpit/data-table";
import { DateField, FilterBar, SearchField, SelectField } from "@/components/cockpit/filters";
import { MetricText, MoneyText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel, ReferenceChip } from "@/components/cockpit/read-model-panel";
import {
  InitialPlannedRiskRecord,
  OpenPlannedRiskRecord,
  RiskSeparationNote,
} from "@/components/cockpit/risk-records";
import { usePageFilters } from "@/components/shell/use-page-filters";
import { useScope } from "@/components/shell/use-scope";
import { useTrades } from "@/data/client/hooks";
import type { TradeSummary } from "@/contracts/portfolio-models";
import { decimalSign, humanizeCode } from "@/lib/format";
import { withScope } from "@/lib/scope";

/**
 * Trade History — Area 36.1.
 *
 * "Give a human the trade ledger." **Trade Detail is a separate destination**, and Execution
 * History and the Audit Trail are two more: they share identifiers and never share a screen
 * (Area 36.3).
 *
 *   A FILL IS NEVER A TRADE                   one row per trade, whatever it took to build it.
 *                                             The trade with an entry, an add and a partial
 *                                             exit is ONE row with ONE identity
 *   A PARTIAL EXIT REDUCES A TRADE            it does not close it and does not create a
 *                                             second one, so a `PARTIALLY_EXITED` row carries
 *                                             realized AND unrealized
 *   STATUS AND COMPLETENESS ARE TWO COLUMNS   a complete trade with a missing bar is
 *                                             `COMPLETE` in status and `PARTIAL` in
 *                                             completeness, and neither is inferred from the
 *                                             other
 *   R DIVIDES BY THE INITIAL RECORD           and a trade with no recorded entry-time risk has
 *                                             no R. It is **never computed from a current
 *                                             stop**
 *   NO OWNER ACTIVITY IS ADOPTED              trades placed by hand are not KalpaMani trades,
 *                                             and this ledger does not absorb them
 */

const FILTER_KEYS = ["q", "status", "dir", "strategy", "outcome", "from", "to"] as const;

const columns = columnsFor<TradeSummary>();

function outcomeOf(row: TradeSummary): "WINNER" | "LOSER" | "FLAT" | "OPEN" {
  if (row.trade_status === "OPEN") return "OPEN";
  const realized = row.realized_pnl.value;
  if (typeof realized !== "string") return "OPEN";
  const sign = decimalSign(realized);
  return sign > 0 ? "WINNER" : sign < 0 ? "LOSER" : "FLAT";
}

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const trades = useTrades(scope);
  const { filters, setFilter, clearFilter, clearAll } = usePageFilters(FILTER_KEYS);

  const items = React.useMemo(() => trades.data?.payload?.items ?? [], [trades.data]);
  const strategies = React.useMemo(
    () => [...new Set(items.map((row) => row.strategy_module.code))].sort(),
    [items],
  );

  const filtered = React.useMemo(
    () =>
      items.filter((row) => {
        if (filters.status !== "" && row.trade_status !== filters.status) return false;
        if (filters.dir !== "" && row.direction !== filters.dir) return false;
        if (filters.strategy !== "" && row.strategy_module.code !== filters.strategy) {
          return false;
        }
        if (filters.outcome !== "" && outcomeOf(row) !== filters.outcome) return false;
        if (filters.from !== "" && row.entry_time.slice(0, 10) < filters.from) return false;
        if (filters.to !== "" && row.entry_time.slice(0, 10) > filters.to) return false;
        return true;
      }),
    [filters, items],
  );

  const tableColumns = React.useMemo(
    () =>
      columns.columns([
        columns.accessor(
          (row) => `${row.security.symbol} ${row.security.display_name} ${row.trade_id}`,
          {
            id: "trade",
            header: () => "Trade",
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
          },
        ),
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
        /* BUSINESS STATUS. It is never a data-completeness state. */
        columns.accessor((row) => row.trade_status, {
          id: "status",
          header: () => "Trade status",
          cell: (info) => (
            <Badge tone="neutral" data-trade-status={info.row.original.trade_status}>
              {humanizeCode(info.row.original.trade_status)}
            </Badge>
          ),
        }),
        /* DATA COMPLETENESS. A SEPARATE column, and neither is inferred from the other. */
        columns.accessor((row) => row.data_completeness, {
          id: "completeness",
          header: () => "Data completeness",
          cell: (info) => (
            <Badge
              tone={info.row.original.data_completeness === "COMPLETE" ? "neutral" : "warning"}
              data-completeness={info.row.original.data_completeness}
            >
              <span aria-hidden="true">
                {info.row.original.data_completeness === "COMPLETE" ? "●" : "◧"}
              </span>
              <span>{humanizeCode(info.row.original.data_completeness)}</span>
            </Badge>
          ),
        }),
        columns.accessor((row) => row.entry_time, {
          id: "entry",
          header: () => "Entry",
          cell: (info) => (
            <span className="flex flex-col">
              <span className="font-mono text-label-s">
                {info.row.original.entry_time.slice(0, 10)}
              </span>
              <MetricText metric={info.row.original.entry_price} neutral />
            </span>
          ),
        }),
        columns.accessor((row) => String(row.exit_time.value ?? ""), {
          id: "exit",
          header: () => "Exit",
          cell: (info) => {
            const row = info.row.original;
            const value = row.exit_time.value;
            return typeof value === "string" ? (
              <span className="flex flex-col">
                <span className="font-mono text-label-s">{value.slice(0, 10)}</span>
                <MetricText metric={row.exit_price} neutral />
              </span>
            ) : (
              <MetricText metric={row.exit_time} />
            );
          },
        }),
        columns.accessor((row) => row.shares_at_entry, {
          id: "shares",
          header: () => "Shares",
          cell: (info) => {
            const row = info.row.original;
            return (
              <span className="flex flex-col font-mono tabular-nums">
                <span>{row.shares_at_entry.toLocaleString("en-US")} at entry</span>
                <span className="text-label-s text-text-tertiary">
                  {row.shares_open.toLocaleString("en-US")} open
                </span>
              </span>
            );
          },
        }),
        columns.accessor((row) => Number(row.initial_position_value.amount), {
          id: "positionValue",
          header: () => "Initial value",
          cell: (info) => (
            <MoneyText amount={info.row.original.initial_position_value.amount} />
          ),
        }),
        columns.accessor((row) => Number(row.realized_pnl.value ?? 0), {
          id: "realized",
          header: () => "Realized",
          cell: (info) => <MetricText metric={info.row.original.realized_pnl} />,
        }),
        columns.accessor((row) => Number(row.unrealized_pnl.value ?? 0), {
          id: "unrealized",
          header: () => "Unrealized",
          cell: (info) => <MetricText metric={info.row.original.unrealized_pnl} />,
        }),
        columns.accessor((row) => Number(row.return_pct.value ?? 0), {
          id: "return",
          header: () => "Return",
          cell: (info) => (
            <MetricText
              metric={info.row.original.return_pct}
              denominator="initial position value"
            />
          ),
        }),
        columns.accessor((row) => Number(row.r_multiple.value ?? 0), {
          id: "r",
          header: () => "R",
          cell: (info) => <MetricText metric={info.row.original.r_multiple} />,
        }),
        columns.accessor((row) => Number(row.holding_period.value ?? 0), {
          id: "holding",
          header: () => "Held",
          cell: (info) => <MetricText metric={info.row.original.holding_period} neutral />,
        }),
        columns.accessor((row) => row.strategy_module.code, {
          id: "strategy",
          header: () => "Strategy",
          cell: (info) => {
            const row = info.row.original;
            const version = row.pins.strategy_version;
            return (
              <span className="flex flex-col">
                <span>{humanizeCode(row.strategy_module.code)}</span>
                <span className="font-mono text-label-s text-text-tertiary">
                  {typeof version === "string" ? version : "version not applicable"}
                </span>
                <span className="text-label-s text-text-tertiary">
                  {humanizeCode(row.alpha_family.code)}
                </span>
              </span>
            );
          },
        }),
        columns.display({
          id: "detail",
          header: () => "Detail",
          cell: (info) => <TradeDetailLink tradeId={info.row.original.trade_id} />,
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
          : key === "from"
            ? "Entered on or after"
            : key === "to"
              ? "Entered on or before"
              : humanizeCode(key.toUpperCase()),
    value: filters[key],
  }));

  return (
    <>
      <PageHeader
        title="Trade History"
        summary="The trade ledger. One row per trade, whatever it took to build it — a fill is never counted as a trade, and a partial exit reduces one rather than closing it."
        pageState={trades.data?.completeness === "PARTIAL" ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 36 — history</Badge>
          <Badge tone="neutral">Basic detail on each row</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadModelPanel
          title="Recorded trades"
          description="Open, partially exited and closed, long and short, with each trade's economics, its two risk quantities and its exact strategy version."
          envelope={trades.data}
          dependency="the portfolio and execution runtimes and their recorded trades"
          operator={operator}
          testId="trades-panel"
          always={
            <FilterBar
              chips={chips}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
              basis="Date filters compare the entry session on the named market calendar, stored in UTC."
            >
              <SearchField
                id="trade-search"
                label="Search"
                value={filters.q}
                onChange={(next) => setFilter("q", next)}
                placeholder="Symbol, name, trade id…"
              />
              <SelectField
                id="trade-status"
                label="Trade status"
                value={filters.status}
                onChange={(next) => setFilter("status", next)}
                options={[
                  { value: "OPEN", label: "Open" },
                  { value: "PARTIALLY_EXITED", label: "Partially exited" },
                  { value: "CLOSED", label: "Closed" },
                ]}
              />
              <SelectField
                id="trade-direction"
                label="Side"
                value={filters.dir}
                onChange={(next) => setFilter("dir", next)}
                options={[
                  { value: "LONG", label: "Long" },
                  { value: "SHORT", label: "Short" },
                ]}
              />
              <SelectField
                id="trade-strategy"
                label="Strategy"
                value={filters.strategy}
                onChange={(next) => setFilter("strategy", next)}
                options={strategies.map((code) => ({ value: code, label: humanizeCode(code) }))}
              />
              <SelectField
                id="trade-outcome"
                label="Outcome"
                value={filters.outcome}
                onChange={(next) => setFilter("outcome", next)}
                options={[
                  { value: "WINNER", label: "Winners" },
                  { value: "LOSER", label: "Losers" },
                  { value: "FLAT", label: "Break-even" },
                  { value: "OPEN", label: "No closed portion" },
                ]}
              />
              <DateField
                id="trade-from"
                label="Entered from"
                value={filters.from}
                onChange={(next) => setFilter("from", next)}
              />
              <DateField
                id="trade-to"
                label="Entered to"
                value={filters.to}
                onChange={(next) => setFilter("to", next)}
              />
            </FilterBar>
          }
        >
          {(payload) => (
            <div className="space-y-3">
              <dl className="flex flex-wrap gap-x-6 gap-y-2">
                <div className="flex flex-col gap-0.5">
                  <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Open trades
                  </dt>
                  <dd>
                    <MetricText metric={payload.open_count} neutral />
                  </dd>
                </div>
                <div className="flex flex-col gap-0.5">
                  <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Closed trades
                  </dt>
                  <dd>
                    <MetricText metric={payload.closed_count} neutral />
                  </dd>
                </div>
                <div className="flex flex-col gap-0.5">
                  <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Population
                  </dt>
                  <dd className="text-label-m text-text-secondary">
                    {humanizeCode(payload.trade_population.code)}
                  </dd>
                </div>
                <div className="flex flex-col gap-0.5">
                  <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Window
                  </dt>
                  <dd className="font-mono text-label-m text-text-secondary">
                    {payload.window.from.slice(0, 10)} → {payload.window.to.slice(0, 10)}
                  </dd>
                </div>
              </dl>
              <RiskSeparationNote />
              <DataTable
                caption="Recorded trades, with entry and exit, economics, both planned-risk quantities and the exact strategy version"
                columns={tableColumns}
                data={filtered}
                getRowId={(row) => row.trade_id}
                globalFilter={filters.q}
                initialSorting={[{ id: "entry", desc: true }]}
                testId="trades-table"
                /*
                 * COLUMN PRIORITY, DECLARED AND MEASURED.
                 *
                 * Fifteen columns of dense content do not fit the reference desktop width, and
                 * a table that forces the page to scroll sideways breaks U14. The order below
                 * is the priority order: identity, side, both statuses, the two economics
                 * columns and R stay at every width; shares, the initial position value, the
                 * holding period and the strategy attribution appear only where there is room
                 * for them, and the row detail carries all of them at every width.
                 */
                columnClasses={{
                  completeness: "hidden lg:table-cell",
                  return: "hidden lg:table-cell",
                  shares: "hidden 2xl:table-cell",
                  positionValue: "hidden 2xl:table-cell",
                  holding: "hidden 2xl:table-cell",
                  strategy: "hidden 2xl:table-cell",
                }}
                empty={
                  <span>
                    No trade matches the filters above. Every figure on this page was computed
                    over the whole delivered page, not over this view.
                  </span>
                }
                renderDetail={(row) => <LedgerRowDetail row={row} operator={operator} />}
              />
              <RowCount shown={filtered.length} total={payload.items.length} noun="trades" />
              {payload.page.truncated && (
                <p
                  className="flex flex-wrap items-center gap-2 text-label-s"
                  data-testid="ledger-truncated"
                >
                  <AvailabilityBadge state="PARTIAL" reason="EXTENT_PARTIALLY_COVERED" />
                  <span className="text-text-tertiary">
                    This read delivered{" "}
                    <span className="font-mono">{payload.items.length}</span> of{" "}
                    <span className="font-mono">
                      {String(payload.page.total.value ?? "—")}
                    </span>{" "}
                    recorded trades. Continuing a page needs a cursor, and this local read
                    client implements none.
                  </span>
                </p>
              )}
              <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                <strong className="text-text-secondary">
                  Existing manual activity is not adopted as platform evidence.
                </strong>{" "}
                Trades placed by hand are not KalpaMani trades, and this ledger does not absorb
                them into any statistic.
              </p>
            </div>
          )}
        </ReadModelPanel>
      </div>
    </>
  );
}

function TradeDetailLink({ tradeId }: { tradeId: string }) {
  const { scope } = useScope();
  return (
    <Link
      href={withScope(`/portfolio/trades/${tradeId}`, scope)}
      className="text-label-m text-accent underline underline-offset-2"
    >
      Open
      <span className="sr-only"> the detail for trade {tradeId}</span>
    </Link>
  );
}

/** The row's own risk records, excursions and reasons — everything the columns cannot hold. */
function LedgerRowDetail({ row, operator }: { row: TradeSummary; operator: boolean }) {
  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <PanelSection
        title="Status and completeness — two facts"
        note="A complete trade with a missing bar is complete in status and partial in completeness. Neither is inferred from the other, and neither is a substitute for the other."
        testId="trade-status-detail"
      >
        <dl className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Trade status
            </dt>
            <dd>
              <Badge tone="neutral" data-detail-trade-status={row.trade_status}>
                {humanizeCode(row.trade_status)}
              </Badge>
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Data completeness
            </dt>
            <dd>
              <Badge
                tone={row.data_completeness === "COMPLETE" ? "neutral" : "warning"}
                data-detail-completeness={row.data_completeness}
              >
                <span aria-hidden="true">
                  {row.data_completeness === "COMPLETE" ? "●" : "◧"}
                </span>
                <span>{humanizeCode(row.data_completeness)}</span>
              </Badge>
            </dd>
          </div>
        </dl>
      </PanelSection>
      <PanelSection
        title="Initial planned risk — immutable"
        note="Recorded at entry, and the only denominator this trade's R multiple may use."
      >
        <InitialPlannedRiskRecord wrapper={row.initial_planned_risk} operator={operator} />
      </PanelSection>
      <PanelSection
        title="Current open planned risk — an assessment"
        note="Present only while the trade holds remaining exposure."
      >
        <OpenPlannedRiskRecord wrapper={row.open_planned_risk} operator={operator} />
      </PanelSection>
      <PanelSection
        title="Excursions"
        note="Path-dependent. An incomplete price path makes each of these PARTIAL rather than optimistic."
      >
        <dl className="grid gap-2 sm:grid-cols-3">
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Maximum favourable
            </dt>
            <dd>
              <MetricText metric={row.mfe} />
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Maximum adverse
            </dt>
            <dd>
              <MetricText metric={row.mae} />
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Capture ratio
            </dt>
            <dd>
              <MetricText metric={row.capture_ratio} denominator="maximum favourable" neutral />
            </dd>
          </div>
        </dl>
      </PanelSection>
      <PanelSection title="Reasons and outcome">
        <dl className="grid gap-2 sm:grid-cols-2">
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Entry reason
            </dt>
            <dd className="text-label-m text-text-secondary">
              {humanizeCode(row.entry_reason.code)}
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Exit reason
            </dt>
            <dd>
              <MetricText metric={row.exit_reason} neutral />
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Stop outcome
            </dt>
            <dd className="text-label-m text-text-secondary">
              {humanizeCode(row.stop_outcome.code)}
            </dd>
          </div>
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Environment
            </dt>
            <dd className="text-label-m text-text-secondary">{row.environment}</dd>
          </div>
        </dl>
        <div className="mt-2 flex flex-wrap gap-2">
          <ReferenceChip reference={row.detail_ref} label="Trade detail" />
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
