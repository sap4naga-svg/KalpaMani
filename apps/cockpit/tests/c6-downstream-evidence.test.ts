import { describe, expect, it } from "vitest";

import { candidateDetailEnvelope } from "@/contracts/signal-models";
import { followReference } from "@/contracts/reference-access";
import { riskDecision } from "@/contracts/risk-decision";
import { isValueBearing } from "@/contracts/validity";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { BOOK, MULTI_EXIT_TRADE, bookSessions, centsToDecimal } from "@/data/fixtures/book";
import { entryOrderEvidence, hasExecutionRecord } from "@/data/fixtures/execution";
import { candidateRecord, riskDecisionFor } from "@/data/fixtures/signals";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";

/**
 * The downstream axis, and the two rules it exists to hold.
 *
 *   A TRADE REFERENCE IS NOT ORDER EVIDENCE   a candidate that became a trade tells you a
 *                                             position was opened. It tells you nothing about
 *                                             whether any order was submitted, acknowledged,
 *                                             partially filled or filled
 *   A RECORDED DECISION EXPLAINS THE SIZE     and only the size. The record is joined on the
 *                                             trade and its sizing never enters the candidate
 *
 * Every expected value is computed here rather than read back from the projection that
 * produced it, and each rule carries a NEGATIVE CONTROL asserting the retired or forbidden
 * shape gives a DIFFERENT answer — so the assertions distinguish the two rules rather than
 * passing under both.
 */

const ORIGIN = "2026-09-06T13:00:00.000Z";
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };
const SESSIONS = bookSessions(Date.parse(ORIGIN));

/** The resolving caller: full scope, and a classification it may read. */
/*
 * `initial_risk_ref` is kind `evidence`, whose 4.3 row names no scope of its own -- it reads
 * "the scope named on the reference", and a `Ref` has no field to name one in. So this is the
 * one shape where a caller-DECLARED scope is the available input, and it is declared here.
 */
const RESOLVING = {
  environment: "RESEARCH",
  provenance: "SYNTHETIC",
  heldScopes: ["signals:read", "risk:read"],
  declaredScope: "risk:read",
  readableClassifications: ["PUBLIC_SAFE"],
} as const;

function client() {
  return new FixtureReadClient({ clock: fixedClock(ORIGIN) });
}

/* ============================ the downstream stage is read, never inferred ============ */

describe("a trade reference is not order evidence", () => {
  it("does not report a fill for a candidate whose linked trade has no order record", async () => {
    const candidates = await client().candidates(DEMO);
    const items = candidates.payload?.items ?? [];
    /*
     * THE NEGATIVE CASE THIS RULE EXISTS FOR.
     *
     * This candidate was approved, a position was opened and the trade is in the book — and
     * nobody recorded an order. Under the retired rule the mere presence of a `tradeId`
     * returned ORDER_FILLED, which asserted a fill this book does not contain.
     */
    const linked = items.find((item) => item.candidate_id === "demo-candidate-0017");
    expect(linked).toBeDefined();
    const detail = await client().candidateDetail(DEMO, "demo-candidate-0017");
    const tradeRef = detail.payload?.downstream_refs.trade;
    /* The trade link is real and resolvable — and it is not order evidence. */
    expect(tradeRef?.resolution).toBe("ENDPOINT");
    expect(hasExecutionRecord(tradeRef?.ref_id ?? "")).toBe(false);
    expect(entryOrderEvidence(tradeRef?.ref_id ?? "")).toBeUndefined();
    /* So the stage stops at the last thing anybody actually wrote down. */
    expect(linked?.downstream_stage.value).toBe("RISK_APPROVED");
    expect(linked?.downstream_stage.value).not.toBe("ORDER_FILLED");
  });

  it("reports a fill only where the fills were recorded", async () => {
    const read = client();
    const candidates = await read.candidates(DEMO);
    let filled = 0;
    for (const item of candidates.payload?.items ?? []) {
      if (item.downstream_stage.value !== "ORDER_FILLED") {
        continue;
      }
      filled += 1;
      const detail = await read.candidateDetail(DEMO, item.candidate_id);
      const tradeId = detail.payload?.downstream_refs.trade.ref_id ?? "";
      expect(hasExecutionRecord(tradeId)).toBe(true);
      expect(entryOrderEvidence(tradeId)?.filled).toBe(true);
    }
    expect(filled).toBeGreaterThan(0);
  });

  it("never reports a downstream stage for a candidate with no recorded decision", async () => {
    const read = client();
    const candidates = await read.candidates(DEMO);
    let withDecision = 0;
    let without = 0;
    for (const item of candidates.payload?.items ?? []) {
      const detail = await read.candidateDetail(DEMO, item.candidate_id);
      /*
       * THE DISCRIMINATOR IS THE RECORD, AND IT USED TO BE THE RESOLUTION.
       *
       * This read `resolution === "AUTHORIZED_READ"` as *a decision exists*. Under
       * ADR-0030 R6 both cases declare AUTHORIZED_READ — `risk_decision`'s row lists
       * nothing else — so the resolution can no longer answer it, and reading
       * existence off it was the conflation that rule removes.
       *
       * The book's own record is the source of truth, which makes this a stronger
       * check than before: the projection is compared against the fixture rather than
       * against another projected field.
       */
      const record = candidateRecord(item.candidate_id);
      const resolved = record?.downstream !== undefined;
      /*
       * The stage and the decision agree in BOTH directions: no stage without a decision, and
       * no decision without a stage.
       */
      expect(isValueBearing(item.downstream_stage.availability), item.candidate_id).toBe(
        resolved,
      );
      /* The reference stays VISIBLE either way, and states the same resolution. */
      expect(detail.payload?.downstream_refs.risk_decision.resolution).toBe(
        "AUTHORIZED_READ",
      );
      /* An absent stage says REFERENT_NOT_FOUND, and never PRODUCER_NOT_IMPLEMENTED. */
      if (!resolved) {
        expect(item.downstream_stage.availability).toBe("NOT_YET_AVAILABLE");
        expect(item.downstream_stage.reason).toBe("REFERENT_NOT_FOUND");
      }
      if (resolved) {
        withDecision += 1;
      } else {
        without += 1;
      }
    }
    /* Both populations are non-empty, so the assertion above is not vacuous either way. */
    expect(withDecision).toBeGreaterThan(0);
    expect(without).toBeGreaterThan(0);
  });

  it("keeps a partially filled ORDER apart from a partially exited POSITION", async () => {
    /*
     * One entry order filled in two parts; another filled at once while reducing the position.
     * They are different facts, and only the first ever reached ORDER_PARTIALLY_FILLED.
     */
    expect(entryOrderEvidence("demo-trade-arb-0001")?.partiallyFilled).toBe(true);
    expect(entryOrderEvidence("demo-trade-cir-0003")?.partiallyFilled).toBe(false);
    const funnel = await client().candidateFunnel(DEMO);
    const axis = funnel.payload?.downstream_axis ?? [];
    expect(axis.find((entry) => entry.stage === "ORDER_PARTIALLY_FILLED")?.count.value).toBe(1);
  });
});

