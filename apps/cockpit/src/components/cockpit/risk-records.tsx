"use client";

import * as React from "react";

import { Badge } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText, MoneyText } from "@/components/cockpit/metric-text";
import { ReferenceChip } from "@/components/cockpit/read-model-panel";
import type {
  CurrentOpenPlannedRisk,
  GapEventRisk,
  InitialPlannedRisk,
  PermittedRisk,
} from "@/contracts/risk-records";
import { isValueBearing } from "@/contracts/validity";
import type { AvailabilityState, FieldReasonCode } from "@/contracts/vocabularies";
import { humanizeCode } from "@/lib/format";

/**
 * The four risk quantities, rendered so they can never be read as one another.
 *
 * `ui-ux-specification.md` §9.4 names two of the four pairs that must never share a label,
 * and this module is where that is enforced in the interface rather than in a convention:
 *
 *   INITIAL PLANNED RISK        the IMMUTABLE entry record, and the ONLY R denominator. It
 *                               carries `recorded_at`, and **a moving stop does not move it**
 *   CURRENT OPEN PLANNED RISK   an ASSESSMENT of the remaining exposure, meaningless without
 *                               its `as_of`, which is therefore always displayed
 *   PERMITTED RISK              POLICY. It renders with its policy reference, and **the
 *                               interface grants no permission by showing one**
 *   GAP AND EVENT RISK          a SEPARATE model, never added into either planned figure
 *
 * **A missing assessment renders as missing** — never as a number, never as zero and never as
 * `NOT_APPLICABLE` unless the question genuinely does not apply to the subject.
 */

export interface RecordWrapper<T> {
  readonly record?: T;
  readonly availability: AvailabilityState;
  readonly reason: FieldReasonCode;
  readonly as_of?: string;
}

function AbsentRecord({
  wrapper,
  what,
}: {
  wrapper: RecordWrapper<unknown>;
  what: string;
}) {
  return (
    <div className="space-y-1" data-testid="absent-record" data-availability={wrapper.availability}>
      <AvailabilityBadge state={wrapper.availability} reason={wrapper.reason} />
      <p className="text-label-s leading-relaxed text-text-tertiary">{what}</p>
      <p className="font-mono text-label-s text-unavailable">{wrapper.reason}</p>
    </div>
  );
}

/** A field row inside a record. */
function Field({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">{term}</dt>
      <dd className="text-numeric-s text-text-secondary">{children}</dd>
    </div>
  );
}

export function InitialPlannedRiskRecord({
  wrapper,
  operator = false,
}: {
  wrapper: RecordWrapper<InitialPlannedRisk>;
  operator?: boolean;
}) {
  if (wrapper.record === undefined || !isValueBearing(wrapper.availability)) {
    return (
      <AbsentRecord
        wrapper={wrapper}
        what={
          wrapper.availability === "NOT_APPLICABLE"
            ? "The trade never opened, so there is no entry-time risk record to be about."
            : "No entry-time risk record was written for this trade. Its R multiple is unavailable and is never computed from a current stop."
        }
      />
    );
  }
  const record = wrapper.record;
  return (
    <dl className="grid gap-2 sm:grid-cols-2" data-testid="initial-planned-risk">
      <Field term="Initial planned risk">
        <MoneyText amount={record.risk_money.amount} />
      </Field>
      <Field term="Of strategy capital at entry">
        <span className="font-mono">{record.risk_pct_of_capital.value}%</span>
        <span className="ml-1 text-label-s text-text-tertiary">
          per {humanizeCode(record.risk_pct_of_capital.denominator)}
        </span>
      </Field>
      <Field term="Entry reference price">
        <MoneyText amount={record.reference_price.amount} />
      </Field>
      <Field term="Recorded at">
        <span className="font-mono text-label-s">{record.recorded_at}</span>
      </Field>
      <Field term="Invalidation level">
        <ReferenceChip reference={record.invalidation_ref} label="Invalidation level" />
        <p className="mt-1 text-label-s text-text-tertiary">
          A reference to a level. <strong>Never an order.</strong>
        </p>
      </Field>
      <Field term="Risk policy">
        <span className="font-mono text-label-s">
          {record.risk_policy_ref.policy_id} · {record.risk_policy_ref.policy_version}
        </span>
      </Field>
      {operator && (
        <Field term="Source">
          <span className="font-mono text-label-s">{record.source}</span>
        </Field>
      )}
    </dl>
  );
}

/**
 * The retained record of each ADD, and the summed denominator R was divided by.
 *
 * §12.4 keeps three facts apart that a single figure would merge: the original entry record,
 * each add's own record at its own reference price and as-of, and the SUM of them, which is
 * the trade-level R denominator and is not any one of the records. It also requires that a
 * trade whose stages carry different `risk_policy_version` values shows every contributing
 * version — which is why each record prints its own policy reference rather than one at the
 * top. **Nothing here is computed on this screen**: the sum arrives as `r_denominator`.
 */
