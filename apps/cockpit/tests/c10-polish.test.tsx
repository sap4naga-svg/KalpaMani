import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PanelSection, ReadModelPanel } from "@/components/cockpit/read-model-panel";
import { Label } from "@/components/ui/primitives";
import { ClockProvider } from "@/components/shell/clock-provider";
import { buildEnvelope } from "@/data/fixtures/envelopes";
import { fixedClock } from "@/lib/clock";
import { DEEP_DESTINATIONS, NAV_ROUTES, resolveRoute } from "@/nav/registry";
import type { EnvelopeOf } from "@/contracts/envelope";

/**
 * The C10 polish corrections, at the boundaries that own the rules they restore.
 *
 * Each test here failed on the tree this cycle started from. They are written against the
 * COMPONENT AND THE REGISTRY rather than against a rendered page, because that is where the
 * rule lives: a panel title is a heading because `ReadModelPanel` makes it one, and a detail
 * screen has a name because the registry gives it one.
 */

const AS_OF = "2026-09-09T12:00:00.000Z";
const ORIGIN_MS = Date.parse(AS_OF);
const clock = fixedClock(AS_OF);

interface Payload {
  readonly note: string;
}

/** One envelope, populated or not, so both branches of the panel are exercised. */
function envelopeFor(payload: Payload | undefined): EnvelopeOf<Payload> {
  return buildEnvelope<Payload>({
    schemaVersion: "v1",
    entityId: "c10-polish-probe",
    availability: payload === undefined ? "NOT_IMPLEMENTED" : "AVAILABLE",
    availabilityReason: payload === undefined ? "PRODUCER_NOT_IMPLEMENTED" : "NONE",
    provenance: "SYNTHETIC",
    classification: "PUBLIC_SAFE",
    environment: "RESEARCH",
    accessScope: "cockpit.read",
    inputs: [
      {
        id: "probe",
        required: true,
        ageAtOriginSeconds: 60,
        contractMaxAgeSeconds: 86_400,
      },
    ],
    payload,
    originMs: ORIGIN_MS,
    evaluationMs: ORIGIN_MS + 1_000,
  });
}

function renderPanel(payload: Payload | undefined) {
  return render(
    <ClockProvider clock={clock}>
      <ReadModelPanel<Payload>
        title="Probe read model"
        envelope={envelopeFor(payload)}
        dependency="a producing subsystem that does not exist"
      >
        {(resolved) => (
          <PanelSection title="A named section">
            <p>{resolved.note}</p>
          </PanelSection>
        )}
      </ReadModelPanel>
    </ClockProvider>,
  );
}

describe("the panel heading structure (ui-ux-specification.md section 11)", () => {
  it("renders a panel title as a level-two heading when the panel has a payload", () => {
    renderPanel({ note: "a rendered payload" });
    const heading = screen.getByRole("heading", { name: "Probe read model" });
    expect(heading.tagName).toBe("H2");
  });

  it("renders a panel title as a level-two heading when the payload is absent", () => {
    /*
     * THE UNAVAILABLE BRANCH IS A DIFFERENT BRANCH. A panel that only titled itself when a
     * read resolved would leave every unavailable screen — which is most of this Cockpit —
     * with no heading structure at all.
     */
    renderPanel(undefined);
    const heading = screen.getByRole("heading", { name: "Probe read model" });
    expect(heading.tagName).toBe("H2");
    expect(screen.getByTestId("unavailable-body")).toBeTruthy();
  });

  it("puts a panel section one level below its panel, so no level is skipped", () => {
    renderPanel({ note: "a rendered payload" });
    const levels = Array.from(document.querySelectorAll("h1, h2, h3, h4, h5, h6")).map(
      (element) => Number(element.tagName.slice(1)),
    );
    expect(levels).toEqual([2, 3]);
    const skipped = levels.filter(
      (level, index) => index > 0 && level - levels[index - 1] > 1,
    );
    expect(skipped).toEqual([]);
  });

  it("keeps the label's appearance identical whichever element it renders", () => {
    const { container: asSpan, unmount } = render(<Label>Same treatment</Label>);
    const spanClass = asSpan.firstElementChild?.className ?? "";
    expect(asSpan.firstElementChild?.tagName).toBe("SPAN");
    unmount();

    const { container: asHeading } = render(<Label as="h2">Same treatment</Label>);
    expect(asHeading.firstElementChild?.tagName).toBe("H2");
    expect(asHeading.firstElementChild?.className).toBe(spanClass);
    expect(spanClass.length).toBeGreaterThan(0);
  });
});

describe("route resolution (the sidebar's sense of place on a drill-down screen)", () => {
  it("resolves a registered route to itself", () => {
    const resolved = resolveRoute("/portfolio/trades");
    expect(resolved).not.toBeNull();
    expect(resolved!.label).toBe("Trade History");
    expect(resolved!.owner?.href).toBe("/portfolio/trades");
  });

  it("resolves a deep destination to its own name and its owning sidebar route", () => {
    expect(DEEP_DESTINATIONS.length).toBeGreaterThan(0);
    for (const destination of DEEP_DESTINATIONS) {
      const probe = destination.route.replace(/\[[^\]]+\]/, "probe-id");
      const resolved = resolveRoute(probe);
      expect(resolved, destination.route).not.toBeNull();
      /* Its OWN name: a trade's detail screen is not the ledger it was opened from. */
      expect(resolved!.label).toBe(destination.label);
      expect(resolved!.owner?.href).toBe(destination.owner);
      expect(resolved!.label).not.toBe(resolved!.owner?.label);
    }
  });

  it("resolves an unregistered path to null rather than to a nearest match", () => {
    /*
     * THE NEGATIVE CONTROL. A prefix that is not itself a route, a near-miss of a deep
     * destination, and a path this application does not serve each resolve to NOTHING — a
     * "nearest match" here would highlight a sidebar entry for an area the reader is not in.
     */
    for (const path of ["/portfolio", "/signals", "/portfolio/trade", "/nowhere", "/attentionx"]) {
      expect(resolveRoute(path), path).toBeNull();
    }
  });

  it("gives every registered route a name no other route shares", () => {
    /* A sidebar whose entries share a name cannot say which one is current. */
    const labels = NAV_ROUTES.map((route) => route.label);
    expect(new Set(labels).size).toBe(labels.length);
    for (const route of NAV_ROUTES) {
      const resolved = resolveRoute(route.href);
      expect(resolved, route.href).not.toBeNull();
      expect(resolved!.label).toBe(route.label);
    }
  });
});
