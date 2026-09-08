"use client";

import * as React from "react";

import { Badge, Card, CardBody, Label } from "@/components/ui/primitives";
import { MetricText } from "@/components/cockpit/metric-text";
import { PageHeader } from "@/components/cockpit/page-header";
import { ReadModelPanel } from "@/components/cockpit/read-model-panel";
import {
  ReadOnlyNotice,
  ReasonList,
  ReferenceListPanel,
} from "@/components/cockpit/research";
import { useScope } from "@/components/shell/use-scope";
import type { FeedbackStage } from "@/contracts/research-models";
import { useFeedbackPipeline } from "@/data/client/hooks";
import { humanizeCode } from "@/lib/format";

/**
 * Feedback / Self-Maturation Loop — Area 16.
 *
 * "Make the learning loop visible as a pipeline with states, owners and blockages."
 *
 *   THE COCKPIT READS THIS LOOP AND DOES NOT DRIVE IT   no stage advances from this screen,
 *                                                       and no control exists that could
 *                                                       advance one
 *   EACH STAGE SHOWS WHAT IT AWAITS                     the authorization each transition
 *                                                       requires, as closed codes
 *   THE TENTH STAGE IS A PERSON                         and it is marked as the one stage no
 *                                                       automation may ever take
 *   NAVIGATION FOLLOWS AN ITEM, NEVER MOVES ONE         a stage's item references open the
 *                                                       queue entry; they do not promote it
 */

export default function Page() {
  const { scope } = useScope();
  const operator = scope.mode === "operator";
  const pipeline = useFeedbackPipeline(scope);
  const payload = pipeline.data?.payload;

  return (
    <>
      <PageHeader
        title="Feedback / Self-Maturation Loop"
        summary="The ten recorded stages, what each consumes and produces, who owns it, how many items sit at it, how many are blocked, and the authorization each transition is waiting on."
        pageState={payload === undefined ? "PARTIAL" : "COMPLETE"}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Area 16</Badge>
          <Badge tone="unavailable">Learning engine: NOT IMPLEMENTED</Badge>
        </div>
      </PageHeader>

      <div className="space-y-4">
        <ReadOnlyNotice
          subject="a recorded pipeline snapshot"
          actions={["advance", "promote", "release", "retry", "unblock"]}
        />

        <Card data-testid="loop-boundary">
          <CardBody className="space-y-2 pt-4">
            <Label>Writes and reads are different systems</Label>
            <p className="max-w-3xl text-label-m leading-relaxed text-text-secondary">
              <strong>The learning engine writes.</strong> It consumes journal and attribution
              records and produces queue items, registrations, Challenger versions, run
              results, shadow evidence and packets. <strong>It does not exist.</strong>
            </p>
            <p className="max-w-3xl text-label-m leading-relaxed text-text-secondary">
              <strong>The Cockpit reads.</strong> It displays projections of all of the above.{" "}
              <strong>It writes nothing, advances no stage and originates no approval</strong> —
              a Cockpit that could advance a stage would be a control plane, and a control plane
              needs authentication, authorization, audit, idempotency and safety architecture
              this application explicitly does not have.
            </p>
          </CardBody>
        </Card>

        <ReadModelPanel
          title="The ten-stage loop"
          description="Everything before the tenth stage may eventually run without a human, within separately approved bounds. The tenth may not, ever."
          envelope={pipeline.data}
          dependency="the learning engine — no learning engine exists"
          operator={operator}
          testId="pipeline"
        >
          {(loaded) => (
            <div className="space-y-3">
              <ol className="space-y-2" data-testid="pipeline-stages">
                {loaded.stages.map((stage, index) => (
                  <StageCard
                    key={stage.stage.code}
                    stage={stage}
                    ordinal={index + 1}
                    scope={scope}
                    operator={operator}
                  />
                ))}
              </ol>
              <p
                className="max-w-3xl text-label-s leading-relaxed text-text-tertiary"
                data-testid="human-only-note"
              >
                <strong className="text-text-secondary">
                  The human-only stage is {humanizeCode(loaded.human_only_stage.code)}.
                </strong>{" "}
                Self-maturing is not self-governing: automation may prepare, evidence and
                recommend a release, and it may take none. Nothing on this screen advances any
                stage, and following an item never moves it.
              </p>
            </div>
          )}
        </ReadModelPanel>
      </div>
    </>
  );
}

function StageCard({
  stage,
  ordinal,
  scope,
  operator,
}: {
  stage: FeedbackStage;
  ordinal: number;
  scope: ReturnType<typeof useScope>["scope"];
  operator: boolean;
}) {
  return (
    <li
      className="rounded-sm border border-border-subtle bg-surface-sunken p-3"
      data-stage={stage.stage.code}
      data-automatable={String(stage.automatable)}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-label-s text-text-tertiary">
            {String(ordinal).padStart(2, "0")}
          </span>
          <h3 className="text-label-m font-semibold text-text-primary">
            {humanizeCode(stage.stage.code)}
          </h3>
          {!stage.automatable && (
            <Badge tone="warning" data-testid="human-only-stage">
              <span aria-hidden="true">⚑</span>
              <span>Human only — never automatable</span>
            </Badge>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-label-s text-text-tertiary">
            <MetricText metric={stage.item_count} neutral /> at this stage
          </span>
          <span className="text-label-s text-text-tertiary">
            <MetricText metric={stage.blocked_count} neutral /> blocked
          </span>
        </div>
      </div>

      <p className="mt-1 text-label-s text-text-tertiary">
        Owner: <strong className="text-text-secondary">{humanizeCode(stage.owner.code)}</strong>
      </p>

      <div className="mt-2 grid gap-3 lg:grid-cols-2">
        <div>
          <Label>Consumes</Label>
          <div className="mt-1">
            <ReasonList codes={stage.inputs} empty="This stage records no input." />
          </div>
        </div>
        <div>
          <Label>Produces</Label>
          <div className="mt-1">
            <ReasonList codes={stage.outputs} empty="This stage records no output." />
          </div>
        </div>
      </div>

      <div className="mt-2">
        <Label>Waiting on</Label>
        <div className="mt-1">
          <ReasonList
            codes={stage.awaiting_authorizations}
            tone="unavailable"
            empty="This stage records no outstanding authorization."
          />
        </div>
      </div>

      <details className="mt-2">
        <summary className="cursor-pointer text-label-s text-text-secondary">
          Refusal reasons, pins and the items at this stage
        </summary>
        <div className="mt-2 space-y-3">
          <div>
            <Label>Refusal reasons</Label>
            <div className="mt-1">
              <ReasonList
                codes={stage.refusal_reasons}
                tone="negative"
                empty="This stage records no refusal reason."
              />
            </div>
          </div>
          <div>
            <Label>Version pins</Label>
            <div className="mt-1">
              <ReasonList codes={stage.pins} empty="This stage records no pin." />
            </div>
          </div>
          <div>
            <ReferenceListPanel
              list={stage.item_refs}
              label="Items reachable at this stage"
              scope={scope}
              empty="No queue-item reference is reachable at this stage."
            />
            <p className="mt-1 max-w-3xl text-label-s leading-relaxed text-text-tertiary">
              This list enumerates{" "}
              <strong className="text-text-secondary">
                {humanizeCode(stage.item_reference_scope.code)}
              </strong>
              , so an empty list is not an empty stage — the count above is the stage&apos;s own
              population.
            </p>
          </div>
          {operator && (
            <p className="font-mono text-label-s text-text-tertiary">
              stage={stage.stage.code} · automatable={String(stage.automatable)}
            </p>
          )}
        </div>
      </details>
    </li>
  );
}
