import { describe, expect, it } from "vitest";

import { tradeDetailEnvelope } from "@/contracts/portfolio-models";
import {
  candidateDetailEnvelope,
  candidateFunnelEnvelope,
  candidateSummaryEnvelope,
  forbiddenCandidateUnit,
  missedOpportunityEnvelope,
} from "@/contracts/signal-models";
import {
  ORDER_SIDES,
  halfEven,
  sideSign,
  slippageHundredthBps,
} from "@/contracts/execution-models";
import { C3_METRIC_DICTIONARY, hundredths } from "@/contracts/values";
import { isValueBearing } from "@/contracts/validity";
import { BRAIN_DECISION_STATES, DOWNSTREAM_STAGES } from "@/contracts/vocabularies";
import { readModelKey } from "@/data/client/query-keys";
import {
  CANDIDATE_DETAIL_IDENTITY,
  CANDIDATE_FUNNEL_IDENTITY,
  MISSED_OPPORTUNITY_IDENTITY,
  READ_MODEL_IDENTITIES,
} from "@/data/client/read-model-identity";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import {
  BENCHMARK_INDEX,
  BOOK,
  MISSING_RISK_RECORD_TRADE,
  MULTI_EXIT_TRADE,
  PARTIAL_PATH_TRADE,
  bookSessions,
  centsToDecimal,
} from "@/data/fixtures/book";
import type { BookTrade } from "@/data/fixtures/book";
import {
  SHORT_LIFECYCLE_TRADE,
  attributionCents,
  hasExecutionRecord,
  resolvedFills,
} from "@/data/fixtures/execution";
import { CANDIDATE_RECORDS, missedRecords } from "@/data/fixtures/signals";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";

/**
 * The C6 read models, their invariants, and the fixture they are projected from.
 *
 * EVERY EXPECTED VALUE IS COMPUTED INDEPENDENTLY of the projection that produced it. Where a
 * rule is error-prone in a specific direction — a slippage sign, a subject mismatch, an AI
 * reference clearing a block — the test carries a NEGATIVE CONTROL asserting that the retired
 * or forbidden rule gives a DIFFERENT answer, so the assertion distinguishes the two rather
 * than passing under both.
 */

const ORIGIN = "2026-09-06T13:00:00.000Z";
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };
const PROJECT = DEFAULT_SCOPE;

function client() {
  return new FixtureReadClient({ clock: fixedClock(ORIGIN) });
}

function tradeOf(tradeId: string): BookTrade {
  const found = BOOK.trades.find((trade) => trade.tradeId === tradeId);
  expect(found, tradeId).toBeDefined();
  return found as BookTrade;
}

/* ==================================================================== admission */

describe("C6 admission and scope isolation", () => {
  it("admits the four signals read models in the demonstration scenario", async () => {
    const read = client();
    const responses = [
      [await read.candidateFunnel(DEMO), candidateFunnelEnvelope],
      [await read.candidates(DEMO), candidateSummaryEnvelope],
      [await read.candidateDetail(DEMO, CANDIDATE_RECORDS[0].candidateId), candidateDetailEnvelope],
      [await read.missedOpportunities(DEMO), missedOpportunityEnvelope],
    ] as const;
    for (const [response, schema] of responses) {
      expect(schema.safeParse(response).success, response.entity_id).toBe(true);
      expect(response.payload, response.entity_id).toBeDefined();
      expect(response.provenance).toBe("SYNTHETIC");
      expect(response.classification).toBe("PUBLIC_SAFE");
      expect(response.access_scope).toBe("signals:read");
    }
  });

  it("reports every signals read model unavailable in project scope, and carries no payload", async () => {
    const read = client();
    for (const response of [
      await read.candidateFunnel(PROJECT),
      await read.candidates(PROJECT),
      await read.candidateDetail(PROJECT, CANDIDATE_RECORDS[0].candidateId),
      await read.missedOpportunities(PROJECT),
    ]) {
      expect(response.availability).toBe("NOT_IMPLEMENTED");
      expect(response.availability_reason).toBe("PRODUCER_NOT_IMPLEMENTED");
      expect(response.payload).toBeUndefined();
    }
  });

  it("carries no signals payload under an environment this application holds no facts for", async () => {
    const read = client();
    for (const environment of ["PAPER", "LIVE"] as const) {
      const scope = { ...DEMO, environment };
      const response = await read.candidateFunnel(scope);
      expect(response.availability).toBe("NOT_IMPLEMENTED");
      expect(response.payload).toBeUndefined();
      expect(response.maturity_stage).toBeUndefined();
    }
  });

  it("gives each signals read model its own cache entry under one access scope", () => {
    const keys = READ_MODEL_IDENTITIES.map((identity) =>
      readModelKey(identity, DEMO).join("|"),
    );
    expect(new Set(keys).size).toBe(keys.length);
    /* Two candidates are two entries: the identity is part of the key. */
    const first = readModelKey(CANDIDATE_DETAIL_IDENTITY, DEMO, ["demo-candidate-0001"]);
    const second = readModelKey(CANDIDATE_DETAIL_IDENTITY, DEMO, ["demo-candidate-0002"]);
    expect(first.join("|")).not.toBe(second.join("|"));
  });

  it("registers every metric the signals and execution payloads carry", async () => {
    const read = client();
    const responses = [
      await read.candidateFunnel(DEMO),
      await read.candidates(DEMO),
      await read.candidateDetail(DEMO, CANDIDATE_RECORDS[0].candidateId),
      await read.missedOpportunities(DEMO),
      await read.tradeDetail(DEMO, MULTI_EXIT_TRADE),
    ];
    const seen = new Set<string>();
    const walk = (value: unknown): void => {
      if (Array.isArray(value)) {
        value.forEach(walk);
        return;
      }
      if (value === null || typeof value !== "object") {
        return;
      }
      const record = value as Record<string, unknown>;
      if (typeof record.metric_id === "string" && typeof record.unit === "string") {
        seen.add(record.metric_id);
      }
      Object.values(record).forEach(walk);
    };
    responses.forEach(walk);
    expect(seen.size).toBeGreaterThan(20);
    for (const metricId of seen) {
      expect(C3_METRIC_DICTIONARY[metricId], metricId).toBeDefined();
    }
  });
});

/* ====================================================== the two axes stay apart */

