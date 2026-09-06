/**
 * The independent-review corrections to What Changed and Attention.
 *
 * Every case here was REPRODUCED against the implementation as reviewed before any fix was
 * written, and each assertion below failed then. They drive the real components and the real
 * pipeline rather than a restatement of them: a rule that only holds in a helper is a rule a
 * screen can still break.
 *
 * Nothing here reads `Date.now()`.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WhatChangedPanel } from "@/components/cockpit/what-changed";
import { ClockProvider } from "@/components/shell/clock-provider";
import {
  available,
  absent,
  emptyRefList,
  qualified,
  reason,
  refListOf,
} from "@/contracts/factories";
import type { AttentionItemPayload, WhatChangedEntryPayload } from "@/contracts/read-models";
import type { EnvelopeOf } from "@/contracts/envelope";
import type { WhatChangedPayload } from "@/data/client/read-client";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { fixedClock } from "@/lib/clock";
import { deduplicate, prepareAttention, rankAttention, severityRank } from "@/lib/attention";
import { DEFAULT_SCOPE, type ViewScope } from "@/lib/scope";

const ORIGIN = Date.parse("2026-09-20T12:00:00.000Z");
const AS_OF = "2026-09-20T12:00:00.000Z";
const BEFORE_AS_OF = "2026-09-19T12:00:00.000Z";
const clock = fixedClock(ORIGIN);

const client = () => new FixtureReadClient({ clock, originMs: ORIGIN });
const demo = (over: Partial<ViewScope> = {}): ViewScope => ({
  ...DEFAULT_SCOPE,
  scenario: "demo",
  ...over,
});

const DEMO = "kalpamani.demo";

function panel(envelope: EnvelopeOf<WhatChangedPayload>, operator = false) {
  return render(
    <ClockProvider clock={clock}>
      <WhatChangedPanel envelope={envelope} scope={demo()} operator={operator} />
    </ClockProvider>,
  );
}

/** A resolvable `source_fact` reference, which the 4.5 invariant requires before rendering. */
const resolvableEvidence = (id: string) =>
  refListOf(
    [
      {
        ref_id: id,
        ref_kind: "source_fact",
        resolution: "AUTHORIZED_READ" as const,
        classification: "PUBLIC_SAFE" as const,
      },
    ],
    "EXACTLY_ONE",
    AS_OF,
  );

const unresolvableEvidence = (id: string) =>
  refListOf(
    [
      {
        ref_id: id,
        ref_kind: "source_fact",
        resolution: "UNRESOLVABLE_V1" as const,
        classification: "PUBLIC_SAFE" as const,
      },
    ],
    "EXACTLY_ONE",
    AS_OF,
  );

const risk = (value: string, asOf: string) =>
  available({ metricId: "risk.open_planned", unit: "USD", value, asOf });

const staleRisk = (value: string, asOf: string) =>
  qualified("STALE", "UPSTREAM_INPUT_STALE", {
    metricId: "risk.open_planned",
    unit: "USD",
    value,
    asOf,
  });

const partialRisk = (value: string, asOf: string) =>
  qualified("PARTIAL", "EXTENT_PARTIALLY_COVERED", {
    metricId: "risk.open_planned",
    unit: "USD",
    value,
    asOf,
  });

function entry(over: Partial<WhatChangedEntryPayload> = {}): WhatChangedEntryPayload {
  return {
    change_id: "case-1",
    subject: reason("OPEN_PLANNED_RISK", DEMO),
    change_kind: reason("VALUE_CHANGE", DEMO),
    before: risk("1610.00", BEFORE_AS_OF),
    after: risk("1850.00", AS_OF),
    materiality: reason("MATERIAL", DEMO),
    evidence_refs: resolvableEvidence("case-1-evidence"),
    ...over,
  };
}

/** A real, admitted envelope, re-pointed at the entries a case needs. */
async function envelopeWith(
  entries: readonly WhatChangedEntryPayload[],
  over: Partial<EnvelopeOf<WhatChangedPayload>> = {},
): Promise<EnvelopeOf<WhatChangedPayload>> {
  const base = await client().whatChanged(demo({ changes: "valid" }));
  return {
    ...base,
    ...over,
    payload: { ...base.payload!, entries: [...entries] },
  };
}

