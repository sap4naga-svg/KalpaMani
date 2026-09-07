"use client";

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge, ScrollRegion } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel, ReferenceChip } from "@/components/cockpit/read-model-panel";
import { useScope } from "@/components/shell/use-scope";
import { useCandidateDetail } from "@/data/client/hooks";
import type { CandidateDetailPayload } from "@/contracts/signal-models";
import { isBlockedState } from "@/contracts/signal-models";
import type { AiEvidenceRecord } from "@/contracts/signal-models";
import { humanizeCode } from "@/lib/format";
import { referenceDestination } from "@/lib/reference-navigation";
import { withScope, type ViewScope } from "@/lib/scope";

/**
 * Candidate Detail / Explainability — Area 7.
 *
 * "Explain one candidate completely enough to disagree with it."
 *
 * FOUR BOUNDARIES THIS SCREEN HOLDS.
 *
 *   NO SIZING, STRUCTURALLY          no share count, dollar amount, position size, order type,
 *                                    route or broker identifier appears here, because
 *                                    `CandidateIntent` carries none. The risk BASIS is a
 *                                    distance to invalidation, expressed as a percentage —
 *                                    a property of the thesis, not an amount of capital
 *   THE STOP IS A REFERENCE          the technical stop names an invalidation LEVEL. Turning
 *                                    one into a protective order is execution's work, and
 *                                    nothing on this page does it or offers to
 *   AI REMOVES, AND NEVER RESTORES   every AI reference carries its model, its prompt, its
 *                                    schema version, its source publish time and the instant
 *                                    this system observed it. A reference may be recorded as
 *                                    having REMOVED a candidate; none is ever the reason a
 *                                    block was cleared
 *   READY IS NOT PERMISSION          `READY_FOR_RISK_REVIEW` records the absence of a
 *                                    deterministic objection. Risk decides separately
 */
