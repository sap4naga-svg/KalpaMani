"use client";

import Link from "next/link";

import { Card, CardBody, Label } from "@/components/ui/primitives";
import { AvailabilityBadge } from "@/components/cockpit/availability";
import { PageHeader } from "@/components/cockpit/page-header";
import { useScope } from "@/components/shell/use-scope";
import { ROUTES_BY_HREF } from "@/nav/registry";
import { withScope } from "@/lib/scope";

/**
 * The shared "not yet implemented" page.
 *
 * ONE component serves every later-cycle route, so there are no dozens of duplicate
 * placeholder components. A registered navigation entry never leads to an accidental 404,
 * and this page NEVER CLAIMS THAT A PLACEHOLDER ROUTE IMPLEMENTS ITS PRODUCT AREA -- it
 * names the area, its purpose, its producer or dependency, and its intended cycle.
 */
export function NotImplementedPage({ href }: { href: string }) {
  const { scope } = useScope();
  const route = ROUTES_BY_HREF.get(href);

  if (route === undefined) {
    return (
      <PageHeader
        title="Unknown area"
        summary="This route is not in the navigation registry."
      />
    );
  }

  const inert = route.status === "inert";

  return (
    <>
      <PageHeader
        title={route.label}
        summary={route.purpose}
      >
        <AvailabilityBadge
          state={inert ? "NOT_AUTHORIZED" : "NOT_IMPLEMENTED"}
          reason={inert ? "PRODUCER_NOT_AUTHORIZED" : "PRODUCER_NOT_IMPLEMENTED"}
        />
      </PageHeader>

      <Card className="max-w-3xl">
        <CardBody className="space-y-4 pt-5">
          <dl className="space-y-3">
            <div>
              <dt>
                <Label>Product area</Label>
              </dt>
              <dd className="mt-0.5 font-mono text-numeric-s text-text-primary">
                {route.areas.map((area) => `Area ${area}`).join(" · ")}
              </dd>
            </div>
            <div>
              <dt>
                <Label>Producer or dependency</Label>
              </dt>
              <dd className="mt-0.5 text-label-m text-text-secondary">{route.dependency}</dd>
            </div>
            <div>
              <dt>
                <Label>Intended cycle</Label>
              </dt>
              <dd className="mt-0.5 font-mono text-numeric-s text-text-primary">
                {route.cycle}
              </dd>
            </div>
          </dl>

          <p className="border-t border-border-subtle pt-4 text-label-m leading-relaxed text-text-tertiary">
            This route is registered and reachable so navigation is complete. It is{" "}
            <strong className="text-text-secondary">not an implementation</strong> of its
            product area, and the C3 foundation makes no claim that it is. The implementing
            cycle is a separate written authorization.
          </p>

          <Link
            href={withScope("/", scope)}
            className="inline-block text-label-m text-accent underline underline-offset-2"
          >
            Back to the Executive Overview
          </Link>
        </CardBody>
      </Card>
    </>
  );
}