/* ============================================================ WHAT CHANGED -- DEGRADED */

describe("a degraded endpoint never becomes a valid change (7, U17)", () => {
  it("reports a degraded BASELINE against its own state, not the after endpoint's", async () => {
    const envelope = await envelopeWith(
      [entry({ before: staleRisk("1610.00", BEFORE_AS_OF), after: risk("1850.00", AS_OF) })],
      { completeness: "PARTIAL" },
    );
    panel(envelope);
    const item = screen.getByTestId("what-changed-item");

    // The row is not a valid change.
    expect(item.getAttribute("data-comparison")).toBe("UNAVAILABLE");
    // No delta, no appearance claim, and no asserted materiality.
    expect(within(item).queryByTestId("change-delta")).toBeNull();
    expect(within(item).queryByTestId("change-appearance")).toBeNull();
    expect(within(item).queryByTestId("change-materiality")).toBeNull();

    // WHICH endpoint is degraded, with ITS state -- not the after endpoint's AVAILABLE badge.
    const baseline = within(item).getByTestId("endpoint-baseline");
    expect(baseline.getAttribute("data-endpoint-state")).toBe("STALE");
    const comparison = within(item).getByTestId("endpoint-comparison");
    expect(comparison.getAttribute("data-endpoint-state")).toBe("AVAILABLE");
    // The stale baseline keeps its own value visible as diagnostic detail.
    expect(baseline.textContent).toContain("1,610.00");
  });

  it("reports a degraded COMPARISON endpoint against its own state", async () => {
    const envelope = await envelopeWith(
      [entry({ before: risk("1610.00", BEFORE_AS_OF), after: partialRisk("1850.00", AS_OF) })],
      { completeness: "PARTIAL" },
    );
    panel(envelope);
    const item = screen.getByTestId("what-changed-item");
    expect(item.getAttribute("data-comparison")).toBe("UNAVAILABLE");
    expect(within(item).queryByTestId("change-delta")).toBeNull();
    const comparison = within(item).getByTestId("endpoint-comparison");
    expect(comparison.getAttribute("data-endpoint-state")).toBe("PARTIAL");
    expect(within(item).getByTestId("endpoint-baseline").getAttribute("data-endpoint-state")).toBe(
      "AVAILABLE",
    );
  });

  it("reports BOTH endpoints when both are degraded", async () => {
    const envelope = await envelopeWith(
      [
        entry({
          before: staleRisk("1610.00", BEFORE_AS_OF),
          after: partialRisk("1850.00", AS_OF),
        }),
      ],
      { completeness: "PARTIAL" },
    );
    panel(envelope);
    const item = screen.getByTestId("what-changed-item");
    expect(within(item).getByTestId("endpoint-baseline").getAttribute("data-endpoint-state")).toBe(
      "STALE",
    );
    expect(
      within(item).getByTestId("endpoint-comparison").getAttribute("data-endpoint-state"),
    ).toBe("PARTIAL");
    expect(within(item).queryByTestId("change-delta")).toBeNull();
  });

  it("still draws a delta when BOTH endpoints are sound", async () => {
    const envelope = await envelopeWith([entry()]);
    panel(envelope);
    const item = screen.getByTestId("what-changed-item");
    expect(item.getAttribute("data-comparison")).toBe("VALID");
    expect(within(item).getByTestId("change-delta").textContent).toContain("→");
    expect(within(item).getByTestId("change-materiality").textContent).toContain("MATERIAL");
  });

  it("keeps the degraded fixture's every entry off the valid-change path", async () => {
    const envelope = await client().whatChanged(demo({ changes: "degraded" }));
    panel(envelope);
    const items = screen.getAllByTestId("what-changed-item");
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(item.getAttribute("data-comparison")).toBe("UNAVAILABLE");
      expect(within(item).queryByTestId("change-delta")).toBeNull();
      expect(within(item).queryByTestId("change-materiality")).toBeNull();
      expect(within(item).getByTestId("endpoint-baseline")).toBeTruthy();
      expect(within(item).getByTestId("endpoint-comparison")).toBeTruthy();
    }
  });
});

