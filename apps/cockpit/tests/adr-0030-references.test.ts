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
import { describe, expect, it } from "vitest";

import { admit } from "@/data/client/read-client";
import { ContractViolationError } from "@/data/client/read-client";
import { candidateDetailEnvelope } from "@/contracts/signal-models";
import { tradeDetailEnvelope, TRADE_DETAIL_SCHEMA } from "@/contracts/portfolio-models";
import { riskSnapshotEnvelope } from "@/contracts/risk-market-models";
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
import type { ResolvingContext } from "@/contracts/reference-access";
import { refListOf } from "@/contracts/factories";
import { available, absent } from "@/contracts/factories";
import type { Ref } from "@/contracts/values";
import { REF_KINDS, FIELD_REASON_CODES, ERROR_CODES } from "@/contracts/vocabularies";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { referenceDestination, nestedDestination } from "@/lib/reference-navigation";
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

const CALLER: ResolvingContext = {
  environment: "RESEARCH",
  provenance: "SYNTHETIC",
  heldScopes: ["portfolio:read", "risk:read", "signals:read"],
  requiredScope: "risk:read",
  readableClassifications: ["PUBLIC_SAFE"],
};

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

  it("assigns the six RefList fields C7 first emits, without implementing any of them", () => {
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
      /* Recorded as specification only: no model, producer, screen or fixture exists. */
      expect(REFERENCE_FIELDS[key].implemented, key).toBe(false);
    }
    expect(REFERENCE_FIELDS["StrategyHealth.transitions[].input_refs"].kinds).toEqual([
      "source_fact",
    ]);
    expect(REFERENCE_FIELDS["FeedbackPipeline.stages[].item_refs"].kinds).toEqual(["queue_item"]);
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

  it("calls an unknown record REFERENT_NOT_FOUND, never a missing producer", () => {
    expect(
      followReference("CandidateDetail.downstream_refs.trade", reference, CALLER, {
        producer: "IMPLEMENTED",
        found: false,
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
        found: false,
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
      { producer: "IMPLEMENTED", found: true },
    );
    expect(noScope).toEqual({ status: "REFUSED", code: "SCOPE_MISSING" });

    const wrongScope = followReference(
      "CandidateDetail.downstream_refs.trade",
      reference,
      { ...CALLER, heldScopes: ["market:read"] },
      { producer: "IMPLEMENTED", found: true },
    );
    expect(wrongScope).toEqual({ status: "REFUSED", code: "SCOPE_INSUFFICIENT" });

    /* Scope held, classification withholds — a DIFFERENT answer, and never a scope error. */
    const withheld = followReference(
      "CandidateDetail.downstream_refs.trade",
      { ...reference, classification: "PRIVATE_OPERATIONAL" },
      CALLER,
      { producer: "IMPLEMENTED", found: true },
    );
    expect(withheld).toEqual({
      status: "UNAVAILABLE",
      availability: "NOT_AUTHORIZED",
      reason: "CLASSIFICATION_WITHHELD",
    });
  });

  it("resolves a recorded tombstone rather than calling it REFERENT_NOT_FOUND", () => {
    const outcome = followReference(
      "AuditEvent.tombstone_of",
      { ...reference, ref_kind: "audit_event", resolution: "AUTHORIZED_READ" },
      { ...CALLER, requiredScope: "risk:read" },
      { producer: "IMPLEMENTED", found: false, tombstone: true },
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
      { ...CALLER, requiredScope: "risk:read" },
      {
        producer: "IMPLEMENTED",
        found: true,
        labels: { environment: "RESEARCH", provenance: "REPOSITORY_TRACKED" },
      },
    );
    expect(outcome).toEqual({ status: "RESOLVED" });
  });

  it("refuses an unlabelled-provenance join the catalogue does not authorize", () => {
    expect(permitsCrossProvenance("TradeDetail.audit_refs")).toBe(false);
    const outcome = followReference(
      "TradeDetail.audit_refs",
      { ...reference, ref_kind: "audit_event" },
      { ...CALLER, requiredScope: "risk:read" },
      {
        producer: "IMPLEMENTED",
        found: true,
        labels: { environment: "RESEARCH", provenance: "BROKER_REPORTED" },
      },
    );
    expect(outcome).toEqual({ status: "REFUSED", code: "PROJECTION_ERROR" });
  });

  it("refuses a target from another environment, wherever it sits", () => {
    const outcome = followReference(
      "QualificationStatus.facts[].source_ref",
      reference,
      { ...CALLER, requiredScope: "risk:read" },
      {
        producer: "IMPLEMENTED",
        found: true,
        labels: { environment: "PAPER", provenance: "REPOSITORY_TRACKED" },
      },
    );
    expect(outcome).toEqual({ status: "REFUSED", code: "PROJECTION_ERROR" });
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

  it("leaves a read model whose payload did not change at v1", async () => {
    const envelope = await client().marketRegime(DEMO);
    expect(envelope.schema_version).toBe("cockpit.market_regime.v1");
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
