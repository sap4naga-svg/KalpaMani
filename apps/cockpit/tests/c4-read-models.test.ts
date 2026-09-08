/**
 * The C4 read models, their admission and the rules the screens depend on.
 *
 * These drive the REAL read client and the published schemas, not isolated helpers: a
 * payload a helper would refuse still reaches a screen if the boundary it actually passes
 * through does not refuse it.
 *
 * Every instant comes from an explicit fixed clock. Nothing here reads `Date.now()`.
 */
import { PERFORMANCE_SERIES_SCHEMA } from "@/contracts/read-models";
import { describe, expect, it } from "vitest";

import { available, emptyRefList, pinsOf, reason, refListOf } from "@/contracts/factories";
import {
  attentionListEnvelope,
  executiveOverviewEnvelope,
  performanceSeriesEnvelope,
  qualificationStatusEnvelope,
  whatChangedEnvelope,
} from "@/contracts/read-models";
import { metricValue, refList, series } from "@/contracts/values";
import { isValueBearing } from "@/contracts/validity";
import { admit, ContractViolationError } from "@/data/client/read-client";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { READ_AT_COMMIT, SNAPSHOT_EXTRACTED_ON } from "@/data/fixtures/tracked-facts";
import { fixedClock } from "@/lib/clock";
import { deduplicate, prepareAttention, rankAttention, severityRank } from "@/lib/attention";
import { DATE_GATE_BASIS, evaluateDateGate, utcCalendarDate } from "@/lib/governance";
import { DEFAULT_SCOPE, PERIOD_TRADING_DAYS, type ViewScope } from "@/lib/scope";
import { readModelKey } from "@/data/client/query-keys";
import { PERFORMANCE_SERIES_IDENTITY } from "@/data/client/read-model-identity";

/** Well after the tracked snapshot date, so the governance input has a positive age. */
const ORIGIN = Date.parse("2026-09-20T12:00:00.000Z");
const AS_OF = "2026-09-20T12:00:00.000Z";

const client = (over: Partial<{ originMs: number }> = {}) =>
  new FixtureReadClient({
    clock: fixedClock(over.originMs ?? ORIGIN),
    originMs: over.originMs ?? ORIGIN,
  });

const demo = (over: Partial<ViewScope> = {}): ViewScope => ({
  ...DEFAULT_SCOPE,
  scenario: "demo",
  ...over,
});

/* ============================================================ CONTRACT COMPLETION */

