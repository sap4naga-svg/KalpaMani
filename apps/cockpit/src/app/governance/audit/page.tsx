"use client";

import * as React from "react";

import { Badge, Label } from "@/components/ui/primitives";
import { FilterBar, SearchField, SelectField } from "@/components/cockpit/filters";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import { ReferenceListPanel, ReferenceRow, SectionState } from "@/components/cockpit/research";
import {
  Fact,
  FactGrid,
  OperationsReadOnlyNotice,
  Timeline,
  WindowStatement,
} from "@/components/cockpit/operations";
import { useScope } from "@/components/shell/use-scope";
import { usePageFilters } from "@/components/shell/use-page-filters";
import { AUDIT_ACTORS, AUDIT_EVENT_KINDS, type AuditEvent } from "@/contracts/audit-models";
import { useAuditEvents } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";
import type { ViewScope } from "@/lib/scope";

/**
 * Audit Trail — Area 26.
 *
 * "Reconstruct what happened, forensically, including things that were not trades."
 *
 *   THE PROJECTION IS NOT THE SOURCE         it carries its own identity and its own rebuild
 *                                            count, separately from every event identity, so a
 *                                            projection defect cannot be mistaken for missing
 *                                            history. **A rebuild is not an audit-event
 *                                            mutation**
 *   A CORRECTION APPENDS                     it names the event it corrects, and the corrected
 *                                            event is still here, unchanged
 *   A DELETION IS A TOMBSTONE                it names what it withdrew and the authority it was
 *                                            made under. The governance record survives
 *   NO LICENSED CONTENT, EVER                subjects arrive as classified REFERENCES, never as
 *                                            payload copies, and the digest is of KalpaMani's
 *                                            own record
 *   A MISSING EVENT IS A GAP                 stated, with its window, and never rendered as a
 *                                            quiet period or filled by an inferred event
 *   THIS IS NOT AN EVIDENCE RESOLVER         a reference opens the RECORD its kind maps to, or
 *                                            the AREA it declares. Nothing here retrieves an
 *                                            artefact, and no destination is invented
 */

const FILTER_KEYS = ["kind", "actor", "q"] as const;

