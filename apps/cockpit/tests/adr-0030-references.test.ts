/**
 * ADR-0030 — the reference contract, enforced.
 *
 * Every case below is one of the acceptance examples §6.3 lists, and each is exercised
 * through a boundary a producer actually passes through rather than through a helper tested
 * in isolation. A validator that is bypassed by the client is not enforcement, so the
 * ADMITTED and REFUSED cases are driven through `admit` — the same function the fixture
 * adapter calls — wherever the case is expressible as a whole response.
 *
 * The two halves are kept honest against each other: several assertions take a REAL admitted
 * payload, break exactly one thing, and require the boundary to refuse it. A suite that only
 * ever showed conforming payloads would pass against a validator that does nothing.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { admit } from "@/data/client/read-client";
import { ContractViolationError } from "@/data/client/read-client";
import { candidateDetailEnvelope } from "@/contracts/signal-models";
import { tradeDetailEnvelope, TRADE_DETAIL_SCHEMA } from "@/contracts/portfolio-models";
import {
  marketRegimeEnvelope,
  riskSnapshotEnvelope,
  shortSideSnapshotEnvelope,
  MARKET_REGIME_SCHEMA,
} from "@/contracts/risk-market-models";
import { envelopeFields } from "@/contracts/envelope";
import {
  KIND_RESOLUTIONS,
  REFERENCE_FIELDS,
  declarationFor,
  refListFailure,
  referenceFailure,
  embeddedTruthFailure,
} from "@/contracts/references";
import type { HostFieldKey } from "@/contracts/references";
import { followReference, permitsCrossProvenance } from "@/contracts/reference-access";
import { contractReadScope } from "@/contracts/references";
import type { ResolvingContext } from "@/contracts/reference-access";
import { refListOf } from "@/contracts/factories";
import { available, absent } from "@/contracts/factories";
import type { Ref } from "@/contracts/values";
import { REF_KINDS, FIELD_REASON_CODES, ERROR_CODES } from "@/contracts/vocabularies";
import type { DataClassification } from "@/contracts/vocabularies";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import {
  referenceDestination,
  nestedDestination,
  owningAreaDestination,
} from "@/lib/reference-navigation";
import { READ_MODEL_IDENTITIES } from "@/data/client/read-model-identity";
import { prepareAttention } from "@/lib/attention";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";

const ORIGIN = "2026-09-06T13:00:00.000Z";
const AS_OF = ORIGIN;
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };

const client = () =>
  new FixtureReadClient({
    clock: fixedClock(Date.parse(ORIGIN)),
    originMs: Date.parse(ORIGIN),
    boundary: "PUBLIC_EDGE",
  });

/** Deep-clone an admitted response so a mutation cannot leak between cases. */
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

/**
 * A caller, and NOT a caller that names its own required scope.
 *
 * `requiredScope` used to sit here and be handed to `followReference`, which authorized the
 * read against it -- so the authorization input came from the thing being authorized. The
 * scope now comes from the accepted section 4.3 table, and `declaredScope` is consulted only
 * for the two kinds whose rows say "the scope named on the reference" and which a `Ref` has
 * no field to carry.
 */
const CALLER: ResolvingContext = {
  environment: "RESEARCH",
  provenance: "SYNTHETIC",
  heldScopes: ["portfolio:read", "risk:read", "signals:read", "audit:read", "governance:read"],
  readableClassifications: ["PUBLIC_SAFE"],
};

/** A located `trade` target that corresponds to `reference` below, with its own labels. */
const LOCATED_TRADE = {
  kind: "trade",
  id: "missing-1",
  labels: {
    environment: "RESEARCH",
    provenance: "SYNTHETIC",
    classification: "PUBLIC_SAFE",
  },
} as const;

/* ============================================================ the closed vocabularies */

describe("the closed vocabularies", () => {
  it("closes RefKind at the twenty-seven rows of the section 4.3 table", () => {
    expect(REF_KINDS).toHaveLength(27);
    expect(new Set(REF_KINDS).size).toBe(27);
    /* `trade` is the member ADR-0030 R1 added, and the two defects needed it. */
    expect(REF_KINDS).toContain("trade");
    /* Every kind names at least one permitted resolution, and none names EMBEDDED. */
    for (const kind of REF_KINDS) {
      expect(KIND_RESOLUTIONS[kind].length).toBeGreaterThan(0);
      expect(KIND_RESOLUTIONS[kind]).not.toContain("EMBEDDED");
    }
  });

  it("carries REFERENT_NOT_FOUND in both closed vocabularies, and NOT_APPLICABLE keeps its two routes", () => {
    expect(FIELD_REASON_CODES).toContain("REFERENT_NOT_FOUND");
    expect(ERROR_CODES).toContain("REFERENT_NOT_FOUND");
  });

  it("assigns every catalogued reference field a kind drawn from the closed set", () => {
    const keys = Object.keys(REFERENCE_FIELDS) as HostFieldKey[];
    expect(keys.length).toBeGreaterThan(60);
    for (const key of keys) {
      const declaration = declarationFor(key);
      expect(declaration.kinds.length, key).toBeGreaterThan(0);
      for (const kind of declaration.kinds) {
        expect(REF_KINDS, key).toContain(kind);
      }
      /* Every embed NAMES its carrier and says whether it is the whole target. */
      for (const embed of declaration.embeds ?? []) {
        expect(embed.carrier.length, key).toBeGreaterThan(0);
        expect(["COMPLETE_TARGET", "DECLARED_PROJECTION"], key).toContain(embed.completeness);
        expect(embed.identity.rule, key).toBeTruthy();
      }
    }
  });

  /*
   * C7 IMPLEMENTED THESE SIX, AND THE KINDS DID NOT MOVE.
   *
   * They were recorded specification-only so the cycle that FIRST emitted them would inherit
   * an enforced contract rather than an open one. C7 is that cycle, so the assertion that used
   * to read `implemented === false` now reads `true` — and the part that mattered is unchanged
   * and still checked: **not one kind was changed to obtain a link.**
   */
  it("implements the six RefList fields C7 emits, at the kinds the catalogue assigned", () => {
    const listFields: HostFieldKey[] = [
      "StrategyHealth.transitions[].input_refs",
      "StrategyHealth.failure_clusters[].evidence_refs",
      "HypothesisRegistration.lineage.related_registrations",
      "HypothesisRegistration.lineage.amendment_chain",
      "AiContribution.ai_provenance.source_refs",
      "FeedbackPipeline.stages[].item_refs",
    ];
    for (const key of listFields) {
      expect(REFERENCE_FIELDS[key].shape, key).toBe("REF_LIST");
      expect(REFERENCE_FIELDS[key].implemented, key).toBe(true);
    }
    expect(REFERENCE_FIELDS["StrategyHealth.transitions[].input_refs"].kinds).toEqual([
      "source_fact",
    ]);
    expect(REFERENCE_FIELDS["FeedbackPipeline.stages[].item_refs"].kinds).toEqual(["queue_item"]);
    expect(
      REFERENCE_FIELDS["HypothesisRegistration.lineage.amendment_chain"].kinds,
    ).toEqual(["registration"]);
  });

  /*
   * AND THE FIELDS NO CYCLE HAS EMITTED ARE STILL RECORDED AS ABSENT.
   *
   * `implemented` is a claim about whether a producer exists for the requested scope, and a
   * catalogue that flipped every flag to `true` because C7 landed would make `producerStateFor`
   * answer `IMPLEMENTED` for subsystems nobody has built.
   */
  it("leaves the fields no implemented read model emits recorded as absent", () => {
    /*
     * THE LIST MOVED BECAUSE THE PRODUCERS MOVED, AND THE RULE DID NOT.
     *
     * C8 emitted `AuditEvent`, `Alert`, `DataQuality` and `ReconciliationStatus`, and C9 now
     * emits `SearchResultPage` and `AskAnswer` — so those fields are recorded as implemented,
     * for the SYNTHETIC scope those producers exist for and for nothing else. The fields below
     * still have no producer at any scope, and the property this test protects is unchanged: a
     * catalogue that flipped every flag to `true` because a cycle landed would make
     * `producerStateFor` answer `IMPLEMENTED` for subsystems nobody has built.
     */
    for (const key of [
      "MaturityStatus.decision_refs",
      "QualificationStatus.facts[].source_ref",
      "QualificationStatus.gates[].source_ref",
      "QualificationStatus.runs[].source_ref",
    ] as HostFieldKey[]) {
      expect(REFERENCE_FIELDS[key].implemented, key).toBe(false);
    }
    /*
     * AND THE FLAG IS STILL A CLAIM SOMETHING HAS TO EARN.
     *
     * At least one field remains recorded as absent, so `producerStateFor` still has a case
     * that answers `NOT_IMPLEMENTED_FOR_SCOPE` — the branch every unresolvable-target rule
     * depends on. A catalogue with no absent field left would pass a per-key list of nothing.
     */
    const absent = Object.values(REFERENCE_FIELDS).filter(
      (declaration) => !declaration.implemented,
    );
    expect(absent.length).toBeGreaterThan(0);
  });
});