describe("the Brain axis and the downstream axis", () => {
  it("renders the eight Brain states as a closed set, including the empty ones", async () => {
    const funnel = await client().candidateFunnel(DEMO);
    const states = (funnel.payload?.brain_axis ?? []).map((entry) => entry.state);
    expect(states).toEqual([...BRAIN_DECISION_STATES]);
    /* Every one of the eight is populated by this book, so none is vacuously satisfied. */
    for (const entry of funnel.payload?.brain_axis ?? []) {
      expect(typeof entry.count.value, entry.state).toBe("number");
      expect(entry.count.value as number, entry.state).toBeGreaterThan(0);
    }
  });

  it("renders every downstream stage, on one stated basis and over a stated population", async () => {
    const funnel = await client().candidateFunnel(DEMO);
    const payload = funnel.payload as NonNullable<typeof funnel.payload>;
    const axis = payload.downstream_axis;
    expect(axis.map((entry) => entry.stage)).toEqual([...DOWNSTREAM_STAGES]);
    /*
     * THE AXIS IS DEMONSTRATED, ON THE SAME TERMS THE BRAIN AXIS BESIDE IT IS.
     *
     * Area 6's accepted V1 availability is "SYNTHETIC demonstration; real candidates
     * NOT_IMPLEMENTED", and section 4.5 makes the downstream `count` a REQUIRED field. The
     * counts here come from declared risk decisions and recorded fills, not from a risk
     * engine or an order router -- neither of which exists.
     */
    const population = payload.downstream_population.count;
    expect(isValueBearing(population.availability)).toBe(true);
    const total = population.value as number;
    const bases = new Set(axis.map((entry) => entry.basis));
    expect(bases.size).toBe(1);
    for (const entry of axis) {
      expect(entry.basis).toBe("EVER_REACHED");
      /* An ever-reached axis overlaps: a filled order was also submitted. */
      expect(entry.overlapping).toBe(true);
      expect(isValueBearing(entry.availability)).toBe(isValueBearing(entry.count.availability));
      if (isValueBearing(entry.count.availability)) {
        expect(entry.count.value as number).toBeLessThanOrEqual(total);
      }
    }
    const at = (stage: string) =>
      (axis.find((entry) => entry.stage === stage)?.count.value as number) ?? 0;
    /* One decision is approved or declined, never both. */
    expect(at("RISK_APPROVED") + at("RISK_REJECTED")).toBeLessThanOrEqual(total);
    /*
     * THE OVERLAP IS REAL AND VISIBLE, and the counts do NOT decrease down the list: more
     * candidates were approved than had an order recorded, and one order passed through a
     * partially filled state on its way to being filled.
     */
    expect(at("RISK_APPROVED")).toBeGreaterThan(at("ORDER_FILLED"));
    expect(at("ORDER_PARTIALLY_FILLED")).toBeGreaterThan(0);
    expect(at("ORDER_PARTIALLY_FILLED")).toBeLessThan(at("ORDER_FILLED"));
    /* Nothing was rejected or cancelled by an order router, and that is a measured zero. */
    expect(at("ORDER_REJECTED")).toBe(0);
    expect(at("ORDER_CANCELLED")).toBe(0);
  });

  it("never admits a downstream stage into the Brain vocabulary, or the reverse", async () => {
    const candidates = await client().candidates(DEMO);
    for (const item of candidates.payload?.items ?? []) {
      expect(BRAIN_DECISION_STATES).toContain(item.brain_state);
      expect(DOWNSTREAM_STAGES).not.toContain(item.brain_state as never);
      const stage = item.downstream_stage.value;
      if (typeof stage === "string") {
        expect(DOWNSTREAM_STAGES).toContain(stage as never);
        expect(BRAIN_DECISION_STATES).not.toContain(stage as never);
      }
    }
  });

  it("refuses a downstream count a reader could not check", async () => {
    const funnel = await client().candidateFunnel(DEMO);
    const base = funnel.payload as NonNullable<typeof funnel.payload>;
    /* The served payload is admissible as it stands. */
    expect(candidateFunnelEnvelope.safeParse(funnel).success).toBe(true);

    /*
     * NEGATIVE CONTROLS. Each forgery is a DIFFERENT way a downstream count stops being
     * checkable, and each must be refused separately -- so the assertion above distinguishes
     * a coherent axis from any axis at all, rather than agreeing with whatever is produced.
     */
    const forge = (mutate: (payload: NonNullable<typeof funnel.payload>) => void) => {
      const payload = structuredClone(base);
      mutate(payload);
      return candidateFunnelEnvelope.safeParse({ ...funnel, payload });
    };

    /* A stage that exceeds the population it was counted over. */
    expect(
      forge((payload) => {
        payload.downstream_axis[0] = {
          ...payload.downstream_axis[0],
          count: { ...payload.downstream_axis[0].count, value: 9_999 },
        };
      }).success,
    ).toBe(false);

    /* A count with no population to divide by. */
    expect(
      forge((payload) => {
        payload.downstream_population = {
          ...payload.downstream_population,
          count: {
            ...payload.downstream_population.count,
            availability: "NOT_IMPLEMENTED",
            reason: "PRODUCER_NOT_IMPLEMENTED",
            value: undefined,
          },
        };
      }).success,
    ).toBe(false);

    /* Two bases on one axis: an ever-reached count beside a current-state one. */
    expect(
      forge((payload) => {
        payload.downstream_axis[0] = {
          ...payload.downstream_axis[0],
          basis: "CURRENT_STATE",
          overlapping: false,
        };
      }).success,
    ).toBe(false);

    /* An overlapping flag that contradicts the basis it travels with. */
    expect(
      forge((payload) => {
        payload.downstream_axis = payload.downstream_axis.map((entry) => ({
          ...entry,
          overlapping: false,
        }));
      }).success,
    ).toBe(false);

    /* A stage declared unavailable while still carrying a number. */
    expect(
      forge((payload) => {
        payload.downstream_axis[0] = {
          ...payload.downstream_axis[0],
          availability: "NOT_IMPLEMENTED",
          reason: "PRODUCER_NOT_IMPLEMENTED",
        };
      }).success,
    ).toBe(false);

    /* Approved and declined together exceeding the one population they partition. */
    expect(
      forge((payload) => {
        const total = payload.downstream_population.count.value as number;
        payload.downstream_axis = payload.downstream_axis.map((entry) =>
          entry.stage === "RISK_APPROVED" || entry.stage === "RISK_REJECTED"
            ? { ...entry, count: { ...entry.count, value: total } }
            : entry,
        );
      }).success,
    ).toBe(false);
  });
});

/* ================================================= counts, denominators, subjects */

describe("funnel counts and conversions", () => {
  it("partitions the consolidated stage exactly, however many reasons a candidate carries", async () => {
    const funnel = await client().candidateFunnel(DEMO);
    const payload = funnel.payload as NonNullable<typeof funnel.payload>;
    const consolidated = payload.stages.find((stage) => stage.stage === "CONSOLIDATED");
    /* Independently: one candidate record is one consolidated candidate. */
    expect(consolidated?.count.value).toBe(CANDIDATE_RECORDS.length);
    const axisTotal = payload.brain_axis.reduce(
      (total, entry) => total + (entry.count.value as number),
      0,
    );
    expect(axisTotal).toBe(CANDIDATE_RECORDS.length);
  });

  it("lets reason occurrences exceed the candidates that carry them, and says they overlap", async () => {
    const funnel = await client().candidateFunnel(DEMO);
    const payload = funnel.payload as NonNullable<typeof funnel.payload>;
    const blocked = payload.brain_axis.find((entry) => entry.state === "BLOCKED_BORROW");
    expect(blocked).toBeDefined();
    const reasonTotal = (blocked?.reasons ?? []).reduce(
      (total, reason) => total + (reason.count.value as number),
      0,
    );
    /*
     * The borrow-blocked candidate carries a primary reason AND two blocking reasons, one of
     * which repeats the primary — so the distinct codes outnumber the candidates.
     */
    expect(reasonTotal).toBeGreaterThan(blocked?.count.value as number);
    expect((blocked?.reasons ?? []).every((reason) => reason.overlapping)).toBe(true);
  });

  it("counts a candidate once however many module decisions consolidated into it", async () => {
    const funnel = await client().candidateFunnel(DEMO);
    const payload = funnel.payload as NonNullable<typeof funnel.payload>;
    const generated = payload.stages.find((stage) => stage.stage === "GENERATED");
    const expected = CANDIDATE_RECORDS.reduce(
      (total, record) => total + record.contributingDecisions,
      0,
    );
    expect(generated?.count.value).toBe(expected);
    /* And the two stages count DIFFERENT subjects, so nothing subtracts one from the other. */
    expect(generated?.subject).toBe("CANDIDATE_DECISIONS");
    expect(payload.stages.find((stage) => stage.stage === "CONSOLIDATED")?.subject).toBe(
      "CANDIDATES",
    );
    expect(expected).toBeGreaterThan(CANDIDATE_RECORDS.length);
  });

  it("carries a rate only where both stages count the same subject", async () => {
    const funnel = await client().candidateFunnel(DEMO);
    const payload = funnel.payload as NonNullable<typeof funnel.payload>;
    let comparable = 0;
    let refused = 0;
    for (const entry of payload.conversion) {
      /* Every conversion shows BOTH counts, so the rate is checkable rather than asserted. */
      expect(typeof entry.numerator.value).toBe("number");
      expect(typeof entry.denominator.value).toBe("number");
      if (entry.from_subject === entry.to_subject) {
        comparable += 1;
        expect(isValueBearing(entry.rate.availability), `${entry.from.code}`).toBe(true);
        /* Recomputed independently of the projection. */
        const expected = Math.round(
          ((entry.numerator.value as number) * 10_000) / (entry.denominator.value as number),
        );
        expect(hundredths(String(entry.rate.value))).toBe(expected);
      } else {
        refused += 1;
        expect(entry.comparable).toBe(false);
        expect(isValueBearing(entry.rate.availability)).toBe(false);
        expect(entry.rate.reason).toBe("NOT_DEFINED_FOR_SUBJECT");
      }
    }
    expect(comparable).toBeGreaterThan(0);
    expect(refused).toBeGreaterThan(0);
  });

  it("does not present READY_FOR_RISK_REVIEW as the end of a successful path", async () => {
    const funnel = await client().candidateFunnel(DEMO);
    const payload = funnel.payload as NonNullable<typeof funnel.payload>;
    /* The stage vocabulary contains no terminal success stage at all. */
    expect(payload.stages.map((stage) => stage.stage)).toEqual([
      "UNIVERSE",
      "ELIGIBLE",
      "GENERATED",
      "CONSOLIDATED",
    ]);
    /* And the ready state is one of eight peers on the axis, not a fifth stage. */
    const ready = payload.brain_axis.find(
      (entry) => entry.state === "READY_FOR_RISK_REVIEW",
    );
    expect(ready).toBeDefined();
    expect(payload.stages.some((stage) => String(stage.stage) === "READY_FOR_RISK_REVIEW")).toBe(
      false,
    );
  });
});

/* ================================================ no sizing reaches a candidate */

