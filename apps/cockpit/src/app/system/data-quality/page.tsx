"use client";

import * as React from "react";

import { Badge, Label } from "@/components/ui/primitives";
import { FilterBar, SelectField } from "@/components/cockpit/filters";
import { FreshnessIndicator } from "@/components/cockpit/freshness";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import {
  ComparisonChart,
  ReferenceListPanel,
  ReferenceRow,
  SectionState,
  type ComparisonRow,
} from "@/components/cockpit/research";
import {
  Fact,
  FactGrid,
  OperationsReadOnlyNotice,
  StateBadge,
  SubjectState,
  WindowStatement,
} from "@/components/cockpit/operations";
import { useScope } from "@/components/shell/use-scope";
import { usePageFilters } from "@/components/shell/use-page-filters";
import type { DataQuality } from "@/contracts/operations-models";
import { INFORMATION_PROFILES, type InformationProfile } from "@/contracts/vocabularies";
import { useDataQuality } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";
import type { ViewScope } from "@/lib/scope";

/**
 * Data Quality & Point-in-Time — Area 22.
 *
 * "Show whether the data underneath every other screen can be trusted."
 *
 *   THE PROFILE VOCABULARY IS THE EXISTING   `PUBLIC_PIT`, `PROVIDER_REALISTIC_PIT` and
 *   ONE AND IS NOT EXTENDED                  `FORWARD_SYSTEM`. There is no fourth member, no
 *                                            default, and no inferred profile
 *   PROVIDER-DERIVED IS NEVER `PUBLIC_PIT`   the contract refuses that pairing at admission,
 *                                            and the screen shows the origin beside the
 *                                            profile so a reader can check it
 *   PROFILE, PROVENANCE AND CLASSIFICATION   three separate axes, three separate fields, and
 *   ARE THREE QUESTIONS                      none of them is displayed as another
 *   COVERAGE NAMES ITS POPULATION            present and requested are separate counts over a
 *                                            named extent, and a partial subject NAMES its gap
 *   NO REAL FEED EXISTS                      no provider is selected, P1 to P9 are
 *                                            UNEVALUATED, and data correctness is NOT
 *                                            ESTABLISHED. Every subject here is synthetic
 */

const FILTER_KEYS = ["profile"] as const;

const PROFILE_TONE: Readonly<
  Record<InformationProfile, React.ComponentProps<typeof Badge>["tone"]>
> = {
  PUBLIC_PIT: "info",
  PROVIDER_REALISTIC_PIT: "warning",
  FORWARD_SYSTEM: "neutral",
};

const PROFILE_MEANING: Readonly<Record<InformationProfile, string>> = {
  PUBLIC_PIT:
    "What was publicly knowable at the time, from a publicly observed source. It is never claimed for provider-derived information.",
  PROVIDER_REALISTIC_PIT:
    "What a provider's own records make available as of a time. Provider-derived price information stays here while its origin is publicly unresolved.",
  FORWARD_SYSTEM:
    "A system-derived observation about now. It is not a point-in-time history and is never read as one.",
};

/**
 * How many subjects carry one profile.
 *
 * A count is a MEASURED value and renders through `MetricText` like every other, with its unit
 * carried by the metric rather than by the sentence around it — and the noun agrees with the
 * number, because "1 subjects" is a sentence a screen should not print.
 */