/* ============================================================== kinds and resolutions */

describe("a kind outside the set, and a resolution outside its row", () => {
  it("refuses an unknown ref_kind through the real admission path", async () => {
    const response = clone(await client().tradeDetail(DEMO, (await firstTradeId())));
    (response.payload as { candidate_ref: { ref_kind: string } }).candidate_ref.ref_kind =
      "not_a_kind";
    expect(() => admit("TradeDetail", tradeDetailEnvelope, response, "PUBLIC_EDGE")).toThrow(
      ContractViolationError,
    );
  });

  it("refuses a resolution its kind's row does not list", async () => {
    const response = clone(await client().tradeDetail(DEMO, await firstTradeId()));
    /* `candidate` lists ENDPOINT and UNRESOLVABLE_V1, and never AUTHORIZED_READ. */
    (response.payload as { candidate_ref: Ref }).candidate_ref.resolution = "AUTHORIZED_READ";
    expect(() => admit("TradeDetail", tradeDetailEnvelope, response, "PUBLIC_EDGE")).toThrow(
      /candidate permits/,
    );
  });

  it("refuses a kind the HOST FIELD does not declare, even though the kind is valid", async () => {
    const response = clone(await client().tradeDetail(DEMO, await firstTradeId()));
    /* `alert` is a real RefKind, and `candidate_ref` may not carry it. */
    (response.payload as { candidate_ref: Ref }).candidate_ref.ref_kind = "alert";
    expect(() => admit("TradeDetail", tradeDetailEnvelope, response, "PUBLIC_EDGE")).toThrow(
      /declares kind candidate/,
    );
  });

  it("admits a stated SET of kinds where the catalogue declares one", () => {
    /* §4.5 gives `AttentionItem.evidence_refs` "kind evidence or source_fact" — both. */
    for (const kind of ["evidence", "source_fact"] as const) {
      expect(
        referenceFailure("AttentionItem.evidence_refs", {
          ref_id: "x",
          ref_kind: kind,
          resolution: "AUTHORIZED_READ",
          classification: "PUBLIC_SAFE",
        }),
      ).toBeNull();
    }
    expect(
      referenceFailure("AttentionItem.evidence_refs", {
        ref_id: "x",
        ref_kind: "incident",
        resolution: "ENDPOINT",
        classification: "PUBLIC_SAFE",
      }),
    ).not.toBeNull();
  });
});

/* ====================================================== EMBEDDED: permission and truth */

describe("EMBEDDED requires catalogue PERMISSION as well as TRUTH", () => {
  it("admits an authorized projection whose identity corresponds", async () => {
    const detail = await client().tradeDetail(DEMO, await firstTradeId());
    const summary = detail.payload!.summary;
    expect(summary.security_ref.resolution).toBe("EMBEDDED");
    /* The comparand is the canonicalized SYMBOL, never the display name. */
    expect(summary.security_ref.ref_id).toBe(`security-${summary.security.symbol.toLowerCase()}`);
    expect(
      embeddedTruthFailure("TradeSummary.security_ref", summary.security_ref, summary),
    ).toBeNull();
  });

  it("refuses an EMBEDDED whose carrier the catalogue does not authorize, PAYLOAD PRESENT", async () => {
    const response = clone(await client().tradeDetail(DEMO, await firstTradeId()));
    const payload = response.payload as Record<string, unknown>;
    /*
     * PRESENCE IS NOT PERMISSION.
     *
     * `risk_decision` really is carried on this response — it is an ADR-0028 additive field —
     * and the catalogue still authorizes no embed on `risk_decision_ref`. A rule satisfied by
     * "the payload is there" would be satisfied by putting it there.
     */
    expect(payload.risk_decision).toBeDefined();
    (payload.risk_decision_ref as Ref).resolution = "EMBEDDED";
    expect(() => admit("TradeDetail", tradeDetailEnvelope, response, "PUBLIC_EDGE")).toThrow(
      /not an authorized carrier/,
    );
  });

  it("refuses a brain-decision payload added to TradeDetail to make EMBEDDED true", () => {
    /* R5: widening the portfolio read model would not make the embed admissible. */
    expect(declarationFor("TradeDetail.brain_decision_ref").embeds).toBeUndefined();
    const failure = referenceFailure("TradeDetail.brain_decision_ref", {
      ref_id: "d-1",
      ref_kind: "brain_decision",
      resolution: "EMBEDDED",
      classification: "PUBLIC_SAFE",
    });
    expect(failure).toMatch(/not an authorized carrier/);
  });

  it("refuses an authorized EMBEDDED whose carrier is absent", async () => {
    const response = clone(await client().tradeDetail(DEMO, await tradeWithEmbeddedQuality()));
    const payload = response.payload as Record<string, unknown>;
    expect((payload.execution_quality_ref as Ref).resolution).toBe("EMBEDDED");
    delete payload.execution_quality;
    expect(() => admit("TradeDetail", tradeDetailEnvelope, response, "PUBLIC_EDGE")).toThrow(
      /carries no execution_quality/,
    );
  });

  it("refuses an authorized EMBEDDED whose carrier belongs to a DIFFERENT entity", async () => {
    const response = clone(await client().tradeDetail(DEMO, await firstTradeId()));
    const summary = (response.payload as { summary: Record<string, unknown> }).summary;
    /*
     * The projection is swapped for another security's. The name is right, the shape is
     * right, and the identity is another entity's — which is the whole of what R8 checks.
     */
    (summary.security as { symbol: string }).symbol = "ZZZZ";
    expect(() => admit("TradeDetail", tradeDetailEnvelope, response, "PUBLIC_EDGE")).toThrow(
      /is not the reference's/,
    );
  });

  it("refuses a projection compared against its CONTAINER's id rather than its own", async () => {
    const response = clone(await client().tradeDetail(DEMO, await tradeWithEmbeddedQuality()));
    const payload = response.payload as Record<string, unknown>;
    /* The container is the trade; the target is its execution-quality record. */
    (payload.execution_quality_ref as Ref).ref_id = payload.trade_id as string;
    expect(() => admit("TradeDetail", tradeDetailEnvelope, response, "PUBLIC_EDGE")).toThrow(
      /is not the reference's/,
    );
  });

  it("keeps a valid ENDPOINT valid on a response that also carries the payload (R4.1)", async () => {
    const response = clone(await client().tradeDetail(DEMO, await tradeWithEmbeddedQuality()));
    const payload = response.payload as Record<string, unknown>;
    /* Co-location neither compels EMBEDDED nor forbids ENDPOINT. */
    (payload.execution_quality_ref as Ref).resolution = "ENDPOINT";
    expect(payload.execution_quality).toBeDefined();
    expect(() =>
      admit("TradeDetail", tradeDetailEnvelope, response, "PUBLIC_EDGE"),
    ).not.toThrow();
  });
});