describe("a candidate carries no sizing and no execution authority", () => {
  it("carries no USD, SHARES or Money quantity anywhere in any candidate payload", async () => {
    const read = client();
    const summaries = await read.candidates(DEMO);
    expect(forbiddenCandidateUnit(summaries.payload)).toBeNull();
    for (const record of CANDIDATE_RECORDS) {
      const detail = await read.candidateDetail(DEMO, record.candidateId);
      expect(forbiddenCandidateUnit(detail.payload), record.candidateId).toBeNull();
    }
  });

  it("detects a dollar amount, a share count and a Money object anywhere in a structure", () => {
    /*
     * THE DETECTOR ITSELF, ON THE EXACT SHAPES §6.2 FORBIDS.
     *
     * Each is nested, because a position size introduced later would be nested. The last case
     * is the NEGATIVE CONTROL: a percentage distance is a property of the thesis and must NOT
     * be flagged, or the guard would refuse the risk basis the contract requires.
     */
    const money = { a: { b: [{ amount: "6302.00", currency: "USD" }] } };
    const dollars = { a: [{ unit: "USD", value: "400.00" }] };
    const shares = { a: { b: { unit: "SHARES", value: 115 } } };
    const permitted = { a: { b: { unit: "PERCENT", value: "3.87" } } };
    expect(forbiddenCandidateUnit(money)).toBe("USD");
    expect(forbiddenCandidateUnit(dollars)).toBe("USD");
    expect(forbiddenCandidateUnit(shares)).toBe("SHARES");
    expect(forbiddenCandidateUnit(permitted)).toBeNull();
  });

  it("strips a sizing field introduced into a candidate, so none can reach a screen", async () => {
    const detail = await client().candidateDetail(DEMO, CANDIDATE_RECORDS[0].candidateId);
    const forged = structuredClone(detail.payload) as NonNullable<typeof detail.payload>;
    /* The exact shape §6.2 forbids: a position size, wearing a plausible field name. */
    (forged.risk_context as unknown as Record<string, unknown>).position_value = {
      value: "6302.00",
      unit: "USD",
      availability: "AVAILABLE",
      reason: "NONE",
      metric_id: "pnl.combined",
      metric_definition_version: "metrics.v1",
    };
    expect(forbiddenCandidateUnit(forged)).toBe("USD");
    const parsed = candidateDetailEnvelope.safeParse({ ...detail, payload: forged });
    /*
     * THE EXCLUSION IS STRUCTURAL, AND THIS IS THE MECHANISM.
     *
     * The field is not part of the type, so the boundary DROPS it: what a consumer receives
     * carries no such quantity, whatever a producer sent. The `forbiddenCandidateUnit` guard
     * in the refinement is the second layer, against a field a later author DECLARES.
     */
    expect(parsed.success).toBe(true);
    const admitted = parsed.success ? parsed.data.payload : undefined;
    expect(
      (admitted?.risk_context as unknown as Record<string, unknown>).position_value,
    ).toBeUndefined();
    expect(forbiddenCandidateUnit(admitted)).toBeNull();
  });

  it("carries the invalidation level as a reference and the risk basis as a distance", async () => {
    const detail = await client().candidateDetail(DEMO, "demo-candidate-0001");
    const payload = detail.payload as NonNullable<typeof detail.payload>;
    expect(payload.invalidation_ref.ref_kind).toBe("evidence");
    expect(payload.risk_context.initial_planned_risk_basis.unit).toBe("PERCENT");
    expect(payload.risk_context.initial_planned_risk_basis.metric_id).toBe(
      "candidate.invalidation_distance",
    );
  });
});

/* ======================================================= AI never restores one */

describe("AI evidence removes candidates and never restores one", () => {
  it("carries no removing AI reference on a candidate with no deterministic objection", async () => {
    const read = client();
    for (const record of CANDIDATE_RECORDS.filter(
      (entry) => entry.state === "READY_FOR_RISK_REVIEW",
    )) {
      const detail = await read.candidateDetail(DEMO, record.candidateId);
      const payload = detail.payload as NonNullable<typeof detail.payload>;
      expect(payload.blocking_reasons, record.candidateId).toHaveLength(0);
      expect(
        payload.ai_evidence.some((entry) => entry.removes_candidate),
        record.candidateId,
      ).toBe(false);
    }
  });

  it("refuses a ready candidate whose block an AI reference claims to have cleared", async () => {
    const detail = await client().candidateDetail(DEMO, "demo-candidate-0001");
    const forged = structuredClone(detail.payload) as NonNullable<typeof detail.payload>;
    forged.ai_evidence[0] = { ...forged.ai_evidence[0], removes_candidate: true };
    /* NEGATIVE CONTROL: the exact combination §14.3 forbids is constructed and refused. */
    expect(candidateDetailEnvelope.safeParse({ ...detail, payload: forged }).success).toBe(false);
  });

  it("states an AI absence as an absence rather than as an empty evidence list", async () => {
    const detail = await client().candidateDetail(DEMO, "demo-candidate-0013");
    const payload = detail.payload as NonNullable<typeof detail.payload>;
    expect(payload.brain_state).toBe("BLOCKED_AI");
    expect(payload.ai_availability).toBe("NOT_YET_AVAILABLE");
    expect(payload.ai_reason).toBe("UPSTREAM_INPUT_MISSING");
    expect(payload.ai_evidence).toHaveLength(0);
    const gap = payload.evidence_gaps.find((entry) => entry.expected.code === "AI_RESEARCH_EVIDENCE");
    expect(gap?.availability).toBe("NOT_YET_AVAILABLE");
  });

  it("qualifies stale AI evidence rather than discarding or trusting it", async () => {
    const detail = await client().candidateDetail(DEMO, "demo-candidate-0015");
    const payload = detail.payload as NonNullable<typeof detail.payload>;
    expect(payload.ai_availability).toBe("STALE");
    expect(payload.ai_reason).toBe("UPSTREAM_INPUT_STALE");
    expect(payload.ai_evidence.length).toBeGreaterThan(0);
  });

  it("records AI evidence that removed a candidate, on the candidate it removed", async () => {
    const detail = await client().candidateDetail(DEMO, "demo-candidate-0012");
    const payload = detail.payload as NonNullable<typeof detail.payload>;
    expect(payload.brain_state).toBe("BLOCKED_CONTRADICTION");
    expect(payload.contradictions.length).toBeGreaterThan(0);
    expect(payload.ai_evidence.some((entry) => entry.removes_candidate)).toBe(true);
  });

  it("carries model, prompt, schema, publish and observation provenance on every AI reference", async () => {
    const read = client();
    for (const record of CANDIDATE_RECORDS) {
      const detail = await read.candidateDetail(DEMO, record.candidateId);
      const payload = detail.payload as NonNullable<typeof detail.payload>;
      expect(payload.ai_evidence_refs.items).toHaveLength(payload.ai_evidence.length);
      for (const entry of payload.ai_evidence) {
        expect(entry.model_version.length).toBeGreaterThan(0);
        expect(entry.prompt_version.length).toBeGreaterThan(0);
        expect(entry.schema_version.length).toBeGreaterThan(0);
        expect(typeof entry.published_at.value).toBe("string");
        expect(typeof entry.observed_at.value).toBe("string");
        /* A source is published before this system observes it, never after. */
        expect(String(entry.published_at.value) <= String(entry.observed_at.value)).toBe(true);
      }
    }
  });
});

/* ================================================= an unknown identity is refused */

describe("an unknown candidate", () => {
  it("returns an honest not-found state and never another candidate", async () => {
    /*
     * The journal was searched by a producer that exists for this scope and holds no such
     * candidate, which ADR-0030 R9 states is `REFERENT_NOT_FOUND` and never inapplicability.
     */
    const response = await client().candidateDetail(DEMO, "demo-candidate-does-not-exist");
    expect(response.availability).toBe("NOT_YET_AVAILABLE");
    expect(response.availability_reason).toBe("REFERENT_NOT_FOUND");
    expect(response.payload).toBeUndefined();
    expect(response.entity_id).toContain("does-not-exist");
  });

  it("serves each candidate under its own identity", async () => {
    const read = client();
    for (const record of CANDIDATE_RECORDS.slice(0, 4)) {
      const detail = await read.candidateDetail(DEMO, record.candidateId);
      expect(detail.payload?.candidate_id).toBe(record.candidateId);
    }
  });
});

/* ============================================ decision time versus follow-up time */

