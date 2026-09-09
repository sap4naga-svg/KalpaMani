"use client";

import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Label,
  Numeric,
  ScrollRegion,
} from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { PageHeader } from "@/components/cockpit/page-header";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { useClock } from "@/components/shell/clock-provider";
import { useScope } from "@/components/shell/use-scope";
import { useQualificationStatus } from "@/data/client/hooks";
import { isValueBearing } from "@/contracts/validity";
import { DATE_STANDING_LABEL, DATE_STANDING_NOTE, evaluateDateGate } from "@/lib/governance";
import { humanizeCode } from "@/lib/format";

/**
 * Project and qualification governance — product area 24.
 *
 * A SOURCE-LINKED READINESS SUMMARY BUILT FROM REAL FACTS. Provenance is
 * `REPOSITORY_TRACKED` and these facts are NEVER relabelled `SYNTHETIC`.
 *
 * Every fact carries the tracked path and commit it was read at. EACH GATE IS READ
 * INDEPENDENTLY — no blanket statement over all seven is correct. P1 to P9 render
 * `UNEVALUATED`. RUN AUTHORIZATION AND ITS DATE GATE RENDER AS TWO SEPARATE FACTS, and
 * PASSING A DATE AUTHORIZES NOTHING.
 *
 * THERE IS NO PERCENTAGE ANYWHERE ON THIS PAGE. Seven gates of unequal scope and nine
 * unevaluated provider tests do not average into a readiness figure; a number produced from
 * them would be an invention, and a progress bar drawn from it would be a confident one.
 *
 * NO ACTION IS OFFERED. Nothing here runs Run B, requests an authorization, starts an
 * assessment or advances a gate — those are human decisions taken elsewhere, and this page
 * only says which one is next.
 *
 * NO private qualification evidence, locator, record, payload, report, execution identifier,
 * object key or digest appears here.
 */
const REPO = "https://github.com/sap4naga-svg/KalpaMani/blob";

function SourceLink({ path, commit }: { path: string; commit: string }) {
  return (
    <a
      href={`${REPO}/${commit}/${path}`}
      target="_blank"
      rel="noreferrer noopener"
      className="font-mono text-label-s text-accent underline underline-offset-2"
    >
      {path}
    </a>
  );
}