describe("the C3 omissions C4 completes", () => {
  it("carries regime_ref, both last-run records and both reference lists", async () => {
    const envelope = await client().executiveOverview(demo());
    const payload = envelope.payload;
    expect(payload).toBeDefined();
    // §4.3 keeps a reference VISIBLE even when it resolves to a state rather than a payload.
    expect(payload?.regime_ref.ref_kind).toBe("regime_context");
    /*
     * ENDPOINT, AND IT USED TO SAY UNRESOLVABLE_V1.
     *
     * `regime_context` resolves by a catalogued GET and its row lists no other
     * member, so ENDPOINT is the only resolution it may declare (ADR-0030 R3).
     */
    expect(payload?.regime_ref.resolution).toBe("ENDPOINT");
    /*
     * AND THE TWO AXES STAY SEPARATE, WHICH IS THE POINT OF THE CHANGE ABOVE.
     *
     * A resolution says HOW a reference resolves; whether the PRODUCER exists is a
     * different question, carried by the value-bearing field beside it. Both last-run
     * records declare a catalogued endpoint AND report NOT_IMPLEMENTED, and the Brain
     * runtime is no more built than it was.
     */
    for (const record of [payload?.last_decision, payload?.last_scout_run]) {
      expect(record!.ref.resolution).toBe("ENDPOINT");
    }
    // The Brain runtime does not exist, so neither record is a timestamp.
    for (const record of [payload?.last_decision, payload?.last_scout_run]) {
      expect(record).toBeDefined();
      expect(isValueBearing(record!.at.availability)).toBe(false);
      expect(record!.at.availability).toBe("NOT_IMPLEMENTED");
      expect(record!.at.value).toBeUndefined();
    }
    expect(payload?.what_changed.items.length).toBeGreaterThan(0);
    expect(payload?.attention.items.length).toBeGreaterThan(0);
  });

  it("counts a reference list by its stated total, never by its page length", () => {
    const reference = {
      ref_id: "one",
      ref_kind: "source_fact" as const,
      resolution: "AUTHORIZED_READ" as const,
      classification: "PUBLIC_SAFE" as const,
    };
    // An untruncated list states a total equal to what it carries.
    expect(refList.safeParse(refListOf([reference], "EXACTLY_ONE", AS_OF)).success).toBe(true);
    // A truncated one states MORE than it carries -- that is what `total` is for.
    const truncated = refListOf([reference], "ZERO_OR_MORE", AS_OF, {
      truncated: true,
      total: 40,
    });
    expect(refList.safeParse(truncated).success).toBe(true);
    // A truncated list whose total equals its length is the defect `total` exists to prevent.
    expect(() =>
      refListOf([reference], "ZERO_OR_MORE", AS_OF, { truncated: true, total: 1 }),
    ).toThrow(RangeError);
    // ...and the schema refuses it too, however it was constructed.
    expect(
      refList.safeParse({ ...refListOf([reference], "ZERO_OR_MORE", AS_OF), truncated: true })
        .success,
    ).toBe(false);
    // A total SMALLER than the items carried is incoherent.
    expect(
      refList.safeParse({
        ...refListOf([reference, { ...reference, ref_id: "two" }], "ZERO_OR_MORE", AS_OF),
        total: available({ metricId: "reference.total", unit: "COUNT", value: 1, asOf: AS_OF }),
      }).success,
    ).toBe(false);
  });

  it("carries a watermark and a full pin set on a payload-bearing response, and neither on an absence", async () => {
    const populated = await client().executiveOverview(demo());
    expect(populated.watermark).toBeDefined();
    expect(populated.pins).toBeDefined();
    // A pin that does not apply SAYS SO, rather than being omitted (§4.2).
    const strategyPin = populated.pins?.strategy_version;
    expect(typeof strategyPin).not.toBe("string");
    expect(typeof strategyPin === "object" ? strategyPin.availability : null).toBe(
      "NOT_APPLICABLE",
    );
    // The two identities that DO apply are pinned as SafeIds.
    expect(typeof populated.pins?.code_identity).toBe("string");
    expect(typeof populated.pins?.config_identity).toBe("string");

    const absent = await client().executiveOverview({ ...demo(), environment: "PAPER" });
    expect(absent.payload).toBeUndefined();
    expect(absent.watermark).toBeUndefined();
    expect(absent.pins).toBeUndefined();
  });

  it("refuses a payload-bearing response with no watermark, and one that outruns its build", async () => {
    const good = await client().executiveOverview(demo());
    for (const candidate of [
      { ...good, watermark: undefined },
      // A projection cannot have consumed source produced after it was built.
      { ...good, watermark: "2099-01-01T00:00:00.000Z" },
    ]) {
      expect(() =>
        admit("ExecutiveOverview", executiveOverviewEnvelope, candidate, "PUBLIC_EDGE"),
      ).toThrow(ContractViolationError);
    }
  });

  it("separates the snapshot's source as-of from the day it was transcribed", async () => {
    const status = await client().qualificationStatus(DEFAULT_SCOPE);
    const payload = status.payload;
    expect(payload?.read_at_commit).toBe(READ_AT_COMMIT);
    expect(payload?.snapshot_extracted_on).toBe(SNAPSHOT_EXTRACTED_ON);
    // Run A's own as-of is the day the SOURCE records, not the day of the transcription.
    const runA = payload?.facts.find((fact) => fact.fact_id === "run-a");
    expect(runA?.as_of).toBe("2026-09-04");
    expect(runA?.as_of).not.toBe(payload?.snapshot_extracted_on);
    // Every fact names the exact tracked path and full commit it was read at.
    for (const fact of payload?.facts ?? []) {
      expect(fact.source.commit).toMatch(/^[0-9a-f]{40}$/);
      expect(fact.source.path.length).toBeGreaterThan(0);
    }
  });
});

/* ================================================================ PERFORMANCE SERIES */