describe("missed opportunities keep decision-time and outcome evidence apart", () => {
  it("registers the measurement window at the decision, before any path was read", async () => {
    const missed = await client().missedOpportunities(DEMO);
    for (const item of missed.payload?.items ?? []) {
      expect(item.window.registered_at.value, item.miss_id).toBe(item.decided_at.value);
      expect(item.window.from, item.miss_id).toBe(String(item.decided_at.value));
      /* The follow-up path starts at the decision and never before it. */
      const first = item.follow_up_series?.points[0]?.t;
      expect(String(first) >= item.window.from.slice(0, 10), item.miss_id).toBe(true);
    }
  });

  it("reports a detection-to-decision delay from two recorded instants", async () => {
    const missed = await client().missedOpportunities(DEMO);
    for (const item of missed.payload?.items ?? []) {
      const detected = Date.parse(String(item.detected_at.value));
      const decided = Date.parse(String(item.decided_at.value));
      expect(item.decision_delay.unit).toBe("SECONDS");
      expect(item.decision_delay.value).toBe(Math.round((decided - detected) / 1000));
      expect(detected).toBeLessThanOrEqual(decided);
    }
  });

  it("states a watchlist expiry only for a watchlist candidate", async () => {
    const missed = await client().missedOpportunities(DEMO);
    for (const item of missed.payload?.items ?? []) {
      if (item.brain_state === "WATCHLIST") {
        expect(isValueBearing(item.expired_at.availability), item.miss_id).toBe(true);
      } else {
        expect(item.expired_at.availability, item.miss_id).toBe("NOT_APPLICABLE");
        expect(item.expired_at.reason, item.miss_id).toBe("NOT_DEFINED_FOR_SUBJECT");
      }
    }
  });

  it("names a cause for every miss, and journals a miss only where a cause was recorded", async () => {
    const missed = await client().missedOpportunities(DEMO);
    const items = missed.payload?.items ?? [];
    expect(items).toHaveLength(missedRecords().length);
    /* A candidate still being watched, with an open window, is NOT a missed opportunity. */
    const stillWatching = CANDIDATE_RECORDS.find(
      (record) => record.candidateId === "demo-candidate-0014",
    );
    expect(stillWatching?.missCause).toBeUndefined();
    expect(items.some((item) => item.candidate_ref.ref_id === "demo-candidate-0014")).toBe(false);
    for (const item of items) {
      expect(item.cause.code.length).toBeGreaterThan(0);
    }
  });

  it("records a downstream risk decline as a cause, not as a Brain state", async () => {
    const missed = await client().missedOpportunities(DEMO);
    const declined = (missed.payload?.items ?? []).find(
      (item) => item.candidate_ref.ref_id === "demo-candidate-0006",
    );
    expect(declined?.brain_state).toBe("READY_FOR_RISK_REVIEW");
    expect(declined?.cause.code).toBe("DOWNSTREAM_RISK_DECISION_DECLINED");
    /*
     * THE DECLINE IS A RECORDED DOWNSTREAM FACT, SO ITS REFERENCE RESOLVES.
     *
     * A cause of DOWNSTREAM_RISK_DECISION_DECLINED asserts that a risk decision was taken;
     * a reference that resolved to nothing would have been the journal describing a decision
     * whose record it also said could not exist.
     */
    const detail = await client().candidateDetail(DEMO, "demo-candidate-0006");
    expect(detail.payload?.downstream_refs.risk_decision.resolution).toBe("AUTHORIZED_READ");
    /*
     * AND THE NEGATIVE CONTROL: a candidate the Brain left ready that was never handed
     * downstream at all has no decision, and its reference resolves to nothing.
     */
    const never = await client().candidateDetail(DEMO, "demo-candidate-0016");
    expect(never.payload?.brain_state).toBe("READY_FOR_RISK_REVIEW");
    /*
     * THE REFERENCE STAYS VISIBLE AND DECLARES THE SAME RESOLUTION.
     *
     * `risk_decision` resolves by AUTHORIZED_READ and its row lists nothing else, so
     * the candidate that was never handed downstream declares exactly what the
     * declined one does (R3). The absence lands on the value-bearing field the
     * target would have filled — the summary's `downstream_stage` — as
     * REFERENT_NOT_FOUND, which is R9's rule and not PRODUCER_NOT_IMPLEMENTED.
     */
    expect(never.payload?.downstream_refs.risk_decision.resolution).toBe(
      "AUTHORIZED_READ",
    );
    const summaries = await client().candidates(DEMO);
    const row = (summaries.payload?.items ?? []).find(
      (item) => item.candidate_id === "demo-candidate-0016",
    );
    expect(row?.downstream_stage.availability).toBe("NOT_YET_AVAILABLE");
    expect(row?.downstream_stage.reason).toBe("REFERENT_NOT_FOUND");
  });
});

/* ================================================= hindsight is not achievable profit */

describe("counterfactuals, windows and populations", () => {
  it("measures the counterfactual at the registered window's close, never at the best point", async () => {
    const missed = await client().missedOpportunities(DEMO);
    for (const item of missed.payload?.items ?? []) {
      if (!isValueBearing(item.counterfactual.availability)) {
        continue;
      }
      const counterfactual = hundredths(String(item.counterfactual.value)) as number;
      const favourable = hundredths(String(item.favourable_movement.value)) as number;
      /*
       * THE NEGATIVE CONTROL FOR HINDSIGHT.
       *
       * The favourable excursion is the best point in the path and is never below the
       * close-to-close movement. At least one row must show them DIFFERING, or "we did not
       * pick the best exit" would be a claim no assertion here distinguishes.
       */
      expect(favourable).toBeGreaterThanOrEqual(Math.max(0, counterfactual));
    }
    const differing = (missed.payload?.items ?? []).filter((item) => {
      if (!isValueBearing(item.counterfactual.availability)) {
        return false;
      }
      return (
        (hundredths(String(item.favourable_movement.value)) as number) !==
        (hundredths(String(item.counterfactual.value)) as number)
      );
    });
    expect(differing.length).toBeGreaterThan(0);
  });

  it("never serves a money counterfactual, because no approved sizing basis exists", async () => {
    const missed = await client().missedOpportunities(DEMO);
    for (const item of missed.payload?.items ?? []) {
      expect(item.counterfactual_money.unit).toBe("USD");
      expect(isValueBearing(item.counterfactual_money.availability), item.miss_id).toBe(false);
      expect(item.counterfactual_money.reason).toBe("POLICY_REFERENCE_MISSING");
      expect(item.counterfactual_money.value).toBeUndefined();
    }
  });

  it("refuses a money counterfactual introduced into a row", async () => {
    const missed = await client().missedOpportunities(DEMO);
    const forged = structuredClone(missed.payload) as NonNullable<typeof missed.payload>;
    forged.items[0] = {
      ...forged.items[0],
      counterfactual_money: {
        ...forged.items[0].counterfactual_money,
        availability: "AVAILABLE",
        reason: "NONE",
        value: "1240.00",
      },
    };
    expect(missedOpportunityEnvelope.safeParse({ ...missed, payload: forged }).success).toBe(false);
  });

  it("renders an incomplete follow-up path PARTIAL and excludes it from the evaluable population", async () => {
    const missed = await client().missedOpportunities(DEMO);
    const partial = (missed.payload?.items ?? []).filter(
      (item) => item.price_path_completeness === "PARTIAL",
    );
    expect(partial.length).toBeGreaterThan(0);
    for (const item of partial) {
      for (const metric of [
        item.counterfactual,
        item.favourable_movement,
        item.adverse_movement,
      ]) {
        expect(metric.availability, item.miss_id).toBe("PARTIAL");
        expect(metric.reason, item.miss_id).toBe("PRICE_PATH_INCOMPLETE");
        /* A missing bar is a QUALIFICATION, not a zero. */
        expect(metric.value, item.miss_id).not.toBeUndefined();
      }
      expect(item.population, item.miss_id).toBeUndefined();
      expect(item.follow_up_series?.completeness).toBe("PARTIAL");
    }
  });

  it("refuses an AVAILABLE path-dependent value over an incomplete path", async () => {
    const missed = await client().missedOpportunities(DEMO);
    const forged = structuredClone(missed.payload) as NonNullable<typeof missed.payload>;
    const index = forged.items.findIndex((item) => item.price_path_completeness === "PARTIAL");
    expect(index).toBeGreaterThanOrEqual(0);
    forged.items[index] = {
      ...forged.items[index],
      counterfactual: {
        ...forged.items[index].counterfactual,
        availability: "AVAILABLE",
        reason: "NONE",
      },
    };
    expect(missedOpportunityEnvelope.safeParse({ ...missed, payload: forged }).success).toBe(false);
  });

  it("computes a false-positive rate over a defined population and refuses the false-negative rate", async () => {
    const missed = await client().missedOpportunities(DEMO);
    const rates = missed.payload?.rates ?? [];
    const positive = rates.find((rate) => rate.kind === "FALSE_POSITIVE");
    const negative = rates.find((rate) => rate.kind === "FALSE_NEGATIVE");
    expect(positive?.population).toBeDefined();
    expect(isValueBearing(positive?.rate.availability ?? "ERROR")).toBe(true);
    /* Recomputed: the denominator is the evaluable population, not the whole page. */
    const evaluable = (missed.payload?.items ?? []).filter(
      (item) => item.price_path_completeness === "COMPLETE",
    );
    expect(positive?.denominator.value).toBe(evaluable.length);
    expect(evaluable.length).toBeLessThan((missed.payload?.items ?? []).length);

    expect(negative?.population).toBeUndefined();
    expect(isValueBearing(negative?.rate.availability ?? "AVAILABLE")).toBe(false);
    expect(negative?.rate.reason).toBe("NOT_DEFINED_FOR_SUBJECT");
    expect(negative?.note).toBeDefined();
  });

  it("refuses a rate whose population nobody defined", async () => {
    const missed = await client().missedOpportunities(DEMO);
    const forged = structuredClone(missed.payload) as NonNullable<typeof missed.payload>;
    const index = forged.rates.findIndex((rate) => rate.kind === "FALSE_NEGATIVE");
    forged.rates[index] = {
      ...forged.rates[index],
      rate: {
        ...forged.rates[index].rate,
        availability: "AVAILABLE",
        reason: "NONE",
        value: "0.12",
      },
    };
    expect(missedOpportunityEnvelope.safeParse({ ...missed, payload: forged }).success).toBe(false);
  });

  it("compares two arms only when every dimension of them agrees", async () => {
    const missed = await client().missedOpportunities(DEMO);
    const comparisons = missed.payload?.comparisons ?? [];
    expect(comparisons.length).toBe(2);
    const compatible = comparisons.find((entry) => entry.comparable);
    const refused = comparisons.find((entry) => !entry.comparable);
    expect(compatible).toBeDefined();
    expect(refused).toBeDefined();

    expect(compatible?.arms).toBeDefined();
    const [takenArm, missedArm] = compatible?.arms as NonNullable<typeof compatible>["arms"];
    expect(takenArm.arm).toBe("TAKEN");
    expect(missedArm.arm).toBe("MISSED");
    expect(takenArm.cost_treatment).toBe(missedArm.cost_treatment);
    expect(takenArm.window.from).toBe(missedArm.window.from);
    expect(takenArm.window.to).toBe(missedArm.window.to);
    expect(takenArm.outcome_basis.code).toBe(missedArm.outcome_basis.code);
    expect(takenArm.information_profile.code).toBe(missedArm.information_profile.code);
    /* The difference is recomputed independently of the projection. */
    expect(hundredths(String(compatible?.difference.value))).toBe(
      (hundredths(String(takenArm.outcome.value)) as number) -
        (hundredths(String(missedArm.outcome.value)) as number),
    );

    /* The refused pair states its incompatibility and carries no difference at all. */
    expect(refused?.refusal).toBeDefined();
    expect(isValueBearing(refused?.difference.availability ?? "AVAILABLE")).toBe(false);
    expect(refused?.arms).toBeDefined();
    const [left, right] = refused?.arms as NonNullable<typeof refused>["arms"];
    expect(left.cost_treatment === right.cost_treatment).toBe(false);
  });

  it("refuses a difference between two arms it has declared incomparable", async () => {
    const missed = await client().missedOpportunities(DEMO);
    const forged = structuredClone(missed.payload) as NonNullable<typeof missed.payload>;
    const index = forged.comparisons.findIndex((entry) => !entry.comparable);
    forged.comparisons[index] = {
      ...forged.comparisons[index],
      difference: {
        ...forged.comparisons[index].difference,
        availability: "AVAILABLE",
        reason: "NONE",
        value: "3.10",
      },
    };
    expect(missedOpportunityEnvelope.safeParse({ ...missed, payload: forged }).success).toBe(false);
  });

  it("refuses a comparison that calls two differing arms comparable", async () => {
    const missed = await client().missedOpportunities(DEMO);
    const forged = structuredClone(missed.payload) as NonNullable<typeof missed.payload>;
    const index = forged.comparisons.findIndex((entry) => !entry.comparable);
    forged.comparisons[index] = { ...forged.comparisons[index], comparable: true };
    expect(missedOpportunityEnvelope.safeParse({ ...missed, payload: forged }).success).toBe(false);
  });
});