/* ================================ the recorded risk decision ========================== */

describe("the risk decision explains the size, and never the opportunity", () => {
  it("resolves the reference and reconciles with the retained entry-stage record", async () => {
    const detail = await client().tradeDetail(DEMO, MULTI_EXIT_TRADE);
    const payload = detail.payload;
    const decision = payload?.risk_decision;
    expect(decision).toBeDefined();
    expect(payload?.risk_decision_ref.resolution).toBe("AUTHORIZED_READ");
    expect(payload?.risk_decision_ref.ref_id).toBe(decision?.decision_id);
    expect(decision?.outcome).toBe("APPROVED");

    /*
     * THE ARITHMETIC A READER CAN CHECK, done here by hand.
     *
     * shares x |reference − invalidation| is the risk the decision assigned, and §4.4 defines
     * the retained entry-stage record the same way — so the two agree to the cent.
     */
    const trade = BOOK.trades.find((entry) => entry.tradeId === MULTI_EXIT_TRADE);
    const stage = trade?.stages[0];
    const expectedCents =
      (stage?.shares ?? 0) * Math.abs((stage?.priceCents ?? 0) - (stage?.invalidationCents ?? 0));
    expect(expectedCents).toBeGreaterThan(0);
    expect(decision?.sizing.shares.value).toBe(stage?.shares);
    expect(decision?.sizing.reference_price.value).toBe(centsToDecimal(stage?.priceCents ?? 0));
    expect(decision?.sizing.invalidation_price.value).toBe(
      centsToDecimal(stage?.invalidationCents ?? 0),
    );
    expect(decision?.assigned_risk.value).toBe(centsToDecimal(expectedCents));
    /* And it agrees with the immutable record the summary already retained. */
    expect(payload?.summary.initial_planned_risk.record?.risk_money.amount).toBe(
      centsToDecimal(expectedCents),
    );
    /* Chronology: sized on or after the Brain decided, never before. */
    const record = candidateRecord("demo-candidate-0001");
    expect(Date.parse(decision?.decided_at ?? "")).toBeGreaterThanOrEqual(
      Date.parse(SESSIONS[record?.session ?? 0]),
    );
  });

  it("records a decline that assigns nothing, with the reasons it declined for", async () => {
    const detail = await client().candidateDetail(DEMO, "demo-candidate-0006");
    expect(detail.payload?.downstream_refs.risk_decision.resolution).toBe("AUTHORIZED_READ");
    const record = candidateRecord("demo-candidate-0006");
    const decision = riskDecisionFor(record!, SESSIONS, ORIGIN);
    expect(decision?.outcome).toBe("REJECTED");
    expect(decision?.rejection_reasons.length ?? 0).toBeGreaterThan(0);
    /* A refused position is not a position: nothing sized, nothing committed, nothing traced. */
    expect(isValueBearing(decision!.sizing.shares.availability)).toBe(false);
    expect(isValueBearing(decision!.assigned_risk.availability)).toBe(false);
    /*
     * BOTH REFERENCES STAY VISIBLE, AND NEITHER RESOLUTION CARRIES THE ABSENCE.
     *
     * `evidence` permits AUTHORIZED_READ alone and `trade` permits ENDPOINT, so a
     * declined decision declares exactly what an approved one does (R3). That it
     * retained no record and opened no trade is established by FOLLOWING them, and
     * the assertion below does precisely that.
     */
    expect(decision?.initial_risk_ref.resolution).toBe("AUTHORIZED_READ");
    expect(decision?.trade_ref.resolution).toBe("ENDPOINT");
    expect(
      followReference(
        "RiskDecision.initial_risk_ref",
        decision!.initial_risk_ref,
        RESOLVING,
        /* The producer exists for this scope, and it holds no such record to LOCATE. */
        { producer: "IMPLEMENTED" },
      ),
    ).toEqual({
      status: "UNAVAILABLE",
      availability: "NOT_YET_AVAILABLE",
      reason: "REFERENT_NOT_FOUND",
    });
  });

  it("refuses a decision whose two halves contradict each other", () => {
    const approved = riskDecisionFor(candidateRecord("demo-candidate-0001")!, SESSIONS, ORIGIN);
    const declined = riskDecisionFor(candidateRecord("demo-candidate-0006")!, SESSIONS, ORIGIN);
    expect(riskDecision.safeParse(approved).success).toBe(true);
    expect(riskDecision.safeParse(declined).success).toBe(true);

    /* NEGATIVE CONTROLS — each a different self-contradiction, refused separately. */
    /* An approval relabelled a decline, still carrying the size it assigned. */
    expect(riskDecision.safeParse({ ...approved, outcome: "REJECTED" }).success).toBe(false);
    /* An approval carrying a rejection reason. */
    expect(
      riskDecision.safeParse({
        ...approved,
        rejection_reasons: [approved!.outcome_reason],
      }).success,
    ).toBe(false);
    /* A decline that nonetheless assigned a size. */
    expect(riskDecision.safeParse({ ...declined, sizing: approved!.sizing }).success).toBe(false);
    /* A decline that assigned risk. */
    expect(
      riskDecision.safeParse({ ...declined, assigned_risk: approved!.assigned_risk }).success,
    ).toBe(false);
    /* A decline naming no reason. */
    expect(riskDecision.safeParse({ ...declined, rejection_reasons: [] }).success).toBe(false);
    /*
     * THE REMOVED CONTROL, AND WHAT REPLACES IT.
     *
     * This asserted that a declined decision carrying the APPROVED one's
     * `initial_risk_ref` is refused — but the only thing distinguishing the two was
     * the RESOLUTION, and ADR-0030 R3 gives `evidence` exactly one. The schema can no
     * longer tell them apart, and pretending otherwise would be a check that passes
     * for the wrong reason.
     *
     * The property is instead asserted where it is now true — at resolution time, in
     * the test above — and the negative control that still bites is a decline whose
     * reference names a kind its host field does not permit.
     */
    expect(
      riskDecision.safeParse({
        ...declined,
        initial_risk_ref: { ...declined!.initial_risk_ref, ref_kind: "trade" },
      }).success,
    ).toBe(false);
    /* ...and one whose resolution its kind does not list. */
    expect(
      riskDecision.safeParse({
        ...declined,
        initial_risk_ref: { ...declined!.initial_risk_ref, resolution: "UNRESOLVABLE_V1" },
      }).success,
    ).toBe(false);
  });

  it("never lets the sizing cross into the candidate payload", async () => {
    const detail = await client().candidateDetail(DEMO, "demo-candidate-0001");
    const serialized = JSON.stringify(detail.payload);
    /* The candidate carries the REFERENCE, and nothing the decision assigned. */
    expect(serialized).toContain("risk_decision");
    expect(serialized).not.toContain("assigned_risk");
    expect(serialized).not.toContain("sizing");
    expect(serialized).not.toContain("SHARES");
    expect(candidateDetailEnvelope.safeParse(detail).success).toBe(true);
  });

  it("keeps the risk snapshot's decision index consistent with the records", async () => {
    const snapshot = await client().riskSnapshot(DEMO);
    const listed = snapshot.payload?.decisions ?? [];
    expect(listed.length).toBeGreaterThan(0);
    /* The index carries the decline as well as the approvals, rather than approvals only. */
    const declined = listed.filter(
      (entry) => entry.outcome.code === "RISK_DECLINED_AT_THE_RECORDED_SIZE",
    );
    expect(declined.length).toBe(1);
    for (const entry of listed) {
      expect(entry.decision_ref.resolution).toBe("AUTHORIZED_READ");
      const candidateId = entry.decision_ref.ref_id.replace(/-risk-decision$/, "");
      const record = candidateRecord(candidateId);
      expect(record, candidateId).toBeDefined();
      /* Chronology: no decision is dated before the Brain decision it followed. */
      expect(Date.parse(entry.at)).toBeGreaterThanOrEqual(
        Date.parse(SESSIONS[record?.session ?? 0]),
      );
    }
  });
});
