import { Badge, Card, CardBody, CardHeader, Label } from "@/components/ui/primitives";
import { PageHeader } from "@/components/cockpit/page-header";

/**
 * The future human control plane -- area 35. INERT.
 *
 * This page renders an EXPLANATION of a future control plane and NOTHING ELSE. There is:
 *
 *   NO control handler          no click handler, and no disabled button whose handler exists
 *   NO mutation route           no route handler, no server action, no API route
 *   NO execution command        nothing here can be triggered, by anyone, in any state
 *
 * A DISABLED BUTTON WHOSE HANDLER EXISTS IS NOT INERT (ui-ux-specification.md section 3),
 * so nothing below is a button at all: each item is static text describing what a
 * separately governed control architecture would need.
 *
 * V1 IS OBSERVATIONAL. No Cockpit endpoint, command, assistant tool, hidden handler,
 * background job or scheduled action may place or cancel an order, change a stop, change
 * risk or capital, activate or promote a strategy, enable leverage, change the provider,
 * execute Run B or an assessment, publish CONTROL, alter production strategy state, or
 * approve or reject a governance release.
 *
 * This is a server component with no client boundary: there is no interactive code here to
 * ship.
 */
const FUTURE_CONTROLS = [
  {
    name: "Kill switch",
    description:
      "A representation only. This is NOT a kill switch, cannot act as one, and must never " +
      "be relied upon as one. The kill switch remains independent of this interface and of " +
      "the AI.",
    needs: "an out-of-band control path with its own authentication, audit and safety design",
  },
  {
    name: "Halt new entries",
    description:
      "A future deterministic safety reduction, owned by the risk engine's own governance.",
    needs: "preapproved deterministic rules in the risk engine, not a dashboard session",
  },
  {
    name: "Strategy promotion",
    description:
      "Promotion into order-producing Paper, and every later stage, requires human " +
      "authorization recorded by the separately governed decision path that owns it.",
    needs: "the authoritative governance decision record, which the Cockpit displays and never originates",
  },
  {
    name: "Risk or capital change",
    description:
      "Capital, risk, leverage and short-exposure increases each require human approval.",
    needs: "a governed change with its own written authorization",
  },
  {
    name: "Governance approval",
    description:
      "READY_FOR_HUMAN_REVIEW is not an approval. The Cockpit displays recorded decisions " +
      "and does not originate authoritative approval records in V1.",
    needs: "the separately governed decision path, so authenticity does not rest on a dashboard session",
  },
] as const;

export default function FutureControlPlanePage() {
  return (
    <>
      <PageHeader
        title="Future Control Plane"
        summary="An inert specification of controls that do not exist. Nothing on this page acts, and no control API route exists anywhere in this application."
      >
        <Badge tone="unavailable" data-testid="inert-marker">
          <span aria-hidden="true">⊘</span>
          <span>INERT — no handler, no route, no action</span>
        </Badge>
      </PageHeader>

      <Card className="mb-5 max-w-3xl border-warning/40">
        <CardBody className="pt-5">
          <p className="text-label-m leading-relaxed text-text-secondary">
            V1 is <strong className="text-text-primary">observational</strong>, and read-only
            is defined by what is <strong className="text-text-primary">absent</strong> rather
            than by what is discouraged. The items below are rendered as text, not as controls:
            there is no button, no handler, no server action and no mutation route behind any
            of them. A control plane needs its own authentication, authorization, audit,
            idempotency and safety architecture, and that is a separate decision that has not
            been made.
          </p>
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {FUTURE_CONTROLS.map((control) => (
          <Card key={control.name} data-testid="inert-control">
            <CardHeader className="flex items-center justify-between gap-2">
              <Label>{control.name}</Label>
              <Badge tone="unavailable">inert</Badge>
            </CardHeader>
            <CardBody className="space-y-2">
              <p className="text-label-m leading-relaxed text-text-secondary">
                {control.description}
              </p>
              <p className="text-label-s text-text-tertiary">
                <span className="uppercase tracking-[0.09em]">Would require: </span>
                {control.needs}
              </p>
            </CardBody>
          </Card>
        ))}
      </div>
    </>
  );
}