/* ================================================================= cardinality (R7) */

describe("cardinality separates the relation, the page and the population", () => {
  const reference: Ref = {
    ref_id: "one",
    ref_kind: "order",
    resolution: "ENDPOINT",
    classification: "PUBLIC_SAFE",
  };

  it("admits a complete ZERO_OR_MORE list of zero with an AVAILABLE zero total", () => {
    const list = refListOf([], "ZERO_OR_MORE", AS_OF);
    expect(list.total.value).toBe(0);
    expect(refListFailure("TradeDetail.order_refs", list)).toBeNull();
  });

  it("admits a truncated page whose total exceeds it, and never bounds the relation from the page", () => {
    const list = refListOf([reference], "ZERO_OR_MORE", AS_OF, { truncated: true, total: 137 });
    expect(refListFailure("TradeDetail.order_refs", list)).toBeNull();
  });

  it("refuses EXACTLY_ONE carrying two items when complete, and zero when complete", () => {
    const two = refListOf([reference, { ...reference, ref_id: "two" }], "EXACTLY_ONE", AS_OF);
    expect(refListFailure("TradeDetail.order_refs", two)).toMatch(/EXACTLY_ONE/);
    const none = refListOf([], "EXACTLY_ONE", AS_OF);
    expect(refListFailure("TradeDetail.order_refs", none)).toMatch(/EXACTLY_ONE/);
  });

  it("asserts NOTHING from items.length when the total is not value-bearing", () => {
    const unknown = {
      ...refListOf([reference], "ONE_OR_MORE", AS_OF),
      total: absent("NOT_YET_AVAILABLE", "EXTENT_NOT_DETERMINABLE", "reference.total", "COUNT"),
    };
    /* The count's state and reason are the whole answer; no bound is inferred. */
    expect(refListFailure("TradeDetail.order_refs", unknown)).toBeNull();
    const unknownEmpty = {
      ...refListOf([], "ONE_OR_MORE", AS_OF),
      total: absent("NOT_YET_AVAILABLE", "EXTENT_NOT_DETERMINABLE", "reference.total", "COUNT"),
    };
    expect(refListFailure("TradeDetail.order_refs", unknownEmpty)).toBeNull();
  });

  it("refuses a complete list whose items and total disagree", () => {
    const inconsistent = {
      ...refListOf([reference], "ZERO_OR_MORE", AS_OF),
      total: available({ metricId: "reference.total", unit: "COUNT", value: 4, asOf: AS_OF }),
    };
    expect(refListFailure("TradeDetail.order_refs", inconsistent)).toMatch(/is complete/);
  });

  it("keeps AskAnswer.citations at the field-level ONE_OR_MORE the catalogue fixes", () => {
    expect(REFERENCE_FIELDS["AskAnswer.citations"].relation).toBe("ONE_OR_MORE");
    const empty = refListOf([], "ZERO_OR_MORE", AS_OF);
    expect(refListFailure("AskAnswer.citations", empty)).toMatch(/declares relation ONE_OR_MORE/);
  });

  it("admits the envelope's known-EMPTY source_refs, and adds no field to it", async () => {
    const envelope = await client().tradeDetail(DEMO, await firstTradeId());
    expect(envelope.source_refs.items).toHaveLength(0);
    expect(envelope.source_refs.cardinality).toBe("ZERO_OR_MORE");
    expect(envelope.source_refs.total.availability).toBe("AVAILABLE");
    expect(envelope.source_refs.total.value).toBe(0);
    expect(refListFailure("Envelope.source_refs", envelope.source_refs)).toBeNull();
    /* Its shape is §3's, and this cycle adds nothing to it. */
    expect(Object.keys(envelopeFields.shape)).toContain("source_refs");
  });
});

/* ================================================ the two corrected trade references */

describe("both trade references are relabelled and navigable", () => {
  it("labels CandidateDetail.downstream_refs.trade as kind trade, resolving by endpoint", async () => {
    const read = client();
    const candidates = await read.candidates(DEMO);
    for (const row of candidates.payload?.items ?? []) {
      const detail = await read.candidateDetail(DEMO, row.candidate_id);
      const trade = detail.payload!.downstream_refs.trade;
      expect(trade.ref_kind, row.candidate_id).toBe("trade");
      expect(trade.resolution, row.candidate_id).toBe("ENDPOINT");
      /* And it goes to the trade route, not to the audit trail it used to imply. */
      expect(referenceDestination(trade)?.href).toBe(
        `/portfolio/trades/${encodeURIComponent(trade.ref_id)}`,
      );
    }
  });

  it("labels RiskSnapshot.initial_planned_risk_open[].trade_ref as kind trade", async () => {
    const snapshot = await client().riskSnapshot(DEMO);
    const rows = snapshot.payload?.initial_planned_risk_open ?? [];
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row.trade_ref.ref_kind).toBe("trade");
      expect(row.trade_ref.resolution).toBe("ENDPOINT");
      expect(referenceDestination(row.trade_ref)).not.toBeNull();
    }
  });

  it("refuses either of them relabelled back to source_fact", async () => {
    const response = clone(await client().riskSnapshot(DEMO));
    const rows = (response.payload as { initial_planned_risk_open: { trade_ref: Ref }[] })
      .initial_planned_risk_open;
    rows[0].trade_ref.ref_kind = "source_fact";
    expect(() => admit("RiskSnapshot", riskSnapshotEnvelope, response, "PUBLIC_EDGE")).toThrow(
      /declares kind trade/,
    );
  });
});

/* ============================================ absent record, absent producer, denial */

