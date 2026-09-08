import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

import { readModelKey } from "@/data/client/query-keys";
import {
  EXECUTIVE_OVERVIEW_IDENTITY,
  QUALIFICATION_IDENTITY,
  type ReadModelIdentity,
} from "@/data/client/read-model-identity";
import { DEEP_DESTINATIONS, NAV_ROUTES, RESERVED_DESTINATIONS, ROUTES_BY_HREF } from "@/nav/registry";
import { COMMAND_KINDS } from "@/components/palette/command-palette";
import { parseScope, scopeToSearchParams, withScope, DEFAULT_SCOPE } from "@/lib/scope";

const SRC = join(process.cwd(), "src");
const APP = join(SRC, "app");

function walk(directory: string): string[] {
  const found: string[] = [];
  for (const entry of readdirSync(directory)) {
    const full = join(directory, entry);
    if (statSync(full).isDirectory()) {
      found.push(...walk(full));
    } else {
      found.push(full);
    }
  }
  return found;
}

const SOURCE_FILES = walk(SRC).filter((path) => /\.(ts|tsx)$/.test(path));

describe("query scope isolation", () => {
  it("puts the environment, provenance, classification and access scope in every key", () => {
    const research = readModelKey(EXECUTIVE_OVERVIEW_IDENTITY, DEFAULT_SCOPE);
    const paper = readModelKey(EXECUTIVE_OVERVIEW_IDENTITY, {
      ...DEFAULT_SCOPE,
      environment: "PAPER",
    });
    const demo = readModelKey(EXECUTIVE_OVERVIEW_IDENTITY, {
      ...DEFAULT_SCOPE,
      scenario: "demo",
    });
    expect(research).not.toEqual(paper);
    expect(research).not.toEqual(demo);
    expect(research).toContain("RESEARCH");
    // Section 7 names all four, and every one of them is present.
    expect(research).toContain(EXECUTIVE_OVERVIEW_IDENTITY.provenance);
    expect(research).toContain("PUBLIC_SAFE");
    expect(research).toContain("executive:read");
    expect(research).toContain(EXECUTIVE_OVERVIEW_IDENTITY.schemaVersion);
    expect(research).toContain("v1");
  });

  it("separates two read models under one scope", () => {
    expect(readModelKey(EXECUTIVE_OVERVIEW_IDENTITY, DEFAULT_SCOPE)).not.toEqual(
      readModelKey(QUALIFICATION_IDENTITY, DEFAULT_SCOPE),
    );
  });

  /**
   * REGRESSION -- finding D.
   *
   * The key took its provenance from the SCENARIO SELECTOR, so the qualification cache
   * entry was labelled SYNTHETIC whenever the demo scenario was selected, though its facts
   * are REPOSITORY_TRACKED in both scenarios, and the operational entries were labelled
   * REPOSITORY_TRACKED in project scope, though they are fixture output in both.
   */
  it("keys provenance from the read model's own source, never from the scenario", () => {
    for (const scenario of ["project", "demo"] as const) {
      const scope = { ...DEFAULT_SCOPE, scenario };
      const qualification = readModelKey(QUALIFICATION_IDENTITY, scope);
      const executive = readModelKey(EXECUTIVE_OVERVIEW_IDENTITY, scope);
      // A real tracked fact is never keyed as synthetic, in EITHER scenario.
      expect(qualification).toContain("REPOSITORY_TRACKED");
      expect(qualification).not.toContain("SYNTHETIC");
      // And fixture output is never keyed as a tracked fact, in EITHER scenario.
      expect(executive).toContain("SYNTHETIC");
      expect(executive).not.toContain("REPOSITORY_TRACKED");
    }
  });

  /** Two access scopes never share one entry, so no key can serve the other's payload. */
  it("never lets two access scopes or classifications share a cache entry", () => {
    const governance = readModelKey(QUALIFICATION_IDENTITY, DEFAULT_SCOPE);
    const executive = readModelKey(EXECUTIVE_OVERVIEW_IDENTITY, DEFAULT_SCOPE);
    expect(governance).toContain("governance:read");
    expect(executive).toContain("executive:read");
    expect(governance).not.toContain("executive:read");
    const withheld: ReadModelIdentity = {
      ...QUALIFICATION_IDENTITY,
      classification: "PRIVATE_OPERATIONAL",
    };
    // A differently classified response is a DIFFERENT entry -- no shared cache (section 7).
    expect(readModelKey(withheld, DEFAULT_SCOPE)).not.toEqual(governance);
  });

  /** Every scope field separates entries, so a rapid scope change cannot flash old data. */
  it("separates every scope field, so no scope reads another's entry", () => {
    const keys = new Set<string>();
    for (const environment of ["RESEARCH", "PAPER", "LIVE"] as const) {
      for (const scenario of ["project", "demo"] as const) {
        for (const mode of ["executive", "operator"] as const) {
          keys.add(
            JSON.stringify(
              readModelKey(EXECUTIVE_OVERVIEW_IDENTITY, {
                ...DEFAULT_SCOPE,
                mode,
                environment,
                scenario,
              }),
            ),
          );
        }
      }
    }
    expect(keys.size).toBe(12);
  });
});

