"use client";

import * as React from "react";
import Link from "next/link";

import { Badge, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { FilterBar, SearchField, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel, ReferenceChip } from "@/components/cockpit/read-model-panel";
import { usePageFilters } from "@/components/shell/use-page-filters";
import { useScope } from "@/components/shell/use-scope";
import { useMissedOpportunities } from "@/data/client/hooks";
import type {
  MissedOpportunity,
  MissedOpportunityPayload,
} from "@/contracts/signal-models";
import { isValueBearing } from "@/contracts/validity";
import { humanizeCode } from "@/lib/format";
import { withScope, type ViewScope } from "@/lib/scope";

/**
 * Missed Opportunities — Area 8.
 *
 * "Learn from what the system saw and did not take." **This is the area most able to
 * mislead**, so its limits are contractual rather than advisory, and every one of them is
 * visible on the screen rather than buried in a footnote.
 *
 *   FAVOURABLE MOVEMENT IS NOT PROFIT   what a price did after a decision is not what a
 *                                       position would have made. Sizing, costs, borrow,
 *                                       slippage and the stop that would have been in place
 *                                       all intervene, and every one of them is listed as an
 *                                       assumption that was NOT modelled
 *   THE WINDOW WAS REGISTERED FIRST     the measurement window is fixed at the decision,
 *                                       before the path is read. **No best-in-hindsight exit
 *                                       is chosen and presented as an executable rule**
 *   NO DOLLAR COUNTERFACTUAL            converting a movement into an amount needs a sizing
 *                                       basis somebody approved. None exists, so the money
 *                                       figure is refused rather than estimated
 *   NO RATE WITHOUT A POPULATION        a false-negative rate counts opportunities that were
 *                                       never detected, and a ledger of detected candidates
 *                                       contains none of them. The count is reported and the
 *                                       rate is refused
 */
export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const missed = useMissedOpportunities(scope);
  const filters = usePageFilters(FILTER_KEYS);

  const payload = missed.data?.payload;
  const rows = React.useMemo(
    () => filterRows(payload, filters.filters),
    [payload, filters.filters],
  );
  const causes = React.useMemo(
    () =>
      [...new Set((payload?.items ?? []).map((item) => item.cause.code))].sort().map((code) => ({
        value: code,
        label: humanizeCode(code),
      })),
    [payload],
  );

  return (
    <>
      <PageHeader
        title="Missed Opportunities"
        summary="Candidates the system saw and did not take, with the cause recorded against each and the price path that followed. Every counterfactual states the window it was registered against, the assumptions it makes and the cost treatment it was measured under."
        pageState={payload === undefined ? "PARTIAL" : "PARTIAL"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 8</Badge>
          <Badge tone="unavailable">No Brain runtime exists</Badge>
          <Badge tone="unavailable">No provider selected — G1 OPEN</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <section
          className="rounded-sm border border-warning/40 bg-warning/10 p-3"
          data-testid="hindsight-warning"
        >
          <p className="max-w-3xl text-label-m leading-relaxed text-text-secondary">
            <strong className="text-warning">
              Favourable movement after a decision is not profit that was available.
            </strong>{" "}
            A price path is not a position. Sizing, commissions, spread, slippage, borrow and
            the protective stop that would have been working all sit between the two, and none
            of them is modelled here. Nothing on this page is an outcome, and no figure here is
            comparable with a realized result.
          </p>
        </section>

        <ReadModelPanel
          title="Recurring causes"
          description="How often each recorded cause appears in the delivered population. A share of a population, never a probability."
          envelope={missed.data}
          dependency="the Brain runtime and its journaled decisions — no Brain runtime exists"
          operator={operator}
          testId="missed-causes-panel"
        >
          {(value) => <CausePatterns payload={value} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Taken versus missed"
          description="Two arms, each carrying its own population, window, horizon, cost treatment, information profile and outcome basis — so a reader can check that they are comparable rather than assume it."
          envelope={missed.data}
          dependency="the Brain runtime, the execution runtime and a qualified price history"
          testId="missed-comparison-panel"
        >
          {(value) => <Comparisons payload={value} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Rates, and the populations they need"
          description="A rate requires a defined evaluable population. Where none is defined, the count is reported and the rate is refused."
          envelope={missed.data}
          dependency="the Brain runtime and a defined evaluable population"
          testId="missed-rates-panel"
        >
          {(value) => <Rates payload={value} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Every recorded miss"
          description="One row per journaled candidate that recorded a cause for not being entered. Filtering narrows what is shown and changes nothing above."
          envelope={missed.data}
          dependency="the Brain runtime and its journaled decisions"
          operator={operator}
          testId="missed-list-panel"
          always={
            <FilterBar
              chips={chipsFor(filters.filters)}
              onRemove={(key) => filters.clearFilter(key as FilterKey)}
              onClearAll={filters.clearAll}
              basis="Windows are half-open, on the named market calendar, in UTC."
            >
              <SearchField
                id="missed-search"
                label="Security"
                value={filters.filters.q}
                onChange={(next) => filters.setFilter("q", next)}
                placeholder="DEMO.KTN"
              />
              <SelectField
                id="missed-cause"
                label="Cause"
                value={filters.filters.cause}
                onChange={(next) => filters.setFilter("cause", next)}
                options={causes}
              />
            </FilterBar>
          }
        >
          {(value) => <MissList payload={value} rows={rows} scope={scope} />}
        </ReadModelPanel>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------- filtering */

const FILTER_KEYS = ["q", "cause"] as const;
type FilterKey = (typeof FILTER_KEYS)[number];

function chipsFor(filters: Readonly<Record<FilterKey, string>>) {
  const chips: { key: string; label: string; value: string }[] = [];
  if (filters.q !== "") {
    chips.push({ key: "q", label: "Search", value: filters.q });
  }
  if (filters.cause !== "") {
    chips.push({ key: "cause", label: "Cause", value: humanizeCode(filters.cause) });
  }
  return chips;
}

function filterRows(
  payload: MissedOpportunityPayload | undefined,
  filters: Readonly<Record<FilterKey, string>>,
) {
  const items = payload?.items ?? [];
  const term = filters.q.trim().toLowerCase();
  return items.filter((item) => {
    if (filters.cause !== "" && item.cause.code !== filters.cause) {
      return false;
    }
    if (term === "") {
      return true;
    }
    return (
      item.security.symbol.toLowerCase().includes(term) ||
      item.security.display_name.toLowerCase().includes(term)
    );
  });
}

/* --------------------------------------------------------------- cause patterns */

function CausePatterns({ payload }: { payload: MissedOpportunityPayload }) {
  return (
    <div className="space-y-2" data-testid="missed-causes">
      <ul className="space-y-1">
        {payload.cause_patterns.map((entry) => (
          <li
            key={entry.cause.code}
            className="flex flex-wrap items-baseline gap-x-3 rounded-sm border border-border-subtle bg-surface-sunken px-3 py-1.5"
            data-cause={entry.cause.code}
          >
            <span className="text-label-m text-text-secondary">
              {humanizeCode(entry.cause.code)}
            </span>
            <MetricText metric={entry.count} neutral />
            <span className="text-label-s text-text-tertiary">
              share of the delivered population:
            </span>
            <MetricText metric={entry.share} neutral />
          </li>
        ))}
      </ul>
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        A share of{" "}
        <span className="font-mono text-text-secondary">
          {humanizeCode(payload.population.code).toLowerCase()}
        </span>
        . It is a proportion of the rows this read delivered, and is not a rate at which a cause
        occurs in the world.
      </p>
    </div>
  );
}

/* ----------------------------------------------------------------- comparisons */

function Comparisons({ payload }: { payload: MissedOpportunityPayload }) {
  return (
    <div className="space-y-3" data-testid="missed-comparisons">
      {payload.comparisons.map((comparison) => (
        <PanelSection
          key={comparison.comparison_id}
          title={comparison.comparable ? "A comparable pair" : "A pair this page refuses to compare"}
          note={
            comparison.comparable
              ? "Both arms share a window, a horizon, a cost treatment, an information profile and an outcome basis. Both are measured as price movement over the registered window — a realized result is never placed in a series with a counterfactual."
              : "The arms differ in dimensions that make a difference meaningless. Nothing about the arithmetic prevents subtracting one from the other; what prevents it is that the answer would mean nothing."
          }
          testId={`comparison-${comparison.comparable ? "compatible" : "refused"}`}
        >
          <div className="grid gap-2 lg:grid-cols-2" data-comparable={String(comparison.comparable)}>
            {comparison.arms.map((arm) => (
              <div
                key={arm.arm}
                className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
                data-arm={arm.arm}
              >
                <p className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                  {arm.arm}
                </p>
                <p className="mt-1">
                  <MetricText metric={arm.outcome} />
                </p>
                <dl className="mt-2 space-y-0.5 text-label-s">
                  {(
                    [
                      ["Population", humanizeCode(arm.population.code)],
                      ["Window", `${arm.window.from.slice(0, 10)} → ${arm.window.to.slice(0, 10)}`],
                      ["Horizon", String(arm.window.horizon.value ?? "—") + " trading days"],
                      ["Cost treatment", arm.cost_treatment],
                      ["Information profile", humanizeCode(arm.information_profile.code)],
                      ["Outcome basis", humanizeCode(arm.outcome_basis.code)],
                      ["Observations", String(arm.observation_count.value ?? "—")],
                    ] as const
                  ).map(([term, value]) => (
                    <div key={term} className="flex flex-wrap gap-x-2">
                      <dt className="text-text-tertiary">{term}:</dt>
                      <dd className="text-text-secondary">{value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Difference
            </span>
            {comparison.comparable ? (
              <MetricText metric={comparison.difference} />
            ) : (
              <>
                <AvailabilityBadge
                  state={comparison.difference.availability}
                  reason={comparison.difference.reason}
                />
                {comparison.refusal !== undefined && (
                  <span className="text-label-s text-warning">
                    {humanizeCode(comparison.refusal.code)}
                  </span>
                )}
              </>
            )}
          </div>
        </PanelSection>
      ))}
    </div>
  );
}

/* ----------------------------------------------------------------------- rates */

function Rates({ payload }: { payload: MissedOpportunityPayload }) {
  return (
    <div className="space-y-2" data-testid="missed-rates">
      {payload.rates.map((rate) => (
        <div
          key={rate.kind}
          className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
          data-rate={rate.kind}
        >
          <div className="flex flex-wrap items-baseline gap-3">
            <span className="text-label-m font-medium text-text-primary">
              {humanizeCode(rate.kind)}
            </span>
            {isValueBearing(rate.rate.availability) ? (
              <MetricText metric={rate.rate} neutral />
            ) : (
              <AvailabilityBadge state={rate.rate.availability} reason={rate.rate.reason} />
            )}
          </div>
          <p className="mt-1 flex flex-wrap items-baseline gap-2 text-label-s text-text-tertiary">
            <span>numerator</span>
            <MetricText metric={rate.numerator} neutral />
            <span>denominator</span>
            <MetricText metric={rate.denominator} neutral />
          </p>
          <p className="mt-1 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            {rate.population === undefined ? (
              <>
                <strong className="text-text-secondary">No population is defined.</strong>{" "}
                {rate.note !== undefined && humanizeCode(rate.note.code)}. The rate is refused
                rather than computed over a population that would not contain the thing being
                counted.
              </>
            ) : (
              <>
                Computed over{" "}
                <span className="text-text-secondary">
                  {humanizeCode(rate.population.code).toLowerCase()}
                </span>
                .
              </>
            )}
          </p>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------- miss list */

function MissList({
  payload,
  rows,
  scope,
}: {
  payload: MissedOpportunityPayload;
  rows: readonly MissedOpportunity[];
  scope: ViewScope;
}) {
  const [open, setOpen] = React.useState<string | null>(null);
  return (
    <div className="space-y-2">
      <p className="text-label-s text-text-tertiary" data-testid="missed-row-count">
        Showing <span className="font-mono text-text-secondary">{rows.length}</span> of{" "}
        <span className="font-mono text-text-secondary">{payload.items.length}</span> delivered
        rows. Counterfactual method:{" "}
        <span className="text-text-secondary">
          {humanizeCode(payload.counterfactual_method.code).toLowerCase()}
        </span>
        .
      </p>
      <ScrollRegion label="Recorded missed opportunities">
        <table
          className="w-full min-w-[52rem] border-collapse text-label-m"
          data-testid="missed-table"
        >
          <caption className="sr-only">
            Each journaled candidate that recorded a cause for not being entered, with its
            Brain state, its recorded cause, the movement observed over the registered window
            and the completeness of the price path that movement was measured on.
          </caption>
          <thead>
            <tr className="border-b border-border-subtle text-left text-text-tertiary">
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Security
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Brain state
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Recorded cause
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Favourable move
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Adverse move
              </th>
              <th scope="col" className="py-1.5 pr-4 font-medium">
                Window movement
              </th>
              <th scope="col" className="py-1.5 font-medium">
                Path
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => {
              const expanded = open === item.miss_id;
              return (
                <React.Fragment key={item.miss_id}>
                  <tr
                    className="border-b border-border-subtle last:border-0"
                    data-miss-id={item.miss_id}
                    data-cause={item.cause.code}
                  >
                    <th scope="row" className="py-2 pr-4 text-left font-normal">
                      <button
                        type="button"
                        onClick={() => setOpen(expanded ? null : item.miss_id)}
                        aria-expanded={expanded}
                        aria-controls={`${item.miss_id}-detail`}
                        className="text-left text-accent underline underline-offset-2"
                      >
                        {item.security.symbol}
                      </button>
                      <span className="mt-0.5 block text-label-s text-text-tertiary">
                        {item.security.display_name}
                      </span>
                    </th>
                    <td className="py-2 pr-4 text-label-s text-text-secondary">
                      {humanizeCode(item.brain_state)}
                    </td>
                    <td className="py-2 pr-4 text-label-s text-text-secondary">
                      {humanizeCode(item.cause.code)}
                    </td>
                    <td className="py-2 pr-4">
                      <MetricText metric={item.favourable_movement} neutral />
                    </td>
                    <td className="py-2 pr-4">
                      <MetricText metric={item.adverse_movement} neutral />
                    </td>
                    <td className="py-2 pr-4">
                      <MetricText metric={item.counterfactual} neutral />
                    </td>
                    <td className="py-2">
                      <Badge
                        tone={item.price_path_completeness === "COMPLETE" ? "neutral" : "warning"}
                        data-path={item.price_path_completeness}
                      >
                        {item.price_path_completeness}
                      </Badge>
                    </td>
                  </tr>
                  {expanded && (
                    <tr id={`${item.miss_id}-detail`} className="border-b border-border-subtle">
                      <td colSpan={7} className="py-3">
                        <MissDetail item={item} scope={scope} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </ScrollRegion>
      {rows.length === 0 && (
        <p className="text-label-m text-text-secondary" data-testid="missed-empty">
          No delivered row matches this filter.
        </p>
      )}
    </div>
  );
}

function MissDetail({ item, scope }: { item: MissedOpportunity; scope: ViewScope }) {
  return (
    <div className="space-y-3" data-testid={`miss-detail-${item.miss_id}`}>
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Detected
          </dt>
          <dd>
            <MetricText metric={item.detected_at} neutral />
          </dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Decided
          </dt>
          <dd>
            <MetricText metric={item.decided_at} neutral />
          </dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Decision delay
          </dt>
          <dd>
            <MetricText metric={item.decision_delay} neutral />
          </dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Watchlist expiry
          </dt>
          <dd>
            <MetricText metric={item.expired_at} neutral />
          </dd>
        </div>
      </dl>

      <PanelSection
        title="The registered measurement window"
        note="Fixed at the decision, before any of the path below was read. A window chosen after the fact is a window chosen to flatter the answer."
      >
        <p className="font-mono text-label-s text-text-secondary">
          {item.window.from} → {item.window.to} ·{" "}
          {String(item.window.horizon.value ?? "—")} trading days ·{" "}
          {humanizeCode(item.window.calendar.code)} · {item.window.timezone}
        </p>
      </PanelSection>

      <PanelSection
        title="The counterfactual, and what it does not include"
        note="Measured at the window's close, on the stated cost treatment. It is HYPOTHETICAL and is never placed in a series with a realized result."
      >
        <div className="flex flex-wrap items-baseline gap-3">
          <MetricText metric={item.counterfactual} />
          <Badge tone="warning">HYPOTHETICAL</Badge>
          <Badge tone="neutral">{item.cost_treatment}</Badge>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            In money
          </span>
          <AvailabilityBadge
            state={item.counterfactual_money.availability}
            reason={item.counterfactual_money.reason}
          />
          <span className="text-label-s text-text-tertiary">
            a movement becomes an amount only under an approved sizing basis, and none exists
          </span>
        </div>
        <ul className="mt-2 flex flex-wrap gap-2" data-testid={`assumptions-${item.miss_id}`}>
          {item.assumptions.map((assumption) => (
            <li
              key={assumption.code}
              className="rounded-sm border border-border-subtle bg-surface-sunken px-2 py-0.5 text-label-s text-text-secondary"
            >
              {humanizeCode(assumption.code)}
            </li>
          ))}
        </ul>
      </PanelSection>

      {item.follow_up_series !== undefined && (
        <PanelSection
          title="The observed follow-up path"
          note="What the price did after the decision. It is the evidence the movement above was measured from, and it is not an outcome."
        >
          <ScrollRegion label={`Follow-up marks for ${item.security.symbol}`}>
            <table className="w-full min-w-[24rem] border-collapse text-label-s">
              <caption className="sr-only">
                Each observed mark after the decision, with the session it belongs to.
              </caption>
              <thead>
                <tr className="border-b border-border-subtle text-left text-text-tertiary">
                  <th scope="col" className="py-1 pr-4 font-medium">
                    Session
                  </th>
                  <th scope="col" className="py-1 font-medium">
                    Mark
                  </th>
                </tr>
              </thead>
              <tbody>
                {item.follow_up_series.points.map((point) => (
                  <tr key={String(point.t)} className="border-b border-border-subtle last:border-0">
                    <th scope="row" className="py-1 pr-4 text-left font-normal font-mono text-text-tertiary">
                      {String(point.t)}
                    </th>
                    <td className="py-1">
                      <MetricText metric={point.v} neutral />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
          <p className="mt-1.5 flex flex-wrap items-center gap-2 text-label-s text-text-tertiary">
            <span>
              covered {item.follow_up_series.coverage.present} of{" "}
              {item.follow_up_series.coverage.requested} requested sessions
            </span>
            {item.follow_up_series.completeness !== "COMPLETE" && (
              <Badge tone="warning">
                {item.follow_up_series.completeness}: a missing bar is missing, not zero
              </Badge>
            )}
          </p>
        </PanelSection>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <ReferenceChip reference={item.candidate_ref} label="Candidate" />
        {item.candidate_ref.resolution === "ENDPOINT" && (
          <Link
            href={withScope(`/signals/candidates/${item.candidate_ref.ref_id}`, scope)}
            className="text-label-m text-accent underline underline-offset-2"
          >
            Why this decision was made
          </Link>
        )}
      </div>
    </div>
  );
}