/* ==================================================== the complete trade lifecycle */

describe("the complete trade lifecycle", () => {
  it("carries orders, fills, protection and reconciliation only where a record was declared", async () => {
    const read = client();
    const recorded = await read.tradeLifecycle(DEMO, MULTI_EXIT_TRADE);
    const kinds = (recorded.payload?.events ?? []).map((event) => event.event_kind.code);
    for (const kind of [
      "ORDER_SUBMITTED_RECORDED",
      "ORDER_ACKNOWLEDGED_RECORDED",
      "FILL_RECORDED",
      "PROTECTIVE_ORDER_PLACED",
      "PROTECTIVE_ORDER_AMENDED",
      "PROTECTIVE_ORDER_CANCELLED",
      "BROKER_RECONCILIATION_RECORDED",
    ]) {
      expect(kinds, kind).toContain(kind);
    }

    /* A trade with NO declared record manufactures none of it. */
    const unrecorded = await read.tradeLifecycle(DEMO, MISSING_RISK_RECORD_TRADE);
    expect(hasExecutionRecord(MISSING_RISK_RECORD_TRADE)).toBe(false);
    const unrecordedKinds = (unrecorded.payload?.events ?? []).map(
      (event) => event.event_kind.code,
    );
    for (const kind of ["ORDER_SUBMITTED_RECORDED", "FILL_RECORDED", "PROTECTIVE_ORDER_PLACED"]) {
      expect(unrecordedKinds, kind).not.toContain(kind);
    }
    const absent = (unrecorded.payload?.absent_kinds ?? []).map((entry) => entry.kind.code);
    expect(absent).toContain("INDIVIDUAL_FILL");
    expect(absent).toContain("PROTECTIVE_ORDER_PLACED");
  });

  it("orders events by event time and retains a late observation where it happened", async () => {
    const lifecycle = await client().tradeLifecycle(DEMO, "demo-trade-arb-0001");
    const events = lifecycle.payload?.events ?? [];
    for (let index = 1; index < events.length; index += 1) {
      expect(events[index].event_time >= events[index - 1].event_time).toBe(true);
    }
    const late = events.filter((event) => event.observed_time > event.event_time);
    expect(late.length).toBe(1);
    /* Three hours late, and sitting at the instant it happened rather than at its arrival. */
    expect(
      Date.parse(late[0].observed_time) - Date.parse(late[0].event_time),
    ).toBe(3 * 3_600_000);
    const index = events.indexOf(late[0]);
    const byArrival = [...events].sort((left, right) =>
      left.observed_time.localeCompare(right.observed_time),
    );
    /* NEGATIVE CONTROL: ordering by arrival gives a DIFFERENT position for that event. */
    expect(byArrival.indexOf(late[0])).not.toBe(index);
  });

  it("distinguishes a partially filled order from a partial position exit", async () => {
    const read = client();
    /* One order, two fills: the first is PARTIAL, the second completes it. */
    const arb = await read.tradeLifecycle(DEMO, "demo-trade-arb-0001");
    const arbEvents = arb.payload?.events ?? [];
    const partialFill = arbEvents.find(
      (event) => event.event_kind.code === "PARTIAL_FILL_RECORDED",
    );
    expect(partialFill?.downstream_stage).toBe("ORDER_PARTIALLY_FILLED");
    const completing = arbEvents.find((event) => event.event_kind.code === "FILL_RECORDED");
    expect(completing?.downstream_stage).toBe("ORDER_FILLED");
    /* The position was never partly exited: the trade is open and has no exit at all. */
    expect(tradeOf("demo-trade-arb-0001").exits).toHaveLength(0);

    /* And the converse: an order that FILLED COMPLETELY while reducing a position. */
    const cir = await read.tradeLifecycle(DEMO, "demo-trade-cir-0003");
    const cirEvents = cir.payload?.events ?? [];
    const partialExit = cirEvents.find(
      (event) => event.event_kind.code === "PARTIAL_EXIT_RECORDED",
    );
    expect(partialExit?.downstream_stage).toBe("ORDER_FILLED");
    expect(
      cirEvents.some((event) => event.downstream_stage === "ORDER_PARTIALLY_FILLED"),
    ).toBe(false);
    expect(tradeOf("demo-trade-cir-0003").status).toBe("PARTIALLY_EXITED");
  });

  it("closes a trade by its remaining balance after several partial exits", async () => {
    const trade = tradeOf(MULTI_EXIT_TRADE);
    expect(trade.exits.length).toBe(3);
    expect(trade.status).toBe("CLOSED");
    const lifecycle = await client().tradeLifecycle(DEMO, MULTI_EXIT_TRADE);
    const events = lifecycle.payload?.events ?? [];
    const partial = events.filter((event) => event.event_kind.code === "PARTIAL_EXIT_RECORDED");
    const final = events.filter((event) => event.event_kind.code === "EXIT_RECORDED");
    expect(partial).toHaveLength(2);
    expect(final).toHaveLength(1);
    /*
     * NEGATIVE CONTROL FOR "PARTIAL OR FINAL IS DECIDED BY WHAT IS LEFT".
     *
     * The final exit (45) is LARGER than the second partial (30), so a rule comparing the
     * exit quantity against the entry quantity, or against the previous exit, would classify
     * these differently. What decides it is the remaining balance, and nothing else.
     */
    expect(final[0].quantity).toBeGreaterThan(partial[1].quantity);
    expect(final[0].quantity).toBeLessThan(trade.stages[0].shares);
    const released = trade.exits.reduce((total, exit) => total + exit.shares, 0);
    expect(released).toBe(trade.sharesAcquired);
    /* ONE trade in the ledger, however many exits it took. */
    const ledger = await client().trades(DEMO);
    expect(
      (ledger.payload?.items ?? []).filter((item) => item.trade_id === MULTI_EXIT_TRADE),
    ).toHaveLength(1);
  });

  it("appends a correction that references the event it corrects, and never mutates it", async () => {
    const lifecycle = await client().tradeLifecycle(DEMO, MULTI_EXIT_TRADE);
    const events = lifecycle.payload?.events ?? [];
    const correction = events.find((event) => event.correction_of !== undefined);
    expect(correction).toBeDefined();
    const corrected = events.find(
      (event) => event.event_id === correction?.correction_of?.ref_id,
    );
    /* Both are present: the corrected event was NOT removed or overwritten. */
    expect(corrected).toBeDefined();
    expect(corrected?.price.value).not.toBe(correction?.price.value);
    expect(Date.parse(correction?.event_time ?? "")).toBeGreaterThan(
      Date.parse(corrected?.event_time ?? ""),
    );
    /* And a trade with no correction says the query ran and found none. */
    const absent = (lifecycle.payload?.absent_kinds ?? []).map((entry) => entry.kind.code);
    expect(absent).not.toContain("CORRECTION_APPENDED");
    const other = await client().tradeLifecycle(DEMO, "demo-trade-cir-0003");
    const otherAbsent = other.payload?.absent_kinds ?? [];
    const corrections = otherAbsent.find((entry) => entry.kind.code === "CORRECTION_APPENDED");
    expect(corrections?.availability).toBe("EMPTY_VERIFIED");
  });

  it("names a missing lifecycle stage rather than inferring it", async () => {
    const lifecycle = await client().tradeLifecycle(DEMO, "demo-trade-nvl-0002");
    const kinds = (lifecycle.payload?.events ?? []).map((event) => event.event_kind.code);
    /* This trade has orders, fills and protection — and nobody reconciled it. */
    expect(kinds).toContain("FILL_RECORDED");
    expect(kinds).not.toContain("BROKER_RECONCILIATION_RECORDED");
    const absent = lifecycle.payload?.absent_kinds ?? [];
    const reconciliation = absent.find((entry) => entry.kind.code === "BROKER_RECONCILIATION");
    expect(reconciliation?.availability).toBe("NOT_YET_AVAILABLE");
    expect(reconciliation?.reason).toBe("UPSTREAM_INPUT_MISSING");
    /* And the detail carries no reconciliation reference for it. */
    const detail = await client().tradeDetail(DEMO, "demo-trade-nvl-0002");
    expect(detail.payload?.reconciliation_refs.items).toHaveLength(0);
  });

  it("never reports a protective-order event as a fill", async () => {
    const lifecycle = await client().tradeLifecycle(DEMO, MULTI_EXIT_TRADE);
    for (const event of lifecycle.payload?.events ?? []) {
      if (event.event_kind.code.startsWith("PROTECTIVE_ORDER")) {
        expect(event.downstream_stage, event.event_id).not.toBe("ORDER_FILLED");
        expect(event.downstream_stage, event.event_id).not.toBe("ORDER_PARTIALLY_FILLED");
      }
    }
  });
});