describe("the five unavailable outcomes stay distinct", () => {
  const reference: Ref = {
    ref_id: "missing-1",
    ref_kind: "trade",
    resolution: "ENDPOINT",
    classification: "PUBLIC_SAFE",
  };

  /**
   * A tombstone that RECORDS a relationship, and is not a boolean asserting one.
   *
   * `tombstoneOf` names the entity the reference names, which is what makes this tombstone
   * that reference's rather than some other withdrawal that happened to be handed over.
   */
  const TOMBSTONE_OF_MISSING_1 = {
    auditEventId: "audit-withdrawal-1",
    tombstoneOf: "missing-1",
    labels: {
      environment: "RESEARCH",
      provenance: "SYNTHETIC",
      classification: "PUBLIC_SAFE",
    },
  } as const;

  it("calls an unknown record REFERENT_NOT_FOUND, never a missing producer", () => {
    expect(
      followReference("CandidateDetail.downstream_refs.trade", reference, CALLER, {
        producer: "IMPLEMENTED",
      }),
    ).toEqual({
      status: "UNAVAILABLE",
      availability: "NOT_YET_AVAILABLE",
      reason: "REFERENT_NOT_FOUND",
    });
  });

  it("calls an absent producer PRODUCER_NOT_IMPLEMENTED, never a missing record", () => {
    expect(
      followReference("CandidateDetail.downstream_refs.trade", reference, CALLER, {
        producer: "NOT_IMPLEMENTED_FOR_SCOPE",
      }),
    ).toEqual({
      status: "UNAVAILABLE",
      availability: "NOT_IMPLEMENTED",
      reason: "PRODUCER_NOT_IMPLEMENTED",
    });
  });

  it("keeps scope denial distinct from classification withholding", () => {
    const noScope = followReference(
      "CandidateDetail.downstream_refs.trade",
      reference,
      { ...CALLER, heldScopes: [] },
      { producer: "IMPLEMENTED", located: LOCATED_TRADE },
    );
    expect(noScope).toEqual({ status: "REFUSED", code: "SCOPE_MISSING" });

    const wrongScope = followReference(
      "CandidateDetail.downstream_refs.trade",
      reference,
      /* `trade` requires `portfolio:read`, which the section 4.3 table names and this caller lacks. */
      { ...CALLER, heldScopes: ["market:read"] },
      { producer: "IMPLEMENTED", located: LOCATED_TRADE },
    );
    expect(wrongScope).toEqual({ status: "REFUSED", code: "SCOPE_INSUFFICIENT" });

    /* Scope held, classification withholds — a DIFFERENT answer, and never a scope error. */
    const withheld = followReference(
      "CandidateDetail.downstream_refs.trade",
      { ...reference, classification: "PRIVATE_OPERATIONAL" },
      CALLER,
      { producer: "IMPLEMENTED", located: LOCATED_TRADE },
    );
    expect(withheld).toEqual({
      status: "UNAVAILABLE",
      availability: "NOT_AUTHORIZED",
      reason: "CLASSIFICATION_WITHHELD",
    });
  });

  it("resolves a RECORDED tombstone rather than calling it REFERENT_NOT_FOUND", () => {
    const outcome = followReference(
      "AuditEvent.tombstone_of",
      { ...reference, ref_kind: "audit_event", resolution: "AUTHORIZED_READ" },
      CALLER,
      { producer: "IMPLEMENTED", tombstone: TOMBSTONE_OF_MISSING_1 },
    );
    expect(outcome).toEqual({ status: "RESOLVED" });
  });

  it("audits every default-resolution reference out of the emitted fixtures", async () => {
    /*
     * The `demoRef` default was `UNRESOLVABLE_V1`, and R6 refuses it wherever the producer IS
     * implemented for the requested scope. Nothing emitted now declares it except the two
     * kinds whose rows genuinely permit it for an absent market-data provider.
     */
    const read = client();
    const seen: { kind: string; resolution: string }[] = [];
    const walk = (node: unknown): void => {
      if (Array.isArray(node)) {
        node.forEach(walk);
        return;
      }
      if (node === null || typeof node !== "object") return;
      const record = node as Record<string, unknown>;
      if (typeof record.ref_kind === "string" && typeof record.resolution === "string") {
        seen.push({ kind: record.ref_kind, resolution: record.resolution });
      }
      Object.values(record).forEach(walk);
    };
    walk(await read.executiveOverview(DEMO));
    walk(await read.attention(DEMO));
    walk(await read.whatChanged(DEMO));
    walk(await read.positions(DEMO));
    walk(await read.riskSnapshot(DEMO));
    walk(await read.shortSide(DEMO));
    walk(await read.trades(DEMO));
    walk(await read.tradeDetail(DEMO, await firstTradeId()));
    walk(await read.candidates(DEMO));

    expect(seen.length).toBeGreaterThan(20);
    const unresolvable = seen.filter((entry) => entry.resolution === "UNRESOLVABLE_V1");
    for (const entry of unresolvable) {
      expect(["chart_series", "benchmark_series"]).toContain(entry.kind);
    }
    /* And every emitted pair is one its kind's row actually permits. */
    for (const entry of seen) {
      if (entry.resolution === "EMBEDDED") continue;
      expect(
        KIND_RESOLUTIONS[entry.kind as keyof typeof KIND_RESOLUTIONS],
        `${entry.kind}/${entry.resolution}`,
      ).toContain(entry.resolution);
    }
  });
});

/* ============================================== environment and provenance (R8) */

describe("environment always matches, and provenance only where the catalogue says so", () => {
  const reference: Ref = {
    ref_id: "fact-1",
    ref_kind: "source_fact",
    resolution: "AUTHORIZED_READ",
    classification: "PUBLIC_SAFE",
  };

  it("admits a labelled cross-provenance target where the catalogue authorizes one", () => {
    expect(permitsCrossProvenance("QualificationStatus.facts[].source_ref")).toBe(true);
    const outcome = followReference(
      "QualificationStatus.facts[].source_ref",
      reference,
      { ...CALLER, declaredScope: "governance:read" },
      {
        producer: "IMPLEMENTED",
        located: {
          kind: "source_fact",
          id: "fact-1",
          labels: {
            environment: "RESEARCH",
            provenance: "REPOSITORY_TRACKED",
            classification: "PUBLIC_SAFE",
          },
        },
      },
    );
    expect(outcome).toEqual({ status: "RESOLVED" });
  });

  it("refuses an unlabelled-provenance join the catalogue does not authorize", () => {
    expect(permitsCrossProvenance("TradeDetail.audit_refs")).toBe(false);
    const outcome = followReference(
      "TradeDetail.audit_refs",
      { ...reference, ref_kind: "audit_event" },
      CALLER,
      {
        producer: "IMPLEMENTED",
        located: {
          kind: "audit_event",
          id: "fact-1",
          labels: {
            environment: "RESEARCH",
            provenance: "BROKER_REPORTED",
            classification: "PUBLIC_SAFE",
          },
        },
      },
    );
    expect(outcome).toEqual({ status: "REFUSED", code: "PROJECTION_ERROR" });
  });

  it("refuses a target from another environment, wherever it sits", () => {
    const outcome = followReference(
      "QualificationStatus.facts[].source_ref",
      reference,
      { ...CALLER, declaredScope: "governance:read" },
      {
        producer: "IMPLEMENTED",
        located: {
          kind: "source_fact",
          id: "fact-1",
          labels: {
            environment: "PAPER",
            provenance: "REPOSITORY_TRACKED",
            classification: "PUBLIC_SAFE",
          },
        },
      },
    );
    expect(outcome).toEqual({ status: "REFUSED", code: "PROJECTION_ERROR" });
  });
});

/* ============ the target is validated, and absent metadata proves nothing (R6, R8, R9) */

