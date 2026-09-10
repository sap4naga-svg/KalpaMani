import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as React from "react";
import { describe, expect, it, vi } from "vitest";

import {
  SUMMARY_DISCLOSURE_LABEL,
  SummaryDisclosure,
} from "@/components/cockpit/mobile-summary";
import { WhatChangedPanel } from "@/components/cockpit/what-changed";
import { ClockProvider } from "@/components/shell/clock-provider";
import { Providers } from "@/components/shell/providers";
import { AVAILABILITY_STATES, DATA_PROVENANCES } from "@/contracts/vocabularies";
import type { EnvelopeOf } from "@/contracts/envelope";
import { createDefaultReadClient } from "@/data/client/default-client";
import type { ReadClient, WhatChangedPayload } from "@/data/client/read-client";
import { fixedClock } from "@/lib/clock";
import {
  SUMMARY_BREAKPOINT_PX,
  SUMMARY_MEDIA_QUERY,
  disclosureAvailabilityStates,
  disclosureProvenances,
  pendingWidget,
  performancePresentedStates,
  settledWidget,
  whatChangedPresentedStates,
} from "@/lib/mobile-summary";
import { CHANGE_VARIANTS, DEFAULT_SCOPE, type ChangeVariant, type ViewScope } from "@/lib/scope";
import ExecutiveOverviewPage from "@/app/page";

/**
 * Decision M (ADR-0033 §2), at the boundaries that own its rules.
 *
 * The browser suite establishes M8 against the rendered page at 390 × 844. These tests hold
 * the two rules a control's badges obey to the contract's vocabulary, hold the derivation
 * of a deferred widget's presented state to the widget's own rendering, and drive the
 * disclosure component and the page across the breakpoint with a controllable media query
 * and a controllable read client — which is how M8.9's "one widget pending, one settled"
 * case is constructed without touching the synthetic book.
 */

// --------------------------------------------------------------- a controllable breakpoint

/**
 * `matchMedia` does not exist in jsdom. This one answers the breakpoint query, and only
 * that query, from a value a test can move — with a `change` event, as a real viewport
 * resize would fire one.
 */
let viewportWidth = 1440;
const mediaListeners = new Set<(event: MediaQueryListEvent) => void>();

function matchesNow(): boolean {
  return viewportWidth < SUMMARY_BREAKPOINT_PX;
}

const mediaQueryList = {
  get matches() {
    return matchesNow();
  },
  media: SUMMARY_MEDIA_QUERY,
  onchange: null,
  addEventListener(_type: "change", listener: (event: MediaQueryListEvent) => void) {
    mediaListeners.add(listener);
  },
  removeEventListener(_type: "change", listener: (event: MediaQueryListEvent) => void) {
    mediaListeners.delete(listener);
  },
  addListener() {},
  removeListener() {},
  dispatchEvent() {
    return true;
  },
};

Object.defineProperty(window, "matchMedia", {
  configurable: true,
  writable: true,
  value: (query: string) => {
    if (query !== SUMMARY_MEDIA_QUERY) {
      throw new Error(`unexpected media query in this test file: ${query}`);
    }
    return mediaQueryList as unknown as MediaQueryList;
  },
});

/** Resizes the "viewport" across the breakpoint, the way a rotation or a window drag does. */
function resizeTo(width: number): void {
  const before = matchesNow();
  viewportWidth = width;
  if (before === matchesNow()) return;
  act(() => {
    for (const listener of mediaListeners) {
      listener({ matches: matchesNow(), media: SUMMARY_MEDIA_QUERY } as MediaQueryListEvent);
    }
  });
}

// --------------------------------------------------------------- the navigation the page reads

let search = "scenario=demo&mode=executive";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
  usePathname: () => "/",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), prefetch: vi.fn() }),
}));

// --------------------------------------------------------------- fixtures

const ORIGIN = Date.parse("2026-09-20T12:00:00.000Z");
const clock = fixedClock(ORIGIN);

const demoScope = (over: Partial<ViewScope> = {}): ViewScope => ({
  ...DEFAULT_SCOPE,
  scenario: "demo",
  ...over,
});

// ================================================================= the badge rules