/* ========================================================== WHAT CHANGED -- APPEARANCE */

describe("absence is not proof of appearance (4.5)", () => {
  it("refuses to call a missing prior value an appearance when the population is PARTIAL", async () => {
    const envelope = await envelopeWith(
      [entry({ change_kind: reason("APPEARANCE", DEMO), before: undefined })],
      { completeness: "PARTIAL" },
    );
    panel(envelope);
    const item = screen.getByTestId("what-changed-item");
    expect(item.getAttribute("data-comparison")).toBe("UNAVAILABLE");
    expect(within(item).getByTestId("appearance-unevidenced")).toBeTruthy();
  });

  it("refuses when the comparison population's completeness is UNKNOWN", async () => {
    const envelope = await envelopeWith(
      [entry({ change_kind: reason("APPEARANCE", DEMO), before: undefined })],
      { completeness: "UNKNOWN" },
    );
    panel(envelope);
    expect(
      within(screen.getByTestId("what-changed-item")).getByTestId("appearance-unevidenced"),
    ).toBeTruthy();
  });

  it("reports an appearance when the prior population is COMPLETE and evidenced", async () => {
    const envelope = await envelopeWith([
      entry({ change_kind: reason("APPEARANCE", DEMO), before: undefined }),
    ]);
    panel(envelope);
    const item = screen.getByTestId("what-changed-item");
    expect(item.getAttribute("data-comparison")).toBe("VALID");
    expect(within(item).queryByTestId("appearance-unevidenced")).toBeNull();
    expect(item.textContent).toContain("verified absent");
  });

  it("keeps a valid numeric zero in an observed prior record a delta, not an appearance", async () => {
    const zero = available({
      metricId: "risk.open_planned",
      unit: "USD",
      value: "0.00",
      asOf: BEFORE_AS_OF,
    });
    const envelope = await envelopeWith([entry({ before: zero })]);
    panel(envelope);
    const item = screen.getByTestId("what-changed-item");
    expect(item.getAttribute("data-comparison")).toBe("VALID");
    expect(within(item).queryByTestId("appearance-unevidenced")).toBeNull();
    expect(within(item).getByTestId("change-delta").textContent).toContain("→");
  });

  it("does not render a change carrying no evidence reference at all, and says how many", async () => {
    const envelope = await envelopeWith([entry({ evidence_refs: emptyRefList(AS_OF) })]);
    panel(envelope);
    expect(screen.queryByTestId("what-changed-item")).toBeNull();
    expect(screen.getByTestId("what-changed-withheld").textContent).toContain("1");
  });
});

/* =============================================================== WHAT CHANGED -- EMPTY */

describe("an empty entry list is not by itself a verified nothing", () => {
  it("does not claim EMPTY_VERIFIED when the comparison did not cover its extent", async () => {
    const envelope = await envelopeWith([], { completeness: "PARTIAL" });
    panel(envelope);
    expect(screen.queryByTestId("what-changed-empty-verified")).toBeNull();
    expect(screen.getByTestId("what-changed-empty-unverified")).toBeTruthy();
  });

  it("does not claim EMPTY_VERIFIED when the envelope itself is degraded", async () => {
    const envelope = await envelopeWith([], { availability: "STALE" });
    panel(envelope);
    expect(screen.queryByTestId("what-changed-empty-verified")).toBeNull();
    expect(screen.getByTestId("what-changed-empty-unverified")).toBeTruthy();
  });

  it("claims EMPTY_VERIFIED for a complete comparison that found nothing", async () => {
    const envelope = await client().whatChanged(demo({ changes: "none" }));
    panel(envelope);
    expect(screen.getByTestId("what-changed-empty-verified")).toBeTruthy();
  });
});

/* ============================================================ WHAT CHANGED -- EVIDENCE */