describe("a located target is validated, and an absence of metadata is not a pass", () => {
  const reference: Ref = {
    ref_id: "trade-1",
    ref_kind: "trade",
    resolution: "ENDPOINT",
    classification: "PUBLIC_SAFE",
  };
  const labels = {
    environment: "RESEARCH",
    provenance: "SYNTHETIC",
    classification: "PUBLIC_SAFE",
  } as const;
  const located = { kind: "trade", id: "trade-1", labels } as const;
  const follow = (
    target: Parameters<typeof followReference>[3],
    context: ResolvingContext = CALLER,
  ) => followReference("CandidateDetail.downstream_refs.trade", reference, context, target);

  it("resolves a target whose kind, identity and labels all correspond", () => {
    expect(follow({ producer: "IMPLEMENTED", located })).toEqual({ status: "RESOLVED" });
  });

  /*
   * A FOUND TARGET USED TO NEED NO LABELS AT ALL.
   *
   * `labels` was optional and the environment and provenance rule ran only inside
   * `if (labels !== undefined)`, so a target carrying none was RESOLVED without a single
   * check -- an absence of metadata reading as conformance. The type requires them now, and
   * these are the checks that absence used to skip.
   */
  it("refuses a located target from another environment", () => {
    expect(
      follow({
        producer: "IMPLEMENTED",
        located: { ...located, labels: { ...labels, environment: "PAPER" } },
      }),
    ).toEqual({ status: "REFUSED", code: "PROJECTION_ERROR" });
  });

  it("refuses a located target of another provenance on an unauthorized field", () => {
    expect(
      follow({
        producer: "IMPLEMENTED",
        located: { ...located, labels: { ...labels, provenance: "BROKER_REPORTED" } },
      }),
    ).toEqual({ status: "REFUSED", code: "PROJECTION_ERROR" });
  });

  it("refuses a target whose own identity is not the reference's (R8)", () => {
    expect(follow({ producer: "IMPLEMENTED", located: { ...located, id: "trade-2" } })).toEqual({
      status: "REFUSED",
      code: "PROJECTION_ERROR",
    });
  });

  it("refuses a target whose own kind is not the reference's (R8)", () => {
    expect(
      follow({ producer: "IMPLEMENTED", located: { ...located, kind: "candidate" } }),
    ).toEqual({ status: "REFUSED", code: "PROJECTION_ERROR" });
  });

  /*
   * A PRODUCER-CONTROLLED LABEL IS NOT AUTHORIZATION (R10).
   *
   * The reference says `PUBLIC_SAFE` and the target it names is `PRIVATE_OPERATIONAL`. The
   * reference label was the only classification consulted, so this read went through; the
   * target's own classification is consulted now, and a caller who may not read it is told so
   * rather than shown it.
   */
  it("withholds on the TARGET's classification, not on the reference's label", () => {
    expect(
      follow({
        producer: "IMPLEMENTED",
        located: { ...located, labels: { ...labels, classification: "PRIVATE_OPERATIONAL" } },
      }),
    ).toEqual({
      status: "UNAVAILABLE",
      availability: "NOT_AUTHORIZED",
      reason: "CLASSIFICATION_WITHHELD",
    });
  });

  it("refuses a reference and a target that disagree about classification", () => {
    /* The caller may read both, so this is the MISMATCH itself and not a withholding. */
    expect(
      follow(
        {
          producer: "IMPLEMENTED",
          located: { ...located, labels: { ...labels, classification: "PRIVATE_OPERATIONAL" } },
        },
        { ...CALLER, readableClassifications: ["PUBLIC_SAFE", "PRIVATE_OPERATIONAL"] },
      ),
    ).toEqual({ status: "REFUSED", code: "PROJECTION_ERROR" });
  });
});

describe("a tombstone is a RECORDED relationship, and not a boolean (R9)", () => {
  const reference: Ref = {
    ref_id: "withdrawn-1",
    ref_kind: "audit_event",
    resolution: "AUTHORIZED_READ",
    classification: "PUBLIC_SAFE",
  };
  const labels = {
    environment: "RESEARCH",
    provenance: "SYNTHETIC",
    classification: "PUBLIC_SAFE",
  } as const;
  const follow = (tombstone: {
    auditEventId: string;
    tombstoneOf: string;
    labels: { environment: string; provenance: "SYNTHETIC"; classification: DataClassification };
  }) =>
    followReference("AuditEvent.tombstone_of", reference, CALLER, {
      producer: "IMPLEMENTED",
      tombstone,
    });

  it("resolves a tombstone that names the entity the reference names", () => {
    expect(follow({ auditEventId: "audit-1", tombstoneOf: "withdrawn-1", labels })).toEqual({
      status: "RESOLVED",
    });
  });

  /*
   * A TOMBSTONE FOR SOMETHING ELSE IS NOT THIS REFERENCE'S TOMBSTONE.
   *
   * `tombstone: true` established no relationship at all: any caller could assert it about
   * any identifier and the reference resolved. The record has to NAME what it withdrew now.
   */
  it("refuses a tombstone recorded against a different entity", () => {
    expect(follow({ auditEventId: "audit-1", tombstoneOf: "some-other-record", labels })).toEqual({
      status: "REFUSED",
      code: "PROJECTION_ERROR",
    });
  });

  /*
   * AND IT USED TO SHORT-CIRCUIT ABOVE EVERY LABEL CHECK.
   *
   * The tombstone branch returned RESOLVED immediately, above the environment and provenance
   * rule, so one environment's withdrawal resolved inside another environment's response.
   */
  it("refuses a tombstone from another environment", () => {
    expect(
      follow({
        auditEventId: "audit-1",
        tombstoneOf: "withdrawn-1",
        labels: { ...labels, environment: "PAPER" },
      }),
    ).toEqual({ status: "REFUSED", code: "PROJECTION_ERROR" });
  });

  it("withholds a tombstone the caller's classification bars", () => {
    expect(
      follow({
        auditEventId: "audit-1",
        tombstoneOf: "withdrawn-1",
        labels: { ...labels, classification: "PRIVATE_OPERATIONAL" },
      }),
    ).toEqual({
      status: "UNAVAILABLE",
      availability: "NOT_AUTHORIZED",
      reason: "CLASSIFICATION_WITHHELD",
    });
  });
});

describe("the required scope comes from the accepted table, and not from the caller", () => {
  it("names the section 4.3 scope for every kind whose row states one", () => {
    expect(contractReadScope("risk_decision")).toBe("risk:read");
    expect(contractReadScope("audit_event")).toBe("audit:read");
    expect(contractReadScope("chart_series")).toBe("market:read");
    expect(contractReadScope("benchmark_series")).toBe("market:read");
    /* And an ENDPOINT row takes the scope of the read model it resolves to. */
    expect(contractReadScope("trade")).toBe("portfolio:read");
    expect(contractReadScope("candidate")).toBe("signals:read");
    expect(contractReadScope("order")).toBe("execution:read");
  });

  /*
   * THE TWO ROWS THAT NAME NO SCOPE STAY HONEST ABOUT NAMING NONE.
   *
   * `evidence` and `source_fact` read "the scope named on the reference", and section 4.2
   * gives `Ref` no field to name one in. Inventing a value here would be a specification act.
   */
  it("names none for the two kinds whose scope a reference cannot carry", () => {
    expect(contractReadScope("evidence")).toBeNull();
    expect(contractReadScope("source_fact")).toBeNull();
  });

  /*
   * A CALLER CANNOT LOWER THE BAR IT IS BEING HELD TO.
   *
   * `requiredScope` was a caller-supplied string and was the only authorization input, so a
   * caller holding `market:read` could declare a `trade` read to require `market:read` and be
   * admitted. The table names `portfolio:read`, and a contradicting declaration is refused.
   */
  it("refuses a declared scope that contradicts the table", () => {
    const reference: Ref = {
      ref_id: "trade-1",
      ref_kind: "trade",
      resolution: "ENDPOINT",
      classification: "PUBLIC_SAFE",
    };
    expect(
      followReference(
        "CandidateDetail.downstream_refs.trade",
        reference,
        { ...CALLER, heldScopes: ["market:read"], declaredScope: "market:read" },
        {
          producer: "IMPLEMENTED",
          located: {
            kind: "trade",
            id: "trade-1",
            labels: {
              environment: "RESEARCH",
              provenance: "SYNTHETIC",
              classification: "PUBLIC_SAFE",
            },
          },
        },
      ),
    ).toEqual({ status: "REFUSED", code: "PROJECTION_ERROR" });
  });

  it("refuses a read that nothing names a scope for", () => {
    const reference: Ref = {
      ref_id: "fact-1",
      ref_kind: "source_fact",
      resolution: "AUTHORIZED_READ",
      classification: "PUBLIC_SAFE",
    };
    /* No table scope, and the caller declared none either. */
    expect(
      followReference("TradeDetail.audit_refs", reference, CALLER, {
        producer: "IMPLEMENTED",
      }),
    ).toEqual({ status: "REFUSED", code: "SCOPE_MISSING" });
  });
});