function ProfileCount({ count, asOf }: { count: number; asOf: string }) {
  return (
    <span className="text-label-s text-text-tertiary">
      <MetricText
        metric={{
          value: count,
          unit: "COUNT",
          availability: "AVAILABLE",
          reason: "NONE",
          as_of: asOf,
          metric_id: "reference.total",
          metric_definition_version: "metrics.v1",
        }}
        neutral
      />{" "}
      {count === 1 ? "subject" : "subjects"}
    </span>
  );
}

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const quality = useDataQuality(scope);
  const payload = quality.data?.payload;
  const { filters, setFilter, clearFilter, clearAll, activeKeys } =
    usePageFilters(FILTER_KEYS);

  const subjects = React.useMemo(() => {
    if (payload === undefined) {
      return [];
    }
    return payload.items.filter(
      (subject) =>
        filters.profile === "" || subject.information_profile === filters.profile,
    );
  }, [payload, filters.profile]);

  return (
    <>
      <PageHeader
        title="Data Quality & Point-in-Time"
        summary="Coverage, freshness, history depth, lineage, revisions, corporate-action timing and borrow-data quality, per subject. A point-in-time profile is declared, never inferred, and provider-derived information never renders as PUBLIC_PIT."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 22</Badge>
          <Badge tone="unavailable">Real provider feed: NOT IMPLEMENTED</Badge>
          <Badge tone="unavailable">G1 OPEN · G2 OPEN · P1–P9 UNEVALUATED</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <OperationsReadOnlyNotice
          subject="recorded data-quality evidence"
          actions={["fetch", "ingest", "backfill", "refresh", "re-run a check"]}
          producer="No provider is selected and no ingestion has run, so no real feed underlies any subject below"
        />

        <ReadModelPanel
          title="The three point-in-time profiles"
          description="The accepted vocabulary, rendered in full, so a screen can be checked against it rather than trusted."
          envelope={quality.data}
          dependency="a qualified point-in-time provider — none is selected, and G1 is OPEN"
          operator={operator}
          testId="profile-legend"
        >
          {(loaded) => (
            <div className="space-y-3">
              <ul className="space-y-2" data-testid="profile-list">
                {loaded.information_profiles.map((profile) => (
                  <li
                    key={profile}
                    className="flex flex-wrap items-baseline gap-2"
                    data-profile={profile}
                  >
                    <Badge tone={PROFILE_TONE[profile]}>{humanizeCode(profile)}</Badge>
                    <span className="max-w-2xl text-label-s leading-relaxed text-text-tertiary">
                      {PROFILE_MEANING[profile]}
                    </span>
                    <ProfileCount
                      count={
                        loaded.items.filter(
                          (subject) => subject.information_profile === profile,
                        ).length
                      }
                      asOf={loaded.window.to}
                    />
                  </li>
                ))}
              </ul>
              <SectionState
                availability={loaded.real_feed_state.availability}
                reason={loaded.real_feed_state.reason}
                note={humanizeCode(loaded.real_feed_state.note.code)}
                testId="real-feed-state"
              />
              <WindowStatement window={loaded.window} label="Evaluated over" />
              <p
                className="max-w-3xl text-label-s leading-relaxed text-text-tertiary"
                data-testid="profile-rule"
              >
                <strong className="text-text-secondary">
                  A profile is declared, never inferred.
                </strong>{" "}
                Every subject states the basis its profile was declared under and the origin of
                the information it is about, and{" "}
                <strong className="text-text-secondary">
                  provider-derived information never renders as PUBLIC_PIT
                </strong>{" "}
                — the contract refuses that pairing at admission.
              </p>
            </div>
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="Coverage by subject"
          description="Present against requested, over a named extent. A subject covering less than it was asked for names the gap."
          envelope={quality.data}
          dependency="a qualified point-in-time provider — none is selected, and G1 is OPEN"
          operator={operator}
          testId="coverage-chart-panel"
        >
          {(loaded) => (
            <ComparisonChart
              caption="Recorded coverage ratio by subject"
              rows={loaded.items.map(
                (subject): ComparisonRow => ({
                  label: subject.subject.code,
                  value: subject.coverage.ratio,
                  context: subject.coverage.present,
                }),
              )}
              unitLabel="ratio of the requested extent"
              contextLabel="Sessions present"
              testId="coverage-chart"
            />
          )}
        </ReadModelPanel>

        <ReadModelPanel
          title="Recorded subjects"
          description="One card per subject, with its profile, its origin, its coverage, its freshness and the strategies a recorded condition affects."
          envelope={quality.data}
          dependency="a qualified point-in-time provider — none is selected, and G1 is OPEN"
          operator={operator}
          testId="subject-panel"
          always={
            <FilterBar
              chips={activeKeys.map((key) => ({
                key,
                label: "Profile",
                value: filters[key],
              }))}
              onRemove={(key) => clearFilter(key as (typeof FILTER_KEYS)[number])}
              onClearAll={clearAll}
            >
              <SelectField
                id="data-quality-profile"
                label="Profile"
                value={filters.profile}
                options={INFORMATION_PROFILES.map((profile) => ({
                  value: profile,
                  label: humanizeCode(profile),
                }))}
                onChange={(next) => setFilter("profile", next)}
              />
            </FilterBar>
          }
        >
          {(loaded) => (
            <div className="space-y-3">
              {subjects.length === 0 ? (
                <p className="text-label-m text-text-tertiary" data-testid="no-subjects">
                  No recorded subject carries this profile. Every subject this read delivered is
                  still part of the population above.
                </p>
              ) : (
                <ul className="space-y-3" data-testid="subject-list">
                  {subjects.map((subject) => (
                    <li key={subject.subject_id}>
                      <SubjectCard subject={subject} scope={scope} operator={operator} />
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-label-s text-text-tertiary" data-testid="subject-count">
                Showing{" "}
                <strong className="font-mono text-text-secondary">{subjects.length}</strong> of{" "}
                <strong className="font-mono text-text-secondary">
                  {loaded.items.length}
                </strong>{" "}
                subjects delivered by this read.
              </p>
            </div>
          )}
        </ReadModelPanel>
      </div>
    </>
  );
}

function SubjectCard({
  subject,
  scope,
  operator,
}: {
  subject: DataQuality;
  scope: ViewScope;
  operator: boolean;
}) {
  return (
    <div
      className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
      data-subject={subject.subject_id}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-label-m font-semibold text-text-primary">
            {humanizeCode(subject.subject.code)}
          </h3>
          <Badge
            tone={PROFILE_TONE[subject.information_profile]}
            data-information-profile={subject.information_profile}
            title={PROFILE_MEANING[subject.information_profile]}
          >
            {humanizeCode(subject.information_profile)}
          </Badge>
          <StateBadge state={subject.information_origin} attribute="information-origin" />
        </div>
        <SubjectState
          availability={subject.subject_state.availability}
          reason={subject.subject_state.reason}
        />
      </div>

      <p className="mt-1 text-label-s text-text-tertiary" data-testid="profile-basis">
        Profile basis: {humanizeCode(subject.profile_basis.code)} · provenance{" "}
        {subject.provenance} · classification {subject.classification}
      </p>

      <FactGrid className="mt-3" columns={4}>
        <Fact label="Present">
          <MetricText metric={subject.coverage.present} neutral />
        </Fact>
        <Fact label="Requested">
          <MetricText metric={subject.coverage.requested} neutral />
        </Fact>
        <Fact label="Coverage">
          <MetricText metric={subject.coverage.ratio} neutral />
        </Fact>
        <Fact label="Extent">{humanizeCode(subject.coverage.extent.code)}</Fact>
        <Fact label="History depth">
          <MetricText metric={subject.history_depth} neutral />
        </Fact>
        <Fact label="Earliest record">
          <MetricText metric={subject.earliest_record} neutral />
        </Fact>
        <Fact label="Dataset version">
          <span className="font-mono text-label-s">{subject.dataset_version}</span>
        </Fact>
        <Fact label="Freshness">
          {/* A SUBJECT'S OWN freshness, distinct from the view-level indicator in the shell. */}
          <FreshnessIndicator report={subject.freshness} testId="subject-freshness" />
        </Fact>
      </FactGrid>

      {subject.missingness.length > 0 && (
        <div className="mt-3" data-testid={`gaps-${subject.subject_id}`}>
          <Label>What is missing, and over what extent</Label>
          <ul className="mt-1 space-y-1">
            {subject.missingness.map((gap) => (
              <li key={gap.gap.code} className="flex flex-wrap items-center gap-2">
                <Badge tone="warning">{humanizeCode(gap.gap.code)}</Badge>
                <span className="text-label-s text-text-tertiary">
                  <MetricText metric={gap.sessions} neutral /> over{" "}
                  {humanizeCode(gap.extent.code)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="mt-3">
        <summary className="cursor-pointer text-label-s text-text-secondary">
          Checks, revisions, corporate actions, borrow quality, lineage and affected strategies
        </summary>
        <div className="mt-2 space-y-3">
          <PanelSection title="Recorded quality checks">
            {subject.quality_checks.length === 0 ? (
              <p className="text-label-s text-text-tertiary">
                This subject records no quality check.
              </p>
            ) : (
              <ul className="space-y-1" data-testid={`checks-${subject.subject_id}`}>
                {subject.quality_checks.map((check) => (
                  <li key={check.check.code} className="flex flex-wrap items-center gap-2">
                    <span className="text-label-m text-text-primary">
                      {humanizeCode(check.check.code)}
                    </span>
                    <StateBadge
                      state={check.result}
                      tone={
                        check.result.code === "PASSED"
                          ? "positive"
                          : check.result.code === "FAILED"
                            ? "negative"
                            : "unavailable"
                      }
                      attribute="check-result"
                    />
                    <span className="text-label-s text-text-tertiary">
                      over <MetricText metric={check.population} neutral />, as of {check.as_of}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </PanelSection>

          <PanelSection
            title="Revisions observed"
            note="Information time is bounded by what the source records: a date-granular update column cannot supply an instant, whatever the comparison found."
          >
            {subject.revision_view.length === 0 ? (
              <p className="text-label-s text-text-tertiary">
                This subject records no revision observation.
              </p>
            ) : (
              <ul className="space-y-1" data-testid={`revisions-${subject.subject_id}`}>
                {subject.revision_view.map((observation) => (
                  <li
                    key={observation.observed_at}
                    className="flex flex-wrap items-center gap-2"
                  >
                    <span className="font-mono text-label-s text-text-tertiary">
                      {observation.observed_at}
                    </span>
                    <StateBadge state={observation.revision_kind} attribute="revision-kind" />
                    <span className="text-label-s text-text-tertiary">
                      <MetricText metric={observation.affected_rows} neutral /> rows ·
                      information time{" "}
                      {humanizeCode(observation.information_time_resolution.code)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </PanelSection>

          <PanelSection
            title="Corporate actions and their timing"
            note="An adjusted series and an actual fill price are different series. An actual fill is never restated by an adjustment factor."
          >
            {subject.corporate_actions.length === 0 ? (
              <p className="text-label-s text-text-tertiary">
                This subject records no corporate action.
              </p>
            ) : (
              <ul className="space-y-2" data-testid={`actions-${subject.subject_id}`}>
                {subject.corporate_actions.map((action) => (
                  <li key={action.action.code} className="space-y-1">
                    <Badge tone="neutral">{humanizeCode(action.action.code)}</Badge>
                    <FactGrid columns={4}>
                      <Fact label="Announced">
                        <MetricText metric={action.announced_on} neutral />
                      </Fact>
                      <Fact label="Effective">
                        <MetricText metric={action.effective_on} neutral />
                      </Fact>
                      <Fact label="Timing basis">
                        {humanizeCode(action.timing_basis.code)}
                      </Fact>
                      <Fact label="Treatment">{humanizeCode(action.treatment.code)}</Fact>
                    </FactGrid>
                  </li>
                ))}
              </ul>
            )}
          </PanelSection>

          <PanelSection title="Borrow-data quality">
            <FactGrid columns={3}>
              <Fact label="State">
                <StateBadge state={subject.borrow_quality.state} attribute="borrow-state" />
              </Fact>
              <Fact label="Records">
                <MetricText metric={subject.borrow_quality.records} neutral />
              </Fact>
              <Fact label="Note">{humanizeCode(subject.borrow_quality.note.code)}</Fact>
            </FactGrid>
          </PanelSection>

          <PanelSection
            title="Strategies a recorded condition affects"
            note="A recorded effect. Nothing on this screen caused it, and nothing here can reverse it."
          >
            {subject.affected_strategies.length === 0 ? (
              <p className="text-label-s text-text-tertiary">
                No strategy is recorded as affected by a condition on this subject.
              </p>
            ) : (
              <ul className="space-y-2" data-testid={`affected-${subject.subject_id}`}>
                {subject.affected_strategies.map((affected) => (
                  <li key={affected.version_ref.ref_id} className="space-y-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-label-m text-text-primary">
                        {humanizeCode(affected.strategy_module.code)}
                      </span>
                      <Badge tone="warning">{humanizeCode(affected.condition.code)}</Badge>
                      <span className="text-label-s text-text-tertiary">
                        {humanizeCode(affected.effect.code)}
                      </span>
                    </div>
                    <ReferenceRow
                      reference={affected.version_ref}
                      label="Strategy version"
                      scope={scope}
                    />
                  </li>
                ))}
              </ul>
            )}
          </PanelSection>

          <ReferenceListPanel
            list={subject.lineage_refs}
            label="Lineage"
            scope={scope}
            empty="This subject records no lineage reference."
          />
          <ReferenceListPanel
            list={subject.incident_refs}
            label="Incidents"
            scope={scope}
            empty="This subject records no incident."
          />
          <ReferenceListPanel
            list={subject.alert_refs}
            label="Alerts raised by this condition"
            scope={scope}
            empty="This subject records no alert."
          />

          {operator && (
            <p className="font-mono text-label-s text-text-tertiary">
              subject_id={subject.subject_id} · profile={subject.information_profile} · origin=
              {subject.information_origin.code}
            </p>
          )}
        </div>
      </details>
    </div>
  );
}