export default function Page() {
  const params = useParams<{ candidateId: string }>();
  const candidateId = typeof params.candidateId === "string" ? params.candidateId : "";
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const detail = useCandidateDetail(scope, candidateId);
  const payload = detail.data?.payload;

  return (
    <>
      <PageHeader
        title={
          payload === undefined
            ? "Candidate Detail"
            : `${payload.security.symbol} — ${humanizeCode(payload.direction)}`
        }
        summary="One decision, explained completely enough to disagree with it: the thesis, the evidence behind it, the evidence it did not have, and the deterministic reasons recorded against it."
        pageState={payload === undefined ? "PARTIAL" : "PARTIAL"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 7</Badge>
          <Badge tone="unavailable">No Brain runtime exists</Badge>
          <Link
            href={withScope("/signals/funnel", scope)}
            className="text-label-m text-accent underline underline-offset-2"
          >
            Back to the funnel
          </Link>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadModelPanel
          title="Decision and thesis"
          description="What the Brain decided, why it decided it, and the condition the thesis rests on."
          envelope={detail.data}
          dependency="the Brain runtime and its journaled candidate decisions"
          operator={operator}
          testId="candidate-decision-panel"
        >
          {(value) => <Decision payload={value} scope={scope} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Deterministic evidence"
          description="The factor scores and the ranking context the decision was taken over. Every value is dimensionless and is pinned to the factor definition that produced it."
          envelope={detail.data}
          dependency="the deterministic factor matrix — no factor calculation exists"
          operator={operator}
          testId="candidate-evidence-panel"
        >
          {(value) => <DeterministicEvidence payload={value} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Risk, event and liquidity context"
          description="The context the Brain may carry, and nothing downstream of it. The invalidation level is a reference; the risk basis is a distance."
          envelope={detail.data}
          dependency="the Brain runtime and its journaled candidate decisions"
          operator={operator}
          testId="candidate-context-panel"
        >
          {(value) => <RiskContext payload={value} operator={operator} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="AI research and challenger evidence"
          description="Bounded structured evidence, each reference carrying its model, prompt, schema version, source publish time and the instant this system observed it."
          envelope={detail.data}
          dependency="the AI Research and Challenger agents — neither exists, and no model is called from this application"
          operator={operator}
          testId="candidate-ai-panel"
        >
          {(value) => <AiEvidence payload={value} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Contradictions, and the evidence this decision did not have"
          description="Unresolved disagreements between sources, and every piece of evidence the decision wanted with the state that explains its absence."
          envelope={detail.data}
          dependency="the Brain runtime, the data platform and the AI agents"
          testId="candidate-gaps-panel"
        >
          {(value) => <Gaps payload={value} />}
        </ReadModelPanel>

        <ReadModelPanel
          title="Lineage, and where this decision goes next"
          description="The exact versions that produced it, and safe references to the separately owned records downstream of it."
          envelope={detail.data}
          dependency="the risk engine and the execution runtime — neither exists"
          operator={operator}
          testId="candidate-lineage-panel"
        >
          {(value) => <Lineage payload={value} operator={operator} scope={scope} />}
        </ReadModelPanel>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------- decision */

function Decision({
  payload,
  scope,
}: {
  payload: CandidateDetailPayload;
  scope: ViewScope;
}) {
  const blocked = isBlockedState(payload.brain_state);
  const ready = payload.brain_state === "READY_FOR_RISK_REVIEW";
  return (
    <div className="space-y-4" data-testid="candidate-decision">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={payload.direction === "LONG" ? "info" : "warning"}>
          <span aria-hidden="true">{payload.direction === "LONG" ? "▲" : "▼"}</span>
          <span>{payload.direction}</span>
        </Badge>
        <Badge
          tone={ready ? "info" : blocked ? "warning" : "neutral"}
          data-brain-state={payload.brain_state}
        >
          {humanizeCode(payload.brain_state)}
        </Badge>
        <Badge tone="neutral">{humanizeCode(payload.strategy_module.code)}</Badge>
        <Badge tone="neutral">{humanizeCode(payload.alpha_family.code)}</Badge>
        <Badge tone="neutral">{humanizeCode(payload.trade_template.code)}</Badge>
        <Badge tone="neutral">{humanizeCode(payload.conviction_band.code)}</Badge>
      </div>

      {ready && (
        <p
          className="rounded-sm border border-info/40 bg-info/10 p-3 text-label-m leading-relaxed text-text-secondary"
          data-testid="ready-note"
        >
          <strong className="text-info">
            This is a handoff, not an approval to trade.
          </strong>{" "}
          It records that the Brain has no deterministic objection. Portfolio and risk decide
          independently, and nothing on this page authorizes an order.
        </p>
      )}

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {(
          [
            ["Security", `${payload.security.symbol} · ${payload.security.display_name}`],
            ["Candidate identity", payload.candidate_id],
            ["Decided", payload.decided_at],
            ["Thesis", humanizeCode(payload.thesis.code)],
            ["Why now", humanizeCode(payload.why_now.code)],
            ["Entry condition", humanizeCode(payload.entry_condition.code)],
          ] as const
        ).map(([term, value]) => (
          <div key={term} className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              {term}
            </dt>
            <dd className="break-words text-label-m text-text-secondary">{value}</dd>
          </div>
        ))}
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Expected horizon
          </dt>
          <dd>
            <MetricText metric={payload.expected_horizon} neutral />
          </dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Setup quality
          </dt>
          <dd>
            <MetricText metric={payload.setup_quality} neutral />
          </dd>
        </div>
        {payload.expires_at !== undefined && (
          <div className="flex flex-col gap-0.5">
            <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
              Watchlist window closes
            </dt>
            <dd>
              <MetricText metric={payload.expires_at} neutral />
            </dd>
          </div>
        )}
      </dl>

      {payload.blocking_reasons.length > 0 && (
        <PanelSection
          title="Deterministic reasons this candidate was blocked"
          note="Closed vocabulary codes from the record. A deterministic failure cannot be rescued by AI, and none of these is cleared by an AI reference."
          testId="blocking-reasons"
        >
          <ul className="flex flex-wrap gap-2">
            {payload.blocking_reasons.map((reason) => (
              <li
                key={reason.code}
                className="rounded-sm border border-warning/40 bg-warning/10 px-2 py-1 text-label-s text-warning"
              >
                {humanizeCode(reason.code)}
              </li>
            ))}
          </ul>
        </PanelSection>
      )}

      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        Its rank was{" "}
        <MetricText metric={payload.rank} neutral /> of{" "}
        <MetricText metric={payload.rank_population} neutral />, on{" "}
        {humanizeCode(payload.ranking_basis.code).toLowerCase()}.{" "}
        <Link
          href={withScope("/signals/funnel", scope)}
          className="text-accent underline underline-offset-2"
        >
          A rank with no population is a position in a list nobody can size.
        </Link>
      </p>
    </div>
  );
}

/* --------------------------------------------------------- deterministic evidence */

function DeterministicEvidence({ payload }: { payload: CandidateDetailPayload }) {
  return (
    <ScrollRegion label="Deterministic factor evidence">
      <table
        className="w-full min-w-[30rem] border-collapse text-label-m"
        data-testid="candidate-factors"
      >
        <caption className="sr-only">
          Each factor this decision was taken over, its dimensionless score, and the factor
          definition version it was computed under.
        </caption>
        <thead>
          <tr className="border-b border-border-subtle text-left text-text-tertiary">
            <th scope="col" className="py-1.5 pr-4 font-medium">
              Factor
            </th>
            <th scope="col" className="py-1.5 pr-4 font-medium">
              Score
            </th>
            <th scope="col" className="py-1.5 font-medium">
              Definition pin
            </th>
          </tr>
        </thead>
        <tbody>
          {payload.deterministic_evidence.map((entry) => (
            <tr key={entry.factor.code} className="border-b border-border-subtle last:border-0">
              <th scope="row" className="py-1.5 pr-4 text-left font-normal text-text-secondary">
                {humanizeCode(entry.factor.code)}
              </th>
              <td className="py-1.5 pr-4">
                <MetricText metric={entry.value} neutral />
              </td>
              <td className="py-1.5 font-mono text-label-s text-text-tertiary">{entry.pin}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollRegion>
  );
}

/* ---------------------------------------------------------------- risk context */

function RiskContext({
  payload,
  operator,
}: {
  payload: CandidateDetailPayload;
  operator: boolean;
}) {
  return (
    <div className="space-y-4" data-testid="candidate-risk-context">
      <div className="rounded-sm border border-border-subtle bg-surface-sunken p-3">
        <p className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
          Distance to invalidation
        </p>
        <p className="mt-1">
          <MetricText
            metric={payload.risk_context.initial_planned_risk_basis}
            denominator="the entry reference"
            operator={operator}
          />
        </p>
        <p className="mt-1.5 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
          <strong className="text-text-secondary">
            This is a distance, not an amount of capital.
          </strong>{" "}
          It is the basis a later risk decision would size against. No share count, no dollar
          amount and no position size exists anywhere in a candidate — the exclusion is a
          property of the type, not a choice this screen made.
        </p>
      </div>

      <PanelSection
        title="The invalidation level"
        note="Carried as a REFERENCE to a level, and never as an order. Turning one into a protective order — its type, its route, its size, its identity — is execution's work."
      >
        <ReferenceChip reference={payload.invalidation_ref} label="Invalidation level" />
      </PanelSection>

      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Gap risk
          </dt>
          <dd>
            <MetricText metric={payload.risk_context.gap_risk} neutral />
          </dd>
        </div>
        <div className="flex flex-col gap-0.5">
          <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Liquidity
          </dt>
          <dd>
            <MetricText metric={payload.risk_context.liquidity_state} neutral />
          </dd>
        </div>
        {(
          [
            ["Earnings carry", payload.risk_context.earnings_carry.code],
            ["Sector", payload.risk_context.sector.code],
            ["Correlation cluster", payload.risk_context.correlation_cluster.code],
            ["Regime context", payload.regime_context.code],
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

      <PanelSection title="Event context" note="Recorded flags, as closed codes.">
        <ul className="flex flex-wrap gap-2">
          {payload.risk_context.event_flags.map((flag) => (
            <li
              key={flag.code}
              className="rounded-sm border border-border-subtle bg-surface-sunken px-2 py-1 text-label-s text-text-secondary"
            >
              {humanizeCode(flag.code)}
            </li>
          ))}
        </ul>
      </PanelSection>

      {payload.short_context !== undefined && (
        <PanelSection
          title="Short context"
          note="Required for a short candidate. Every figure comes from a borrow RECORD; borrow is never inferred from price behaviour."
          testId="candidate-short-context"
        >
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {(
              [
                ["Borrow required", payload.short_context.borrow_required ? "YES" : "NO"],
                ["Borrow state", humanizeCode(payload.short_context.borrow_state.code)],
                ["Fee state", humanizeCode(payload.short_context.fee_state.code)],
                ["Squeeze", humanizeCode(payload.short_context.squeeze_state.code)],
                ["Short-sale restriction", humanizeCode(payload.short_context.ssr_state.code)],
                ["Recall risk", humanizeCode(payload.short_context.recall_risk.code)],
              ] as const
            ).map(([term, value]) => (
              <div key={term} className="flex flex-col gap-0.5">
                <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                  {term}
                </dt>
                <dd className="text-label-m text-text-secondary">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="mt-2">
            <ReferenceChip
              reference={payload.short_context.borrow_evidence_ref}
              label="Borrow evidence"
            />
          </div>
        </PanelSection>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ AI evidence */

function AiEvidence({ payload }: { payload: CandidateDetailPayload }) {
  if (payload.ai_evidence.length === 0) {
    return (
      <div className="space-y-2" data-testid="candidate-ai-absent">
        <AvailabilityBadge state={payload.ai_availability} reason={payload.ai_reason} />
        <p className="max-w-3xl text-label-m leading-relaxed text-text-secondary">
          <strong>The producer answered nothing at all.</strong> That is an absence, not an
          empty list of findings — and it is why this candidate is blocked. Required AI
          evidence that is missing fails closed; it never resolves in the candidate&rsquo;s
          favour.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-3" data-testid="candidate-ai-evidence">
      <div className="flex flex-wrap items-center gap-2">
        <AvailabilityBadge state={payload.ai_availability} reason={payload.ai_reason} />
        {payload.ai_availability === "STALE" && (
          <span className="text-label-s text-text-tertiary">
            The evidence exists and is past its contract. It is shown with the instant it was
            true at, and it is neither treated as current nor discarded as missing.
          </span>
        )}
      </div>
      <ul className="space-y-2">
        {payload.ai_evidence.map((entry) => (
          <EvidenceRow key={entry.reference.ref_id} entry={entry} />
        ))}
      </ul>
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        <strong className="text-text-secondary">
          AI may remove a candidate and may never restore one.
        </strong>{" "}
        A reference marked <em>removed this candidate</em> contributed to a block. No reference
        anywhere is recorded as the reason a block was cleared, and the contract refuses one
        that claims to be.
      </p>
    </div>
  );
}

function EvidenceRow({ entry }: { entry: AiEvidenceRecord }) {
  return (
    <li
      className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
      data-evidence-id={entry.reference.ref_id}
      data-removes={String(entry.removes_candidate)}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-label-m font-medium text-text-primary">
          {humanizeCode(entry.finding.code)}
        </span>
        {entry.removes_candidate && (
          <Badge tone="warning">removed this candidate</Badge>
        )}
        <Badge tone="neutral">{humanizeCode(entry.source.code)}</Badge>
      </div>
      <dl className="mt-2 grid gap-x-6 gap-y-1 font-mono text-label-s sm:grid-cols-2 lg:grid-cols-3">
        {(
          [
            ["model_version", entry.model_version],
            ["prompt_version", entry.prompt_version],
            ["schema_version", entry.schema_version],
          ] as const
        ).map(([key, value]) => (
          <div key={key} className="flex flex-col">
            <dt className="text-text-tertiary">{key}</dt>
            <dd className="truncate text-text-secondary">{value}</dd>
          </div>
        ))}
        <div className="flex flex-col">
          <dt className="text-text-tertiary">source published</dt>
          <dd className="text-text-secondary">
            <MetricText metric={entry.published_at} neutral />
          </dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-text-tertiary">observed here</dt>
          <dd className="text-text-secondary">
            <MetricText metric={entry.observed_at} neutral />
          </dd>
        </div>
        <div className="flex flex-col">
          <dt className="text-text-tertiary">confidence · quality</dt>
          <dd className="flex flex-wrap gap-2 text-text-secondary">
            <MetricText metric={entry.confidence} neutral />
            <MetricText metric={entry.quality} neutral />
          </dd>
        </div>
      </dl>
      <div className="mt-2">
        <ReferenceChip reference={entry.reference} label="Evidence artefact" />
      </div>
    </li>
  );
}

/* ------------------------------------------------------- contradictions and gaps */

function Gaps({ payload }: { payload: CandidateDetailPayload }) {
  return (
    <div className="space-y-3">
      {payload.contradictions.length > 0 ? (
        <PanelSection
          title="Unresolved contradictions"
          note="Two evidence sources disagree, and the compiler did not silently prefer one. The candidate carries the contradiction."
          testId="candidate-contradictions"
        >
          <ul className="space-y-1">
            {payload.contradictions.map((entry) => (
              <li
                key={entry.code}
                className="rounded-sm border border-warning/40 bg-warning/10 px-2 py-1 text-label-s text-warning"
              >
                {humanizeCode(entry.code)}
              </li>
            ))}
          </ul>
        </PanelSection>
      ) : (
        <p className="text-label-m text-text-secondary" data-testid="candidate-no-contradictions">
          No unresolved contradiction was recorded against this candidate.
        </p>
      )}

      <PanelSection
        title="Evidence this decision did not have"
        note="Each with the availability state and closed reason code that explain its absence. A missing input is named, never inferred and never filled with a zero."
      >
        <ScrollRegion label="Evidence gaps">
          <table
            className="w-full min-w-[30rem] border-collapse text-label-m"
            data-testid="candidate-evidence-gaps"
          >
            <caption className="sr-only">
              Each piece of evidence this decision wanted and did not have, with the state and
              reason code that explain its absence.
            </caption>
            <thead>
              <tr className="border-b border-border-subtle text-left text-text-tertiary">
                <th scope="col" className="py-1.5 pr-4 font-medium">
                  Expected
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
              {payload.evidence_gaps.map((gap) => (
                <tr
                  key={gap.expected.code}
                  className="border-b border-border-subtle last:border-0"
                  data-gap={gap.expected.code}
                >
                  <th scope="row" className="py-1.5 pr-4 text-left font-normal text-text-secondary">
                    {humanizeCode(gap.expected.code)}
                  </th>
                  <td className="py-1.5 pr-4">
                    <AvailabilityBadge state={gap.availability} reason={gap.reason} />
                  </td>
                  <td className="py-1.5 font-mono text-label-s text-unavailable">{gap.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      </PanelSection>
    </div>
  );
}

/* --------------------------------------------------------------------- lineage */

function Lineage({
  payload,
  operator,
  scope,
}: {
  payload: CandidateDetailPayload;
  operator: boolean;
  scope: ViewScope;
}) {
  const trade = payload.downstream_refs.trade;
  return (
    <div className="space-y-3" data-testid="candidate-lineage">
      <div className="flex flex-wrap gap-2">
        <ReferenceChip reference={payload.downstream_refs.risk_decision} label="Risk decision" />
        <ReferenceChip reference={trade} label="Trade" />
        <ReferenceChip reference={payload.regime_ref} label="Regime context" />
        <ReferenceChip reference={payload.security_ref} label="Security" />
      </div>
      {trade.resolution === "ENDPOINT" && (
        <p className="text-label-m text-text-secondary">
          This candidate became a recorded trade.{" "}
          <Link
            href={withScope(referenceDestination(trade)?.href ?? "/portfolio/trades", scope)}
            className="text-accent underline underline-offset-2"
          >
            Open its complete lifecycle
          </Link>
          .
        </p>
      )}
      <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        <strong className="text-text-secondary">The risk decision is not on this screen.</strong>{" "}
        Sizing, the order and the fills are separately owned records; this page carries safe
        references to them and resolves none of them into a candidate. Where a decision was
        recorded the reference resolves and the size it assigned is on the trade&rsquo;s own
        detail — never here, because a share count, a dollar amount or a position size in a
        candidate payload is exactly the boundary this screen exists to hold. Where none was
        recorded the reference resolves to an availability state instead.
      </p>

      {operator && (
        <ScrollRegion label="Lineage pins" className="border-t border-border-subtle pt-3">
          <dl className="grid min-w-[30rem] grid-cols-2 gap-x-6 gap-y-1 font-mono text-label-s sm:grid-cols-3">
            {Object.entries(payload.pins).map(([key, pin]) => (
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