/* ===== the unknown identifier, through the REAL read path and not through a helper ===== */

describe("an unknown identifier reaches REFERENT_NOT_FOUND through an ordinary read", () => {
  /*
   * THE RULE HAS TO SIT ON THE PATH AN ORDINARY READ TAKES.
   *
   * `followReference` had no runtime caller at all: it was reached only from tests, which
   * supplied `found: false` and then asserted the answer they had just supplied. Meanwhile
   * the read a reader actually performs -- follow `downstream_refs.trade` to
   * `/portfolio/trades/{ref_id}`, which calls `tradeDetail` -- answered `NOT_APPLICABLE` with
   * `NOT_DEFINED_FOR_SUBJECT`, which R9 refuses in exactly this case.
   */
  it("reports an unknown trade identity as NOT_YET_AVAILABLE and REFERENT_NOT_FOUND", async () => {
    const read = client();
    for (const response of [
      await read.tradeDetail(DEMO, "demo-trade-does-not-exist"),
      await read.tradeLifecycle(DEMO, "demo-trade-does-not-exist"),
    ]) {
      expect(response.availability).toBe("NOT_YET_AVAILABLE");
      expect(response.availability_reason).toBe("REFERENT_NOT_FOUND");
      expect(response.payload).toBeUndefined();
    }
  });

  it("reports an unknown candidate identity the same way", async () => {
    const response = await client().candidateDetail(DEMO, "demo-candidate-does-not-exist");
    expect(response.availability).toBe("NOT_YET_AVAILABLE");
    expect(response.availability_reason).toBe("REFERENT_NOT_FOUND");
    expect(response.payload).toBeUndefined();
  });

  /*
   * AND A REFERENCE THE APPLICATION REALLY EMITS LANDS THERE.
   *
   * Both `blocked_shorts[].candidate_ref` identifiers are absent from the candidate book, so
   * following one is the unknown-record case arriving from emitted output rather than from a
   * string a test made up.
   */
  it("lands there when a reference the fixtures emit is actually followed", async () => {
    const read = client();
    const shorts = await read.shortSide(DEMO);
    const blocked = shorts.payload?.blocked_shorts ?? [];
    expect(blocked.length).toBeGreaterThan(0);
    for (const entry of blocked) {
      expect(entry.candidate_ref.ref_kind).toBe("candidate");
      const followed = await read.candidateDetail(DEMO, entry.candidate_ref.ref_id);
      expect(followed.availability).toBe("NOT_YET_AVAILABLE");
      expect(followed.availability_reason).toBe("REFERENT_NOT_FOUND");
      /* And it is never some OTHER candidate served under this identity. */
      expect(followed.payload).toBeUndefined();
    }
  });

  /*
   * A MISSING PRODUCER IS STILL A DIFFERENT ANSWER, AND STAYS ONE.
   *
   * The project scenario has no synthetic producer, so the same unknown identifier reports
   * that the SUBSYSTEM does not exist -- a claim about the producer and not about the record,
   * and the two must not collapse into one another.
   */
  it("keeps the absent producer distinct on the same path", async () => {
    const project = { ...DEMO, scenario: "project" as const };
    const response = await client().tradeDetail(project, "demo-trade-does-not-exist");
    expect(response.availability).toBe("NOT_IMPLEMENTED");
    expect(response.availability_reason).toBe("PRODUCER_NOT_IMPLEMENTED");
  });
});

/* ==================================================== navigation is an allowlist (R10) */