export default function QualificationGovernancePage() {
  const { scope } = useScope();
  const clock = useClock();
  const query = useQualificationStatus(scope);
  const operator = scope.mode === "operator";
  const payload = query.data?.payload;

  if (query.data === undefined || payload === undefined) {
    return (
      <>
        <PageHeader
          title="Project & Qualification Governance"
          summary="Real governance facts, each read independently from tracked repository authority."
        />
        {query.data !== undefined ? (
          <Card>
            <CardBody className="pt-5">
              <AvailabilityBadge
                state={query.data.availability}
                reason={query.data.availability_reason}
              />
              <p className="mt-2 max-w-2xl text-label-m text-text-tertiary">
                These are the repository&rsquo;s own governance facts, recorded under the
                project&rsquo;s actual runtime environment. Under a Paper or Live selector
                there is no such record to show.
              </p>
            </CardBody>
          </Card>
        ) : (
          <>
            <div className="skeleton-shape h-40 w-full" data-testid="skeleton" />
            <span className="sr-only">Loading</span>
          </>
        )}
      </>
    );
  }

  const openGates = payload.gates.filter((gate) => gate.state === "OPEN").length;

  return (
    <>
      <PageHeader
        title="Project & Qualification Governance"
        summary="Real facts, read from tracked repository authority at a recorded commit. Each gate is read on its own; no blanket statement over all seven is correct."
      >
        <div className="flex flex-wrap items-center gap-2">
          <ProvenanceBadge provenance={query.data.provenance} />
          <Badge tone="neutral">PUBLIC_SAFE</Badge>
          <Badge tone="neutral">
            Phase: {humanizeCode(payload.implementation_phase.code)}
          </Badge>
          <span className="font-mono text-label-s text-text-tertiary">
            read at {payload.read_at_commit.slice(0, 12)}
          </span>
        </div>
      </PageHeader>

      {/* THE NEXT GOVERNANCE EVENT. What must happen, never when it will. */}
      <Card className="mb-4" data-testid="next-required-event">
        <CardHeader>
          <Label as="h2">Next required governance event</Label>
        </CardHeader>
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="accent">{humanizeCode(payload.next_required_event.event.code)}</Badge>
            <span className="text-label-m text-text-tertiary">taken by</span>
            <Badge tone="neutral">{humanizeCode(payload.next_required_event.actor.code)}</Badge>
          </div>
          <p className="max-w-3xl text-label-m leading-relaxed text-text-secondary">
            <span className="text-text-tertiary">Prerequisite: </span>
            {humanizeCode(payload.next_required_event.prerequisite.code)}.
          </p>
          <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            This is a <strong>human decision recorded elsewhere</strong>. The Cockpit does not
            request it, grant it, schedule it or predict it, and there is no control here that
            could.
          </p>
          {operator && (
            <SourceLink
              path={payload.next_required_event.source.path}
              commit={payload.next_required_event.source.commit}
            />
          )}
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {/* RUN AUTHORIZATION AND DATE ELIGIBILITY -- two separate facts, side by side. */}
        <Card className="xl:col-span-2">
          <CardHeader>
            <Label as="h2">Run authorization and date eligibility</Label>
            <p className="mt-1 max-w-3xl text-label-m text-text-secondary">
              Two separate facts, evaluated separately and displayed separately.{" "}
              <strong>Passing a date authorizes nothing.</strong> {DATE_STANDING_NOTE}
            </p>
          </CardHeader>
          <CardBody className="space-y-3">
            {payload.run_authorizations.map((entry) => {
              const standing = evaluateDateGate(entry.date_gate.value, clock.now());
              return (
                <div
                  key={entry.run.code}
                  data-testid="run-authorization"
                  data-run={entry.run.code}
                  data-date-standing={standing.standing}
                  className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-numeric-s font-medium text-text-primary">
                      {humanizeCode(entry.run.code)}
                    </p>
                    {entry.preceded_by !== undefined && (
                      <span className="text-label-s text-text-tertiary">
                        after {humanizeCode(entry.preceded_by.code)}
                      </span>
                    )}
                  </div>

                  <dl className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div>
                      <dt>
                        <Label>Authorization</Label>
                      </dt>
                      <dd className="mt-1">
                        <Badge tone="negative">
                          <span aria-hidden="true">⊘</span>
                          <span>{entry.authorization.code}</span>
                        </Badge>
                        <p className="mt-1 text-label-s text-text-tertiary">
                          A separate written decision. Not derived from any date.
                        </p>
                      </dd>
                    </div>

                    <div>
                      <dt>
                        <Label>Earliest target date</Label>
                      </dt>
                      <dd className="mt-1">
                        {isValueBearing(entry.date_gate.availability) ? (
                          <>
                            <span className="font-mono text-numeric-s text-text-secondary">
                              {String(entry.date_gate.value)}
                            </span>
                            <p className="mt-1 flex flex-wrap items-center gap-1.5">
                              <Badge
                                tone={
                                  standing.standing === "REACHED" ? "neutral" : "unavailable"
                                }
                              >
                                <span aria-hidden="true">
                                  {standing.standing === "REACHED" ? "◷" : "◌"}
                                </span>
                                <span>{DATE_STANDING_LABEL[standing.standing]}</span>
                              </Badge>
                            </p>
                            <p className="mt-1 font-mono text-label-s text-text-tertiary">
                              basis {humanizeCode(entry.date_basis.code)} · evaluated{" "}
                              {standing.evaluatedOn ?? "unknown"}
                            </p>
                          </>
                        ) : (
                          <AvailabilityBadge
                            state={entry.date_gate.availability}
                            reason={entry.date_gate.reason}
                          />
                        )}
                      </dd>
                    </div>

                    <div>
                      <dt>
                        <Label>Minimum separation</Label>
                      </dt>
                      <dd className="mt-1">
                        {isValueBearing(entry.minimum_separation.availability) ? (
                          <span className="font-mono text-numeric-s text-text-secondary">
                            {String(entry.minimum_separation.value)} calendar days
                          </span>
                        ) : (
                          <AvailabilityBadge
                            state={entry.minimum_separation.availability}
                            reason={entry.minimum_separation.reason}
                          />
                        )}
                      </dd>
                    </div>
                  </dl>

                  <p className="mt-2 text-label-s leading-relaxed text-text-tertiary">
                    <strong>This run cannot be started from here.</strong> There is no button,
                    no handler and no route that would run it, and reaching the date above
                    would not create one.
                  </p>

                  {operator && (
                    <div className="mt-2">
                      <SourceLink path={entry.source.path} commit={entry.source.commit} />
                    </div>
                  )}
                </div>
              );
            })}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <Label as="h2">Decision gates</Label>
            <p className="mt-1 text-label-m text-text-secondary">
              <span className="font-mono">{openGates}</span> of{" "}
              <span className="font-mono">{payload.gates.length}</span> open. Each gate is read
              on its own, and G3 is closed for the Sharadar personal-use licence and nothing
              else.
            </p>
          </CardHeader>
          <CardBody>
            <ScrollRegion label="Decision gates table">
              <table className="w-full min-w-[28rem] border-collapse text-label-m">
                <caption className="sr-only">Decision gates and their scopes</caption>
                <thead>
                  <tr className="border-b border-border-subtle text-left">
                    {["Gate", "State", "Scope"].map((heading) => (
                      <th
                        key={heading}
                        scope="col"
                        className="py-1.5 pr-3 font-medium text-text-tertiary"
                      >
                        {heading}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {payload.gates.map((gate) => (
                    <tr
                      key={gate.gate}
                      className="border-b border-border-subtle last:border-0"
                      data-testid="decision-gate"
                      data-gate={gate.gate}
                    >
                      <th
                        scope="row"
                        className="py-2 pr-3 text-left font-mono text-text-primary"
                      >
                        {gate.gate}
                      </th>
                      <td className="py-2 pr-3">
                        <Badge tone={gate.state === "OPEN" ? "warning" : "positive"}>
                          <span aria-hidden="true">{gate.state === "OPEN" ? "◑" : "●"}</span>
                          <span>{gate.state}</span>
                        </Badge>
                      </td>
                      <td className="py-2 text-text-secondary">
                        {humanizeCode(gate.scope.code)}
                        {operator && (
                          <div className="mt-0.5">
                            <SourceLink path={gate.source.path} commit={gate.source.commit} />
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <Label as="h2">Provider qualification tests P1–P9</Label>
          </CardHeader>
          <CardBody>
            <ul className="flex flex-wrap gap-2">
              {payload.provider_tests.map((test) => (
                <li key={test.test.code}>
                  <Badge tone="unavailable" data-availability="UNEVALUATED">
                    <span aria-hidden="true">◇</span>
                    <span className="font-mono">{test.test.code}</span>
                    <span>{test.state}</span>
                  </Badge>
                </li>
              ))}
            </ul>
            <p className="mt-3 max-w-2xl text-label-m leading-relaxed text-text-tertiary">
              <strong>Unevaluated is the only state this payload can carry today.</strong> Run A
              completed once and is a <em>command outcome</em>, not a provider verdict: it
              retrieved bytes and published them, and it established no correctness, no quality
              and no entitlement. P1–P9 are evaluated by the combined assessment, which runs
              after Run B.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Badge tone="unavailable">Data correctness NOT ESTABLISHED</Badge>
              <Badge tone="unavailable">Provider selected NONE</Badge>
            </div>
          </CardBody>
        </Card>

        {/* THE CHAIN, NOT A SCORE. */}
        <Card data-testid="blockers">
          <CardHeader>
            <Label as="h2">What stands in front of the next gate</Label>
            <p className="mt-1 text-label-m text-text-secondary">
              A chain of recorded states. <strong>Not a score, and not a percentage</strong> —
              gates of unequal scope do not average.
            </p>
          </CardHeader>
          <CardBody>
            <ol className="space-y-2">
              {payload.blockers.map((blocker, index) => (
                <li
                  key={blocker.blocker_id}
                  className="flex flex-wrap items-center gap-2"
                  data-testid="blocker"
                >
                  <Numeric size="s" className="text-text-tertiary">
                    {index + 1}.
                  </Numeric>
                  <span className="text-label-m text-text-primary">
                    {humanizeCode(blocker.subject.code)}
                  </span>
                  <Badge tone="warning">{humanizeCode(blocker.state.code)}</Badge>
                  <span className="text-label-s text-text-tertiary">
                    blocks {humanizeCode(blocker.blocks.code)}
                  </span>
                  {operator && (
                    <SourceLink path={blocker.source.path} commit={blocker.source.commit} />
                  )}
                </li>
              ))}
            </ol>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <Label as="h2">Architecture decision records</Label>
          </CardHeader>
          <CardBody>
            <ul className="space-y-2">
              {payload.adr_states.map((entry) => (
                <li key={entry.adr} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-numeric-s text-text-primary">{entry.adr}</span>
                  <Badge
                    tone={entry.state.code === "ACCEPTED_IN_FORCE" ? "positive" : "warning"}
                  >
                    {humanizeCode(entry.state.code)}
                  </Badge>
                  {operator && (
                    <SourceLink path={entry.source.path} commit={entry.source.commit} />
                  )}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <Label as="h2">Recorded project facts</Label>
          </CardHeader>
          <CardBody>
            <ScrollRegion label="Recorded project facts table">
              <table className="w-full min-w-[34rem] border-collapse text-label-m">
                <caption className="sr-only">Recorded project facts and their sources</caption>
                <thead>
                  <tr className="border-b border-border-subtle text-left">
                    {["Subject", "State", "As of", "Source"].map((heading) => (
                      <th
                        key={heading}
                        scope="col"
                        className="py-1.5 pr-3 font-medium text-text-tertiary"
                      >
                        {heading}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {payload.facts.map((fact) => (
                    <tr
                      key={fact.fact_id}
                      className="border-b border-border-subtle last:border-0"
                      data-testid="recorded-fact"
                    >
                      <th
                        scope="row"
                        className="py-2 pr-3 text-left font-normal text-text-primary"
                      >
                        {humanizeCode(fact.subject.code)}
                      </th>
                      <td className="py-2 pr-3 text-text-secondary">
                        {humanizeCode(fact.state.code)}
                      </td>
                      <td className="py-2 pr-3 font-mono text-text-tertiary">{fact.as_of}</td>
                      <td className="py-2">
                        <SourceLink path={fact.source.path} commit={fact.source.commit} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border-subtle pt-3">
              <Badge tone="negative">{humanizeCode(payload.phase_state.code)}</Badge>
              <Badge tone="negative">
                Live trading {humanizeCode(payload.live_trading.code)}
              </Badge>
            </div>
          </CardBody>
        </Card>
      </div>

      {/* SNAPSHOT PROVENANCE -- source as-of and extraction date, kept apart. */}
      <Card className="mt-4" data-testid="snapshot-provenance">
        <CardHeader>
          <Label as="h2">Snapshot provenance</Label>
        </CardHeader>
        <CardBody className="space-y-3">
          <dl className="grid grid-cols-1 gap-x-8 gap-y-2 font-mono text-label-s sm:grid-cols-3">
            <div className="flex flex-col">
              <dt className="text-text-tertiary">source commit</dt>
              <dd className="truncate text-text-secondary">{payload.read_at_commit}</dd>
            </div>
            <div className="flex flex-col">
              <dt className="text-text-tertiary">source as-of</dt>
              <dd className="text-text-secondary">
                {payload.facts[0]?.as_of ?? "absent"} — each fact carries its own
              </dd>
            </div>
            <div className="flex flex-col">
              <dt className="text-text-tertiary">transcribed on</dt>
              <dd className="text-text-secondary">{payload.snapshot_extracted_on}</dd>
            </div>
          </dl>
          <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            These facts are a <strong>snapshot transcribed at the commit named above</strong>,
            and the three dates are kept apart on purpose: a fact&rsquo;s own as-of is when the
            source records it became true, and the transcription date is when someone copied
            it. Collapsing them would date every fact to the day of the copy.
          </p>
          <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
            The application performs <strong>no network read</strong> of GitHub, AWS, a provider
            or a broker to refresh them — at runtime or at build time — so they age. A later
            cycle refreshes them by re-reading the tracked sources under its own authorization.
            A historical success carries its as-of time, and{" "}
            <strong>
              current runtime health is never claimed from a past qualification success
            </strong>
            .
          </p>
        </CardBody>
      </Card>
    </>
  );
}