describe("the disclosure badge rule (M5) — one badge per distinct settled non-AVAILABLE state", () => {
  it("orders the badges by the contract's vocabulary, whatever order the widgets settle in", () => {
    const widgets = [
      settledWidget("ERROR"),
      settledWidget("NOT_YET_AVAILABLE"),
      settledWidget("STALE"),
      settledWidget("NOT_IMPLEMENTED"),
    ];
    const states = disclosureAvailabilityStates(widgets);
    expect(states).toEqual(["NOT_YET_AVAILABLE", "NOT_IMPLEMENTED", "STALE", "ERROR"]);
    // The order is the vocabulary's own, and nothing else: the same relative order it declares.
    const positions = states.map((state) => AVAILABILITY_STATES.indexOf(state));
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
  });

  it("carries no badge for AVAILABLE and reports a repeated state once", () => {
    expect(
      disclosureAvailabilityStates([
        settledWidget("AVAILABLE"),
        settledWidget("NOT_IMPLEMENTED"),
        settledWidget(["NOT_IMPLEMENTED", "AVAILABLE"]),
      ]),
    ).toEqual(["NOT_IMPLEMENTED"]);
    expect(disclosureAvailabilityStates([settledWidget("AVAILABLE")])).toEqual([]);
  });

  it("lets a pending read contribute nothing and suppress nothing beside it (M6)", () => {
    expect(
      disclosureAvailabilityStates([pendingWidget(), settledWidget("NOT_YET_AVAILABLE")]),
    ).toEqual(["NOT_YET_AVAILABLE"]);
    expect(disclosureAvailabilityStates([pendingWidget(), pendingWidget()])).toEqual([]);
  });

  it("never omits ERROR, never outranks it and never merges it into another state", () => {
    const states = disclosureAvailabilityStates([
      settledWidget("PARTIAL"),
      settledWidget("ERROR"),
      settledWidget("STALE"),
    ]);
    expect(states).toContain("ERROR");
    expect(states).toHaveLength(3);
  });

  it("invents no precedence: every non-AVAILABLE state survives beside every other", () => {
    const every = AVAILABILITY_STATES.map((state) => settledWidget(state));
    expect(disclosureAvailabilityStates(every)).toEqual(
      AVAILABILITY_STATES.filter((state) => state !== "AVAILABLE"),
    );
  });
});

describe("the disclosure provenance rule (M5, §5) — every distinct provenance, never one chosen", () => {
  it("carries both badges for a section mixing a tracked fact with synthetic tiles", () => {
    expect(
      disclosureProvenances([
        settledWidget("AVAILABLE", "SYNTHETIC"),
        settledWidget("AVAILABLE", "REPOSITORY_TRACKED"),
        settledWidget("AVAILABLE", "SYNTHETIC"),
      ]),
    ).toEqual(["SYNTHETIC", "REPOSITORY_TRACKED"]);
  });

  it("orders them by the vocabulary and keeps a pending tracked tile's known provenance", () => {
    const provenances = disclosureProvenances([
      settledWidget("NOT_IMPLEMENTED"),
      pendingWidget("REPOSITORY_TRACKED"),
      settledWidget("AVAILABLE", "SYNTHETIC"),
    ]);
    expect(provenances).toEqual(["SYNTHETIC", "REPOSITORY_TRACKED"]);
    const positions = provenances.map((source) => DATA_PROVENANCES.indexOf(source));
    expect(positions).toEqual([...positions].sort((a, b) => a - b));
  });

  it("carries nothing for a widget that displays no provenance — an absence carries none", () => {
    expect(disclosureProvenances([settledWidget("NOT_IMPLEMENTED"), pendingWidget()])).toEqual(
      [],
    );
  });
});

// ================================================================= presented states, held to the panel

/** The badges the rendered What Changed panel itself shows, as states. */
function renderedPanelStates(envelope: EnvelopeOf<WhatChangedPayload>): string[] {
  const { container, unmount } = render(
    <ClockProvider clock={clock}>
      <WhatChangedPanel envelope={envelope} scope={demoScope()} operator={false} />
    </ClockProvider>,
  );
  const badges = Array.from(container.querySelectorAll("[data-availability]"))
    // An endpoint's own badge inside a row is that endpoint's, not the panel's.
    .filter((element) => element.closest("[data-testid='what-changed-item']") === null)
    .map((element) => element.getAttribute("data-availability") ?? "");
  unmount();
  return Array.from(new Set(badges));
}

