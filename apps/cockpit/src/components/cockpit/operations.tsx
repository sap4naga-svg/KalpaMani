"use client";

import * as React from "react";

import { Badge, Card, CardBody, Label } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { MetricText } from "@/components/cockpit/metric-text";
import { ReasonList } from "@/components/cockpit/research";
import { SEVERITY_RANK, type AlertSeverity } from "@/contracts/operations-models";
import type { MetricValue, ReasonCoded } from "@/contracts/values";
import type { AvailabilityState, FieldReasonCode } from "@/contracts/vocabularies";
import { humanizeCode } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The presentation pieces the six C8 screens share.
 *
 * They exist once because the same four statements have to be made on six screens, and six
 * copies is six chances for one of them to drift:
 *
 *   A SCREEN SAYS WHAT IT CANNOT DO          the controls it does not have are NAMED, from the
 *                                            payload's own closed list, rather than being
 *                                            merely absent from the markup
 *   SEVERITY IS RANKED, NEVER COMPARED       the order comes from the accepted vocabulary and
 *                                            its declared rank map — never from `localeCompare`
 *                                            over three words
 *   A HISTORICAL FACT CARRIES ITS AS-OF      a last success, a last reconciliation and a last
 *                                            observation each render WITH the instant they were
 *                                            true at, beside the present state that is a
 *                                            different question
 *   AN ABSENCE IS A SENTENCE                 a section with nothing in it says so; a section
 *                                            whose producer does not exist says that instead
 *
 * **NOTHING IN THIS MODULE ACTS.** There is no button that starts, stops, retries, triggers,
 * reconnects, acknowledges, resolves, snoozes, dismisses or notifies; every control here
 * filters, sorts or discloses.
 */

/**
 * The standing statement every C8 screen carries.
 *
 * **A screen that displays an operational record must say that it does not drive one**, and it
 * says so once, in one component, so the sentence cannot drift between six pages.
 */
export function OperationsReadOnlyNotice({
  subject,
  actions,
  producer,
  testId,
}: {
  subject: string;
  /** The specific verbs this screen deliberately does not offer. */
  actions: readonly string[];
  /** The producing subsystem that does not exist, named. */
  producer: string;
  testId?: string;
}) {
  return (
    <p
      className="max-w-3xl rounded-sm border border-border-subtle bg-surface-sunken px-3 py-2 text-label-s leading-relaxed text-text-tertiary"
      data-testid={testId ?? "read-only-notice"}
    >
      <strong className="text-text-secondary">This screen reads {subject}.</strong> It has no{" "}
      {actions.join(", ")} control, and no such control exists anywhere in this application.{" "}
      <strong className="text-text-secondary">{producer}</strong>, so every record below is a
      repository-owned synthetic fixture: <strong>no order has been placed</strong>, no broker
      has been contacted, no job has been run, no notification has been sent and{" "}
      <strong>no value here is a result, a verdict or an authorization</strong>.
    </p>
  );
}

/**
 * The controls a screen does not have, rendered from the payload's own closed list.
 *
 * Naming them is the point: an absent button is invisible, and a reader cannot tell a control
 * that was left out from one that was never built.
 */
export function AbsentControls({
  controls,
  label,
  testId,
}: {
  controls: readonly ReasonCoded[];
  label: string;
  testId?: string;
}) {
  return (
    <div className="space-y-1" data-testid={testId ?? "absent-controls"}>
      <Label>{label}</Label>
      <ReasonList
        codes={controls}
        tone="unavailable"
        empty="This screen records no absent control."
      />
    </div>
  );
}

const SEVERITY_TONE: Readonly<Record<string, React.ComponentProps<typeof Badge>["tone"]>> = {
  HIGH: "negative",
  MEDIUM: "warning",
  LOW: "neutral",
};

/**
 * A severity, ranked from the DECLARED vocabulary.
 *
 * `data-severity-rank` carries the rank the accepted table assigns, so a test can assert the
 * ordering a screen presents against the vocabulary rather than against the rendered text.
 */
export function SeverityBadge({
  severity,
  className,
}: {
  severity: ReasonCoded;
  className?: string;
}) {
  const rank = SEVERITY_RANK[severity.code as AlertSeverity];
  return (
    <Badge
      tone={SEVERITY_TONE[severity.code] ?? "neutral"}
      className={className}
      data-severity={severity.code}
      data-severity-rank={rank}
      title="Severity is ordered by the accepted vocabulary's declared rank, never by comparing text."
    >
      <span aria-hidden="true">▲</span>
      <span>{humanizeCode(severity.code)}</span>
    </Badge>
  );
}

/** A closed-vocabulary state, rendered as prose with its code available to a test. */
export function StateBadge({
  state,
  tone = "neutral",
  attribute,
  className,
}: {
  state: ReasonCoded;
  tone?: React.ComponentProps<typeof Badge>["tone"];
  /** The data attribute name a test reads the code from. */
  attribute?: string;
  className?: string;
}) {
  const attributes = attribute === undefined ? {} : { [`data-${attribute}`]: state.code };
  return (
    <Badge tone={tone} className={className} {...attributes} data-code={state.code}>
      {humanizeCode(state.code)}
    </Badge>
  );
}

/**
 * A recorded historical fact, rendered WITH the instant it was true at.
 *
 * This is the shape "a last success carries its as-of time" takes on a screen. The present
 * state is a different question and is rendered separately, never derived from this.
 */