export function AddPlannedRiskRecords({
  adds,
  denominator,
  operator = false,
}: {
  adds: readonly { stage_ordinal: number; record: InitialPlannedRisk }[];
  denominator?: { amount: string; currency: string };
  operator?: boolean;
}) {
  return (
    <div className="space-y-4" data-testid="add-planned-risk">
      {adds.map((add) => (
        <div key={add.stage_ordinal} className="space-y-1.5">
          <p className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
            Add {add.stage_ordinal} — its own record
          </p>
          <InitialPlannedRiskRecord
            wrapper={{
              record: add.record,
              availability: "AVAILABLE",
              reason: "NONE",
              as_of: add.record.recorded_at,
            }}
            operator={operator}
          />
        </div>
      ))}
      {denominator !== undefined && (
        <div
          className="border-t border-border-subtle pt-3"
          data-testid="r-denominator"
        >
          <dl className="grid gap-2 sm:grid-cols-2">
            <Field term="R denominator — the retained records summed">
              <MoneyText amount={denominator.amount} />
            </Field>
          </dl>
          <p className="mt-1 max-w-2xl text-label-s leading-relaxed text-text-tertiary">
            The R multiple is divided by the <strong>sum</strong> of every retained stage
            record, so it is not the entry record shown above it. Each record keeps its own
            policy version, and every version that contributed is printed with its record.
          </p>
        </div>
      )}
    </div>
  );
}

export function OpenPlannedRiskRecord({
  wrapper,
  operator = false,
}: {
  wrapper: RecordWrapper<CurrentOpenPlannedRisk>;
  operator?: boolean;
}) {
  if (wrapper.record === undefined || !isValueBearing(wrapper.availability)) {
    return (
      <AbsentRecord
        wrapper={wrapper}
        what={
          wrapper.availability === "NOT_APPLICABLE"
            ? "There is no remaining exposure for an assessment to be about."
            : "No risk assessment exists for the remaining exposure. It is unavailable, and it is not zero."
        }
      />
    );
  }
  const record = wrapper.record;
  return (
    <dl className="grid gap-2 sm:grid-cols-2" data-testid="open-planned-risk">
      <Field term="Current open planned risk">
        <MetricText metric={record.risk_money} neutral />
      </Field>
      <Field term="Of strategy capital as of">
        <MetricText metric={record.risk_pct_of_capital} neutral />
      </Field>
      <Field term="Assessed at">
        <span className="font-mono text-label-s">{record.as_of}</span>
        {record.staleness === "STALE" && (
          <Badge tone="warning" className="ml-2" data-testid="assessment-stale">
            <span aria-hidden="true">◑</span>
            <span>Stale assessment</span>
          </Badge>
        )}
      </Field>
      <Field term="Protection">
        <span>{humanizeCode(record.protection_state.code)}</span>
      </Field>
      {operator && (
        <>
          <Field term="Assessment">
            <ReferenceChip reference={record.assessment_ref} label="Risk decision" />
          </Field>
          <Field term="Source">
            <span className="font-mono text-label-s">{record.source}</span>
          </Field>
        </>
      )}
    </dl>
  );
}

export function PermittedRiskRecord({
  scope,
  wrapper,
}: {
  scope: string;
  wrapper: RecordWrapper<PermittedRisk>;
}) {
  return (
    <div
      className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
      data-testid={`permitted-${scope}`}
      data-scope={scope}
    >
      <p className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
        {humanizeCode(scope)}
      </p>
      <div className="mt-1.5">
        {wrapper.record === undefined || !isValueBearing(wrapper.availability) ? (
          <AbsentRecord
            wrapper={wrapper}
            what="A permitted limit is a separately governed policy value. No policy version records this one, so no number is served under a default nobody approved."
          />
        ) : (
          <dl className="space-y-1.5">
            <Field term="Permitted">
              <MetricText metric={wrapper.record.limit_money} neutral />
            </Field>
            <Field term="Of capital">
              <MetricText metric={wrapper.record.limit_pct} neutral />
            </Field>
            <Field term="Policy">
              <span className="font-mono text-label-s">
                {wrapper.record.policy_ref.policy_id} ·{" "}
                {wrapper.record.policy_ref.policy_version}
              </span>
            </Field>
          </dl>
        )}
      </div>
    </div>
  );
}

export function GapEventRiskRecord({
  wrapper,
}: {
  wrapper: RecordWrapper<GapEventRisk>;
}) {
  if (wrapper.record === undefined || !isValueBearing(wrapper.availability)) {
    return (
      <AbsentRecord
        wrapper={wrapper}
        what="The gap and event model does not apply to this subject, or has produced nothing for it."
      />
    );
  }
  const record = wrapper.record;
  return (
    <dl className="grid gap-2 sm:grid-cols-2" data-testid="gap-event-risk">
      <Field term="Modelled loss">
        <MetricText metric={record.modelled_loss} neutral />
      </Field>
      <Field term="Model version">
        <span className="font-mono text-label-s">{record.model_version}</span>
      </Field>
      <Field term="As of">
        <span className="font-mono text-label-s">{record.as_of}</span>
      </Field>
      <Field term="Scenario">
        <ReferenceChip reference={record.scenario_ref} label="Scenario evidence" />
      </Field>
    </dl>
  );
}

/**
 * The sentence that keeps the two planned-risk figures apart, wherever they are shown
 * together.
 */
export function RiskSeparationNote() {
  return (
    <p className="text-label-s leading-relaxed text-text-tertiary" data-testid="risk-separation-note">
      <strong className="text-text-secondary">Initial planned risk</strong> is the immutable
      entry-time record and the only denominator an R multiple may use.{" "}
      <strong className="text-text-secondary">Current open planned risk</strong> is the risk
      engine&rsquo;s assessment of the remaining exposure, carrying its own as-of.{" "}
      <strong className="text-text-secondary">A moving stop changes only the second.</strong>{" "}
      Neither is derived from the other, and neither is a permitted limit.
    </p>
  );
}