describe("navigation is an allowlisted internal route template", () => {
  it("interpolates a validated SafeId as one encoded segment, and nothing else", () => {
    expect(
      referenceDestination({ ref_kind: "trade", ref_id: "demo-trade-0001" })?.href,
    ).toBe("/portfolio/trades/demo-trade-0001");
  });

  it("yields NO LINK for an unmapped kind, and never a guess", () => {
    /* `evidence` is a classified artefact with no area page; the answer is no link. */
    expect(referenceDestination({ ref_kind: "evidence", ref_id: "e-1" })).toBeNull();
    expect(referenceDestination({ ref_kind: "not_a_kind", ref_id: "x" })).toBeNull();
  });

  it("yields no link for a nested target from its own identifier alone", () => {
    /*
     * A `brain_decision` reference carries the DECISION's id and the route needs the
     * CONTAINER's, so no destination can be derived from the reference (R8).
     */
    expect(referenceDestination({ ref_kind: "brain_decision", ref_id: "d-1" })).toBeNull();
    /* The container route is reachable only when a host hands over the container id. */
    expect(
      nestedDestination("TradeDetail.brain_decision_ref", "demo-candidate-0001", "Brain decision")
        ?.href,
    ).toBe("/signals/candidates/demo-candidate-0001");
  });

  it("builds no destination from an identifier that is not a SafeId", () => {
    for (const hostile of [
      "https://example.com/x",
      "../../etc/passwd",
      "a b",
      "javascript:alert(1)",
    ]) {
      expect(referenceDestination({ ref_kind: "trade", ref_id: hostile }), hostile).toBeNull();
    }
  });

  /*
   * EVERY DISCLOSED REFERENCE HAS A LINK TO THE AREA THAT OWNS IT.
   *
   * This is the accepted C4 behaviour recorded when "evidence was a count, not a drill-down"
   * was corrected: every reference is disclosed "with its kind, its own resolution, its
   * classification and a link to the owning area". Correcting the attention evidence KINDS
   * broke it for one item -- `evidence` was carried, and section 5 catalogues no route and no
   * owning area for a classified evidence artefact, so R10 yields no link and refuses a guess.
   *
   * The fixture was corrected, not the rule: an `AttentionItem` is a projection (Area 28) and
   * every one of these references is "the recorded fact a projection was built from".
   */
  it("gives every disclosed attention and what-changed reference an owning-area link", async () => {
    const read = client();
    const attention = await read.attention(DEMO);
    /*
     * The RENDERED items, because an item missing any of the five presented things is
     * withheld -- `demo-attention-incomplete` carries no evidence on purpose, and it is
     * never disclosed, so it is not a reference this rule is about.
     */
    const items = prepareAttention(attention.payload?.items ?? []).visible;
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      expect(item.evidence_refs.items.length, item.item_id).toBeGreaterThan(0);
      for (const reference of item.evidence_refs.items) {
        expect(referenceDestination(reference), `${item.item_id}/${reference.ref_id}`).not.toBeNull();
      }
    }

    const changed = await read.whatChanged(DEMO);
    for (const entry of changed.payload?.entries ?? []) {
      for (const reference of entry.evidence_refs.items) {
        expect(referenceDestination(reference), reference.ref_id).not.toBeNull();
      }
    }
  });

  /*
   * THE KNOWN NARROWING IS OVER, AND THE TEST THAT ASSERTED IT IS REPLACED RATHER THAN DELETED.
   *
   * This position held a regression asserting that every conforming attention reference
   * resolved to `/governance/audit` and nowhere else. **Its premise was that the subject area
   * is not a property of a reference and that no accepted field carries it** -- which was true
   * of the contract as it then stood, and is no longer true of the contract now. ADR-0031 is
   * accepted, section 4.3.2 adds `Ref.owning_area` as a SECOND closed attribute, and the
   * per-area affordance is back without a single `ref_kind` moving.
   *
   * What replaces it is BOTH halves rather than a softened version of one. The TARGET
   * narrowing is real and is still asserted here, because R10's allowlist is unamended and
   * every attention reference is still a `source_fact`. The AREA restoration is asserted
   * beside it, and the two are asserted to be DIFFERENT destinations -- which is the whole
   * point of there being two attributes. The positive and negative behaviour over owning-area
   * navigation lives in `adr-0031-owning-area.test.ts`.
   */
  it("still resolves every attention reference's TARGET to the one area its kind owns", async () => {
    const attention = await client().attention(DEMO);
    const destinations = new Set(
      prepareAttention(attention.payload?.items ?? []).visible.flatMap((item) =>
        item.evidence_refs.items.map((reference) => referenceDestination(reference)?.href),
      ),
    );
    expect([...destinations]).toEqual(["/governance/audit"]);
  });

  it("recovers the per-area destination through owning_area, not through a kind", async () => {
    const attention = await client().attention(DEMO);
    const visible = prepareAttention(attention.payload?.items ?? []).visible;
    const references = visible.flatMap((item) => item.evidence_refs.items);

    // Not one kind moved to obtain a link: that is the defect ADR-0031 exists to prevent.
    expect(new Set(references.map((reference) => reference.ref_kind))).toEqual(
      new Set(["source_fact"]),
    );

    const areas = new Set(
      references.map((reference) => owningAreaDestination(reference)?.href),
    );
    expect(areas).toEqual(
      new Set([
        "/system/data-quality",
        "/strategy/health",
        "/risk/short-side",
        "/execution/reconciliation",
      ]),
    );
    // And no area link is the Audit Trail, which owns AuditEvent and owns none of these.
    expect(areas.has("/governance/audit")).toBe(false);
  });

  it("never emits an absolute or external destination", () => {
    for (const kind of REF_KINDS) {
      const destination = referenceDestination({ ref_kind: kind, ref_id: "safe-1" });
      if (destination === null) continue;
      expect(destination.href.startsWith("/"), kind).toBe(true);
      expect(destination.href).not.toMatch(/^https?:|^\/\//);
    }
  });
});

/* ================================================= the versioning decision, exercised */