describe("what a deferred What Changed panel presents, held to what it renders", () => {
  const variants: readonly ChangeVariant[] = CHANGE_VARIANTS.filter((v) => v !== "auto");

  it.each(variants)("agrees with the rendered panel for the %s variant", async (variant) => {
    const envelope = await createDefaultReadClient(clock).whatChanged(
      demoScope({ changes: variant }),
    );
    const presented = whatChangedPresentedStates(envelope).filter((s) => s !== "AVAILABLE");
    const rendered = renderedPanelStates(envelope).filter((s) => s !== "AVAILABLE");
    expect(new Set(presented)).toEqual(new Set(rendered));
  });

  it("presents the envelope's own state, and no delta, when there is no payload", async () => {
    const envelope = await createDefaultReadClient(clock).whatChanged({
      ...DEFAULT_SCOPE,
      scenario: "project",
    });
    expect(envelope.payload).toBeUndefined();
    expect(whatChangedPresentedStates(envelope)).toEqual([envelope.availability]);
    expect(envelope.availability).not.toBe("AVAILABLE");
  });
});

describe("what a deferred performance overview presents", () => {
  it("presents AVAILABLE alone over a complete window and adds PARTIAL over a gapped one", async () => {
    const client = createDefaultReadClient(clock);
    const complete = await client.performanceSeries(demoScope({ period: "3M" }));
    expect(performancePresentedStates(complete)).toEqual(["AVAILABLE"]);
    const gapped = await client.performanceSeries(demoScope({ period: "ALL" }));
    expect(performancePresentedStates(gapped)).toEqual(["AVAILABLE", "PARTIAL"]);
  });

  it("presents the envelope's state when no series exists", async () => {
    const envelope = await createDefaultReadClient(clock).performanceSeries({
      ...DEFAULT_SCOPE,
      scenario: "project",
    });
    expect(envelope.payload).toBeUndefined();
    expect(performancePresentedStates(envelope)).toEqual([envelope.availability]);
  });
});

// ================================================================= the component, across the breakpoint

function Probe({ availability = [], provenance = [] }: {
  availability?: Parameters<typeof SummaryDisclosure>[0]["availability"];
  provenance?: Parameters<typeof SummaryDisclosure>[0]["provenance"];
}) {
  return (
    <section aria-labelledby="probe-heading">
      <SummaryDisclosure
        id="supporting-context"
        headingId="probe-heading"
        fullWidthHeading={{ className: "full-heading" }}
        availability={availability}
        provenance={provenance}
      >
        <p data-testid="probe-content">deferred content</p>
        <button type="button">a control inside</button>
      </SummaryDisclosure>
    </section>
  );
}