describe("the performance series", () => {
  it("is a validated read model, aligned across its three series", async () => {
    const envelope = await client().performanceSeries(demo({ period: "3M" }));
    const payload = envelope.payload;
    expect(payload).toBeDefined();
    /* Pinned to the constant, so a later bump cannot leave this asserting a stale one. */
    expect(envelope.schema_version).toBe(PERFORMANCE_SERIES_SCHEMA);

    const { equity, return_series: returns, drawdown_series: drawdowns } = payload!;
    expect(equity.points).toHaveLength(PERIOD_TRADING_DAYS["3M"]);
    expect(returns.points).toHaveLength(equity.points.length);
    expect(drawdowns.points).toHaveLength(equity.points.length);
    // One point is one session: the three series carry the same instants.
    for (let index = 0; index < equity.points.length; index += 1) {
      expect(returns.points[index].t).toBe(equity.points[index].t);
      expect(drawdowns.points[index].t).toBe(equity.points[index].t);
    }
    // Strictly ordered in time, and no duplicate session.
    for (let index = 1; index < equity.points.length; index += 1) {
      expect(equity.points[index].t > equity.points[index - 1].t).toBe(true);
    }
  });

  it("carries every point as a typed metric in a stated unit and precision", async () => {
    const payload = (await client().performanceSeries(demo())).payload!;
    for (const point of payload.equity.points) {
      expect(point.v.metric_id).toBe("portfolio.equity");
      expect(point.v.unit).toBe("USD");
      // Decimal strings, never binary floats, and exactly two places (§4.2).
      expect(point.v.value).toMatch(/^-?\d+\.\d{2}$/);
      expect(metricValue.safeParse(point.v).success).toBe(true);
    }
    for (const point of payload.return_series.points) {
      expect(point.v.metric_id).toBe("return.time_weighted");
      expect(point.v.unit).toBe("PERCENT");
    }
    expect(payload.drawdown_series.points[0].v.metric_id).toBe("drawdown.current");
  });

  it("never draws a positive drawdown, and starts at its own peak", async () => {
    const payload = (await client().performanceSeries(demo())).payload!;
    for (const point of payload.drawdown_series.points) {
      const value = String(point.v.value);
      // equity / running_peak - 1 is never positive (§12.3).
      expect(value.startsWith("-") || !/[1-9]/.test(value)).toBe(true);
    }
    expect(payload.drawdown_series.points[0].v.value).toBe("0.00");
  });

  it("keeps a cash flow out of the return and drawdown series", async () => {
    const payload = (await client().performanceSeries(demo({ period: "3M" }))).payload!;
    expect(payload.cash_flows.length).toBeGreaterThan(0);
    const flow = payload.cash_flows[0];
    expect(flow.kind).toBe("DEPOSIT");
    expect(flow.amount.sign_convention).toBe("INFLOW_POSITIVE_OUTFLOW_NEGATIVE");
    const flowDate = flow.at.slice(0, 10);
    const index = payload.equity.points.findIndex((point) => point.t === flowDate);
    expect(index).toBeGreaterThan(0);

    // EQUITY steps up by the flow...
    const before = Number(payload.equity.points[index - 1].v.value);
    const after = Number(payload.equity.points[index].v.value);
    expect(after - before).toBeGreaterThan(4_000);

    // ...and the RETURN does not. A deposit is not a profit (§4.5).
    const returnBefore = Number(payload.return_series.points[index - 1].v.value);
    const returnAfter = Number(payload.return_series.points[index].v.value);
    expect(Math.abs(returnAfter - returnBefore)).toBeLessThan(2);

    // ...and the drawdown creates no new peak from it (§12.3).
    const drawdownBefore = Number(payload.drawdown_series.points[index - 1].v.value);
    const drawdownAfter = Number(payload.drawdown_series.points[index].v.value);
    expect(Math.abs(drawdownAfter - drawdownBefore)).toBeLessThan(2);
  });

  it("reports a gapped extent as PARTIAL, and never fills the gap", async () => {
    const envelope = await client().performanceSeries(demo({ period: "ALL" }));
    const payload = envelope.payload!;
    expect(payload.equity.completeness).toBe("PARTIAL");
    expect(payload.equity.coverage.present).toBeLessThan(payload.equity.coverage.requested);
    expect(envelope.completeness).toBe("PARTIAL");
    // The missing sessions are ABSENT, not zeroed.
    expect(payload.equity.points.every((point) => point.v.value !== "0.00")).toBe(true);
  });

  it("refuses a series that claims to be complete while carrying a gap", () => {
    const point = {
      t: "2026-09-01",
      v: available({
        metricId: "portfolio.equity",
        unit: "USD",
        value: "80000.00",
        asOf: AS_OF,
      }),
    };
    const calendar = { code: "XNYS", vocabulary: "demo", vocabulary_version: "v1" };
    expect(
      series.safeParse({
        points: [point],
        granularity: "DAILY",
        calendar,
        timezone: "UTC",
        coverage: { present: 1, requested: 5 },
        completeness: "COMPLETE",
      }).success,
    ).toBe(false);
    // ...and refuses a coverage that disagrees with the points it actually carries.
    expect(
      series.safeParse({
        points: [point],
        granularity: "DAILY",
        calendar,
        timezone: "UTC",
        coverage: { present: 5, requested: 5 },
        completeness: "COMPLETE",
      }).success,
    ).toBe(false);
  });

  it("shows NO series at all in project scope, and never a flat line at strategy capital", async () => {
    const envelope = await client().performanceSeries(DEFAULT_SCOPE);
    expect(envelope.payload).toBeUndefined();
    expect(envelope.availability).toBe("NOT_IMPLEMENTED");
    expect(envelope.availability_reason).toBe("PRODUCER_NOT_IMPLEMENTED");
  });

  it("does not restamp its points when only the evaluation time moves", async () => {
    const first = await client().performanceSeries(demo());
    const later = new FixtureReadClient({
      clock: fixedClock(ORIGIN + 900_000),
      originMs: ORIGIN,
    });
    const second = await later.performanceSeries(demo());
    expect(second.payload?.equity.points.map((point) => point.t)).toEqual(
      first.payload?.equity.points.map((point) => point.t),
    );
    expect(second.payload?.window).toEqual(first.payload?.window);
    // The projection lag between two fixed instants cannot move.
    expect(second.freshness.projection_lag.value).toBe(first.freshness.projection_lag.value);
  });

  it("gives each period its own cache entry, so one range never draws under another's label", () => {
    const keys = new Set(
      (["1M", "3M", "6M", "1Y", "ALL"] as const).map((period) =>
        JSON.stringify(readModelKey(PERFORMANCE_SERIES_IDENTITY, demo({ period }), [period])),
      ),
    );
    expect(keys.size).toBe(5);
  });

  it("refuses a benchmark drawn without a name", async () => {
    const good = await client().performanceSeries(demo());
    expect(() =>
      admit(
        "PerformanceSeries",
        performanceSeriesEnvelope,
        { ...good, payload: { ...good.payload, benchmark_label: undefined } },
        "PUBLIC_EDGE",
      ),
    ).toThrow(ContractViolationError);
  });
});