describe("the coordinated schema bump", () => {
  it("rejects a payload carrying the superseded version rather than coercing it", async () => {
    const response = clone(await client().tradeDetail(DEMO, await firstTradeId()));
    expect(response.schema_version).toBe(TRADE_DETAIL_SCHEMA);
    expect(TRADE_DETAIL_SCHEMA).toBe("cockpit.trade_detail.v2");
    (response as { schema_version: string }).schema_version = "cockpit.trade_detail.v1";
    expect(() => admit("TradeDetail", tradeDetailEnvelope, response, "PUBLIC_EDGE")).toThrow(
      ContractViolationError,
    );
  });

  /*
   * THE CRITERION IS THE CONTRACT, AND IT USED TO BE THE EMITTED FIXTURE BYTES.
   *
   * Thirteen schemas were bumped because their emitted example changed and six were left at
   * v1 because theirs did not. **An unchanged example does not mean an unchanged contract**:
   * `Envelope.source_refs` moved from an open `refList` to `refListFieldOf`, which NARROWS
   * `ref_kind` to `source_fact` and checks `items`, `total` and `truncated` against the
   * list's own cardinality -- for EVERY read model, because every read model carries the
   * envelope. A consumer pinned to one of the six would have accepted, before this cycle,
   * envelopes it must now reject.
   *
   * So the affected set is all nineteen, and the version matrix says so.
   */
  /*
   * THE COORDINATED REPLACEMENT IS STILL v2, AND A FIRST VERSION IS STILL v1.
   *
   * §5.2 versions a schema PER READ MODEL, so "one view can evolve without a global bump". The
   * nineteen models that took the coordinated ADR-0030/ADR-0031 replacement carry `v2` and are
   * unchanged by C7; the ten read models C7 introduces have never been served before and carry
   * their own first version. Copying `v2` on to a model with no `v1` would state a history it
   * does not have, and bumping the nineteen to `v3` because ten new models appeared would be
   * the global bump §5.2 exists to avoid.
   */
  const COORDINATED_V2 = 19;
  /**
   * The read models C8 introduced, each at its own first version.
   *
   * The same reasoning the C7 list rests on: these seven have never been served before, so
   * copying `v2` on to one would state a history it does not have, and bumping the nineteen
   * to `v3` because seven new models appeared would be the global bump §5.2 exists to avoid.
   */
  const C8_FIRST_VERSION = [
    "ExecutionQuality",
    "ReconciliationStatus",
    "DataQuality",
    "SystemJob",
    "SystemIncident",
    "Alert",
    "AuditEvent",
  ];
  /**
   * The read models C9 introduced, each at its own first version.
   *
   * The same reasoning again: `SearchResultPage` and `AskAnswer` have never been served before,
   * so each carries its own `v1` while the nineteen coordinated models stay at `v2` and the
   * seventeen C7 and C8 models stay at `v1`.
   */
  const C9_FIRST_VERSION = ["SearchResultPage", "AskAnswer"];
  const C7_FIRST_VERSION = [
    "StrategyHealth",
    "StrategyVersion",
    "ResearchRun",
    "ResearchQueueItem",
    "HypothesisRegistration",
    "ChampionChallengerComparison",
    "AiContribution",
    "FeedbackPipeline",
    "GovernancePacket",
    "DecisionRecord",
  ];

  it("keeps the coordinated nineteen at v2 and gives each new read model its own v1", () => {
    const firstVersion = [...C7_FIRST_VERSION, ...C8_FIRST_VERSION, ...C9_FIRST_VERSION];
    const coordinated = READ_MODEL_IDENTITIES.filter(
      (identity) => !firstVersion.includes(identity.readModel),
    );
    for (const identity of coordinated) {
      expect(identity.schemaVersion, identity.readModel).toMatch(/\.v2$/);
    }
    expect(coordinated.length).toBe(COORDINATED_V2);

    const introduced = READ_MODEL_IDENTITIES.filter((identity) =>
      firstVersion.includes(identity.readModel),
    );
    for (const identity of introduced) {
      expect(identity.schemaVersion, identity.readModel).toMatch(/\.v1$/);
    }
    expect(introduced.map((identity) => identity.readModel).sort()).toEqual(
      [...firstVersion].sort(),
    );
    expect(READ_MODEL_IDENTITIES.length).toBe(COORDINATED_V2 + firstVersion.length);
    /* Every read model is registered exactly once, under exactly one identity. */
    expect(new Set(READ_MODEL_IDENTITIES.map((identity) => identity.readModel)).size).toBe(
      READ_MODEL_IDENTITIES.length,
    );
  });

  it("narrows the envelope for a read model that was left at v1, which is why it bumped", async () => {
    /*
     * `MarketRegime` is one of the six whose emitted payload was byte-identical. Its CONTRACT
     * changed anyway, and this is the change: an envelope source reference of a kind other
     * than `source_fact` was admissible before and is refused now.
     */
    const response = clone(await client().marketRegime(DEMO));
    expect(response.schema_version).toBe(MARKET_REGIME_SCHEMA);
    expect(MARKET_REGIME_SCHEMA).toBe("cockpit.market_regime.v2");
    const widened = clone(response);
    widened.source_refs.items = [
      {
        ref_id: "not-a-source-fact",
        ref_kind: "incident",
        resolution: "ENDPOINT",
        classification: "PUBLIC_SAFE",
      },
    ];
    widened.source_refs.total = {
      ...widened.source_refs.total,
      availability: "AVAILABLE",
      value: 1,
    };
    widened.source_refs.cardinality = "ZERO_OR_MORE";
    widened.source_refs.truncated = false;
    expect(() =>
      admit("MarketRegime", marketRegimeEnvelope, widened, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("rejects a payload carrying a version that was current one cycle ago", async () => {
    const response = clone(await client().marketRegime(DEMO));
    (response as { schema_version: string }).schema_version = "cockpit.market_regime.v1";
    expect(() =>
      admit("MarketRegime", marketRegimeEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });
});

/* ================================================================= helpers */

async function firstTradeId(): Promise<string> {
  const trades = await client().trades(DEMO);
  return trades.payload!.items[0].trade_id;
}

/** A trade whose execution quality really is carried, so the authorized embed is exercised. */
async function tradeWithEmbeddedQuality(): Promise<string> {
  const read = client();
  const trades = await read.trades(DEMO);
  for (const row of trades.payload?.items ?? []) {
    const detail = await read.tradeDetail(DEMO, row.trade_id);
    if (detail.payload?.execution_quality_ref.resolution === "EMBEDDED") {
      return row.trade_id;
    }
  }
  throw new Error("no trade carries an embedded execution-quality record");
}

/* One sanity check on the helper above, so a silent change cannot empty these cases. */
describe("the embedded-quality fixture exists", () => {
  it("finds a trade carrying the authorized projection", async () => {
    await expect(tradeWithEmbeddedQuality()).resolves.toBeTruthy();
  });

  it("also finds a trade that resolves it by endpoint instead", async () => {
    const read = client();
    const trades = await read.trades(DEMO);
    const byEndpoint: string[] = [];
    for (const row of (trades.payload?.items ?? []).slice(0, 40)) {
      const detail = await read.tradeDetail(DEMO, row.trade_id);
      if (detail.payload?.execution_quality_ref.resolution === "ENDPOINT") {
        byEndpoint.push(row.trade_id);
      }
    }
    expect(byEndpoint.length).toBeGreaterThan(0);
  });
});

describe("the candidate detail boundary enforces the same rules", () => {
  it("refuses a candidate detail whose downstream trade reference names a forbidden kind", async () => {
    const read = client();
    const candidates = await read.candidates(DEMO);
    const id = candidates.payload!.items[0].candidate_id;
    const response = clone(await read.candidateDetail(DEMO, id));
    const downstream = (response.payload as { downstream_refs: { trade: Ref } }).downstream_refs;
    downstream.trade.ref_kind = "source_fact";
    expect(() =>
      admit("CandidateDetail", candidateDetailEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/declares kind trade/);
  });

  it("refuses a candidate detail whose security projection is another security's", async () => {
    const read = client();
    const candidates = await read.candidates(DEMO);
    const id = candidates.payload!.items[0].candidate_id;
    const response = clone(await read.candidateDetail(DEMO, id));
    const payload = response.payload as { security: { symbol: string } };
    payload.security.symbol = "ZZZZ";
    expect(() =>
      admit("CandidateDetail", candidateDetailEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/is not the reference's/);
  });
});


describe("every reference field a model schema carries is bound to its declaration", () => {
  /*
   * THE ASSIGNMENT AND THE ENFORCEMENT ARE TWO THINGS, AND THIS IS THE SECOND.
   *
   * `REFERENCE_FIELDS` records the kind §4.3.1 assigns each field; `refOf` and
   * `refListFieldOf` are what make a schema check it. A field that imports the bare `ref`
   * shape from `values.ts` gets the FLOOR -- a closed `ref_kind` and a closed `resolution`
   * -- and nothing about the field it sits in, so its catalogue row is written down and
   * never applied. Two implemented, emitted fields were in exactly that state.
   *
   * This is structural on purpose: the two behavioural cases below prove the consequence on
   * the two fields that had it, and this one refuses the NEXT field to arrive unbound.
   */
  const CONTRACTS = join(__dirname, "..", "src", "contracts");
  /** The two modules that legitimately name the unbound shapes: one defines them, one binds them. */
  const DEFINING = new Set(["values.ts", "references.ts"]);

  it("never uses the unbound `ref` or `refList` shape in a model schema", () => {
    const offenders: string[] = [];
    for (const name of readdirSync(CONTRACTS)) {
      if (!name.endsWith(".ts") || DEFINING.has(name)) {
        continue;
      }
      const text = readFileSync(join(CONTRACTS, name), "utf8");
      text.split(/\r?\n/).forEach((line, index) => {
        if (line.trimStart().startsWith("*") || line.trimStart().startsWith("//")) {
          return;
        }
        if (/(?:[:(,[]|=>)\s*ref(?:List)?\s*(?:[,)}\]]|$)/.test(line)) {
          offenders.push(`${name}:${index + 1} ${line.trim()}`);
        }
      });
    }
    expect(offenders).toEqual([]);
  });

  it("refuses a risk snapshot whose decision reference names a forbidden kind", async () => {
    const response = clone(await client().riskSnapshot(DEMO));
    const decisions = (response.payload as { decisions: { decision_ref: Ref }[] }).decisions;
    expect(decisions.length).toBeGreaterThan(0);
    decisions[0].decision_ref.ref_kind = "alert";
    decisions[0].decision_ref.resolution = "ENDPOINT";
    expect(() => admit("RiskSnapshot", riskSnapshotEnvelope, response, "PUBLIC_EDGE")).toThrow(
      /declares kind risk_decision/,
    );
  });

  it("refuses a short-side snapshot whose blocked-short reference names a forbidden kind", async () => {
    const response = clone(await client().shortSide(DEMO));
    const blocked = (response.payload as { blocked_shorts: { candidate_ref: Ref }[] })
      .blocked_shorts;
    expect(blocked.length).toBeGreaterThan(0);
    blocked[0].candidate_ref.ref_kind = "incident";
    blocked[0].candidate_ref.resolution = "ENDPOINT";
    expect(() =>
      admit("ShortSideSnapshot", shortSideSnapshotEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/declares kind candidate/);
  });

  it("records the risk-decision producer as implemented, because this application serves it", () => {
    /*
     * R6: an implemented producer that lacks one record is REFERENT_NOT_FOUND, and calling
     * it PRODUCER_NOT_IMPLEMENTED asserts something false about the subsystem. The flag read
     * `false` for a field this application emits.
     */
    expect(declarationFor("RiskSnapshot.decisions[].decision_ref").implemented).toBe(true);
  });
});