describe("the disclosure component (M5, M7)", () => {
  it("renders no control above the breakpoint, and the section exactly as before", () => {
    resizeTo(1440);
    render(<Probe />);
    const control = screen.getByTestId("disclosure-supporting-context-control");
    expect(control).toHaveAttribute("hidden");
    expect(screen.getByTestId("disclosure-supporting-context")).toHaveAttribute("open");
    const heading = screen.getByRole("heading", { level: 2, name: "Supporting context" });
    expect(heading).toHaveClass("full-heading");
    expect(control.contains(heading)).toBe(false);
    expect(screen.getByTestId("probe-content")).toBeVisible();
    // The hidden control is EMPTY: no duplicate label or badge text sits in the document.
    expect(control.textContent).toBe("");
    expect(screen.getAllByText("Supporting context")).toHaveLength(1);
  });

  it("renders the control collapsed by default below the breakpoint, with the h2 inside it", () => {
    resizeTo(390);
    render(<Probe />);
    const details = screen.getByTestId("disclosure-supporting-context");
    const control = screen.getByTestId("disclosure-supporting-context-control");
    expect(details).not.toHaveAttribute("open");
    expect(control).not.toHaveAttribute("hidden");
    const heading = screen.getByRole("heading", { level: 2, name: "Supporting context" });
    expect(control.contains(heading)).toBe(true);
    expect(screen.getByTestId("probe-content")).not.toBeVisible();
  });

  it("toggles on activation, keeps focus on the control, and reveals the same content", async () => {
    /*
     * jsdom implements the summary's click activation but neither its keyboard activation nor
     * its `toggle` event; the browser suite (M8.5) proves Enter, Space and focus in a real
     * browser. Here the event the browser would fire is dispatched by hand, so the component's
     * own handler runs against a real `open` change.
     */
    resizeTo(390);
    const user = userEvent.setup();
    render(<Probe />);
    const details = screen.getByTestId("disclosure-supporting-context");
    const control = screen.getByTestId("disclosure-supporting-context-control");
    const content = screen.getByTestId("probe-content");

    control.focus();
    await user.click(control);
    act(() => {
      details.dispatchEvent(new Event("toggle"));
    });
    expect(details).toHaveAttribute("open");
    expect(document.activeElement).toBe(control);
    expect(content).toBeVisible();
    // The revealed node is the node that was there all along.
    expect(screen.getByTestId("probe-content")).toBe(content);

    await user.click(control);
    act(() => {
      details.dispatchEvent(new Event("toggle"));
    });
    expect(details).not.toHaveAttribute("open");
    expect(document.activeElement).toBe(control);
    expect(content).not.toBeVisible();
  });

  it("carries every badge it is given, in the order given, and no value", () => {
    resizeTo(390);
    render(
      <Probe
        availability={["NOT_YET_AVAILABLE", "NOT_IMPLEMENTED"]}
        provenance={["SYNTHETIC", "REPOSITORY_TRACKED"]}
      />,
    );
    const control = screen.getByTestId("disclosure-supporting-context-control");
    const availability = Array.from(control.querySelectorAll("[data-availability]")).map((e) =>
      e.getAttribute("data-availability"),
    );
    expect(availability).toEqual(["NOT_YET_AVAILABLE", "NOT_IMPLEMENTED"]);
    const provenance = Array.from(control.querySelectorAll("[data-provenance]")).map((e) =>
      e.getAttribute("data-provenance"),
    );
    expect(provenance).toEqual(["SYNTHETIC", "REPOSITORY_TRACKED"]);
    expect(control.textContent).not.toMatch(/[0-9$%]/);
    expect(control.querySelector("[data-testid='skeleton']")).toBeNull();
  });

  it("keeps the same DOM node and the reader's expansion across a crossing in each direction", () => {
    resizeTo(390);
    render(<Probe />);
    const details = screen.getByTestId("disclosure-supporting-context");
    const content = screen.getByTestId("probe-content");

    // The reader expands it.
    act(() => {
      (details as HTMLDetailsElement).open = true;
      details.dispatchEvent(new Event("toggle"));
    });
    expect(details).toHaveAttribute("open");

    // Upward: no control, everything visible, the same node.
    resizeTo(1024);
    expect(screen.getByTestId("disclosure-supporting-context-control")).toHaveAttribute("hidden");
    expect(screen.getByTestId("probe-content")).toBe(content);
    expect(content).toBeVisible();

    // Downward again: the reader's expansion survives, on the same node.
    resizeTo(390);
    expect(screen.getByTestId("disclosure-supporting-context-control")).not.toHaveAttribute(
      "hidden",
    );
    expect(details).toHaveAttribute("open");
    expect(screen.getByTestId("probe-content")).toBe(content);
  });

  it("does not record a crossing's own toggle as the reader expanding the section", () => {
    resizeTo(390);
    render(<Probe />);
    const details = screen.getByTestId("disclosure-supporting-context");
    expect(details).not.toHaveAttribute("open");

    resizeTo(1024);
    // The browser fires `toggle` when the crossing opened the element; it is not the reader.
    act(() => {
      details.dispatchEvent(new Event("toggle"));
    });
    resizeTo(390);
    expect(details).not.toHaveAttribute("open");
  });

  it("never collapses a section that holds focus when the viewport crosses downward", () => {
    resizeTo(1024);
    render(<Probe />);
    const details = screen.getByTestId("disclosure-supporting-context");
    const inside = screen.getByRole("button", { name: "a control inside" });
    act(() => {
      inside.focus();
    });
    expect(document.activeElement).toBe(inside);

    resizeTo(390);
    expect(details).toHaveAttribute("open");
    expect(document.activeElement).toBe(inside);
    expect(inside).toBeVisible();
  });

  it("labels each disclosure with its fixed text, and none of the labels carries a digit", () => {
    for (const label of Object.values(SUMMARY_DISCLOSURE_LABEL)) {
      expect(label).not.toMatch(/[0-9]/);
    }
    expect(SUMMARY_DISCLOSURE_LABEL["what-changed"]).toBe("What changed — details");
  });
});

