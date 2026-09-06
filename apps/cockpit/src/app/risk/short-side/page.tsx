"use client";

import * as React from "react";
import Link from "next/link";

import { Badge, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText, MoneyText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel, ReferenceChip } from "@/components/cockpit/read-model-panel";
import { PermittedRiskRecord } from "@/components/cockpit/risk-records";
import { useScope } from "@/components/shell/use-scope";
import { useShortSide } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";
import { withScope } from "@/lib/scope";

/**
 * Short-Side Dashboard — Area 13.
 *
 * "Make short-specific risk visible, **because it has no long-side mirror**."
 *
 * ONE RULE GOVERNS EVERY FIGURE ON THIS PAGE.
 *
 *   **BORROW AVAILABILITY IS NEVER INFERRED FROM PRICE.** Hard-to-borrow conditions and price
 *   action correlate; a correlation is not a borrow record. A security whose borrow state is
 *   unknown renders **unknown or `BLOCKED_BORROW`** — never as available — and every borrow
 *   figure carries the record reference it was read from.
 *
 * **GATE G5 — historical borrow qualification — is OPEN**, and every borrow statistic here
 * inherits that. **Short research is NOT AUTHORIZED**, and nothing on this page performs any.
 */
export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const shortSide = useShortSide(scope);

  return (
    <>
      <PageHeader
        title="Short-Side Dashboard"
        summary="Gross short exposure, the borrow records behind it, and the short-specific risks that have no long-side equivalent."
        pageState={shortSide.data?.completeness === "PARTIAL" ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 13</Badge>
          <Badge tone="unavailable">G5 historical borrow: OPEN</Badge>
          <Badge tone="unavailable">Short research: NOT AUTHORIZED</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadModelPanel
          title="Short exposure"
          description="Gross short against its governed limit, and the recorded states that bound it."
          envelope={shortSide.data}
          dependency="borrow data and the risk engine — no borrow feed exists and G5 is OPEN"
          operator={operator}
          testId="short-exposure"
        >
          {(payload) => (
            <div className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="flex flex-col gap-0.5">
                  <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Gross short
                  </span>
                  <span>
                    <MoneyText amount={payload.gross_short.amount} />
                    <span className="ml-1 text-label-s text-text-tertiary">
                      {payload.gross_short.direction}
                    </span>
                  </span>
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Crowding
                  </span>
                  <MetricText metric={payload.crowding} neutral />
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Utilization
                  </span>
                  <MetricText metric={payload.utilization} neutral />
                </div>
                <div className="flex flex-col gap-0.5">
                  <span className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                    Snapshot as of
                  </span>
                  <span className="font-mono text-label-m text-text-secondary">
                    {payload.as_of}
                  </span>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-3">
                <PanelSection
                  title="Squeeze"
                  note="A recorded state. Nothing here assesses one from price behaviour."
                >
                  <Badge tone="neutral" data-squeeze={payload.squeeze_state.code}>
                    {humanizeCode(payload.squeeze_state.code)}
                  </Badge>
                </PanelSection>
                <PanelSection
                  title="Short-sale restriction"
                  note="An exchange-recorded state. No exchange feed exists, so none is recorded."
                >
                  <Badge tone="neutral" data-ssr={payload.ssr_state.code}>
                    {humanizeCode(payload.ssr_state.code)}
                  </Badge>
                </PanelSection>
                <PanelSection
                  title="Recall and buy-in"
                  note="A lender-recorded risk. No lender feed exists, so none is recorded."
                >
                  <Badge tone="neutral" data-recall={payload.recall_risk.code}>
                    {humanizeCode(payload.recall_risk.code)}
                  </Badge>
                </PanelSection>
              </div>

              <PanelSection
                title="Permitted gross short"
                note="A separately governed policy value. The research parameter of CLAUDE.md §6 is a different thing and is shown on the Risk Dashboard, labelled as a research parameter."
              >
                <div className="max-w-sm">
                  <PermittedRiskRecord
                    scope={payload.permitted_gross_short_scope}
                    wrapper={payload.permitted_gross_short}
                  />
                </div>
              </PanelSection>
            </div>
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="Borrow records"
          description="One row per short position. Each figure carries the record it was read from, and a security with no record renders unknown."
          envelope={shortSide.data}
          dependency="a borrow data feed — G5 historical borrow qualification is OPEN"
          operator={operator}
          testId="borrow-records"
        >
          {(payload) => (
            <div className="space-y-3">
              <ScrollRegion
                label="Borrow records for the open short positions"
                className="rounded-sm border border-border-subtle"
              >
                <table className="w-full min-w-[44rem] border-collapse text-label-m" data-testid="borrow-table">
                  <caption className="sr-only">
                    Borrow availability, fee, quantity and fee deterioration for each open
                    short position, with the borrow record each was read from.
                  </caption>
                  <thead className="bg-surface-sunken">
                    <tr className="border-b border-border-subtle text-left text-text-tertiary">
                      <th scope="col" className="px-3 py-2 font-medium">
                        Security
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Borrow availability
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Fee
                      </th>
                      <th scope="col" className="px-3 py-2 font-medium">
                        Quantity
                      </th>
                      <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                        Fee deterioration
                      </th>
                      <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                        Record
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {payload.borrow.map((record) => {
                      const unknown = record.availability.code.includes("UNKNOWN");
                      return (
                        <tr
                          key={record.security_ref.ref_id}
                          className="border-b border-border-subtle last:border-0"
                          data-borrow-availability={record.availability.code}
                        >
                          <th
                            scope="row"
                            className="px-3 py-1.5 text-left font-normal text-text-secondary"
                          >
                            {record.security_label}
                          </th>
                          <td className="px-3 py-1.5">
                            <Badge tone={unknown ? "warning" : "neutral"}>
                              <span aria-hidden="true">{unknown ? "◌" : "●"}</span>
                              <span>{humanizeCode(record.availability.code)}</span>
                            </Badge>
                          </td>
                          <td className="px-3 py-1.5">
                            <MetricText metric={record.fee} neutral />
                          </td>
                          <td className="px-3 py-1.5">
                            <MetricText metric={record.quantity} neutral />
                          </td>
                          <td className="hidden px-3 py-1.5 lg:table-cell">
                            <MetricText metric={record.deterioration} neutral />
                          </td>
                          <td className="hidden px-3 py-1.5 lg:table-cell">
                            <ReferenceChip reference={record.record_ref} label="Borrow record" />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </ScrollRegion>
              <p
                className="max-w-3xl text-label-s leading-relaxed text-text-tertiary"
                data-testid="borrow-inference-note"
              >
                <strong className="text-text-secondary">
                  Borrow availability is never inferred from price.
                </strong>{" "}
                Hard-to-borrow conditions and price action correlate, and a correlation is not
                a borrow record. One security above has no record at all, and it renders{" "}
                <strong>unknown</strong> — not available, and not assumed from anything the
                price did. The fee, the quantity and the shortability answer are three separate
                observations, and each carries its own state.
              </p>
              <div className="flex flex-wrap items-center gap-2 text-label-s text-text-tertiary">
                <span>Short positions referenced:</span>
                {payload.short_positions.items.map((reference) => (
                  <ReferenceChip key={reference.ref_id} reference={reference} />
                ))}
              </div>
            </div>
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="Blocked shorts"
          description="Candidates the record says were declined for a borrow reason."
          envelope={shortSide.data}
          dependency="the Brain runtime and its journaled candidate decisions"
          testId="blocked-shorts"
        >
          {(payload) => (
            <div className="space-y-3">
              <ul className="space-y-2">
                {payload.blocked_shorts.map((blocked) => (
                  <li
                    key={blocked.candidate_ref.ref_id}
                    className="flex flex-wrap items-center gap-2 rounded-sm border border-border-subtle bg-surface-sunken px-3 py-2"
                    data-blocked-reason={blocked.reason.code}
                  >
                    <Badge tone="warning">
                      <span aria-hidden="true">⊘</span>
                      <span>{humanizeCode(blocked.reason.code)}</span>
                    </Badge>
                    <ReferenceChip reference={blocked.candidate_ref} label="Candidate" />
                  </li>
                ))}
              </ul>
              <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                <strong className="text-text-secondary">
                  A blocked short is a decision that was taken, not an opportunity that was
                  measured.
                </strong>{" "}
                No counterfactual outcome is shown for one: computing what a declined short
                would have made needs a price path nobody has, and stating the window,
                assumptions and cost treatment such a figure would require.
              </p>
              <p className="flex flex-wrap items-center gap-2 text-label-s text-text-tertiary">
                <span>Borrow-related missed opportunities</span>
                <ReferenceChip
                  reference={payload.missed_opportunity_ref}
                  label="Missed opportunities"
                />
                <span>
                  are owned by Area 8, which is a later cycle. It is named here rather than
                  approximated.
                </span>
              </p>
              <p className="text-label-s text-text-tertiary">
                Short-side results by strategy live on{" "}
                <Link
                  href={withScope("/strategy/performance", scope)}
                  className="text-accent underline underline-offset-2"
                >
                  Strategy Performance
                </Link>
                , attributed to the exact version that produced them.
              </p>
            </div>
          )}
        </ReadModelPanel>

        <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
          <AvailabilityBadge state="NOT_AUTHORIZED" reason="PRODUCER_NOT_AUTHORIZED" />{" "}
          <span className="ml-2">
            <strong className="text-text-secondary">
              No borrow query and no short research is performed by this application.
            </strong>{" "}
            Every figure above is a repository-owned fixture, and connecting any of it to a
            real borrow feed is a separate written authorization behind an open gate.
          </span>
        </p>
      </div>
    </>
  );
}
