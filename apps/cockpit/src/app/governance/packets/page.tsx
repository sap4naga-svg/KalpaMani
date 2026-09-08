"use client";

import * as React from "react";

import { Badge, Button, Card, CardBody, CardHeader, Label, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { FilterBar, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import {
  MeasureList,
  ReadOnlyNotice,
  ReasonList,
  ReferenceListPanel,
  ReferenceRow,
} from "@/components/cockpit/research";
import { usePageFilters } from "@/components/shell/use-page-filters";
import { useScope } from "@/components/shell/use-scope";
import type { DecisionRecord, GovernancePacket } from "@/contracts/governance-models";
import { useDecisions, useGovernancePackets } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";

/**
 * Governance Packets — Area 19.
 *
 * "Present the evidence a human needs in order to decide."
 *
 *   FOUR THINGS THAT ARE NEVER ONE THING   a RECOMMENDATION is what automation assembled;
 *                                          READINESS is that the required evidence is present;
 *                                          a DECISION is a recorded human act; EXECUTION is
 *                                          what a decision authorized. Each has its own panel
 *   READY FOR HUMAN REVIEW IS NOT APPROVAL and the screen says so beside every packet that
 *                                          carries the state
 *   READ-ONLY, WITHOUT EXCEPTION           no approve, reject, request-more-evidence or
 *                                          release control exists here or anywhere in this
 *                                          application
 *   A SYNTHETIC DECISION AUTHORIZES        nothing in this repository. No promotion, capital
 *   NOTHING                                change, parameter replacement or release has been
 *                                          approved anywhere in it
 */

const FILTER_KEYS = ["state", "module"] as const;

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const packets = useGovernancePackets(scope);
  const decisions = useDecisions(scope);
  const { filters, setFilter, clearFilter, clearAll } = usePageFilters(FILTER_KEYS);
  const [selected, setSelected] = React.useState<string | null>(null);

  const payload = packets.data?.payload;
  const items = React.useMemo(() => payload?.items ?? [], [payload]);
  const visible = items.filter(
    (entry) =>
      (filters.state === "" || entry.state === filters.state) &&
      (filters.module === "" || entry.strategy_module.code === filters.module),
  );
  const chosen = visible.find((entry) => entry.packet_id === selected) ?? visible[0];
  const modules = [...new Set(items.map((entry) => entry.strategy_module.code))].sort();
  const decisionItems = decisions.data?.payload?.items ?? [];
  const outcomes = decisions.data?.payload?.decision_outcomes ?? [];
  const recordedOutcomes = new Set(decisionItems.map((entry) => entry.outcome));

  return (
    <>
      <PageHeader
        title="Governance Packets"
        summary="Assembled packets and the recorded human decisions attached to them: the proposal, its cause, the evidence, the risks, the operational impact, what is missing and the recommendation."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 19</Badge>
          <Badge tone="unavailable">Governance runtime: NOT IMPLEMENTED</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadOnlyNotice
          subject="assembled packets and recorded decisions"
          actions={["approve", "reject", "request more evidence", "release", "promote"]}
        />

        <Card data-testid="packet-vocabulary">
          <CardBody className="space-y-2 pt-4">
            <Label>Recommendation, readiness, decision and execution</Label>
            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                  Recommendation
                </dt>
                <dd className="text-label-s text-text-secondary">
                  What automation assembled. <strong>Input to a human decision, never the
                  decision.</strong>
                </dd>
              </div>
              <div>
                <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                  Readiness
                </dt>
                <dd className="text-label-s text-text-secondary">
                  That the evidence a packet requires is present.{" "}
                  <strong>Ready for human review is not an approval.</strong>
                </dd>
              </div>
              <div>
                <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                  Decision
                </dt>
                <dd className="text-label-s text-text-secondary">
                  A recorded human act with authority, time and reasoning, taken through the
                  separately governed path that owns approvals.
                </dd>
              </div>
              <div>
                <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                  Execution
                </dt>
                <dd className="text-label-s text-text-secondary">
                  What a decision authorized, performed by the deterministic mechanism that owns
                  it. <strong>Nothing here performs one.</strong>
                </dd>
              </div>
            </dl>
          </CardBody>
        </Card>

        <ReadModelPanel
          title="Packets"
          description="An assembling packet names what it is still waiting for. A packet ready for human review is missing nothing it requires — and is still not approved."
          envelope={packets.data}
          dependency="the governance packet assembler — no governance runtime exists"
          operator={operator}
          testId="packet-table"
          always={
            <FilterBar
              chips={[
                ...(filters.state === ""
                  ? []
                  : [{ key: "state", label: "State", value: filters.state }]),
                ...(filters.module === ""
                  ? []
                  : [{ key: "module", label: "Module", value: filters.module }]),
              ]}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
              basis="Filtering narrows what is shown. It changes no packet state and grants no approval."
            >
              <SelectField
                id="packet-state"
                label="Packet state"
                value={filters.state}
                options={(payload?.packet_states ?? []).map((state) => ({
                  value: state,
                  label: humanizeCode(state),
                }))}
                onChange={(next) => setFilter("state", next)}
              />
              <SelectField
                id="packet-module"
                label="Module"
                value={filters.module}
                options={modules.map((code) => ({ value: code, label: humanizeCode(code) }))}
                onChange={(next) => setFilter("module", next)}
              />
            </FilterBar>
          }
        >
          {() => (
            <ScrollRegion label="Governance packets">
              <table
                className="w-full min-w-[56rem] border-collapse text-label-m"
                data-testid="packet-rows"
              >
                <caption className="sr-only">
                  Every assembled packet with its proposal, the two versions it concerns, its
                  state, its trial count, whether a human decision has been recorded against it
                  and what it is still missing.
                </caption>
                <thead className="bg-surface-sunken">
                  <tr className="border-b border-border-subtle text-left text-text-tertiary">
                    <th scope="col" className="px-3 py-2 font-medium">
                      Packet
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Proposal
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      State
                    </th>
                    <th scope="col" className="hidden px-3 py-2 font-medium lg:table-cell">
                      Trial count
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Recorded decision
                    </th>
                    <th scope="col" className="px-3 py-2 font-medium">
                      Detail
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visible.length === 0 && (
                    <tr>
                      <td colSpan={6} className="px-3 py-6 text-text-tertiary">
                        No packet matches this filter.
                      </td>
                    </tr>
                  )}
                  {visible.map((entry) => (
                    <tr
                      key={entry.packet_id}
                      className="border-b border-border-subtle last:border-0"
                      data-packet={entry.packet_id}
                      data-packet-state={entry.state}
                    >
                      <th
                        scope="row"
                        className="px-3 py-1.5 text-left font-normal text-text-secondary"
                      >
                        <span className="flex flex-col">
                          <span className="font-mono">{entry.packet_id}</span>
                          <span className="text-label-s text-text-tertiary">
                            {humanizeCode(entry.strategy_module.code)}
                          </span>
                        </span>
                      </th>
                      <td className="px-3 py-1.5 text-text-secondary">
                        {humanizeCode(entry.proposal.code)}
                      </td>
                      <td className="px-3 py-1.5">
                        <span className="flex flex-col gap-1">
                          <Badge
                            tone={
                              entry.state === "READY_FOR_HUMAN_REVIEW" ? "info" : "unavailable"
                            }
                          >
                            {humanizeCode(entry.state)}
                          </Badge>
                          {entry.state === "READY_FOR_HUMAN_REVIEW" && (
                            <span className="text-label-s text-text-tertiary">
                              not an approval
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="hidden px-3 py-1.5 lg:table-cell">
                        <MetricText metric={entry.trial_count} neutral />
                      </td>
                      <td className="px-3 py-1.5">
                        {entry.decision_ref === undefined ? (
                          <span className="text-label-s text-text-tertiary">
                            None recorded
                          </span>
                        ) : (
                          <ReferenceRow
                            reference={entry.decision_ref}
                            label="Decision"
                            scope={scope}
                          />
                        )}
                      </td>
                      <td className="px-3 py-1.5">
                        <Button
                          size="sm"
                          variant={entry.packet_id === chosen?.packet_id ? "primary" : "subtle"}
                          aria-pressed={entry.packet_id === chosen?.packet_id}
                          onClick={() => setSelected(entry.packet_id)}
                        >
                          Evidence
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
          )}
        </ReadModelPanel>

        {chosen !== undefined && (
          <PacketDetail
            packet={chosen}
            decision={decisionItems.find(
              (entry) => entry.decision_id === chosen.decision_ref?.ref_id,
            )}
            operator={operator}
            scope={scope}
          />
        )}

        <ReadModelPanel
          title="Recorded decisions"
          description="The Cockpit displays a decision and does not originate it. Every recorded decision is immutable and attaches to the packet it was taken on."
          envelope={decisions.data}
          dependency="the separately governed decision path that owns approvals"
          operator={operator}
          testId="decision-panel"
        >
          {(loaded) => (
            <div className="space-y-3">
              <ul className="space-y-2" data-testid="decision-rows">
                {loaded.items.map((entry) => (
                  <li key={entry.decision_id}>
                    <DecisionCard decision={entry} scope={scope} />
                  </li>
                ))}
              </ul>
              <div
                className="flex flex-wrap items-center gap-2 rounded-sm border border-border-subtle bg-surface-sunken p-3"
                data-testid="decision-outcome-vocabulary"
              >
                <Label>Outcome vocabulary</Label>
                {outcomes.map((outcome) => (
                  <Badge
                    key={outcome}
                    tone={recordedOutcomes.has(outcome) ? "neutral" : "unavailable"}
                    data-outcome={outcome}
                    data-recorded={String(recordedOutcomes.has(outcome))}
                  >
                    {humanizeCode(outcome)}
                    {!recordedOutcomes.has(outcome) && " — none recorded"}
                  </Badge>
                ))}
              </div>
              <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
                <strong className="text-text-secondary">
                  No approved decision appears in this demonstration, and that is deliberate.
                </strong>{" "}
                No promotion, capital change, parameter replacement or release has been approved
                anywhere in this repository, and a synthetic approval on the one screen whose
                subject is authorization is the fixture most likely to be read as one.
              </p>
            </div>
          )}
        </ReadModelPanel>
      </div>
    </>
  );
}

function PacketDetail({
  packet,
  decision,
  operator,
  scope,
}: {
  packet: GovernancePacket;
  decision: DecisionRecord | undefined;
  operator: boolean;
  scope: ReturnType<typeof useScope>["scope"];
}) {
  return (
    <Card data-testid="packet-detail" data-packet={packet.packet_id}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>{humanizeCode(packet.proposal.code)}</Label>
          <p className="mt-0.5 font-mono text-label-m text-text-secondary">
            {packet.packet_id}
          </p>
          <p className="mt-0.5 text-label-s text-text-tertiary">
            <span className="font-mono">{packet.champion_version}</span> →{" "}
            <span className="font-mono">{packet.challenger_version}</span>
          </p>
        </div>
        <Badge tone={packet.state === "READY_FOR_HUMAN_REVIEW" ? "info" : "unavailable"}>
          {humanizeCode(packet.state)}
        </Badge>
      </CardHeader>
      <CardBody className="space-y-4">
        <PanelSection
          title="Cause and recommendation"
          note="A recommendation prepared by automation is input to a human decision, and is labelled as such — never as the decision."
          testId="packet-recommendation"
        >
          <dl className="grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Cause
              </dt>
              <dd className="text-label-m text-text-secondary">
                {humanizeCode(packet.cause.code)}
              </dd>
            </div>
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Recommendation
              </dt>
              <dd className="text-label-m text-text-secondary" data-testid="packet-recommendation-value">
                {humanizeCode(packet.recommendation.code)}
              </dd>
            </div>
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Decision authority
              </dt>
              <dd className="text-label-m text-text-secondary">
                {humanizeCode(packet.decision_authority.code)}
              </dd>
            </div>
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Trial count, read from the registry
              </dt>
              <dd>
                <MetricText metric={packet.trial_count} neutral operator={operator} />
              </dd>
            </div>
          </dl>
        </PanelSection>

        <PanelSection
          title="What the packet is missing"
          note="A packet with incomplete evidence, an unrecorded trial count, no baseline comparison or unevaluated criteria is refused rather than assembled."
          testId="packet-missing"
        >
          {packet.missing_evidence.length === 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <AvailabilityBadge state="EMPTY_VERIFIED" reason="EMPTY_RESULT_VERIFIED" />
              <span className="text-label-m text-text-tertiary">
                This packet is missing nothing it requires.{" "}
                <strong className="text-text-secondary">
                  That is readiness for review, and it is not an approval.
                </strong>
              </span>
            </div>
          ) : (
            <ReasonList
              codes={packet.missing_evidence}
              tone="negative"
              empty="Nothing is missing."
              testId="packet-missing-list"
            />
          )}
        </PanelSection>

        <PanelSection
          title="Criteria evaluation"
          note="The registration's own success and failure criteria, and whether each was evaluated. An unevaluated criterion is a state, not a blank."
          testId="packet-criteria"
        >
          <ul className="space-y-1">
            {packet.criteria_evaluation.map((entry) => (
              <li
                key={entry.criterion.code}
                className="flex flex-wrap items-center gap-2 rounded-sm border border-border-subtle p-2"
                data-criterion={entry.criterion.code}
                data-criterion-kind={entry.kind}
              >
                <Badge tone={entry.kind === "SUCCESS" ? "positive" : "negative"}>
                  {entry.kind === "SUCCESS" ? "Success" : "Failure"}
                </Badge>
                <span className="text-label-m text-text-secondary">
                  {humanizeCode(entry.criterion.code)}
                </span>
                {entry.verdict === undefined ? (
                  <AvailabilityBadge
                    state={entry.outcome.availability}
                    reason={entry.outcome.reason}
                  />
                ) : (
                  <Badge tone="neutral">{humanizeCode(entry.verdict.code)}</Badge>
                )}
              </li>
            ))}
          </ul>
        </PanelSection>

        <PanelSection
          title="Risk and operational impact"
          note="What the proposal would change if it were taken. Displaying an impact grants no permission to incur it."
          testId="packet-impact"
        >
          <div className="grid gap-3 lg:grid-cols-2">
            <div>
              <Label>Risk impact</Label>
              <div className="mt-1">
                <MeasureList
                  entries={packet.risk_impact.map((axis) => ({
                    label: axis.axis.code,
                    value: axis.value,
                  }))}
                  columns={2}
                  operator={operator}
                />
              </div>
            </div>
            <div>
              <Label>Operational impact</Label>
              <div className="mt-1">
                <MeasureList
                  entries={packet.operational_impact.map((axis) => ({
                    label: axis.axis.code,
                    value: axis.value,
                  }))}
                  columns={2}
                  operator={operator}
                />
              </div>
            </div>
          </div>
          <div className="mt-3">
            <Label>Failure modes</Label>
            <div className="mt-1">
              <ReasonList
                codes={packet.failure_modes}
                tone="warning"
                empty="No failure mode is recorded on this packet."
              />
            </div>
          </div>
        </PanelSection>

        <PanelSection
          title="Evidence and exposure"
          note="Every reuse the evidence rests on travels with the packet."
          testId="packet-evidence"
        >
          <div className="space-y-3">
            <div className="grid gap-3 lg:grid-cols-3">
              <ReferenceListPanel
                list={packet.run_refs}
                label="Authorized runs"
                scope={scope}
                empty="This packet cites no run."
              />
              <ReferenceListPanel
                list={packet.shadow_refs}
                label="Shadow evidence"
                scope={scope}
                empty="This packet cites no shadow evidence."
              />
              <ReferenceListPanel
                list={packet.evidence_refs}
                label="Other evidence"
                scope={scope}
                empty="This packet cites no other evidence artefact."
              />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <ReferenceRow
                reference={packet.registration_ref}
                label="Registration"
                scope={scope}
              />
              <ReferenceRow
                reference={packet.comparison_ref}
                label="Champion comparison"
                scope={scope}
              />
            </div>
            <div>
              <Label>Exposure disclosure</Label>
              <div className="mt-1">
                <ReasonList
                  codes={packet.exposure_disclosure}
                  tone="warning"
                  empty="This packet records no reuse: its evidence rests on an untouched holdout."
                />
              </div>
            </div>
          </div>
        </PanelSection>

        <PanelSection
          title="The recorded decision"
          note="Displayed, and never originated here. A decision in this demonstration authorizes nothing in this repository."
          testId="packet-decision"
        >
          {decision === undefined ? (
            <div className="flex flex-wrap items-center gap-2">
              <AvailabilityBadge state="NOT_YET_AVAILABLE" reason="UPSTREAM_INPUT_MISSING" />
              <span className="max-w-3xl text-label-m text-text-tertiary">
                No human decision has been recorded against this packet.{" "}
                <strong className="text-text-secondary">
                  This screen offers no way to take one
                </strong>
                , and the automation&apos;s authority ends exactly here.
              </span>
            </div>
          ) : (
            <DecisionCard decision={decision} scope={scope} />
          )}
        </PanelSection>
      </CardBody>
    </Card>
  );
}

function DecisionCard({
  decision,
  scope,
}: {
  decision: DecisionRecord;
  scope: ReturnType<typeof useScope>["scope"];
}) {
  /*
   * A DIV, AND NOT A LIST ITEM.
   *
   * This card is rendered inside a list on the decisions panel and OUTSIDE one on a packet's
   * detail, and a list item with no list is a structure a screen reader cannot announce. The
   * list supplies its own `<li>`; the card supplies the content.
   */
  return (
    <div
      className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
      data-decision={decision.decision_id}
      data-outcome={decision.outcome}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Badge
          tone={
            decision.outcome === "REJECTED"
              ? "negative"
              : decision.outcome === "APPROVED"
                ? "positive"
                : "warning"
          }
        >
          {humanizeCode(decision.outcome)}
        </Badge>
        <span className="font-mono text-label-s text-text-tertiary">
          {decision.decision_id}
        </span>
        <span className="font-mono text-label-s text-text-tertiary">{decision.decided_at}</span>
        <Badge tone="info">Immutable</Badge>
      </div>
      <p className="mt-1 text-label-m text-text-secondary">
        Authority: {humanizeCode(decision.authority.code)}
      </p>
      <div className="mt-2">
        <Label>Recorded reasoning</Label>
        <div className="mt-1">
          <ReasonList codes={decision.reasoning} empty="No reasoning is recorded." />
        </div>
      </div>
      <p className="mt-2 text-label-s text-text-secondary">
        Authorized action:{" "}
        <strong>{humanizeCode(decision.authorized_action.code)}</strong>
      </p>
      <div className="mt-2 grid gap-2 lg:grid-cols-2">
        <ReferenceListPanel
          list={decision.affected_versions}
          label="Affected versions"
          scope={scope}
          empty="No version is recorded as affected."
        />
        <div className="space-y-1">
          <ReferenceRow reference={decision.packet_ref} label="Packet" scope={scope} />
          <ReferenceRow reference={decision.reasoning_ref} label="Reasoning" scope={scope} />
        </div>
      </div>
    </div>
  );
}