describe("scope in the URL", () => {
  it("round-trips every scope field, so a link reproduces the whole view", () => {
    const scope = {
      mode: "operator",
      environment: "PAPER",
      scenario: "demo",
      period: "1Y",
      granularity: "MONTHLY",
      changes: "degraded",
    } as const;
    expect(parseScope(scopeToSearchParams(scope))).toEqual(scope);
  });

  it("falls back to the default for an unknown value rather than accepting it", () => {
    const params = new URLSearchParams("mode=execute&env=PROD&scenario=live");
    expect(parseScope(params)).toEqual(DEFAULT_SCOPE);
  });

  it("preserves scope across a navigation and keeps unrelated parameters", () => {
    const href = withScope("/risk?filter=short", {
      ...DEFAULT_SCOPE,
      mode: "operator",
      environment: "PAPER",
    });
    expect(href).toContain("filter=short");
    expect(href).toContain("mode=operator");
    expect(href).toContain("env=PAPER");
  });
});

describe("the navigation registry", () => {
  it("resolves every registered route to a real page", () => {
    for (const route of NAV_ROUTES) {
      const segments = route.href === "/" ? [] : route.href.slice(1).split("/");
      const page = join(APP, ...segments, "page.tsx");
      expect(() => statSync(page), `${route.href} must resolve to a page`).not.toThrow();
    }
  });

  it("registers no duplicate href", () => {
    expect(ROUTES_BY_HREF.size).toBe(NAV_ROUTES.length);
  });

  it("names a producer, a purpose and a cycle for every route", () => {
    for (const route of NAV_ROUTES) {
      expect(route.purpose.length, route.href).toBeGreaterThan(10);
      expect(route.dependency.length, route.href).toBeGreaterThan(3);
      expect(route.cycle.length, route.href).toBeGreaterThan(1);
    }
  });

  it("resolves every implemented deep destination to a real page, and no other", () => {
    for (const destination of DEEP_DESTINATIONS) {
      const segments = destination.route.slice(1).split("/");
      const page = join(APP, ...segments, "page.tsx");
      if (destination.status === "implemented") {
        expect(() => statSync(page), `${destination.route} must resolve`).not.toThrow();
      } else {
        // A reserved destination has no page: it is named, and it is not pretended into being.
        expect(() => statSync(page), `${destination.route} must not exist yet`).toThrow();
      }
    }
    /*
     * C6 IMPLEMENTED THE LAST RESERVED DESTINATION.
     *
     * Both deep destinations now resolve to a real page, so the reserved list is empty. The
     * loop above still checks BOTH directions — an implemented destination must resolve, and a
     * reserved one must NOT exist — so an empty list here is a statement about this cycle
     * rather than a check that stopped checking.
     */
    expect(RESERVED_DESTINATIONS).toEqual([]);
    expect(DEEP_DESTINATIONS.every((destination) => destination.status === "implemented")).toBe(
      true,
    );
  });

  /**
   * The registry's cycle must be the traceability matrix's.
   *
   * C3 recorded a cycle for Area 25 that the matrix disagreed with, and the matrix governs.
   * These are the areas C5 delivers, and recording any of them under another cycle would say
   * this application implements something it does not, or does not implement something it
   * does.
   */
  it("records the C5 areas as implemented, at the cycle the matrix assigns", () => {
    const expected: Readonly<Record<string, number>> = {
      "/portfolio/performance": 2,
      "/portfolio/positions": 3,
      "/portfolio/trades": 36,
      "/strategy/performance": 4,
      "/market/regime": 11,
      "/risk": 12,
      "/risk/short-side": 13,
    };
    for (const [href, area] of Object.entries(expected)) {
      const route = ROUTES_BY_HREF.get(href);
      expect(route, href).toBeDefined();
      expect(route?.status, href).toBe("implemented");
      expect(route?.areas, href).toContain(area);
      expect(route?.cycle, href).toContain("C5");
    }
  });

  it("records the C6 areas as implemented, at the cycle the matrix assigns", () => {
    const expected: Readonly<Record<string, number>> = {
      "/signals/funnel": 6,
      "/signals/missed": 8,
    };
    for (const [href, area] of Object.entries(expected)) {
      const route = ROUTES_BY_HREF.get(href);
      expect(route, href).toBeDefined();
      expect(route?.status, href).toBe("implemented");
      expect(route?.areas, href).toContain(area);
      expect(route?.cycle, href).toContain("C6");
    }
    /* Area 7 is a deep destination rather than a sidebar entry (Area 36.3). */
    const candidate = DEEP_DESTINATIONS.find(
      (destination) => destination.route === "/signals/candidates/[candidateId]",
    );
    expect(candidate?.status).toBe("implemented");
    expect(candidate?.cycle).toBe("C6");
  });

  it("records the C7 areas as implemented, at the cycle the matrix assigns", () => {
    const expected: Readonly<Record<string, number>> = {
      "/strategy/health": 5,
      "/strategy/champion-challenger": 15,
      "/strategy/versions": 20,
      "/research/runs": 14,
      "/research/queue": 17,
      "/research/hypotheses": 18,
      "/research/feedback": 16,
      "/research/ai-contribution": 21,
      "/governance/packets": 19,
    };
    for (const [href, area] of Object.entries(expected)) {
      const route = ROUTES_BY_HREF.get(href);
      expect(route, href).toBeDefined();
      expect(route?.status, href).toBe("implemented");
      expect(route?.areas, href).toContain(area);
      expect(route?.cycle, href).toBe("C7");
      /* An implemented route still names the producing subsystem it does NOT have. */
      expect(route?.dependency, href).not.toBe("the producing subsystem does not exist");
      expect(route?.dependency.length, href).toBeGreaterThan(10);
    }
  });

  /** The areas a later cycle owns are still recorded as later cycles, and still placeholders. */
  it("leaves the C8 and later areas recorded as placeholders", () => {
    for (const href of [
      "/execution/quality",
      "/execution/reconciliation",
      "/governance/audit",
      "/system/data-quality",
      "/system/operations",
      "/system/alerts",
    ]) {
      const route = ROUTES_BY_HREF.get(href);
      expect(route?.status, href).toBe("placeholder");
      expect(route?.cycle, href).toBe("C8");
    }
  });

  it("keeps the settled route paths of the UI specification", () => {
    for (const href of [
      "/",
      "/attention",
      "/portfolio/performance",
      "/portfolio/positions",
      "/portfolio/trades",
      "/strategy/performance",
      "/strategy/health",
      "/strategy/champion-challenger",
      "/strategy/versions",
      "/signals/funnel",
      "/signals/missed",
      "/risk",
      "/risk/short-side",
      "/market/regime",
      "/execution/quality",
      "/execution/reconciliation",
      "/research/runs",
      "/research/queue",
      "/research/hypotheses",
      "/research/feedback",
      "/research/ai-contribution",
      "/governance/packets",
      "/governance/qualification",
      "/governance/maturity",
      "/governance/audit",
      "/governance/controls",
      "/system/data-quality",
      "/system/operations",
      "/system/alerts",
    ]) {
      expect(ROUTES_BY_HREF.has(href), href).toBe(true);
    }
  });
});

