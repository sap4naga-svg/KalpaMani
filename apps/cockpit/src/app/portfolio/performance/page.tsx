"use client";

import * as React from "react";

import { Badge, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PerformanceOverview } from "@/components/cockpit/performance-chart";
import {
  PerformanceSummaryPanel,
  RMultipleDistribution,
} from "@/components/cockpit/performance-summary";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { ReadModelPanel, ReferenceChip } from "@/components/cockpit/read-model-panel";
import { ReturnHeatmap } from "@/components/cockpit/return-heatmap";
import { RollingSeriesPanel } from "@/components/cockpit/rolling-series";
import {
  BenchmarkComparisonUnavailable,
  BenchmarkComparisonView,
} from "@/components/cockpit/benchmark-comparison";
import { useScope } from "@/components/shell/use-scope";
import {
  useExecutiveOverview,
  usePerformanceSeries,
  usePerformanceSummary,
  useTrailingWindowSummaries,
} from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";
import {
  PERFORMANCE_PERIODS,
  PERIOD_LABEL,
  type PerformancePeriod,
  type ScopeGranularity,
} from "@/lib/scope";

/**
 * Portfolio Performance — Area 2.
 *
 * "Show what the portfolio actually did, over time, **with the assumptions visible**."
 *
 * FIVE BOUNDARIES THIS PAGE EXISTS TO HOLD.
 *
 *   CASH FLOWS ARE NOT PROFIT           a deposit moves EQUITY and appears in neither the
 *                                       return nor the drawdown series, and the page says so
 *                                       beside the curve rather than in a footnote
 *   REALIZED IS NOT UNREALIZED          they are separate metrics, reported separately, and
 *                                       a combined figure is never presented as realized
 *   EVERY RATIO SHOWS ITS RULE          its denominator, its observed count and its declared
 *                                       minimum — or `INSUFFICIENT_OBSERVATIONS`
 *   A BENCHMARK IS NOT SPLICED          the named benchmarks resolve to nothing because no
 *                                       provider is selected, and the one drawable curve is
 *                                       an obviously invented demonstration index
 *   A WINDOW IS NOT AN EXPERIMENT       the trailing windows overlap, they are five views of
 *                                       one book, and comparing them establishes nothing
 *   A LOOKBACK IS NOT A PERIOD          added by the C5 completion follow-up: the period is
 *                                       the extent the series is requested over, the rolling
 *                                       lookback is how far each point inside it looks back,
 *                                       and both are printed side by side
 */