/* ====================================================================== ATTENTION */

describe("attention ranking, deduplication and completeness", () => {
  const load = async () => {
    const envelope = await client().attention(demo());
    return envelope.payload!.items;
  };

  it("ranks by materiality then severity, with a stable tie-break", async () => {
    const ranked = rankAttention(await load());
    const ranks = ranked.map((item) => item.materiality_rank);
    expect([...ranks]).toEqual([...ranks].sort((left, right) => left - right));
    const sev = (code: string) => reason(code, "kalpamani.demo");
    expect(severityRank(sev("HIGH"))).toBeLessThan(severityRank(sev("MEDIUM")));
    expect(severityRank(sev("MEDIUM"))).toBeLessThan(severityRank(sev("LOW")));
    // An unknown severity sorts after every known one rather than being guessed at.
    expect(severityRank(sev("URGENT"))).toBeGreaterThan(severityRank(sev("LOW")));
  });

  it("produces the same order under every permutation of the producer's output", async () => {
    const items = await load();
    const forward = rankAttention(items).map((item) => item.item_id);
    const reversed = rankAttention([...items].reverse()).map((item) => item.item_id);
    const rotated = rankAttention([...items.slice(2), ...items.slice(0, 2)]).map(
      (item) => item.item_id,
    );
    expect(reversed).toEqual(forward);
    expect(rotated).toEqual(forward);
  });

  it("deduplicates by key, keeping the most recently seen, whatever order they arrive in", async () => {
    const items = await load();
    const duplicated = items.filter((item) => item.dedup_key === "demo-dedup-mark-staleness");
    expect(duplicated).toHaveLength(2);

    const survivorOf = (input: typeof items) =>
      deduplicate(input).find((item) => item.dedup_key === "demo-dedup-mark-staleness")?.item_id;
    expect(survivorOf(items)).toBe("demo-attention-2");
    expect(survivorOf([...items].reverse())).toBe("demo-attention-2");
  });

  it("withholds an item missing any of the five presented things, and says how many", async () => {
    const items = await load();
    const prepared = prepareAttention(items);
    // The unsourced fixture carries no evidence reference at all.
    expect(items.some((item) => item.item_id === "demo-attention-incomplete")).toBe(true);
    expect(prepared.visible.some((item) => item.item_id === "demo-attention-incomplete")).toBe(
      false,
    );
    expect(prepared.withheldIncomplete).toBe(1);
    expect(prepared.deduplicated).toBe(1);
    expect(prepared.rankedTotal).toBe(4);
  });

  it("never ranks an unmeasured impact as zero", async () => {
    const prepared = prepareAttention(await load());
    const unmeasured = prepared.visible.find((item) => item.item_id === "demo-attention-2");
    const measuredZero = prepared.visible.find((item) => item.item_id === "demo-attention-3");
    // One has NO impact value; the other has a MEASURED zero. They are different answers.
    expect(isValueBearing(unmeasured!.impact.availability)).toBe(false);
    expect(unmeasured!.impact.value).toBeUndefined();
    expect(isValueBearing(measuredZero!.impact.availability)).toBe(true);
    expect(measuredZero!.impact.value).toBe("0.00");
    // ...and neither one's rank came from its impact.
    expect(unmeasured!.materiality_rank).toBeLessThan(measuredZero!.materiality_rank);
  });

  it("filters without concealing, reporting the total the filter hid", async () => {
    const items = await load();
    const high = prepareAttention(items, { severities: ["HIGH"], evidenceKinds: [] });
    expect(high.visible).toHaveLength(1);
    // The unfiltered total stays visible, so a subset is never read as the whole.
    expect(high.rankedTotal).toBe(4);

    /*
     * THE EVIDENCE KINDS CHANGED, AND THE PROPERTY UNDER TEST DID NOT.
     *
     * These items used to carry `data_quality`, `health_transition` and
     * `reconciliation` evidence — three kinds §4.5 does not permit on
     * `AttentionItem.evidence_refs`, which declares "evidence or source_fact". The
     * producer was corrected rather than the field widened, so every item now
     * carries a `source_fact`.
     *
     * What this test is about is that a filter HIDES without CONCEALING, and that
     * is asserted in both directions below.
     */
    const bySourceFact = prepareAttention(items, {
      severities: [],
      evidenceKinds: ["source_fact"],
    });
    /*
     * ALL FOUR ARE SOURCE FACTS, AND THE BORROW ITEM WAS BRIEFLY `evidence`.
     *
     * An `AttentionItem` is a projection (Area 28), and section 4.3 defines `source_fact`
     * as "the recorded fact a projection was built from" -- which each of these references
     * is. Typing the borrow one `evidence` left it the only reference with no owning-area
     * destination, because section 5 catalogues no route for a classified evidence artefact.
     */
    expect(bySourceFact.visible.length).toBe(4);
    expect(bySourceFact.rankedTotal).toBe(4);
    /*
     * `evidence` is the OTHER kind section 4.5 permits here, and no item carries one today.
     * Selecting it is a true "none of these" rather than a missing control, which is why the
     * chips come from the CONTRACT and not from the sample.
     */
    const byEvidence = prepareAttention(items, { severities: [], evidenceKinds: ["evidence"] });
    expect(byEvidence.visible.length).toBe(0);
    expect(byEvidence.rankedTotal).toBe(4);

    /* A kind no item carries hides every row, and still reports the whole total. */
    const byAbsentKind = prepareAttention(items, {
      severities: [],
      evidenceKinds: ["incident"],
    });
    expect(byAbsentKind.visible).toHaveLength(0);
    expect(byAbsentKind.rankedTotal).toBe(4);
  });

  it("carries evidence with a resolution and a classification on every rendered item", async () => {
    for (const item of prepareAttention(await load()).visible) {
      expect(item.evidence_refs.items.length).toBeGreaterThan(0);
      for (const reference of item.evidence_refs.items) {
        expect(reference.resolution.length).toBeGreaterThan(0);
        expect(reference.classification).toBe("PUBLIC_SAFE");
      }
      // A recommended action is a GOVERNANCE verb, never an execution instruction.
      expect(item.recommended_action.code).toMatch(/^REVIEW_/);
    }
  });

  it("refuses an attention payload whose item carries an unregistered impact metric", async () => {
    const good = await client().attention(demo());
    const corrupted = {
      ...good,
      payload: {
        items: [
          {
            ...good.payload!.items[0],
            impact: { ...good.payload!.items[0].impact, metric_id: "attention.invented" },
          },
        ],
      },
    };
    expect(() =>
      admit("AttentionItem", attentionListEnvelope, corrupted, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });
});

/* =================================================================== WHAT CHANGED */

describe("what changed, and its comparison baselines", () => {
  it("lists real changes when both endpoints are sound", async () => {
    const envelope = await client().whatChanged(demo({ changes: "valid" }));
    const payload = envelope.payload!;
    expect(payload.baseline_as_of).toBeDefined();
    expect(payload.comparison_as_of).toBeDefined();
    expect(payload.baseline_state).toBeUndefined();
    expect(payload.entries.length).toBeGreaterThan(0);
    // The baseline endpoint precedes the comparison endpoint.
    expect(payload.baseline_as_of! < payload.comparison_as_of!).toBe(true);
    expect(envelope.completeness).toBe("COMPLETE");
  });

  it("distinguishes 'nothing changed' from 'nothing to compare against'", async () => {
    const none = (await client().whatChanged(demo({ changes: "none" }))).payload!;
    // A completed comparison over a sound baseline that found no difference.
    expect(none.entries).toHaveLength(0);
    expect(none.baseline_as_of).toBeDefined();
    expect(none.baseline_state).toBeUndefined();

    const missing = (await client().whatChanged(demo({ changes: "no-baseline" }))).payload!;
    // No prior endpoint at all: a STATE with a reason, and no entries.
    expect(missing.entries).toHaveLength(0);
    expect(missing.baseline_as_of).toBeUndefined();
    expect(missing.baseline_state).toEqual({
      availability: "NOT_YET_AVAILABLE",
      reason: "UPSTREAM_INPUT_MISSING",
    });
  });

  it("reports a degraded endpoint with its qualification instead of a clean delta", async () => {
    const envelope = await client().whatChanged(demo({ changes: "degraded" }));
    const payload = envelope.payload!;
    expect(payload.entries.length).toBeGreaterThan(0);
    for (const entry of payload.entries) {
      const degraded =
        entry.after.availability !== "AVAILABLE" ||
        (entry.before !== undefined && entry.before.availability !== "AVAILABLE");
      expect(degraded).toBe(true);
      // Materiality is not asserted over a degraded comparison.
      expect(entry.materiality.code).toBe("INDETERMINATE");
    }
    // A comparison that did not cover its extent says so on the envelope.
    expect(envelope.completeness).toBe("PARTIAL");
  });

  it("has no baseline at all in project scope", async () => {
    const envelope = await client().whatChanged(DEFAULT_SCOPE);
    expect(envelope.payload).toBeUndefined();
    expect(envelope.availability).toBe("NOT_YET_AVAILABLE");
    expect(envelope.availability_reason).toBe("UPSTREAM_INPUT_MISSING");
  });

  it("refuses a payload that states a change against a baseline it does not have", async () => {
    const good = await client().whatChanged(demo({ changes: "valid" }));
    const fabricated = {
      ...good,
      payload: {
        ...good.payload,
        baseline_as_of: undefined,
        baseline_state: { availability: "NOT_YET_AVAILABLE", reason: "UPSTREAM_INPUT_MISSING" },
      },
    };
    expect(() =>
      admit("WhatChangedEntry", whatChangedEnvelope, fabricated, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses a baseline that is both present and explained away, and one that is neither", async () => {
    const good = await client().whatChanged(demo({ changes: "valid" }));
    for (const payload of [
      // Both: two claims about whether a baseline exists.
      {
        ...good.payload,
        baseline_state: { availability: "NOT_YET_AVAILABLE", reason: "UPSTREAM_INPUT_MISSING" },
      },
      // Neither: an absent baseline with nothing saying why.
      { ...good.payload, baseline_as_of: undefined, entries: [] },
    ]) {
      expect(() =>
        admit("WhatChangedEntry", whatChangedEnvelope, { ...good, payload }, "PUBLIC_EDGE"),
      ).toThrow(ContractViolationError);
    }
  });

  it("refuses an entry whose prior value is not a value", async () => {
    const good = await client().whatChanged(demo({ changes: "valid" }));
    const entry = good.payload!.entries[0];
    const corrupted = {
      ...good,
      payload: {
        ...good.payload,
        entries: [
          {
            ...entry,
            before: {
              unit: "DIMENSIONLESS",
              availability: "NOT_YET_AVAILABLE",
              reason: "UPSTREAM_INPUT_MISSING",
              metric_id: "strategy.health_state",
              metric_definition_version: "metrics.v1",
            },
          },
        ],
      },
    };
    expect(() =>
      admit("WhatChangedEntry", whatChangedEnvelope, corrupted, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses a baseline dated after the comparison it is a baseline for", async () => {
    const good = await client().whatChanged(demo({ changes: "valid" }));
    expect(() =>
      admit(
        "WhatChangedEntry",
        whatChangedEnvelope,
        {
          ...good,
          payload: { ...good.payload, baseline_as_of: "2099-01-01T00:00:00.000Z" },
        },
        "PUBLIC_EDGE",
      ),
    ).toThrow(ContractViolationError);
  });
});

/* ======================================================== GOVERNANCE AND DATE GATES */

describe("date eligibility never becomes authorization", () => {
  const RUN_B_GATE = "2026-09-12";

  it("evaluates before, on and after the gate on a stated calendar basis", () => {
    expect(DATE_GATE_BASIS).toBe("UTC_CALENDAR_DATE");
    expect(utcCalendarDate(Date.parse("2026-09-11T23:59:59.999Z"))).toBe("2026-09-11");

    const before = evaluateDateGate(RUN_B_GATE, Date.parse("2026-09-11T23:59:59.999Z"));
    const on = evaluateDateGate(RUN_B_GATE, Date.parse("2026-09-12T00:00:00.000Z"));
    const onLate = evaluateDateGate(RUN_B_GATE, Date.parse("2026-09-12T23:59:59.999Z"));
    const after = evaluateDateGate(RUN_B_GATE, Date.parse("2026-09-13T00:00:00.000Z"));

    expect(before.standing).toBe("NOT_REACHED");
    expect(on.standing).toBe("REACHED");
    expect(onLate.standing).toBe("REACHED");
    expect(after.standing).toBe("REACHED");
    // Each evaluation states the date it compared, so a reader can check the comparison.
    expect(on.evaluatedOn).toBe("2026-09-12");
    expect(on.gateDate).toBe(RUN_B_GATE);
  });

  it("treats an absent or unparseable gate as UNDETERMINED, never as reached", () => {
    for (const candidate of [undefined, null, "", "soon", "2026-13-01", 20260912]) {
      const evaluation = evaluateDateGate(candidate, Date.parse("2099-01-01T00:00:00.000Z"));
      expect(evaluation.standing).toBe("UNDETERMINED");
      expect(evaluation.gateDate).toBeNull();
    }
  });

  it("leaves the authorization NOT_AUTHORIZED on every side of the date", async () => {
    for (const instant of [
      "2026-09-11T12:00:00.000Z",
      "2026-09-12T12:00:00.000Z",
      "2027-01-01T12:00:00.000Z",
    ]) {
      const status = await new FixtureReadClient({
        clock: fixedClock(instant),
        originMs: Date.parse(instant),
      }).qualificationStatus(DEFAULT_SCOPE);
      const runB = status.payload?.run_authorizations.find(
        (entry) => entry.run.code === "RUN_B",
      );
      // THE DATE MOVES. THE AUTHORIZATION DOES NOT.
      expect(runB?.date_gate.value).toBe(RUN_B_GATE);
      expect(runB?.authorization.code).toBe("NOT_AUTHORIZED");
      expect(runB?.minimum_separation.value).toBe(8);
      expect(runB?.date_basis.code).toBe("UTC_CALENDAR_DATE");
    }
  });

  it("carries the date as a date and the separation as a duration, in their own units", async () => {
    const status = await client().qualificationStatus(DEFAULT_SCOPE);
    const runB = status.payload?.run_authorizations.find((entry) => entry.run.code === "RUN_B");
    // A calendar date is not a count of days: CALENDAR_DAYS is a DURATION unit.
    expect(runB?.date_gate.unit).toBe("DIMENSIONLESS");
    expect(runB?.date_gate.unit).not.toBe("CALENDAR_DAYS");
    // The separation IS a duration, and carries the duration unit.
    expect(runB?.minimum_separation.unit).toBe("CALENDAR_DAYS");
  });

  it("records every gate independently, and P1-P9 as unevaluated", async () => {
    const payload = (await client().qualificationStatus(DEFAULT_SCOPE)).payload!;
    expect(payload.gates).toHaveLength(7);
    expect(payload.gates.filter((gate) => gate.state === "OPEN")).toHaveLength(6);
    const g3 = payload.gates.find((gate) => gate.gate === "G3");
    expect(g3?.state).toBe("CLOSED");
    // Closed for the personal-use licence AND NOTHING ELSE.
    expect(g3?.scope.code).toBe("SHARADAR_PERSONAL_USE_LICENCE_ONLY");
    expect(payload.provider_tests).toHaveLength(9);
    expect(payload.provider_tests.every((test) => test.state === "UNEVALUATED")).toBe(true);
  });

  it("states the blockers as a chain, and never as a completion percentage", async () => {
    const payload = (await client().qualificationStatus(DEFAULT_SCOPE)).payload!;
    expect(payload.blockers.length).toBeGreaterThan(0);
    expect(payload.next_required_event.event.code).toBe("RUN_B_WRITTEN_AUTHORIZATION");
    expect(payload.next_required_event.actor.code).toBe("OWNER");
    /*
     * STRUCTURAL, not a forbidden-word scan. An earlier revision of this test searched the
     * serialized payload for "completion" and matched the ADR-0028 FILENAME -- which is how a
     * string assertion fails a correct payload and would equally have passed a wrong one.
     *
     * The real property is about SHAPE: nothing in this payload is a ratio or a percentage,
     * so no aggregate over the gates can have been computed into it. Every metric the payload
     * carries is a date, a duration or a count.
     */
    const metrics = [
      ...payload.run_authorizations.flatMap((entry) => [
        entry.date_gate,
        entry.minimum_separation,
      ]),
    ];
    expect(metrics.length).toBeGreaterThan(0);
    for (const metric of metrics) {
      expect(["DIMENSIONLESS", "CALENDAR_DAYS"]).toContain(metric.unit);
      expect(metric.unit).not.toBe("PERCENT");
      expect(metric.unit).not.toBe("RATIO");
    }
    // Each gate carries a state from a two-member vocabulary and no score of its own.
    for (const gate of payload.gates) {
      expect(["OPEN", "CLOSED"]).toContain(gate.state);
      expect(Object.keys(gate).sort()).toEqual(["gate", "scope", "source", "state"]);
    }
  });

  it("keeps Run A a command outcome rather than a provider verdict", async () => {
    const facts = (await client().qualificationStatus(DEFAULT_SCOPE)).payload!.facts;
    const state = (id: string) => facts.find((fact) => fact.fact_id === id)?.state.code;
    expect(state("run-a")).toBe("COMPLETED_ONCE");
    expect(state("provider-tests")).toBe("UNEVALUATED");
    expect(state("data-quality")).toBe("NOT_ESTABLISHED");
    expect(state("provider-selected")).toBe("NONE");
    expect(state("provider-entitlement")).toBe("UNKNOWN");
    expect(state("run-a-retry")).toBe("NOT_AUTHORIZED");
    expect(state("backtesting")).toBe("NOT_STARTED");
  });
});

/* ================================================================= SCOPE ISOLATION */

describe("scope isolation across the C4 read models", () => {
  it("returns no payload at all under an unpopulated environment", async () => {
    for (const environment of ["PAPER", "LIVE"] as const) {
      const reads = await Promise.all([
        client().performanceSeries(demo({ environment })),
        client().attention(demo({ environment })),
        client().whatChanged(demo({ environment })),
        client().qualificationStatus(demo({ environment })),
      ]);
      for (const envelope of reads) {
        expect(envelope.payload).toBeUndefined();
        expect(envelope.availability).toBe("NOT_IMPLEMENTED");
        expect(envelope.maturity_stage).toBeUndefined();
        expect(envelope.watermark).toBeUndefined();
      }
    }
  });

  it("keeps the change variant out of the shared scope key and in the comparison's own read", async () => {
    // Two variants are two different ANSWERS from the same read model.
    const valid = await client().whatChanged(demo({ changes: "valid" }));
    const none = await client().whatChanged(demo({ changes: "none" }));
    expect(valid.payload?.entries.length).toBeGreaterThan(0);
    expect(none.payload?.entries).toHaveLength(0);
  });

  it("admits the whole C4 surface at the public edge, and refuses nothing it should not", async () => {
    const envelopes = await Promise.all([
      client().executiveOverview(demo()),
      client().attention(demo()),
      client().whatChanged(demo()),
      client().performanceSeries(demo()),
      client().qualificationStatus(demo()),
    ]);
    for (const envelope of envelopes) {
      expect(envelope.classification).toBe("PUBLIC_SAFE");
      expect(["SYNTHETIC", "REPOSITORY_TRACKED"]).toContain(envelope.provenance);
      expect(envelope.source_refs.total.value).toBe(0);
    }
    // The empty source-reference list still counts itself.
    expect(emptyRefList(AS_OF).total.unit).toBe("COUNT");
    expect(pinsOf().model_version).toBeDefined();
  });

  it("refuses a qualification payload relabelled to a maturity the mapping forbids", async () => {
    const good = await client().qualificationStatus(DEFAULT_SCOPE);
    for (const maturity of ["AUTOMATED_PAPER", "MICRO_LIVE", "SCALED_LIVE"] as const) {
      expect(() =>
        admit(
          "QualificationStatus",
          qualificationStatusEnvelope,
          { ...good, maturity_stage: maturity },
          "PUBLIC_EDGE",
        ),
      ).toThrow(ContractViolationError);
    }
  });
});
