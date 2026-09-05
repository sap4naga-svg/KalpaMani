"use client";

import {
  Badge,
  Card,
  CardBody,
  CardHeader,
  Label,
  ScrollRegion,
} from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { PageHeader } from "@/components/cockpit/page-header";
import { ProvenanceBadge } from "@/components/cockpit/provenance";
import { useScope } from "@/components/shell/use-scope";
import { useQualificationStatus } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";

/**
 * Project and qualification governance -- area 24.
 *
 * A COMPACT, SOURCE-LINKED READINESS SUMMARY built from REAL facts. Provenance is
 * REPOSITORY_TRACKED and these facts are NEVER relabelled SYNTHETIC.
 *
 * Every fact carries the tracked path and commit it was read at. EACH GATE IS READ
 * INDEPENDENTLY -- no blanket statement over all seven is correct. P1 to P9 render
 * UNEVALUATED. RUN AUTHORIZATION AND ITS DATE GATE RENDER AS TWO SEPARATE FACTS, and
 * PASSING A DATE AUTHORIZES NOTHING.
 *
 * NO private qualification evidence, locator, record, payload, report, execution
 * identifier, object key or digest appears here.
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
        <div className="skeleton-shape h-40 w-full" data-testid="skeleton" />
        <span className="sr-only">Loading</span>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Project & Qualification Governance"
        summary="Real facts, read from tracked repository authority at a recorded commit. Each gate is read on its own; no blanket statement over all seven is correct."
      >
        <div className="flex flex-wrap items-center gap-2">
          <ProvenanceBadge provenance={query.data.provenance} />
          <Badge tone="neutral">PUBLIC_SAFE</Badge>
          <span className="font-mono text-label-s text-text-tertiary">
            read at {payload.read_at_commit.slice(0, 12)}
          </span>
        </div>
      </PageHeader>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <Label>Decision gates</Label>
            <p className="mt-1 text-label-m text-text-secondary">
              Each gate is read on its own. G3 is closed for the Sharadar
              personal-use licence and nothing else.
            </p>
          </CardHeader>
          <CardBody>
            <ScrollRegion label="Decision gates table">
              <table className="w-full min-w-[28rem] border-collapse text-label-m">
                <caption className="sr-only">
                  Decision gates and their scopes
                </caption>
                <thead>
                  <tr className="border-b border-border-subtle text-left">
                    <th
                      scope="col"
                      className="py-1.5 pr-3 font-medium text-text-tertiary"
                    >
                      Gate
                    </th>
                    <th
                      scope="col"
                      className="py-1.5 pr-3 font-medium text-text-tertiary"
                    >
                      State
                    </th>
                    <th
                      scope="col"
                      className="py-1.5 font-medium text-text-tertiary"
                    >
                      Scope
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {payload.gates.map((gate) => (
                    <tr
                      key={gate.gate}
                      className="border-b border-border-subtle last:border-0"
                    >
                      <th
                        scope="row"
                        className="py-2 pr-3 text-left font-mono text-text-primary"
                      >
                        {gate.gate}
                      </th>
                      <td className="py-2 pr-3">
                        <Badge
                          tone={gate.state === "OPEN" ? "warning" : "positive"}
                        >
                          <span aria-hidden="true">
                            {gate.state === "OPEN" ? "◑" : "●"}
                          </span>
                          <span>{gate.state}</span>
                        </Badge>
                      </td>
                      <td className="py-2 text-text-secondary">
                        {humanizeCode(gate.scope.code)}
                        {operator && (
                          <div className="mt-0.5">
                            <SourceLink
                              path={gate.source.path}
                              commit={gate.source.commit}
                            />
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
            <Label>Run authorization and date eligibility</Label>
            <p className="mt-1 text-label-m text-text-secondary">
              Two separate facts.{" "}
              <strong>Passing a date authorizes nothing.</strong>
            </p>
          </CardHeader>
          <CardBody className="space-y-3">
            {payload.run_authorizations.map((entry) => (
              <div
                key={entry.run.code}
                data-testid="run-authorization"
                className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
              >
                <p className="text-numeric-s font-medium text-text-primary">
                  {humanizeCode(entry.run.code)}
                </p>
                <dl className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div>
                    <dt>
                      <Label>Authorization</Label>
                    </dt>
                    <dd className="mt-0.5">
                      <Badge tone="negative">{entry.authorization.code}</Badge>
                    </dd>
                  </div>
                  <div>
                    <dt>
                      <Label>Date eligibility</Label>
                    </dt>
                    <dd className="mt-0.5">
                      {entry.date_gate.availability === "AVAILABLE" ? (
                        <span className="font-mono text-numeric-s text-text-secondary">
                          earliest {String(entry.date_gate.value)}
                        </span>
                      ) : (
                        <AvailabilityBadge
                          state={entry.date_gate.availability}
                          reason={entry.date_gate.reason}
                        />
                      )}
                    </dd>
                  </div>
                </dl>
                {operator && (
                  <div className="mt-2">
                    <SourceLink
                      path={entry.source.path}
                      commit={entry.source.commit}
                    />
                  </div>
                )}
              </div>
            ))}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <Label>Provider qualification tests P1–P9</Label>
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
            <p className="mt-3 text-label-m text-text-tertiary">
              Unevaluated is the only state this payload can carry today. Data
              correctness and quality are <strong>not established</strong>, and
              no provider is selected.
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <Label>Architecture decision records</Label>
          </CardHeader>
          <CardBody>
            <ul className="space-y-2">
              {payload.adr_states.map((entry) => (
                <li
                  key={entry.adr}
                  className="flex flex-wrap items-center gap-2"
                >
                  <span className="font-mono text-numeric-s text-text-primary">
                    {entry.adr}
                  </span>
                  <Badge
                    tone={
                      entry.state.code === "ACCEPTED_IN_FORCE"
                        ? "positive"
                        : "warning"
                    }
                  >
                    {humanizeCode(entry.state.code)}
                  </Badge>
                  {operator && (
                    <SourceLink
                      path={entry.source.path}
                      commit={entry.source.commit}
                    />
                  )}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>

        <Card className="xl:col-span-2">
          <CardHeader>
            <Label>Recorded project facts</Label>
          </CardHeader>
          <CardBody>
            <ScrollRegion label="Recorded project facts table">
              <table className="w-full min-w-[34rem] border-collapse text-label-m">
                <caption className="sr-only">
                  Recorded project facts and their sources
                </caption>
                <thead>
                  <tr className="border-b border-border-subtle text-left">
                    <th
                      scope="col"
                      className="py-1.5 pr-3 font-medium text-text-tertiary"
                    >
                      Subject
                    </th>
                    <th
                      scope="col"
                      className="py-1.5 pr-3 font-medium text-text-tertiary"
                    >
                      State
                    </th>
                    <th
                      scope="col"
                      className="py-1.5 pr-3 font-medium text-text-tertiary"
                    >
                      As of
                    </th>
                    <th
                      scope="col"
                      className="py-1.5 font-medium text-text-tertiary"
                    >
                      Source
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {payload.facts.map((fact) => (
                    <tr
                      key={fact.fact_id}
                      className="border-b border-border-subtle last:border-0"
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
                      <td className="py-2 pr-3 font-mono text-text-tertiary">
                        {fact.as_of}
                      </td>
                      <td className="py-2">
                        <SourceLink
                          path={fact.source.path}
                          commit={fact.source.commit}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollRegion>
            <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-border-subtle pt-3">
              <Badge tone="negative">
                {humanizeCode(payload.phase_state.code)}
              </Badge>
              <Badge tone="negative">
                Live trading {humanizeCode(payload.live_trading.code)}
              </Badge>
            </div>
          </CardBody>
        </Card>
      </div>

      <p className="mt-6 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
        These facts are a{" "}
        <strong>snapshot transcribed at the commit named above</strong>. The
        application performs no network read of GitHub, AWS, a provider or a
        broker to refresh them, so they age; a later cycle refreshes them by
        re-reading the tracked sources. A historical success carries its as-of
        time, and{" "}
        <strong>
          current runtime health is never claimed from a past qualification
          success
        </strong>
        .
      </p>
    </>
  );
}