export default function Page() {
  const { scope, setScope } = useScope();
  const operator = scope.mode === "operator";
  const series = usePerformanceSeries(scope);
  const overview = useExecutiveOverview(scope);
  const summary = usePerformanceSummary(scope, scope.period);
  const trailing = useTrailingWindowSummaries(scope);

  const loaded =
    series.data !== undefined && summary.data !== undefined && overview.data !== undefined;
  const degraded =
    loaded &&
    (series.data?.completeness === "PARTIAL" ||
      summary.data?.payload === undefined ||
      overview.data?.payload === undefined);

  return (
    <>
      <PageHeader
        title="Portfolio Performance"
        summary="Equity, return and drawdown against the authoritative strategy capital, with the assumptions every figure was computed under shown beside it."
        pageState={degraded ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 2</Badge>
          <Badge tone="neutral">Strategy capital USD 80,000 — authoritative</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <PerformanceOverview
          envelope={series.data}
          scope={scope}
          operator={operator}
          onPeriodChange={(period: PerformancePeriod) => setScope({ period })}
          onGranularityChange={(granularity: ScopeGranularity) => setScope({ granularity })}
          heading="Equity, return and drawdown"
          summary="One window, one granularity, three aligned series. A gap breaks the line; nothing is interpolated and no gap is filled with a zero."
          testId="performance-curves"
        />

        <RealizedAndUnrealised overview={overview.data} operator={operator} />

        <ReadModelPanel
          title="Monthly return heat map"
          description="Each cell is one produced monthly time-weighted return. The heat map places values; it computes none."
          envelope={series.data}
          dependency="the portfolio valuation projection and its recorded equity history"
          testId="heatmap-panel"
        >
          {(payload) =>
            payload.period_return_series === undefined ? (
              <AvailabilityBadge state="NOT_YET_AVAILABLE" reason="UPSTREAM_INPUT_MISSING" />
            ) : (
              <ReturnHeatmap
                series={payload.period_return_series}
                granularity={payload.granularity}
              />
            )
          }
        </ReadModelPanel>

        <ReadModelPanel
          title={`Summary — ${PERIOD_LABEL[scope.period]}`}
          description="Expectancy, profit factor, win rate, the risk-adjusted measure and the R distribution, over one defined population."
          envelope={summary.data}
          dependency="the recorded trade population and the portfolio valuation projection"
          operator={operator}
          testId="window-summary"
        >
          {(payload) => (
            <div className="space-y-4">
              <PerformanceSummaryPanel
                summary={payload}
                operator={operator}
                subject="the portfolio"
              />
              <div className="space-y-2 border-t border-border-subtle pt-3">
                <h3 className="text-label-m font-semibold text-text-primary">
                  R-multiple distribution
                </h3>
                <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                  Each trade&rsquo;s outcome divided by its <strong>initial</strong> planned
                  risk. A trade with no recorded entry-time risk record has no R, and it is
                  excluded from the population above rather than counted at zero.
                </p>
                <RMultipleDistribution summary={payload} />
              </div>
            </div>
          )}
        </ReadModelPanel>

        <TrailingWindows trailing={trailing} operator={operator} />

        <RollingSeriesPanel envelope={series.data} scope={scope} operator={operator} />

        <BenchmarkPanel envelope={series.data} operator={operator} />
      </div>
    </>
  );
}

/**
 * Realized and unrealized, kept apart.
 *
 * §12.4: they are separate metrics. A combined figure exists in the dictionary, is labelled
 * combined, and **is never presented as realized** — so this table reports the two and does
 * not add them.
 */
function RealizedAndUnrealised({
  overview,
  operator,
}: {
  overview: ReturnType<typeof useExecutiveOverview>["data"];
  operator: boolean;
}) {
  return (
    <ReadModelPanel
      title="Realized and unrealized profit and loss"
      description="Two separate metrics, reported separately. A closed portion produces realized; an open portion produces unrealized. Neither is summed into the other here."
      envelope={overview}
      dependency="the portfolio valuation projection"
      operator={operator}
      testId="pnl-windows"
    >
      {(payload) => (
        <>
          <ScrollRegion label="Realized and unrealized profit and loss by window">
            <table className="w-full min-w-[30rem] border-collapse text-label-m">
              <caption className="sr-only">
                Realized and unrealized profit and loss for each reported window, in USD.
              </caption>
              <thead>
                <tr className="border-b border-border-subtle text-left text-text-tertiary">
                  <th scope="col" className="py-1.5 pr-4 font-medium">
                    Window
                  </th>
                  <th scope="col" className="py-1.5 pr-4 font-medium">
                    Realized
                  </th>
                  <th scope="col" className="py-1.5 font-medium">
                    Unrealized
                  </th>
                </tr>
              </thead>
              <tbody>
                {payload.pnl.map((entry) => (
                  <tr
                    key={entry.window}
                    className="border-b border-border-subtle last:border-0"
                    data-window={entry.window}
                  >
                    <th
                      scope="row"
                      className="py-1.5 pr-4 text-left font-normal text-text-secondary"
                    >
                      {humanizeCode(entry.window)}
                    </th>
                    <td className="py-1.5 pr-4">
                      <MetricText metric={entry.realized} operator={operator} />
                    </td>
                    <td className="py-1.5">
                      <MetricText metric={entry.unrealized} operator={operator} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollRegion>
          <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            <strong className="text-text-secondary">Unrealized is a point-in-time figure</strong>,
            not a flow: it is the open book marked to its latest recorded prices, and it is the
            same in every window because it is not something a window accumulates. Realized is
            the flow, and only exits inside a window count toward it.
          </p>
        </>
      )}
    </ReadModelPanel>
  );
}

/**
 * Trailing-window performance.
 *
 * FIVE READS, NOT ONE ROLLING CALCULATION. Each row is a separate `PerformanceSummary` over
 * its own window, with its own population and its own observation rules — which is why a
 * short window reports `INSUFFICIENT_OBSERVATIONS` where a long one reports a ratio. **No
 * rolling series is derived here**, because deriving one would be a screen computing a metric
 * the producer did not.
 *
 * THE ROLLING SERIES IS A SEPARATE PANEL AND A SEPARATE READ. It arrives on the payload,
 * produced, under its own metric identifiers, and this table is still five discrete windows
 * rather than a rolling one — they answer different questions and neither replaces the other.
 */
function TrailingWindows({
  trailing,
  operator,
}: {
  trailing: ReturnType<typeof useTrailingWindowSummaries>;
  operator: boolean;
}) {
  return (
    <Card data-testid="trailing-windows">
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label as="h2">Trailing-window performance</Label>
          <p className="mt-0.5 max-w-3xl text-label-m leading-relaxed text-text-secondary">
            One read per window. A shorter window is a smaller population, so a ratio that is
            computable over the full extent may be below its declared minimum over a month —
            and it reports that rather than a number.
          </p>
        </div>
        {trailing[0]?.data?.payload !== undefined && (
          <ProvenanceBadge provenance={trailing[0].data.provenance} />
        )}
      </CardHeader>
      <CardBody className="space-y-3">
        <ScrollRegion label="Performance by trailing window">
          <table className="w-full min-w-[52rem] border-collapse text-label-m">
            <caption className="sr-only">
              Time-weighted return, maximum drawdown, expectancy, profit factor, win rate and
              Sharpe for each trailing window, with the closed-trade count each was computed
              over.
            </caption>
            <thead>
              <tr className="border-b border-border-subtle text-left text-text-tertiary">
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  Window
                </th>
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  Return
                </th>
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  Max drawdown
                </th>
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  Expectancy
                </th>
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  Profit factor
                </th>
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  Win rate
                </th>
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  Sharpe
                </th>
                <th scope="col" className="py-1.5 font-medium">
                  Closed trades
                </th>
              </tr>
            </thead>
            <tbody>
              {PERFORMANCE_PERIODS.map((period, index) => {
                const result = trailing[index];
                const payload = result?.data?.payload;
                return (
                  <tr
                    key={period}
                    className="border-b border-border-subtle last:border-0"
                    data-window={period}
                  >
                    <th
                      scope="row"
                      className="py-1.5 pr-4 text-left font-normal text-text-secondary"
                    >
                      {PERIOD_LABEL[period]}
                    </th>
                    {payload === undefined ? (
                      <td colSpan={7} className="py-1.5 text-text-tertiary">
                        {result?.data === undefined ? (
                          <span
                            className="skeleton-shape inline-block h-3 w-40"
                            data-testid="skeleton"
                          />
                        ) : (
                          <AvailabilityBadge
                            state={result.data.availability}
                            reason={result.data.availability_reason}
                          />
                        )}
                      </td>
                    ) : (
                      <>
                        <td className="py-1.5 pr-4">
                          <MetricText metric={payload.total_return} operator={operator} />
                        </td>
                        <td className="py-1.5 pr-4">
                          <MetricText metric={payload.max_drawdown} operator={operator} />
                        </td>
                        <td className="py-1.5 pr-4">
                          <MetricText metric={payload.expectancy} operator={operator} />
                        </td>
                        <td className="py-1.5 pr-4">
                          <MetricText metric={payload.profit_factor} neutral />
                        </td>
                        <td className="py-1.5 pr-4">
                          <MetricText
                            metric={payload.win_rate}
                            denominator="defined population"
                            neutral
                          />
                        </td>
                        <td className="py-1.5 pr-4">
                          <MetricText metric={payload.sharpe} neutral />
                        </td>
                        <td className="py-1.5 font-mono text-text-secondary">
                          {String(payload.observation_count.value ?? "—")}
                        </td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </ScrollRegion>
        <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
          <strong className="text-text-secondary">
            These windows overlap, and they are not independent samples.
          </strong>{" "}
          A one-month result is contained in the one-year result. They are five views of one
          book rather than five experiments, and comparing them establishes nothing about any
          strategy.
        </p>
      </CardBody>
    </Card>
  );
}

/**
 * The benchmark comparison surface.
 *
 * **SPY, QQQ and IWM resolve to nothing here, and that is the correct answer.** Carrying a
 * synthetic curve under one of those names would be a claim about a real index. The one
 * drawable series is an obviously invented demonstration index, drawn on its own line, and
 * the page says which is which.
 */
function BenchmarkPanel({
  envelope,
  operator,
}: {
  envelope: ReturnType<typeof usePerformanceSeries>["data"];
  operator: boolean;
}) {
  return (
    <ReadModelPanel
      title="Benchmark comparison"
      description="Area 2 names SPY, QQQ and IWM. This application holds none of them."
      envelope={envelope}
      dependency="a qualified market-data provider — G1 and G2 are OPEN and no provider is selected"
      testId="benchmark-panel"
    >
      {(payload) => (
        <div className="space-y-3">
          <div className="space-y-1.5">
            <h3 className="text-label-m font-semibold text-text-primary">Named benchmarks</h3>
            <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
              Each reference is carried so the join is specified, and each resolves to an
              availability state rather than to a payload because{" "}
              <strong className="text-text-secondary">
                no market-data provider is selected
              </strong>{" "}
              — a synthetic curve labelled with a real index&rsquo;s name would be a claim
              about that index.
            </p>
            <div className="flex flex-wrap gap-2">
              {payload.benchmark_refs.items.map((reference) => (
                <ReferenceChip key={reference.ref_id} reference={reference} />
              ))}
            </div>
            <p className="text-label-s text-text-tertiary">
              References carried:{" "}
              <span className="font-mono">
                {String(payload.benchmark_refs.total.value ?? "—")}
              </span>
              . Resolvable to a price series: <span className="font-mono">0</span>.
            </p>
          </div>
          {payload.benchmark_label !== undefined && (
            <div className="space-y-1.5 border-t border-border-subtle pt-3">
              <h3 className="text-label-m font-semibold text-text-primary">
                The one drawable curve
              </h3>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="synthetic">SYNTHETIC</Badge>
                <span className="text-label-m text-text-secondary">
                  {humanizeCode(payload.benchmark_label.code)}
                </span>
              </div>
              <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                A repository-owned deterministic curve with no market behind it. It is drawn as{" "}
                <strong>its own line</strong> on the return view and is never spliced into the
                portfolio&rsquo;s. It is <strong>not</strong> a market index, and comparing
                against it establishes nothing.
              </p>
            </div>
          )}
          {/*
            * THE COMPARISON ITSELF, at the only scope this application can honestly reach.
            *
            * Area 2 asks for a comparison against SPY, QQQ and IWM. Those three resolve to
            * nothing above and stay outstanding; what IS deliverable without a provider is
            * the comparison behaviour — common-date alignment, rebasing, matched boundaries,
            * two separately labelled arms and the limits stated on the chart — against the
            * repository-owned curve. The named-benchmark requirement is disclosed as still
            * open rather than treated as satisfied by a synthetic stand-in.
            */}
          <div className="space-y-1.5 border-t border-border-subtle pt-3">
            <h3 className="text-label-m font-semibold text-text-primary">
              The comparison, against the one drawable curve
            </h3>
            {payload.benchmark_comparison === undefined ? (
              <BenchmarkComparisonUnavailable />
            ) : (
              <BenchmarkComparisonView
                comparison={payload.benchmark_comparison}
                operator={operator}
              />
            )}
          </div>
          <p
            className="max-w-3xl text-label-s leading-relaxed text-text-tertiary"
            data-testid="named-benchmark-outstanding"
          >
            <strong className="text-text-secondary">
              The named-benchmark requirement is not satisfied by this.
            </strong>{" "}
            Area 2 names SPY, QQQ and IWM; a comparison against a repository-owned curve is
            not a comparison against any of them, and calling it one would be the claim the
            unresolvable references above exist to withhold. Real price history for the three
            stays blocked while <strong>G1 is OPEN</strong> and no provider is selected.
          </p>
        </div>
      )}
    </ReadModelPanel>
  );
}