// ================================================================= the page, with a controlled read client

/**
 * A read client whose named reads never settle, and which otherwise answers exactly as the
 * default one does. This is how a widget is left pending without inventing data: the read
 * is the fixture read, merely not yet answered.
 */
function clientHolding(...held: (keyof ReadClient)[]): ReadClient {
  const base = createDefaultReadClient(clock);
  return new Proxy(base, {
    get(target, property, receiver) {
      if (held.includes(property as keyof ReadClient)) {
        return () => new Promise<never>(() => {});
      }
      const value = Reflect.get(target, property, receiver) as unknown;
      return typeof value === "function" ? (value as (...a: unknown[]) => unknown).bind(target) : value;
    },
  });
}

function renderPage(client: ReadClient, query = "scenario=demo&mode=executive") {
  search = query;
  return render(
    <Providers clock={clock} readClient={client}>
      <ExecutiveOverviewPage />
    </Providers>,
  );
}

describe("the Executive Overview below the breakpoint, with one read held pending (M8.9)", () => {
  it("carries the settled states' badges and no skeleton while the gates read is pending", async () => {
    resizeTo(390);
    renderPage(clientHolding("qualificationStatus"));
    const control = await screen.findByTestId("disclosure-supporting-context-control");
    // The overview read settled: the demo fixture degrades the permitted-risk tile and reports
    // both last-run records as absent, and the control carries each distinct state once.
    const badges = () =>
      Array.from(control.querySelectorAll("[data-availability]")).map((e) =>
        e.getAttribute("data-availability"),
      );
    await vi.waitFor(() => expect(badges()).toEqual(["NOT_YET_AVAILABLE", "NOT_IMPLEMENTED"]));
    // The gates tile is still pending behind the control, as a skeleton, and it contributes
    // no badge and no skeleton to the control.
    const gates = screen.getByTestId("tile-open-gates");
    expect(within(gates).getAllByTestId("skeleton").length).toBeGreaterThan(0);
    expect(control.querySelector("[data-testid='skeleton']")).toBeNull();
    // Its provenance is known before its value, and the synthetic tiles carry theirs.
    expect(
      Array.from(control.querySelectorAll("[data-provenance]")).map((e) =>
        e.getAttribute("data-provenance"),
      ),
    ).toEqual(["SYNTHETIC", "REPOSITORY_TRACKED"]);
  });

  it("carries nothing but the label and the known provenance while every read is pending", async () => {
    resizeTo(390);
    renderPage(clientHolding("qualificationStatus", "executiveOverview", "whatChanged", "performanceSeries"));
    const supporting = await screen.findByTestId("disclosure-supporting-context-control");
    expect(supporting.querySelectorAll("[data-availability]")).toHaveLength(0);
    expect(supporting.querySelector("[data-testid='skeleton']")).toBeNull();
    expect(
      Array.from(supporting.querySelectorAll("[data-provenance]")).map((e) =>
        e.getAttribute("data-provenance"),
      ),
    ).toEqual(["REPOSITORY_TRACKED"]);
    for (const id of ["what-changed", "performance-overview"]) {
      const control = screen.getByTestId(`disclosure-${id}-control`);
      expect(control.querySelectorAll("[data-availability]")).toHaveLength(0);
      expect(control.querySelectorAll("[data-provenance]")).toHaveLength(0);
      expect(control.querySelector("[data-testid='skeleton']")).toBeNull();
    }
    // And the page still renders its skeletons where they belong: inside the deferred content.
    expect(screen.getAllByTestId("skeleton").length).toBeGreaterThan(0);
  });

  it("renders the Response evidence disclosure collapsed when Operator mode is entered", async () => {
    resizeTo(390);
    renderPage(createDefaultReadClient(clock), "scenario=demo&mode=operator");
    const details = await screen.findByTestId("disclosure-response-evidence");
    expect(details).not.toHaveAttribute("open");
    const control = screen.getByTestId("disclosure-response-evidence-control");
    expect(within(control).getByRole("heading", { level: 2, name: "Response evidence" })).toBeTruthy();
    expect(
      Array.from(control.querySelectorAll("[data-provenance]")).map((e) =>
        e.getAttribute("data-provenance"),
      ),
    ).toEqual(["SYNTHETIC"]);
  });
});