/* ============================================================= execution quality */

describe("slippage, sides and the arithmetic behind them", () => {
  it("signs every side so an adverse buy and an adverse sell both read positive", () => {
    /* The four hand-calculated cases of §12.3.1, in hundredths of a basis point. */
    expect(slippageHundredthBps("BUY_TO_OPEN", 100_10, 100_00)).toBe(1_000);
    expect(slippageHundredthBps("SELL_TO_CLOSE", 99_90, 100_00)).toBe(1_000);
    expect(slippageHundredthBps("BUY_TO_OPEN", 99_95, 100_00)).toBe(-500);
    expect(slippageHundredthBps("SELL_TO_CLOSE", 100_05, 100_00)).toBe(-500);
    /* A cover is a BUY and an open short is a SELL: the sign follows the side. */
    expect(sideSign("BUY_TO_COVER")).toBe(1);
    expect(sideSign("SELL_TO_OPEN")).toBe(-1);
    expect(new Set(ORDER_SIDES).size).toBe(4);
    /*
     * NEGATIVE CONTROL FOR THE MISSING SIGN.
     *
     * Without `side_sign`, an adverse buy and an adverse sell average to ZERO. With it they
     * average to +10 bps. The two rules give different answers on this pair.
     */
    const unsignedBuy = Math.round(((100_10 - 100_00) / 100_00) * 1_000_000);
    const unsignedSell = Math.round(((99_90 - 100_00) / 100_00) * 1_000_000);
    expect((unsignedBuy + unsignedSell) / 2).toBe(0);
    const signedBuy = slippageHundredthBps("BUY_TO_OPEN", 100_10, 100_00) as number;
    const signedSell = slippageHundredthBps("SELL_TO_CLOSE", 99_90, 100_00) as number;
    expect((signedBuy + signedSell) / 2).toBe(1_000);
  });

  it("multiplies by ten thousand, so a ratio is not mistaken for basis points", () => {
    /* One percent is 100 basis points, which is 10,000 hundredths of one. */
    expect(slippageHundredthBps("BUY_TO_OPEN", 101_00, 100_00)).toBe(10_000);
    /* NEGATIVE CONTROL: the un-multiplied quotient is four orders of magnitude smaller. */
    expect((101_00 - 100_00) / 100_00).toBe(0.01);
  });

  it("refuses a division by a zero reference price", () => {
    expect(slippageHundredthBps("BUY_TO_OPEN", 100_00, 0)).toBeNull();
  });

  it("rounds half to even, once, at the declared scale", () => {
    expect(halfEven(5, 2)).toBe(2);
    expect(halfEven(7, 2)).toBe(4);
    expect(halfEven(-5, 2)).toBe(-2);
    expect(halfEven(1, 3)).toBe(0);
  });

  it("keeps a short's order sides opposite to its position direction", async () => {
    expect(SHORT_LIFECYCLE_TRADE).not.toBeNull();
    const tradeId = SHORT_LIFECYCLE_TRADE as string;
    const trade = tradeOf(tradeId);
    expect(trade.direction).toBe("SHORT");
    const detail = await client().tradeDetail(DEMO, tradeId);
    const fills = detail.payload?.fill_quality ?? [];
    expect(fills.length).toBe(2);
    /* A short OPENS with a sell and CLOSES with a buy. */
    expect(fills[0].side).toBe("SELL_TO_OPEN");
    expect(fills[1].side).toBe("BUY_TO_COVER");
    /* And the long demonstration is the mirror image. */
    const long = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const longFills = long.payload?.fill_quality ?? [];
    expect(longFills[0].side).toBe("BUY_TO_OPEN");
    expect(longFills[longFills.length - 1].side).toBe("SELL_TO_CLOSE");
  });

  it("weights a multi-fill order so its fills reconcile with the ledger price", async () => {
    const trade = tradeOf("demo-trade-arb-0001");
    const days = BOOK.trades.length > 0 ? sessionsFor() : [];
    const fills = resolvedFills(trade, days);
    expect(fills).toHaveLength(2);
    const filled = fills.reduce((total, fill) => total + fill.shares, 0);
    expect(filled).toBe(trade.stages[0].shares);
    /* Independently: the quantity-weighted fill price IS the recorded entry price. */
    const weighted = fills.reduce((total, fill) => total + fill.shares * fill.priceCents, 0);
    expect(weighted).toBe(trade.stages[0].shares * trade.stages[0].priceCents);
    /* The two fills genuinely differ, so the weighting is doing work. */
    expect(fills[0].priceCents).not.toBe(fills[1].priceCents);

    const detail = await client().tradeDetail(DEMO, "demo-trade-arb-0001");
    const quality = detail.payload?.fill_quality ?? [];
    expect(quality).toHaveLength(2);
    for (const [index, record] of quality.entries()) {
      const expected = slippageHundredthBps(
        record.side,
        hundredths(String(record.fill_price.value)) as number,
        hundredths(String(record.reference_price.price.value)) as number,
      );
      expect(hundredths(String(record.slippage.value)), `fill ${index}`).toBe(expected);
    }
    /* One fill is favourable and one is adverse, so the sign is exercised in both directions. */
    const values = quality.map((record) => hundredths(String(record.slippage.value)) as number);
    expect(values.some((value) => value < 0)).toBe(true);
    expect(values.some((value) => value > 0)).toBe(true);
  });

  it("reports the aggregate below its declared minimum rather than computing it", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const aggregate = detail.payload?.execution_quality;
    expect(aggregate?.scope).toBe("AGGREGATE");
    expect(aggregate?.slippage.metric_id).toBe("slippage.aggregate");
    expect(aggregate?.slippage.availability).toBe("INSUFFICIENT_OBSERVATIONS");
    expect(aggregate?.slippage.reason).toBe("BELOW_MINIMUM_OBSERVATIONS");
    expect(aggregate?.minimum_observations.value).toBe(20);
    expect(aggregate?.observation_count.value).toBe(4);
    /* Every per-fill value beside it stays available: their minimum is one fill. */
    for (const record of detail.payload?.fill_quality ?? []) {
      expect(record.slippage.metric_id).toBe("slippage");
      expect(isValueBearing(record.slippage.availability)).toBe(true);
    }
    /* And no fill was silently excluded: the count is a measured zero. */
    expect(aggregate?.excluded_fills?.value).toBe(0);
  });

  it("refuses an aggregate computed below its declared minimum", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const forged = structuredClone(detail.payload) as NonNullable<typeof detail.payload>;
    const aggregate = forged.execution_quality as NonNullable<typeof forged.execution_quality>;
    forged.execution_quality = {
      ...aggregate,
      slippage: {
        ...aggregate.slippage,
        availability: "AVAILABLE",
        reason: "NONE",
        value: "4.20",
      },
    };
    expect(tradeDetailEnvelope.safeParse({ ...detail, payload: forged }).success).toBe(false);
  });

  it("states a clock source and accuracy on every latency it reports", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    for (const record of [
      ...(detail.payload?.fill_quality ?? []),
      detail.payload?.execution_quality,
    ]) {
      if (record === undefined) {
        continue;
      }
      expect(record.clock_source.code.length).toBeGreaterThan(0);
      expect(record.clock_accuracy.unit).toBe("SECONDS");
      expect(record.signal_to_order_latency.unit).toBe("SECONDS");
      expect(record.order_to_fill_latency.unit).toBe("SECONDS");
      expect(record.reference_price.name.code.length).toBeGreaterThan(0);
      expect(record.reference_price.at.length).toBeGreaterThan(0);
    }
  });
});

