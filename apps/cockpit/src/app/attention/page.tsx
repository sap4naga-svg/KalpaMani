"use client";

import Link from "next/link";

import { Badge, Card, CardBody, CardHeader, Label } from "@/components/ui/primitives";
import { AttentionPanel } from "@/components/cockpit/attention";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { PageHeader } from "@/components/cockpit/page-header";
import { useScope } from "@/components/shell/use-scope";
import { useAttention } from "@/data/client/hooks";
import { withScope } from "@/lib/scope";

/**
 * Attention Required — product area 28.
 *
 * THE SAME READ MODEL AND THE SAME RANKING as the executive summary. This page adds filters
 * and shows every item; it does not re-derive the list, so the count on the landing page and
 * the list here cannot disagree.
 *
 * NOTHING HERE ACTS. There is no acknowledge, no dismiss, no resolve, no snooze and no
 * assign — those verbs change state in systems this application only reads, and a control
 * that appeared to work while doing nothing would be worse than its absence. A recommended
 * action names a permitted GOVERNANCE action for a person to take elsewhere.
 */
export default function AttentionPage() {
  const { scope } = useScope();
  const attention = useAttention(scope);
  const operator = scope.mode === "operator";

  return (
    <>
      <PageHeader
        title="Attention Required"
        summary="Every item shows what happened, why it matters, its impact, its evidence and a permitted governance action. Ranked by materiality then severity, and deduplicated against the alert feed."
        pageState={
          attention.data !== undefined && attention.data.availability !== "AVAILABLE"
            ? "PARTIAL"
            : "COMPLETE"
        }
      >
        <p className="max-w-3xl text-label-s leading-relaxed text-text-tertiary">
          An item missing any of those five things is <strong>not rendered</strong>, and the
          panel states how many it withheld. A shorter list is never presented as a quieter
          system.
        </p>
      </PageHeader>

      {attention.data === undefined ? (
        <Card>
          <CardHeader>
            <Label as="h2">Attention required</Label>
          </CardHeader>
          <CardBody>
            <div className="skeleton-shape h-40 w-full" data-testid="skeleton" />
            <span className="sr-only">Loading the attention list</span>
          </CardBody>
        </Card>
      ) : (
        <AttentionPanel
          envelope={attention.data}
          scope={scope}
          operator={operator}
          withFilters
        />
      )}

      <Card className="mt-6">
        <CardHeader>
          <Label as="h2">What this page cannot do</Label>
        </CardHeader>
        <CardBody className="space-y-3">
          <div className="flex flex-wrap gap-2">
            {["ACKNOWLEDGE", "DISMISS", "RESOLVE", "SNOOZE", "ASSIGN", "SUPPRESS"].map(
              (verb) => (
                <Badge key={verb} tone="unavailable">
                  <span aria-hidden="true">⊘</span>
                  <span>{verb}</span>
                </Badge>
              ),
            )}
          </div>
          <p className="max-w-3xl text-label-m leading-relaxed text-text-tertiary">
            None of these exists here, and none is a disabled button waiting to be enabled:
            there is no handler, no control route and no mutation of any kind in this
            application. Each would change state in a system the Cockpit only reads, and
            acknowledging an alert that no producer knows was acknowledged is a record of
            nothing.
          </p>
          <p className="max-w-3xl text-label-m leading-relaxed text-text-tertiary">
            The alert feed these items are deduplicated against is{" "}
            <Link
              href={withScope("/system/alerts", scope)}
              className="text-accent underline underline-offset-2"
            >
              System Alerts
            </Link>
            , which arrives with the cycle that produces it.{" "}
            <AvailabilityBadge state="NOT_IMPLEMENTED" reason="PRODUCER_NOT_IMPLEMENTED" />
          </p>
        </CardBody>
      </Card>
    </>
  );
}