describe("evidence is a drill-down, not a bare count", () => {
  it("shows each reference's own resolution state in executive mode too", async () => {
    const envelope = await envelopeWith([entry()]);
    panel(envelope);
    const references = screen.getAllByTestId("change-evidence-reference");
    expect(references).toHaveLength(1);
    expect(references[0]!.textContent).toContain("AUTHORIZED_READ");
    expect(references[0]!.textContent).toContain("Source fact");
    expect(references[0]!.textContent).toContain("case-1-evidence");
  });

  /**
   * `UNRESOLVABLE_V1` IS A STATED RESOLUTION, NOT A GAP (4.2). The reference is carried so
   * the join is specified, and it resolves to an availability state rather than to a payload
   * — so it is rendered WITH that resolution, and never silently dropped.
   */
  it("renders an UNRESOLVABLE_V1 reference with its stated resolution rather than dropping it", async () => {
    const envelope = await envelopeWith([
      entry({ evidence_refs: unresolvableEvidence("case-1-evidence") }),
    ]);
    panel(envelope);
    expect(screen.getByTestId("what-changed-item")).toBeTruthy();
    const reference = screen.getByTestId("change-evidence-reference");
    expect(reference.textContent).toContain("UNRESOLVABLE_V1");
    expect(screen.getByTestId("change-evidence-unresolvable-note")).toBeTruthy();
  });

  it("carries a resolution and a classification on every rendered demo reference", async () => {
    const envelope = await client().whatChanged(demo({ changes: "valid" }));
    panel(envelope);
    const references = screen.getAllByTestId("change-evidence-reference");
    expect(references.length).toBeGreaterThan(0);
    for (const reference of references) {
      expect(reference.getAttribute("data-resolution")).toBeTruthy();
      expect(reference.getAttribute("data-classification")).toBe("PUBLIC_SAFE");
    }
  });
});

/* ================================================================ ATTENTION -- DEDUPE */

const attentionItem = (over: Partial<AttentionItemPayload> = {}): AttentionItemPayload => ({
  item_id: "item-a",
  what_happened: reason("MARK_DATA_OLDER_THAN_CONTRACT", DEMO),
  why_it_matters: reason("EXPOSURE_FIGURES_MAY_BE_STALE", DEMO),
  impact: available({ metricId: "attention.impact_usd", unit: "USD", value: "1.00", asOf: AS_OF }),
  evidence_refs: resolvableEvidence("evidence-a"),
  recommended_action: reason("REVIEW_DATA_QUALITY_EVIDENCE", DEMO),
  severity: reason("MEDIUM", DEMO),
  materiality_rank: 1,
  dedup_key: "key-1",
  first_seen: BEFORE_AS_OF,
  last_seen: AS_OF,
  occurrence_count: available({
    metricId: "attention.occurrence_count",
    unit: "COUNT",
    value: 4,
    asOf: AS_OF,
  }),
  ...over,
});

const unknownCount = absent(
  "NOT_YET_AVAILABLE",
  "UPSTREAM_INPUT_MISSING",
  "attention.occurrence_count",
  "COUNT",
);

const countOf = (value: number) =>
  available({
    metricId: "attention.occurrence_count",
    unit: "COUNT",
    value,
    asOf: AS_OF,
  });

function permutations<T>(list: readonly T[]): T[][] {
  if (list.length <= 1) {
    return [[...list]];
  }
  return list.flatMap((value, index) =>
    permutations([...list.slice(0, index), ...list.slice(index + 1)]).map((rest) => [
      value,
      ...rest,
    ]),
  );
}