/** The session dates the fixture adapter projects over, rebuilt for a direct fixture call. */
function sessionsFor(): readonly string[] {
  const read = new FixtureReadClient({ clock: fixedClock(ORIGIN) });
  return bookSessions(read.sessionOriginMs);
}

/* ================================================= attribution and the benchmark */

describe("attribution and benchmark comparison", () => {
  it("decomposes a trade's outcome into components that sum to it exactly", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const attribution = detail.payload?.attribution as NonNullable<
      NonNullable<typeof detail.payload>["attribution"]
    >;
    const components = ["strategy", "factor", "regime", "execution", "cost"] as const;
    const total = components.reduce(
      (sum, key) => sum + (hundredths(String(attribution[key].value)) as number),
      0,
    );
    const trade = tradeOf(MULTI_EXIT_TRADE);
    /* Independently: the outcome is realized plus unrealized, in cents. */
    expect(total).toBe(trade.realizedCents + trade.unrealizedCents);
    /* A closed, finalized decomposition says so; finalization is a recorded event. */
    expect(attribution.state).toBe("FINAL");
  });

  it("labels an open trade's decomposition provisional", async () => {
    const detail = await client().tradeDetail(DEMO, "demo-trade-arb-0001");
    expect(detail.payload?.attribution.state).toBe("PROVISIONAL");
  });

  it("attributes nothing on a trade nobody attributed", async () => {
    const detail = await client().tradeDetail(DEMO, "demo-trade-nvl-0002");
    const attribution = detail.payload?.attribution as NonNullable<
      NonNullable<typeof detail.payload>["attribution"]
    >;
    for (const key of ["strategy", "factor", "regime", "execution", "cost"] as const) {
      expect(isValueBearing(attribution[key].availability), key).toBe(false);
      expect(attribution[key].value, key).toBeUndefined();
    }
    expect(attributionCents(tradeOf("demo-trade-nvl-0002"))).toBeNull();
  });

  it("aligns the benchmark to exactly the boundaries the trade used", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const payload = detail.payload as NonNullable<typeof detail.payload>;
    const trade = tradeOf(MULTI_EXIT_TRADE);
    expect(payload.benchmark_window?.from).toBe(payload.summary.entry_time);
    const points = payload.benchmark_series?.points ?? [];
    expect(points.length).toBe(trade.lastSession - trade.stages[0].session + 1);
    /* The first point is a measured zero: the movement is stated SINCE the entry. */
    expect(hundredths(String(points[0].v.value))).toBe(0);
    /* Independently recomputed from the index the book owns. */
    const base = BENCHMARK_INDEX[trade.stages[0].session];
    const expected = Math.round(
      ((BENCHMARK_INDEX[trade.lastSession] - base) * 10_000) / base,
    );
    expect(hundredths(String(payload.benchmark_movement.value))).toBe(expected);
    expect(payload.benchmark_basis).toBe("PRICE_RETURN");
    expect(payload.benchmark_label).toBeDefined();
  });

  it("refuses a benchmark movement stated against no series", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const forged = structuredClone(detail.payload) as NonNullable<typeof detail.payload>;
    delete forged.benchmark_series;
    expect(tradeDetailEnvelope.safeParse({ ...detail, payload: forged }).success).toBe(false);
  });

  it("refuses a benchmark window that does not open where the trade did", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const forged = structuredClone(detail.payload) as NonNullable<typeof detail.payload>;
    forged.benchmark_window = {
      ...(forged.benchmark_window as NonNullable<typeof forged.benchmark_window>),
      from: "2020-01-02T21:00:00.000Z",
    };
    expect(tradeDetailEnvelope.safeParse({ ...detail, payload: forged }).success).toBe(false);
  });
});

/* ============================================== retained risk and no leakage */

describe("retained per-stage risk survives the complete lifecycle", () => {
  it("keeps the original entry facts unchanged on a trade that added", async () => {
    const detail = await client().tradeDetail(DEMO, "demo-trade-nvl-0002");
    const summary = detail.payload?.summary as NonNullable<
      NonNullable<typeof detail.payload>["summary"]
    >;
    const trade = tradeOf("demo-trade-nvl-0002");
    expect(summary.shares_at_entry).toBe(trade.stages[0].shares);
    expect(hundredths(String(summary.entry_price.value))).toBe(trade.stages[0].priceCents);
    expect(summary.shares_acquired).toBe(trade.sharesAcquired);
    /* The R denominator is the SUM of the retained stage records, recomputed here. */
    const expected = trade.stages.reduce(
      (total, stage) =>
        total + stage.shares * Math.abs(stage.priceCents - stage.invalidationCents),
      0,
    );
    expect(summary.r_denominator?.amount).toBe(centsToDecimal(expected));
    expect((summary.add_planned_risk ?? []).length).toBe(trade.stages.length - 1);
  });

  it("leaves initial planned risk untouched by a protective-order amendment", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const trade = tradeOf(MULTI_EXIT_TRADE);
    const record = detail.payload?.summary.initial_planned_risk.record;
    /* Independently: the entry-time record, at the entry-time invalidation level. */
    const expected = trade.stages[0].shares * Math.abs(
      trade.stages[0].priceCents - trade.stages[0].invalidationCents,
    );
    expect(record?.risk_money.amount).toBe(centsToDecimal(expected));
    expect(record?.reference_price.amount).toBe(centsToDecimal(trade.stages[0].priceCents));
    /* The lifecycle DID move the protective level, twice, and the record did not follow. */
    const lifecycle = await client().tradeLifecycle(DEMO, MULTI_EXIT_TRADE);
    const amendments = (lifecycle.payload?.events ?? []).filter(
      (event) => event.event_kind.code === "PROTECTIVE_ORDER_AMENDED",
    );
    expect(amendments.length).toBeGreaterThanOrEqual(2);
    for (const amendment of amendments) {
      expect(hundredths(String(amendment.price.value))).not.toBe(
        trade.stages[0].invalidationCents,
      );
    }
  });

  it("reports no remaining exposure on a closed trade rather than a zero", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const wrapper = detail.payload?.summary.open_planned_risk;
    expect(wrapper?.availability).toBe("NOT_APPLICABLE");
    expect(wrapper?.reason).toBe("NOT_DEFINED_FOR_SUBJECT");
    expect(wrapper?.record).toBeUndefined();
    /* And its retained entry record is still there, unchanged. */
    expect(detail.payload?.summary.initial_planned_risk.record).toBeDefined();
  });
});

