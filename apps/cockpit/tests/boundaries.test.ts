import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

import { readModelKey } from "@/data/client/query-keys";
import { NAV_ROUTES, ROUTES_BY_HREF } from "@/nav/registry";
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
  it("puts the environment and the provenance in every cache key", () => {
    const research = readModelKey("executive-overview", "v1", DEFAULT_SCOPE);
    const paper = readModelKey("executive-overview", "v1", {
      ...DEFAULT_SCOPE,
      environment: "PAPER",
    });
    const demo = readModelKey("executive-overview", "v1", {
      ...DEFAULT_SCOPE,
      scenario: "demo",
    });
    expect(research).not.toEqual(paper);
    expect(research).not.toEqual(demo);
    expect(research).toContain("RESEARCH");
    expect(demo).toContain("SYNTHETIC");
    expect(research).toContain("REPOSITORY_TRACKED");
  });

  it("separates two read models under one scope", () => {
    expect(readModelKey("a", "v1", DEFAULT_SCOPE)).not.toEqual(
      readModelKey("b", "v1", DEFAULT_SCOPE),
    );
  });
});

describe("scope in the URL", () => {
  it("round-trips mode, environment and scenario", () => {
    const scope = { mode: "operator", environment: "PAPER", scenario: "demo" } as const;
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