describe("the V1 safety boundary, enforced by absence", () => {
  it("defines a closed command vocabulary containing no state-changing verb", () => {
    expect([...COMMAND_KINDS]).toEqual(["navigate", "filter"]);
  });

  it("exposes no route handler, server action or API route anywhere", () => {
    const handlers = walk(APP).filter((path) =>
      /(^|[\\/])route\.(ts|tsx|js)$/.test(path),
    );
    expect(handlers, "no control or mutation API route may exist").toEqual([]);

    const serverActions = SOURCE_FILES.filter((path) =>
      readFileSync(path, "utf8").includes('"use server"'),
    );
    expect(serverActions.map((path) => relative(SRC, path))).toEqual([]);
  });

  it("has no forbidden execution verb in an interactive handler", () => {
    // Every forbidden action of ADR-0027 section 3, refused BY NAME.
    const forbidden = [
      "placeOrder",
      "cancelOrder",
      "submitOrder",
      "changeStop",
      "setRisk",
      "setCapital",
      "promoteStrategy",
      "activateStrategy",
      "enableLeverage",
      "setProvider",
      "executeRunB",
      "publishControl",
      "approveRelease",
      "rejectRelease",
      "killSwitch",
    ];
    for (const path of SOURCE_FILES) {
      const text = readFileSync(path, "utf8");
      for (const verb of forbidden) {
        expect(text.includes(`${verb}(`), `${relative(SRC, path)} must not call ${verb}`).toBe(
          false,
        );
      }
    }
  });

  it("keeps the inert control page free of any handler", () => {
    const controls = readFileSync(join(APP, "governance", "controls", "page.tsx"), "utf8");
    // Actual handler syntax, so the prose above the page may still name what is absent.
    expect(controls).not.toContain("onClick={");
    expect(controls).not.toContain("onSubmit={");
    expect(controls).not.toContain("onChange={");
    expect(controls).not.toContain('"use client"');
    expect(controls).not.toContain("<button");
  });

  it("adds no chart library import outside the one component that owns it", () => {
    const importers = SOURCE_FILES.filter((path) =>
      readFileSync(path, "utf8").includes("lightweight-charts"),
    ).map((path) => relative(SRC, path).replace(/\\/g, "/"));
    /*
     * ONE MODULE MAY REACH THE CHART LIBRARY.
     *
     * It builds a canvas on construction and needs real browser APIs, so it is imported
     * inside one effect in one component. A second importer would be a second place for a
     * server render or a test environment to touch it.
     */
    expect(importers).toEqual(["components/cockpit/trade-chart.tsx"]);
  });

  it("makes no network call of any kind from the application", () => {
    for (const path of SOURCE_FILES) {
      const text = readFileSync(path, "utf8");
      const file = relative(SRC, path);
      expect(/\bfetch\s*\(/.test(text), `${file} must not call fetch`).toBe(false);
      expect(text.includes("XMLHttpRequest"), file).toBe(false);
      expect(text.includes("new WebSocket"), file).toBe(false);
      expect(text.includes("EventSource"), file).toBe(false);
    }
  });

  it("contains no credential, account, bucket, broker or provider identifier", () => {
    const forbidden = [
      "AKIA",
      "arn:aws",
      "secretsmanager",
      "amazonaws.com",
      "s3://",
      "api_key",
      "apiKey",
      "IB_",
      "IBKR_",
      "sharadar.",
      "nasdaqdatalink",
    ];
    for (const path of SOURCE_FILES) {
      const text = readFileSync(path, "utf8");
      for (const needle of forbidden) {
        expect(text.includes(needle), `${relative(SRC, path)} must not contain ${needle}`).toBe(
          false,
        );
      }
      // No twelve-digit AWS account id, and no broker-native order id shape.
      expect(/\b\d{12}\b/.test(text), `${relative(SRC, path)} must not carry a 12-digit id`).toBe(
        false,
      );
    }
  });

  it("keeps presentation from importing fixture data", () => {
    const presentation = SOURCE_FILES.filter(
      (path) => path.includes(join("src", "app")) || path.includes(join("src", "components")),
    );
    for (const path of presentation) {
      const text = readFileSync(path, "utf8");
      expect(
        text.includes("data/fixtures/"),
        `${relative(SRC, path)} must reach data through the read-client boundary`,
      ).toBe(false);
    }
  });

  it("names the fixture adapter in exactly one composition module", () => {
    const importers = SOURCE_FILES.filter((path) =>
      readFileSync(path, "utf8").includes("@/data/fixtures/adapter"),
    ).map((path) => relative(SRC, path).replace(/\\/g, "/"));
    expect(importers).toEqual(["data/client/default-client.ts"]);
  });
});