export function HistoricalFact({
  label,
  metric,
  operator,
  testId,
}: {
  label: string;
  metric: MetricValue;
  operator?: boolean;
  testId?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5" data-testid={testId}>
      <Label>{label}</Label>
      <span className="text-numeric-s">
        <MetricText metric={metric} operator={operator} neutral />
      </span>
      <span className="text-label-s text-text-tertiary">
        A recorded historical fact, with the instant it was true at. It is not a statement
        about the present.
      </span>
    </div>
  );
}

/**
 * A present-state statement, with its own availability.
 *
 * It is rendered beside a historical fact and never derived from one — which is the whole of
 * "separate last successful run from current status", and of "a past reconciliation is not
 * current health".
 */
export function PresentState({
  label,
  availability,
  reason,
  note,
  testId,
}: {
  label: string;
  availability: AvailabilityState;
  reason: FieldReasonCode;
  note: ReasonCoded;
  testId?: string;
}) {
  return (
    <div className="flex flex-col gap-1" data-testid={testId}>
      <Label>{label}</Label>
      <AvailabilityBadge state={availability} reason={reason} className="self-start" />
      <span className="max-w-md text-label-s leading-relaxed text-text-tertiary">
        {humanizeCode(note.code)}
      </span>
    </div>
  );
}

/** A short definition list, for the facts a card states about one record. */
export function FactGrid({
  children,
  columns = 3,
  className,
}: {
  children: React.ReactNode;
  columns?: 2 | 3 | 4;
  className?: string;
}) {
  const layout =
    columns === 2 ? "sm:grid-cols-2" : columns === 3 ? "sm:grid-cols-3" : "sm:grid-cols-4";
  return (
    <dl className={cn("grid grid-cols-1 gap-x-6 gap-y-2", layout, className)}>{children}</dl>
  );
}

export function Fact({
  label,
  children,
  testId,
}: {
  label: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5" data-testid={testId}>
      <dt>
        <Label>{label}</Label>
      </dt>
      <dd className="text-label-m text-text-primary">{children}</dd>
    </div>
  );
}

/** One entry on a recorded timeline. Ordered by the instant it happened. */
export interface TimelineEntry {
  readonly at: string;
  readonly title: string;
  readonly detail?: string;
  readonly badge?: React.ReactNode;
  readonly children?: React.ReactNode;
  readonly key: string;
}

/**
 * A recorded timeline.
 *
 * An ordered list rather than a table, because a timeline is a sequence and a screen reader
 * should read it as one. Every entry shows the instant it happened at.
 */
export function Timeline({
  entries,
  empty,
  testId,
}: {
  entries: readonly TimelineEntry[];
  empty: string;
  testId?: string;
}) {
  if (entries.length === 0) {
    return (
      <p className="text-label-s text-text-tertiary" data-testid={testId}>
        {empty}
      </p>
    );
  }
  return (
    <ol className="space-y-2" data-testid={testId}>
      {entries.map((entry) => (
        <li
          key={entry.key}
          className="rounded-sm border border-border-subtle bg-surface-sunken p-2.5"
          data-timeline-entry={entry.key}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-label-s text-text-tertiary">{entry.at}</span>
              <span className="text-label-m font-medium text-text-primary">{entry.title}</span>
            </div>
            {entry.badge}
          </div>
          {entry.detail !== undefined && (
            <p className="mt-1 text-label-s text-text-tertiary">{entry.detail}</p>
          )}
          {entry.children}
        </li>
      ))}
    </ol>
  );
}

/**
 * A half-open window, with its calendar basis and timezone.
 *
 * §6: "a range without an explicit calendar basis and timezone is a range whose boundaries
 * depend on the reader's clock."
 */
export function WindowStatement({
  window,
  label,
  testId,
}: {
  window: {
    readonly from: string;
    readonly to: string;
    readonly calendar: ReasonCoded;
    readonly timezone: "UTC";
  };
  label: string;
  testId?: string;
}) {
  return (
    <p
      className="flex flex-wrap items-center gap-2 text-label-s text-text-tertiary"
      data-testid={testId ?? "window-statement"}
    >
      <Badge tone="neutral">{window.timezone}</Badge>
      <span>
        {label} <span className="font-mono text-text-secondary">{window.from}</span> to{" "}
        <span className="font-mono text-text-secondary">{window.to}</span>, half-open, on{" "}
        {humanizeCode(window.calendar.code)}.
      </span>
    </p>
  );
}

/**
 * A card whose whole subject is unavailable, stating what and why.
 *
 * Used where a ROW rather than a panel is degraded: the panel around it stays usable, and the
 * row says its own state rather than rendering as an empty one.
 */
export function SubjectState({
  availability,
  reason,
  className,
}: {
  availability: AvailabilityState;
  reason: FieldReasonCode;
  className?: string;
}) {
  return (
    <AvailabilityBadge state={availability} reason={reason} className={className} />
  );
}

/** A bordered section inside a page, with its own heading. */
export function OperationsCard({
  title,
  description,
  children,
  actions,
  testId,
}: {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  actions?: React.ReactNode;
  testId?: string;
}) {
  return (
    <Card data-testid={testId}>
      <CardBody className="space-y-3 pt-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <Label>{title}</Label>
            {description !== undefined && (
              <p className="mt-0.5 max-w-3xl text-label-m leading-relaxed text-text-secondary">
                {description}
              </p>
            )}
          </div>
          {actions}
        </div>
        {children}
      </CardBody>
    </Card>
  );
}
