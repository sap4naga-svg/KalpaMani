"use client";

import * as React from "react";

import { Badge, Button, Card, CardBody, CardHeader, Label } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { PageHeader } from "@/components/cockpit/page-header";
import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import {
  ComparisonChart,
  EvaluationClassBadge,
  ExposureDisclosure,
  ReadOnlyNotice,
  ReasonList,
  ReferenceListPanel,
  ReferenceRow,
  SectionState,
} from "@/components/cockpit/research";
import { useScope } from "@/components/shell/use-scope";
import type { ChampionChallengerComparison } from "@/contracts/research-models";
import { useChampionChallenger } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";

/**
 * Champion / Challenger — Area 15.
 *
 * "Compare a production strategy version against its candidate replacement."
 *
 *   READINESS IS DISPLAYED, NEVER CONFERRED   "ready" would mean the evidence a packet
 *                                             requires is present. It never means approved,
 *                                             and no promotion path exists from this view
 *   THE POPULATION IS EXPLICIT                a comparison over an unstated population is a
 *                                             comparison of two different questions, so the
 *                                             comparable population and window are shown
 *   HYPOTHETICAL IS NEVER REALIZED            shadow economics carry their assumptions and
 *                                             sit apart from realized outcomes, of which a
 *                                             Challenger has none and can have none
 *   EVERY RESULT CARRIES ITS CLASS            and its exposure disclosure. Exploratory reuse
 *                                             is never displayed as fresh out-of-sample
 *                                             evidence
 */

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const comparisons = useChampionChallenger(scope);
  const [selected, setSelected] = React.useState<string | null>(null);

  const payload = comparisons.data?.payload;
  const items = React.useMemo(() => payload?.items ?? [], [payload]);
  const chosen =
    items.find((entry) => entry.challenger_version === selected) ?? items[0];

  return (
    <>
      <PageHeader
        title="Champion / Challenger"
        summary="Each Challenger against the Champion it was derived from, over an explicitly comparable population, with the evidence completeness and readiness the record states."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 15</Badge>
          <Badge tone="unavailable">Research runtime: NOT IMPLEMENTED</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadOnlyNotice
          subject="recorded paired-version comparisons"
          actions={["promote", "activate", "allocate capital to", "replace", "approve"]}
        />

        <ReadModelPanel
          title="Comparisons"
          description="A Challenger that outperforms is a Challenger that outperforms. The Champion is unchanged until an authorized promotion, and this screen performs none."
          envelope={comparisons.data}
          dependency="the research runtime and the shadow runner — neither exists"
          operator={operator}
          testId="comparison-list"
        >
          {(loaded) => (
            <ul className="space-y-2" data-testid="comparison-rows">
              {loaded.items.map((entry) => (
                <li
                  key={entry.challenger_version}
                  className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
                  data-comparison={entry.challenger_version}
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="positive" data-role="CHAMPION">
                        Champion
                      </Badge>
                      <span className="font-mono text-label-m text-text-secondary">
                        {entry.champion_version}
                      </span>
                      <span aria-hidden="true" className="text-text-tertiary">
                        vs
                      </span>
                      <Badge tone="info" data-role="CHALLENGER">
                        Challenger
                      </Badge>
                      <span className="font-mono text-label-m text-text-secondary">
                        {entry.challenger_version}
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <EvaluationClassBadge evaluationClass={entry.evaluation_class} />
                      <Badge
                        tone={
                          entry.evidence_completeness === "COMPLETE"
                            ? "positive"
                            : entry.evidence_completeness === "PARTIAL"
                              ? "warning"
                              : "unavailable"
                        }
                        data-evidence-completeness={entry.evidence_completeness}
                      >
                        Evidence {humanizeCode(entry.evidence_completeness)}
                      </Badge>
                      <Button
                        size="sm"
                        variant={
                          entry.challenger_version === chosen?.challenger_version
                            ? "primary"
                            : "subtle"
                        }
                        aria-pressed={entry.challenger_version === chosen?.challenger_version}
                        onClick={() => setSelected(entry.challenger_version)}
                      >
                        Detail
                      </Button>
                    </div>
                  </div>
                  <p
                    className="mt-2 text-label-s text-text-tertiary"
                    data-readiness={entry.readiness.code}
                  >
                    Recorded readiness:{" "}
                    <strong className="text-text-secondary">
                      {humanizeCode(entry.readiness.code)}
                    </strong>
                    . <strong>Readiness is displayed and never conferred</strong>, and it never
                    means approved.
                  </p>
                </li>
              ))}
            </ul>
          )}
        </ReadModelPanel>

        {chosen !== undefined && (
          <ComparisonDetail entry={chosen} operator={operator} scope={scope} />
        )}
      </div>
    </>
  );
}