describe("deduplication is deterministic under every input order", () => {
  /**
   * THE MIXED KNOWN/UNKNOWN CYCLE. Equal `last_seen`, one unknown occurrence count, and the
   * pairwise preference is not transitive: c beats a on count, a beats b on identifier and b
   * beats c on identifier. Folding a cycle depends on arrival order, and all three won.
   */
  const cycle = [
    attentionItem({ item_id: "item-a", occurrence_count: countOf(3) }),
    attentionItem({ item_id: "item-b", occurrence_count: unknownCount }),
    attentionItem({ item_id: "item-c", occurrence_count: countOf(5) }),
  ];

  it("produces one survivor for a mixed known/unknown group, in every order", () => {
    const survivors = new Set(
      permutations(cycle).map((order) =>
        deduplicate(order)
          .map((item) => item.item_id)
          .join(","),
      ),
    );
    expect([...survivors]).toHaveLength(1);
  });

  it("reports the same visible list and the same diagnostics in every order", () => {
    const results = permutations(cycle).map((order) => {
      const prepared = prepareAttention(order);
      return JSON.stringify({
        visible: prepared.visible.map((item) => item.item_id),
        rankedTotal: prepared.rankedTotal,
        deduplicated: prepared.deduplicated,
        withheldIncomplete: prepared.withheldIncomplete,
        conflicting: prepared.conflicting,
      });
    });
    expect(new Set(results).size).toBe(1);
  });

  it("collapses exact duplicates without reporting a conflict", () => {
    const twice = [attentionItem(), attentionItem()];
    const prepared = prepareAttention(twice);
    expect(prepared.visible.map((item) => item.item_id)).toEqual(["item-a"]);
    expect(prepared.deduplicated).toBe(1);
    expect(prepared.conflicting).toBe(0);
  });

  it("never silently chooses between equal-identity records whose content conflicts", () => {
    const conflicting = [
      attentionItem({ what_happened: reason("MARK_DATA_OLDER_THAN_CONTRACT", DEMO) }),
      attentionItem({ what_happened: reason("RECONCILIATION_BREAK_OPEN", DEMO) }),
    ];
    for (const order of permutations(conflicting)) {
      const prepared = prepareAttention(order);
      // The conflict is surfaced, and the issue does not vanish from the list.
      expect(prepared.conflicting).toBe(1);
      expect(prepared.visible).toHaveLength(1);
      expect(prepared.visible[0]!.item_id).toBe("item-a");
    }
    const rendered = permutations(conflicting).map((order) =>
      JSON.stringify(prepareAttention(order).visible),
    );
    expect(new Set(rendered).size).toBe(1);
  });

  it("keeps the newest record when authority actually determines a winner", () => {
    const older = attentionItem({ item_id: "item-old", last_seen: BEFORE_AS_OF });
    const newer = attentionItem({ item_id: "item-new", last_seen: AS_OF });
    for (const order of [
      [older, newer],
      [newer, older],
    ]) {
      expect(deduplicate(order).map((item) => item.item_id)).toEqual(["item-new"]);
    }
  });
});

describe("severity is ranked in its own vocabulary", () => {
  const foreignHigh = {
    code: "HIGH",
    vocabulary: "some.other.vocabulary",
    vocabulary_version: "v1",
  };

  it("does not rank a coincidentally identical code from another vocabulary", () => {
    expect(severityRank(reason("MEDIUM", DEMO))).toBeLessThan(severityRank(foreignHigh));
  });

  it("does not rank a known code carried at an unknown vocabulary version", () => {
    const drifted = { code: "HIGH", vocabulary: DEMO, vocabulary_version: "v2" };
    expect(severityRank(reason("LOW", DEMO))).toBeLessThan(severityRank(drifted));
  });

  it("orders its own vocabulary's codes", () => {
    expect(severityRank(reason("HIGH", DEMO))).toBeLessThan(severityRank(reason("MEDIUM", DEMO)));
    expect(severityRank(reason("MEDIUM", DEMO))).toBeLessThan(severityRank(reason("LOW", DEMO)));
    expect(severityRank(reason("URGENT", DEMO))).toBeGreaterThan(severityRank(reason("LOW", DEMO)));
  });

  it("ranks a foreign HIGH after a native LOW rather than ahead of it", () => {
    const native = attentionItem({
      item_id: "native",
      severity: reason("LOW", DEMO),
      dedup_key: "k-native",
    });
    const foreign = attentionItem({
      item_id: "foreign",
      severity: foreignHigh,
      dedup_key: "k-foreign",
    });
    expect(rankAttention([foreign, native]).map((item) => item.item_id)).toEqual([
      "native",
      "foreign",
    ]);
  });
});
