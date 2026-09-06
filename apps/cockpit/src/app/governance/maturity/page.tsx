"use client";

import { Badge, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { PageHeader } from "@/components/cockpit/page-header";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { useScope } from "@/components/shell/use-scope";
import { useQualificationStatus } from "@/data/client/hooks";
import { MATURITY_ENVIRONMENTS } from "@/contracts/envelope";
import { MATURITY_STAGES, type MaturityStage } from "@/contracts/vocabularies";
import { humanizeCode } from "@/lib/format";

/**
 * Environment and Deployment Maturity — product area 25.
 *
 * THE MAPPING IS TRANSCRIBED, NOT INVENTED. `COCKPIT_FEEDBACK_EXTENSION.md` §4.1 pairs each
 * maturity stage with the runtime environment that produces it, and this page reads the same
 * constant the envelope validator enforces — so a stage shown here and a stage the boundary
 * would admit cannot drift apart.
 *
 * SELECTING AN ENVIRONMENT ADVANCES NO MATURITY. The environment control in the header is a
 * VIEWING SCOPE: it changes which records are asked for, and it grants nothing. Nothing on
 * this page promotes, demotes, approves or advances anything, and there is no control that
 * could.
 *
 * SHADOW SHOWS NO ORDER AUTHORITY. It is the last stage before order production begins, and
 * `AUTOMATED_PAPER` — the first stage that produces orders — HAS NEVER BEEN REACHED.
 */

/** What each stage IS, and what it may do. Order authority is stated for every one. */
const STAGE_DESCRIPTION: Readonly<
  Record<MaturityStage, { purpose: string; orderAuthority: string; ordersProduced: boolean }>
> = {
  RESEARCH: {
    purpose: "Offline research and backtesting. No live feed and no broker session.",
    orderAuthority: "None. No order of any kind is produced.",
    ordersProduced: false,
  },
  SHADOW: {
    purpose:
      "Runs against live inputs and records what it would have decided, alongside production.",
    orderAuthority: "None. A shadow decision is recorded and never submitted.",
    ordersProduced: false,
  },
  AUTOMATED_PAPER: {
    purpose: "The first order-producing stage, against the IBKR paper account only.",
    orderAuthority: "Paper orders only. Never a live broker order.",
    ordersProduced: true,
  },
  MICRO_LIVE: {
    purpose: "Real money at deliberately small size, under a separate written authorization.",
    orderAuthority: "Live orders at bounded size.",
    ordersProduced: true,
  },
  SCALED_LIVE: {
    purpose: "Real money at governed size, after a recorded scaling decision.",
    orderAuthority: "Live orders at governed size.",
    ordersProduced: true,
  },
};

/**
 * The stage this project has actually reached.
 *
 * `RESEARCH`, and it is stated as a constant rather than derived from a selector: a viewing
 * scope answers "what am I looking at", not "what has been reached".
 */
const REACHED_STAGE: MaturityStage = "RESEARCH";

export default function MaturityPage() {
  const { scope } = useScope();
  const qualification = useQualificationStatus(scope);
  const operator = scope.mode === "operator";
  const query = qualification;
  const payload = qualification.data?.payload;
  const liveTrading = payload?.live_trading.code;

  return (
    <>
      <PageHeader
        title="Environment & Deployment Maturity"
        summary="The five maturity stages against the unchanged runtime environment enum. Selecting an environment advances no maturity and grants no authority."
      >
        <div className="flex flex-wrap items-center gap-2">
          <ProvenanceBadge provenance="REPOSITORY_TRACKED" />
          <Badge tone="neutral">Viewing: {scope.environment}</Badge>
          <Badge tone="positive">Reached: {REACHED_STAGE}</Badge>
        </div>
      </PageHeader>

      <Card>
        <CardHeader>
          <Label>Stage to runtime environment</Label>
          <p className="mt-1 max-w-3xl text-label-m text-text-secondary">
            Transcribed from the accepted mapping. The runtime{" "}
            <code className="font-mono">Environment</code> enum is unchanged, and the envelope
            boundary refuses any pairing this table does not contain — so a record cannot be
            re-badged into an environment that never produced it.
          </p>
        </CardHeader>
        <CardBody>
          <ScrollRegion label="Maturity stages and their runtime environments">
            <table className="w-full min-w-[46rem] border-collapse text-label-m">
              <caption className="sr-only">
                Each maturity stage, the runtime environment that produces it, its order
                authority and whether this project has reached it.
              </caption>
              <thead>
                <tr className="border-b border-border-subtle text-left">
                  {["Stage", "Environment", "Purpose", "Order authority", "Reached"].map(
                    (heading) => (
                      <th
                        key={heading}
                        scope="col"
                        className="py-1.5 pr-3 font-medium text-text-tertiary"
                      >
                        {heading}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {MATURITY_STAGES.map((stage) => {
                  const description = STAGE_DESCRIPTION[stage];
                  const reached = stage === REACHED_STAGE;
                  return (
                    <tr
                      key={stage}
                      className="border-b border-border-subtle last:border-0"
                      data-testid="maturity-stage"
                      data-stage={stage}
                    >
                      <th
                        scope="row"
                        className="py-2 pr-3 text-left font-mono text-text-primary"
                      >
                        {stage}
                      </th>
                      <td className="py-2 pr-3 font-mono text-text-secondary">
                        {MATURITY_ENVIRONMENTS[stage]}
                      </td>
                      <td className="max-w-sm py-2 pr-3 text-text-secondary">
                        {description.purpose}
                      </td>
                      <td className="max-w-xs py-2 pr-3">
                        <Badge tone={description.ordersProduced ? "warning" : "neutral"}>
                          <span aria-hidden="true">
                            {description.ordersProduced ? "◑" : "○"}
                          </span>
                          <span>{description.ordersProduced ? "Produces orders" : "No orders"}</span>
                        </Badge>
                        <p className="mt-1 text-label-s text-text-tertiary">
                          {description.orderAuthority}
                        </p>
                      </td>
                      <td className="py-2">
                        {reached ? (
                          <Badge tone="positive">
                            <span aria-hidden="true">●</span>
                            <span>Reached</span>
                          </Badge>
                        ) : (
                          <AvailabilityBadge
                            state="NOT_YET_AVAILABLE"
                            reason="UPSTREAM_INPUT_MISSING"
                          />
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </ScrollRegion>
        </CardBody>
      </Card>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <Label>Why selecting an environment changes nothing</Label>
          </CardHeader>
          <CardBody className="space-y-3 text-label-m leading-relaxed text-text-secondary">
            <p>
              The environment control is a <strong>viewing scope</strong>. It selects which
              records are asked for, and it advances no maturity, grants no authority and
              enables no order path.
            </p>
            <p>
              Only <code className="font-mono">RESEARCH</code> is populated. Selecting Paper or
              Live returns a <strong>payloadless</strong> response saying the producing
              subsystem does not exist, rather than the same records under a different badge —
              because re-badging them would manufacture evidence of Paper or Live operation
              out of a viewer&rsquo;s selection.
            </p>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <AvailabilityBadge state="NOT_IMPLEMENTED" reason="PRODUCER_NOT_IMPLEMENTED" />
              <span className="text-label-s text-text-tertiary">
                what Paper and Live return today
              </span>
            </div>
          </CardBody>
        </Card>

        <Card data-testid="live-trading">
          <CardHeader>
            <Label>Order production and live trading</Label>
          </CardHeader>
          <CardBody className="space-y-3">
            {/*
              * The tracked fact, or the STATE saying it was not read — never a hard-coded
              * value dressed as one. Under an unpopulated environment there is no governance
              * record to read, and printing `HARD_DISABLED` anyway would show a constant in
              * the shape of a fact nobody looked up.
              */}
            <div className="flex flex-wrap items-center gap-2">
              {liveTrading === undefined ? (
                <AvailabilityBadge
                  state={query.data?.availability ?? "NOT_IMPLEMENTED"}
                  reason={query.data?.availability_reason ?? "PRODUCER_NOT_IMPLEMENTED"}
                />
              ) : (
                <>
                  <Badge tone="negative">
                    <span aria-hidden="true">⊘</span>
                    <span>Live trading {humanizeCode(liveTrading)}</span>
                  </Badge>
                  <ProvenanceBadge provenance="REPOSITORY_TRACKED" />
                </>
              )}
            </div>
            <p className="max-w-2xl text-label-m leading-relaxed text-text-secondary">
              <code className="font-mono">AUTOMATED_PAPER</code> is the first stage that
              produces an order of any kind, and it{" "}
              <strong>has never been reached</strong>. Live trading is hard-disabled behind two
              independent gates, and the second of them is deliberately not implemented.
            </p>
            <p className="max-w-2xl text-label-m leading-relaxed text-text-tertiary">
              Promotion between stages is a governed human decision recorded in an approved
              packet. <strong>This page performs none of it</strong>: there is no promote, no
              demote, no approve and no advance, and no control route exists that could carry
              one.
            </p>
            {operator && payload !== undefined && (
              <dl className="grid grid-cols-2 gap-x-6 gap-y-1 pt-1 font-mono text-label-s">
                <div className="flex flex-col">
                  <dt className="text-text-tertiary">read_at_commit</dt>
                  <dd className="truncate text-text-secondary">
                    {payload.read_at_commit.slice(0, 12)}
                  </dd>
                </div>
                <div className="flex flex-col">
                  <dt className="text-text-tertiary">phase_state</dt>
                  <dd className="truncate text-text-secondary">{payload.phase_state.code}</dd>
                </div>
              </dl>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}