const KIND_TONE: Readonly<Record<string, React.ComponentProps<typeof Badge>["tone"]>> = {
  CORRECTION_APPENDED: "warning",
  RECORD_TOMBSTONED: "negative",
  SAFETY_ACTION_RECORDED: "warning",
  GOVERNANCE_DECISION_RECORDED: "info",
};

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const audit = useAuditEvents(scope);
  const payload = audit.data?.payload;
  const { filters, setFilter, clearFilter, clearAll, activeKeys } =
    usePageFilters(FILTER_KEYS);

  const events = React.useMemo(() => {
    if (payload === undefined) {
      return [];
    }
    const term = filters.q.trim().toLowerCase();
    return payload.items
      .filter((event) => filters.kind === "" || event.event_kind.code === filters.kind)
      .filter((event) => filters.actor === "" || event.actor.code === filters.actor)
      .filter(
        (event) =>
          term === "" ||
          event.event_id.toLowerCase().includes(term) ||
          event.event_kind.code.toLowerCase().includes(term) ||
          event.summary.code.toLowerCase().includes(term),
      )
      .toSorted((left, right) => {
        const byTime = right.event_time.localeCompare(left.event_time);
        return byTime !== 0 ? byTime : left.event_id.localeCompare(right.event_id);
      });
  }, [payload, filters.kind, filters.actor, filters.q]);

  return (
    <>
      <PageHeader
        title="Audit Trail"
        summary="An append-only timeline of recorded events, ordered by when they happened and retaining when this system saw them. Corrections append, deletions are tombstones, and the projection that renders them is identified separately from the events themselves."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 26</Badge>
          <Badge tone="unavailable">Platform event stream: NOT IMPLEMENTED</Badge>
          <Badge tone="neutral">Classified references only — never payload copies</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <OperationsReadOnlyNotice
          subject="a recorded event timeline"
          actions={["append", "edit", "delete", "sign", "export"]}
          producer="No authoritative audit store, append path, signature or retention mechanism exists in this application"
        />

        <ReadModelPanel
          title="The projection, and the events it projects"
          description="Two identities, kept apart. Rebuilding this projection moves its own rebuild count and mutates no event."
          envelope={audit.data}
          dependency="a platform audit event stream — none exists"
          operator={operator}
          testId="audit-projection"
        >
          {(loaded) => (
            <div className="space-y-3">
              <FactGrid columns={4}>
                <Fact label="Projection identity" testId="projection-id">
                  <span className="font-mono text-label-s">
                    {loaded.projection.projection_id}
                  </span>
                </Fact>
                <Fact label="Built at">
                  <MetricText metric={loaded.projection.built_at} neutral />
                </Fact>
                <Fact label="Rebuilds" testId="rebuild-count">
                  <MetricText metric={loaded.projection.rebuild_count} neutral />
                </Fact>
                <Fact label="Events delivered">
                  <MetricText metric={loaded.event_count} neutral />
                </Fact>
              </FactGrid>
              <SectionState
                availability={loaded.projection.source_stream_state.availability}
                reason={loaded.projection.source_stream_state.reason}
                note={`The source stream this projection would read is ${humanizeCode(
                  loaded.projection.source_stream.code,
                )}.`}
                testId="source-stream-state"
              />
              <WindowStatement window={loaded.window} label="Events recorded from" />
              <p
                className="max-w-3xl text-label-s leading-relaxed text-text-tertiary"
                data-testid="projection-rule"
              >
                <strong className="text-text-secondary">
                  The authoritative audit events are not this projection.
                </strong>{" "}
                Rebuilding a read model must never mutate a source event, and the two are
                separately identified so a projection defect cannot be mistaken for missing
                history. This page rebuilds; the record does not change.
              </p>
            </div>
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="Gaps in the recorded history"
          description="A missing event is a gap, and never an inferred event."
          envelope={audit.data}
          dependency="a platform audit event stream — none exists"
          operator={operator}
          testId="audit-gaps"
        >
          {(loaded) =>
            loaded.gaps.length === 0 ? (
              <p className="text-label-m text-text-tertiary">
                This projection records no gap over the window above.
              </p>
            ) : (
              <ul className="space-y-2" data-testid="gap-list">
                {loaded.gaps.map((gap) => (
                  <li
                    key={`${gap.from}-${gap.to}`}
                    className="rounded-sm border border-warning/40 bg-surface-sunken p-2.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="warning">Gap</Badge>
                      <span className="font-mono text-label-s text-text-secondary">
                        {gap.from} to {gap.to}
                      </span>
                      <span className="font-mono text-label-s text-unavailable">
                        {gap.reason}
                      </span>
                    </div>
                    <p className="mt-1 text-label-s text-text-tertiary">
                      {humanizeCode(gap.detail.code)}. A quieter stretch of timeline is not
                      evidence that less happened.
                    </p>
                  </li>
                ))}
              </ul>
            )
          }
        </ReadModelPanel>

        <ReadModelPanel
          title="Recorded events"
          description="Ordered by when each event happened. The instant this system observed it is retained separately, so a late arrival sits where it occurred."
          envelope={audit.data}
          dependency="a platform audit event stream — none exists"
          operator={operator}
          testId="audit-events"
          always={
            <FilterBar
              chips={activeKeys.map((key) => ({
                key,
                label: key === "q" ? "Search" : key === "kind" ? "Event kind" : "Actor",
                value: filters[key],
              }))}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
            >
              <SelectField
                id="audit-kind"
                label="Event kind"
                value={filters.kind}
                options={AUDIT_EVENT_KINDS.map((kind) => ({
                  value: kind,
                  label: humanizeCode(kind),
                }))}
                onChange={(next) => setFilter("kind", next)}
              />
              <SelectField
                id="audit-actor"
                label="Actor"
                value={filters.actor}
                options={AUDIT_ACTORS.map((actor) => ({
                  value: actor,
                  label: humanizeCode(actor),
                }))}
                onChange={(next) => setFilter("actor", next)}
              />
              <SearchField
                id="audit-search"
                label="Search"
                value={filters.q}
                placeholder="Event, kind or summary"
                onChange={(next) => setFilter("q", next)}
              />
            </FilterBar>
          }
        >
          {(loaded) => (
            <div className="space-y-3">
              <Timeline
                entries={events.map((event) => ({
                  key: event.event_id,
                  at: event.event_time,
                  title: humanizeCode(event.summary.code),
                  badge: (
                    <span className="flex flex-wrap items-center gap-1.5">
                      <Badge
                        tone={KIND_TONE[event.event_kind.code] ?? "neutral"}
                        data-event-kind={event.event_kind.code}
                      >
                        {humanizeCode(event.event_kind.code)}
                      </Badge>
                      <Badge tone="neutral" data-actor={event.actor.code}>
                        {humanizeCode(event.actor.code)}
                      </Badge>
                    </span>
                  ),
                  children: <EventDisclosure event={event} scope={scope} operator={operator} />,
                }))}
                empty="No recorded event matches this filter. Every event this read delivered is still part of the population above."
                testId="audit-timeline"
              />
              <p className="text-label-s text-text-tertiary" data-testid="audit-count">
                Showing{" "}
                <strong className="font-mono text-text-secondary">{events.length}</strong> of{" "}
                <strong className="font-mono text-text-secondary">
                  {loaded.items.length}
                </strong>{" "}
                recorded events delivered by this read.
              </p>
            </div>
          )}
        </ReadModelPanel>
      </div>
    </>
  );
}

function EventDisclosure({
  event,
  scope,
  operator,
}: {
  event: AuditEvent;
  scope: ViewScope;
  operator: boolean;
}) {
  return (
    <details className="mt-2" data-event={event.event_id}>
      <summary className="cursor-pointer text-label-s text-text-secondary">
        Subjects, linked context, lineage and the record digest
      </summary>
      <div className="mt-2 space-y-3">
        <FactGrid columns={3}>
          <Fact label="Event identity">
            <span className="font-mono text-label-s">{event.event_id}</span>
          </Fact>
          <Fact label="Observed at" testId={`observed-${event.event_id}`}>
            <span className="font-mono text-label-s">{event.observed_time}</span>
          </Fact>
          <Fact label="Record digest" testId={`digest-${event.event_id}`}>
            <span className="font-mono text-label-s">{event.record_digest}</span>
          </Fact>
        </FactGrid>

        {event.supersedes !== undefined && (
          <PanelSection
            title="This event corrects another"
            note="A correction APPENDS. The event it corrects is unchanged and is still on this timeline."
            testId={`correction-${event.event_id}`}
          >
            <ReferenceRow reference={event.supersedes} label="Corrects" scope={scope} />
          </PanelSection>
        )}

        {event.tombstone_of !== undefined && (
          <PanelSection
            title="This event withdraws a record"
            note="A tombstone preserves the governance record without retaining what was withdrawn. It bypasses no identity, classification or scope check."
            testId={`tombstone-${event.event_id}`}
          >
            <ReferenceRow reference={event.tombstone_of} label="Withdrew" scope={scope} />
            {event.deletion_authority !== undefined && (
              <p className="mt-1 text-label-s text-text-tertiary">
                Deletion authority:{" "}
                <strong className="text-text-secondary">
                  {humanizeCode(event.deletion_authority.code)}
                </strong>
              </p>
            )}
          </PanelSection>
        )}

        <ReferenceListPanel
          list={event.subject_refs}
          label="Subjects, as classified references"
          scope={scope}
          empty="This event references no recorded subject."
          testId={`subjects-${event.event_id}`}
        />
        <ReferenceListPanel
          list={event.related_refs}
          label="Linked candidate, trade, research, health and incident context"
          scope={scope}
          empty="This event records no linked context."
          testId={`related-${event.event_id}`}
        />

        <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
          <strong className="text-text-secondary">
            No licensed content appears in an audit payload.
          </strong>{" "}
          A subject arrives as a classified reference to a record held elsewhere, and the digest
          above is of KalpaMani&apos;s own record — never of a vendor payload.
        </p>

        {operator && (
          <div>
            <Label>Version pins</Label>
            <p className="mt-1 font-mono text-label-s text-text-tertiary">
              code_identity=
              {typeof event.lineage.code_identity === "string"
                ? event.lineage.code_identity
                : "not applicable"}{" "}
              · config_identity=
              {typeof event.lineage.config_identity === "string"
                ? event.lineage.config_identity
                : "not applicable"}
            </p>
          </div>
        )}
      </div>
    </details>
  );
}