/* ======================================================= joins and destinations */

describe("the four concepts stay on separate screens", () => {
  it("resolves a journaled candidate by endpoint and leaves the rest unresolvable", async () => {
    const withCandidate = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    expect(withCandidate.payload?.candidate_ref.resolution).toBe("ENDPOINT");
    const candidateId = withCandidate.payload?.candidate_ref.ref_id as string;
    const candidate = await client().candidateDetail(DEMO, candidateId);
    /* The reference is followable: it resolves to a real payload. */
    expect(candidate.payload?.candidate_id).toBe(candidateId);

    /*
     * A TRADE WITH NO JOURNALED CANDIDATE DECLARES THE SAME RESOLUTION.
     *
     * It used to declare `UNRESOLVABLE_V1`, which says the PRODUCER does not exist —
     * false here, and refused by ADR-0030 R6, because the candidate producer is
     * implemented for this scope and merely holds no record for this trade. The
     * absence moves to the value-bearing place that can carry it: the `gaps` entry.
     */
    const without = await client().tradeDetail(DEMO, MISSING_RISK_RECORD_TRADE);
    expect(without.payload?.candidate_ref.resolution).toBe("ENDPOINT");
    const candidateGap = without.payload?.gaps.find(
      (gap) => gap.expected.code === "CANDIDATE_AND_THESIS",
    );
    expect(candidateGap?.availability).toBe("NOT_YET_AVAILABLE");
    expect(candidateGap?.reason).toBe("REFERENT_NOT_FOUND");
  });

  it("carries the audit and reconciliation joins without pretending they resolve", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const payload = detail.payload as NonNullable<typeof detail.payload>;
    /*
     * THE AUDIT JOIN NOW RESOLVES, AND THE PROPERTY THIS TEST PROTECTS IS UNCHANGED.
     *
     * C6 asserted an empty list because no audit producer existed for any scope. C8 implements
     * one, so this trade's references are bound to the events that actually name it — and the
     * enduring rule is the one below: a reference is carried with the resolution its kind's
     * §4.3 row permits, and the audit trail stays a SEPARATE read model on a SEPARATE screen
     * rather than being folded into this payload.
     */
    expect(payload.audit_refs.items.length).toBeGreaterThan(0);
    for (const reference of payload.audit_refs.items) {
      expect(reference.ref_kind).toBe("audit_event");
      /* §4.3 resolves an `audit_event` under an AUTHORIZED_READ on `audit:read`. */
      expect(reference.resolution).toBe("AUTHORIZED_READ");
      /* The join is a REFERENCE: no audit payload is embedded in this trade's detail. */
      expect(Object.keys(payload)).not.toContain("audit_events");
    }
    /* A trade the timeline never mentions carries an empty list, and that is a true answer. */
    const unmentioned = await client().tradeDetail(DEMO, PARTIAL_PATH_TRADE);
    expect(unmentioned.payload?.audit_refs.items).toHaveLength(0);
    /*
     * THE RISK DECISION RESOLVES, BECAUSE THE BOOK RECORDS ONE FOR THIS TRADE.
     *
     * §4.3 resolves a `risk_decision` under an AUTHORIZED_READ, and the joined record travels
     * with it. A trade whose sizing nobody recorded is a separate case, asserted below.
     */
    expect(payload.risk_decision_ref.resolution).toBe("AUTHORIZED_READ");
    expect(payload.risk_decision?.decision_id).toBe(payload.risk_decision_ref.ref_id);
    /*
     * `reconciliation` resolves by a catalogued GET and its row lists no other member,
     * so ENDPOINT is the only resolution it may declare (R3).
     */
    for (const reference of payload.reconciliation_refs.items) {
      expect(reference.resolution).toBe("ENDPOINT");
    }
    /* Order, fill and protective references DO resolve, through the lifecycle endpoint. */
    for (const reference of [
      ...payload.order_refs.items,
      ...payload.fill_refs.items,
      ...payload.protection_refs.items,
    ]) {
      expect(reference.resolution).toBe("ENDPOINT");
    }
    expect(payload.order_refs.items.length).toBeGreaterThan(0);
  });

  it("still names the stages a complete detail does not carry", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const gaps = (detail.payload?.gaps ?? []).map((gap) => gap.expected.code);
    /*
     * A RECORDED DECISION IS NOT A GAP, AND AN ABSENT ONE STILL IS.
     *
     * This trade's decision was recorded, so declaring it missing would contradict both the
     * joined record here and the outcome `/risk` lists for it. The audit trail is Area 26's
     * and genuinely does not exist.
     */
    expect(gaps).not.toContain("RISK_ENGINE_DECISION");
    expect(gaps).toContain("IMMUTABLE_AUDIT_EVENTS");
    for (const gap of detail.payload?.gaps ?? []) {
      expect(isValueBearing(gap.availability), gap.expected.code).toBe(false);
    }
    /* A trade with no execution record names five more. */
    const sparse = await client().tradeDetail(DEMO, MISSING_RISK_RECORD_TRADE);
    const sparseGaps = (sparse.payload?.gaps ?? []).map((gap) => gap.expected.code);
    expect(sparseGaps).toContain("ORDER_AND_FILL_MECHANICS");
    expect(sparseGaps).toContain("EXECUTION_QUALITY");
    expect(sparseGaps.length).toBeGreaterThan(gaps.length);
    /*
     * AND A TRADE NOBODY SIZED ON RECORD STILL NAMES THE ABSENCE.
     *
     * The negative control for the assertion above: the gap is refused where a decision
     * exists and reported where none does, so the two are distinguished rather than the
     * gap simply having been deleted.
     */
    expect(sparseGaps).toContain("RISK_ENGINE_DECISION");
    expect(sparse.payload?.risk_decision).toBeUndefined();
    /*
     * The reference stays visible and declares the one resolution its row lists; the
     * gap beside it is what says no record was written, as REFERENT_NOT_FOUND.
     */
    expect(sparse.payload?.risk_decision_ref.resolution).toBe("AUTHORIZED_READ");
    const riskGap = sparse.payload?.gaps.find(
      (gap) => gap.expected.code === "RISK_ENGINE_DECISION",
    );
    expect(riskGap?.availability).toBe("NOT_YET_AVAILABLE");
    expect(riskGap?.reason).toBe("REFERENT_NOT_FOUND");
  });
});

/* ================================================= determinism and provenance */

describe("the signals fixtures are deterministic and obviously synthetic", () => {
  it("produces an identical payload on two reads at the same instant", async () => {
    const first = await client().candidateFunnel(DEMO);
    const second = await client().candidateFunnel(DEMO);
    expect(JSON.stringify(first.payload)).toBe(JSON.stringify(second.payload));
  });

  it("names only obviously fictional securities", async () => {
    const candidates = await client().candidates(DEMO);
    for (const item of candidates.payload?.items ?? []) {
      expect(item.security.symbol.startsWith("DEMO.")).toBe(true);
    }
    const missed = await client().missedOpportunities(DEMO);
    for (const item of missed.payload?.items ?? []) {
      expect(item.security.symbol.startsWith("DEMO.")).toBe(true);
    }
  });

  it("states the population and the window every count was drawn over", async () => {
    const read = client();
    const funnel = await read.candidateFunnel(DEMO);
    expect(funnel.payload?.population.code.length).toBeGreaterThan(0);
    expect(funnel.payload?.scope.code.length).toBeGreaterThan(0);
    expect(funnel.payload?.window.calendar.code.length).toBeGreaterThan(0);
    const missed = await read.missedOpportunities(DEMO);
    expect(missed.payload?.population.code.length).toBeGreaterThan(0);
    expect(missed.payload?.counterfactual_method.code.length).toBeGreaterThan(0);
    for (const item of missed.payload?.items ?? []) {
      expect(item.assumptions.length).toBeGreaterThan(3);
      expect(item.cost_treatment).toBe("GROSS");
    }
  });

  it("keeps the ledger population at its declared page size after the C6 addition", async () => {
    const ledger = await client().trades(DEMO);
    expect(ledger.payload?.page.truncated).toBe(false);
    expect(ledger.payload?.page.total.value).toBe(BOOK.trades.length);
    expect(BOOK.trades.length).toBe(200);
  });

  it("keys the funnel and the missed ledger under separate cache entries", () => {
    expect(readModelKey(CANDIDATE_FUNNEL_IDENTITY, DEMO).join("|")).not.toBe(
      readModelKey(MISSED_OPPORTUNITY_IDENTITY, DEMO).join("|"),
    );
  });
});