function ComparisonDetail({
  entry,
  operator,
  scope,
}: {
  entry: ChampionChallengerComparison;
  operator: boolean;
  scope: ReturnType<typeof useScope>["scope"];
}) {
  void operator;
  return (
    <Card data-testid="comparison-detail" data-comparison={entry.challenger_version}>
      <CardHeader className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Label>Challenger</Label>
          <p className="mt-0.5 font-mono text-label-m text-text-secondary">
            {entry.challenger_version}
          </p>
          <p className="mt-0.5 text-label-s text-text-tertiary">
            against Champion{" "}
            <span className="font-mono">{entry.champion_version}</span>
          </p>
        </div>
        <EvaluationClassBadge evaluationClass={entry.evaluation_class} />
      </CardHeader>
      <CardBody className="space-y-4">
        <PanelSection
          title="The population the two were compared over"
          note="Two versions are comparable only over an explicitly comparable population and window."
          testId="comparison-population"
        >
          <dl className="grid gap-3 sm:grid-cols-2">
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Comparable population
              </dt>
              <dd className="text-label-m text-text-secondary">
                {humanizeCode(entry.comparable_population.code)}
              </dd>
            </div>
            <div>
              <dt className="text-label-s uppercase tracking-[0.09em] text-text-tertiary">
                Window
              </dt>
              <dd className="font-mono text-label-s text-text-secondary">
                {entry.window.from} → {entry.window.to} ({entry.window.timezone},{" "}
                {humanizeCode(entry.window.calendar.code)})
              </dd>
            </div>
          </dl>
          <div className="mt-2">
            <ReferenceRow
              reference={entry.registration_ref}
              label="Registration"
              scope={scope}
            />
          </div>
        </PanelSection>

        <PanelSection
          title="Overlap"
          note="How much of one version's behaviour the other shares. A ratio with no defined population is not shown."
          testId="comparison-overlap"
        >
          <ComparisonChart
            caption={`Population overlap between ${entry.champion_version} and ${entry.challenger_version}`}
            rows={entry.overlap.map((measure) => ({
              label: measure.measure.code,
              value: measure.value,
            }))}
            unitLabel="ratio"
            testId="overlap-chart"
          />
        </PanelSection>

        <PanelSection
          title="Divergence"
          note="Where the two versions did different things. Counts and ratios are separate measures, and neither is a profit figure."
          testId="comparison-divergence"
        >
          <ComparisonChart
            caption={`Divergence between ${entry.champion_version} and ${entry.challenger_version}`}
            rows={entry.divergence.map((measure) => ({
              label: measure.measure.code,
              value: measure.value,
            }))}
            unitLabel="their own declared units"
            testId="divergence-chart"
          />
        </PanelSection>

        <PanelSection
          title="Factor-exposure differences"
          note="What the Challenger would be exposed to that the Champion is not."
          testId="comparison-exposure"
        >
          <ComparisonChart
            caption={`Exposure differences for ${entry.challenger_version}`}
            rows={entry.exposure_difference.map((axis) => ({
              label: axis.axis.code,
              value: axis.value,
            }))}
            unitLabel="percent"
            testId="exposure-chart"
          />
        </PanelSection>

        <PanelSection
          title="Hypothetical shadow economics"
          note="Shadow produces no order, in any environment. These are modelled figures under stated assumptions, and they are never placed in a series with a realized result."
          testId="comparison-shadow"
        >
          <div className="space-y-3">
            {entry.shadow_economics.length === 0 ? (
              <SectionState
                availability="NOT_YET_AVAILABLE"
                reason="UPSTREAM_INPUT_MISSING"
                note="No shadow run has been authorized or performed for this Challenger, so no hypothetical economics exist."
                testId="shadow-absent"
              />
            ) : (
              <ComparisonChart
                caption={`Hypothetical shadow economics for ${entry.challenger_version}`}
                rows={entry.shadow_economics.map((measure) => ({
                  label: measure.measure.code,
                  value: measure.value,
                }))}
                unitLabel="percent, hypothetical"
                testId="shadow-chart"
              />
            )}
            <div>
              <Label>Stated assumptions</Label>
              <div className="mt-1">
                <ReasonList
                  codes={entry.shadow_assumptions}
                  tone="warning"
                  empty="No shadow assumption is recorded."
                />
              </div>
            </div>
            <div
              className="flex flex-wrap items-center gap-2 rounded-sm border border-border-subtle p-3"
              data-testid="realized-outcomes"
            >
              <Label>Realized outcomes</Label>
              <AvailabilityBadge
                state={entry.realized_outcomes.availability}
                reason={entry.realized_outcomes.reason}
              />
              <span className="max-w-2xl text-label-s text-text-tertiary">
                <strong className="text-text-secondary">
                  A Challenger produces no order in any environment
                </strong>
                , so it has no realized outcome at all — an inapplicable question rather than a
                missing measurement.
              </span>
            </div>
          </div>
        </PanelSection>

        <PanelSection
          title="Readiness, and what it is not"
          note="Recorded readiness means the evidence a governance packet requires is present. It is not an approval, and this screen confers nothing."
          testId="comparison-readiness"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="unavailable" data-readiness={entry.readiness.code}>
              {humanizeCode(entry.readiness.code)}
            </Badge>
            <Badge
              tone={
                entry.evidence_completeness === "COMPLETE"
                  ? "positive"
                  : entry.evidence_completeness === "PARTIAL"
                    ? "warning"
                    : "unavailable"
              }
            >
              Evidence {humanizeCode(entry.evidence_completeness)}
            </Badge>
          </div>
          <p className="mt-2 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            <strong className="text-text-secondary">No promotion path exists from this
            view.</strong>{" "}
            A Challenger may progress automatically only through preapproved research and
            shadow stages; promotion requires a governance packet and a human decision, and
            neither is taken here.
          </p>
        </PanelSection>

        <PanelSection title="Evidence and exposure" testId="comparison-evidence">
          <div className="space-y-3">
            <div className="grid gap-3 lg:grid-cols-2">
              <ReferenceListPanel
                list={entry.evidence_refs}
                label="Authorized runs cited"
                scope={scope}
                empty="This comparison cites no run: nothing has been run against it."
              />
              <ReferenceListPanel
                list={entry.shadow_refs}
                label="Shadow evidence cited"
                scope={scope}
                empty="This comparison cites no shadow evidence, because no shadow run has been authorized."
              />
            </div>
            <ExposureDisclosure disclosure={entry.data_exposure_disclosure} />
          </div>
        </PanelSection>
      </CardBody>
    </Card>
  );
}
