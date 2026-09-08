/**
 * ADR-0031 — owning-area navigation, enforced and rendered.
 *
 * The affordance this restores was lost because a producer wrote an AREA into a field that
 * answers a different question, so the tests that matter here are the ones that would catch
 * it coming back: every case is driven through `admit` — the same function the fixture
 * adapter calls — or through the same closed table the application renders from, and never
 * through a helper written for the test.
 *
 * Both directions are asserted. A suite that only showed conforming payloads would pass
 * against a validator that does nothing, so several cases take a REAL admitted response,
 * break exactly one thing, and require the boundary to refuse it.
 */
import { describe, expect, it } from "vitest";

import { admit, ContractViolationError } from "@/data/client/read-client";
import { attentionListEnvelope, ATTENTION_LIST_SCHEMA } from "@/contracts/read-models";
import { positionSnapshotEnvelope } from "@/contracts/portfolio-models";
import { owningAreaContradiction } from "@/contracts/references";
import { followReference } from "@/contracts/reference-access";
import type { ResolvingContext } from "@/contracts/reference-access";
import { refListOf } from "@/contracts/factories";
import { ref as refSchema } from "@/contracts/values";
import type { Ref } from "@/contracts/values";
import { OWNING_AREAS } from "@/contracts/vocabularies";
import type { OwningArea } from "@/contracts/vocabularies";
import {
  NAVIGABLE_OWNING_AREAS,
  owningAreaDestination,
  referenceDestination,
} from "@/lib/reference-navigation";
import { ROUTES_BY_HREF } from "@/nav/registry";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { prepareAttention } from "@/lib/attention";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";

const ORIGIN = "2026-09-06T13:00:00.000Z";
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };

const client = () =>
  new FixtureReadClient({
    clock: fixedClock(Date.parse(ORIGIN)),
    originMs: Date.parse(ORIGIN),
    boundary: "PUBLIC_EDGE",
  });

const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

/** A reference, built the way a producer builds one. */
const reference = (
  refId: string,
  owningArea?: OwningArea,
  refKind: Ref["ref_kind"] = "source_fact",
): Ref => ({
  ref_id: refId,
  ref_kind: refKind,
  resolution: "AUTHORIZED_READ",
  classification: "PUBLIC_SAFE",
  ...(owningArea === undefined ? {} : { owning_area: owningArea }),
});

/**
 * A `RefList` field whose three facts agree, so only the case under test can refuse it.
 *
 * Built by the SAME factory the fixtures use, so a list assembled here cannot be admissible
 * in a way a real one would not be.
 */
const listOf = (items: readonly Ref[], asOf: string) =>
  refListOf(items, "ZERO_OR_MORE", asOf);

/* ============================================================ the closed vocabulary */

describe("the OwningArea vocabulary is closed at the seven accepted members", () => {
  it("maps every member to exactly one internal area landing route", () => {
    expect([...NAVIGABLE_OWNING_AREAS].sort()).toEqual([...OWNING_AREAS].sort());
    const hrefs = OWNING_AREAS.map(
      (area) => owningAreaDestination({ owning_area: area })!.href,
    );
    expect(new Set(hrefs).size).toBe(OWNING_AREAS.length);
  });

  it("carries the area numbers and routes the accepted §4.3.2 table states", () => {
    const accepted: Readonly<Record<OwningArea, readonly [number, string]>> = {
      DATA_QUALITY: [22, "/system/data-quality"],
      STRATEGY_HEALTH: [5, "/strategy/health"],
      RECONCILIATION: [10, "/execution/reconciliation"],
      SHORT_SIDE: [13, "/risk/short-side"],
      ALERTS: [27, "/system/alerts"],
      SYSTEM_OPERATIONS: [23, "/system/operations"],
      AUDIT_TRAIL: [26, "/governance/audit"],
    };
    for (const area of OWNING_AREAS) {
      const destination = owningAreaDestination({ owning_area: area })!;
      const [number, href] = accepted[area];
      expect(destination.href, area).toBe(href);
      expect(destination.area, area).toBe(number);
      // The route is registered and its declared areas contain the one the table names.
      expect(ROUTES_BY_HREF.get(href)?.areas, area).toContain(number);
    }
  });

  it("names the AREA and never phrases the control as retrieval", () => {
    for (const area of OWNING_AREAS) {
      const label = owningAreaDestination({ owning_area: area })!.label;
      expect(label.toLowerCase(), area).toContain("area");
      for (const verb of ["resolve", "open", "retrieve", "view", "show", "evidence"]) {
        expect(label.toLowerCase(), `${area}/${verb}`).not.toContain(verb);
      }
    }
  });

  it("emits no absolute, external or entity-segmented route", () => {
    for (const area of OWNING_AREAS) {
      const href = owningAreaDestination({ owning_area: area })!.href;
      expect(href.startsWith("/"), area).toBe(true);
      expect(href, area).not.toMatch(/^https?:|^\/\/|\{|%/);
    }
  });

  it("carries the destination route's own implemented or placeholder status", () => {
    /*
     * FIVE PLACEHOLDERS AND TWO IMPLEMENTED SCREENS TODAY; the affordance says which.
     *
     * C7 built the Strategy Health area, so its destination is no longer a placeholder. The
     * count is the point of the assertion — the affordance carries the DESTINATION'S OWN
     * status rather than a second copy of it, so it moves when a screen is built.
     */
    const statuses = OWNING_AREAS.map(
      (area) => owningAreaDestination({ owning_area: area })!.status,
    );
    expect(statuses.filter((status) => status === "placeholder")).toHaveLength(5);
    expect(owningAreaDestination({ owning_area: "SHORT_SIDE" })!.status).toBe("implemented");
    expect(owningAreaDestination({ owning_area: "STRATEGY_HEALTH" })!.status).toBe(
      "implemented",
    );
    expect(owningAreaDestination({ owning_area: "AUDIT_TRAIL" })!.status).toBe("placeholder");
    for (const area of OWNING_AREAS) {
      const destination = owningAreaDestination({ owning_area: area })!;
      expect(destination.status, area).toBe(ROUTES_BY_HREF.get(destination.href)!.status);
    }
  });
});

/* ================================================================== absence, and no default */

describe("an absent owning area is an absence and never the Audit Trail", () => {
  it("yields no area destination at all", () => {
    expect(owningAreaDestination(reference("evidence-1"))).toBeNull();
    expect(owningAreaDestination({})).toBeNull();
  });

  it("never falls back to AUDIT_TRAIL, or to any nearest member", () => {
    for (const declared of [undefined, "", "UNKNOWN_AREA", "audit_trail", "DATA QUALITY"]) {
      const destination = owningAreaDestination({ owning_area: declared as string | undefined });
      expect(destination, String(declared)).toBeNull();
    }
  });

  it("reaches AUDIT_TRAIL only from a reference that declares it", () => {
    expect(owningAreaDestination({ owning_area: "AUDIT_TRAIL" })!.href).toBe("/governance/audit");
  });
});

/* ========================================================= admission: the closed value */

describe("an owning_area outside the closed set is refused at admission", () => {
  it("refuses an unknown member rather than coercing or dropping it", async () => {
    const response = clone(await client().attention(DEMO));
    const item = response.payload!.items[0]!;
    (item.evidence_refs.items[0] as unknown as Record<string, unknown>).owning_area =
      "SHORT_SIDE_DASHBOARD";
    expect(() =>
      admit("AttentionList", attentionListEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses a route, a URL or free text where a member belongs", () => {
    for (const value of ["/system/data-quality", "https://example.test/area", "Data quality"]) {
      const candidate = { ...reference("evidence-1"), owning_area: value };
      expect(refSchema.safeParse(candidate).success, value).toBe(false);
    }
  });

  it("admits the seven members, and only those", () => {
    for (const area of OWNING_AREAS) {
      expect(refSchema.safeParse(reference("evidence-1", area)).success, area).toBe(true);
    }
    expect(refSchema.safeParse(reference("evidence-1")).success).toBe(true);
  });
});

/* ================================================ admission: the contradiction, at unit scope */

describe("one record is not owned by two areas, anywhere in one response", () => {
  it("refuses a contradiction inside one RefList", () => {
    const failure = owningAreaContradiction({
      evidence_refs: {
        items: [reference("fact-1", "DATA_QUALITY"), reference("fact-1", "ALERTS")],
      },
    });
    expect(failure).toContain("not owned by two areas");
  });

  it("refuses a contradiction across TWO DIFFERENT RefLists in one response", async () => {
    const response = clone(await client().attention(DEMO));
    const asOf = response.as_of_time;
    const item = response.payload!.items[0]!;
    const contested = item.evidence_refs.items[0]!;
    expect(contested.owning_area).toBe("DATA_QUALITY");
    response.source_refs = listOf(
      [reference(contested.ref_id, "SYSTEM_OPERATIONS", contested.ref_kind)],
      asOf,
    ) as typeof response.source_refs;
    expect(() =>
      admit("AttentionList", attentionListEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses a contradiction between a SCALAR Ref and a list beside it", async () => {
    const response = clone(await client().positions(DEMO));
    const position = response.payload!.items[0]!;
    const scalar = position.trade_ref;
    (scalar as unknown as Record<string, unknown>).owning_area = "RECONCILIATION";
    response.source_refs = listOf(
      [reference(scalar.ref_id, "AUDIT_TRAIL", scalar.ref_kind)],
      response.as_of_time,
    ) as typeof response.source_refs;
    expect(() =>
      admit("PositionSnapshot", positionSnapshotEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("admits the SAME area declared twice, and keeps both references", () => {
    const unit = {
      a: { items: [reference("fact-1", "DATA_QUALITY")] },
      b: { items: [reference("fact-1", "DATA_QUALITY")] },
    };
    expect(owningAreaContradiction(unit)).toBeNull();
    // Not collapsed, and the shared area is not deduplicated away.
    expect(unit.a.items).toHaveLength(1);
    expect(unit.b.items).toHaveLength(1);
    expect(unit.a.items[0]!.owning_area).toBe("DATA_QUALITY");
    expect(unit.b.items[0]!.owning_area).toBe("DATA_QUALITY");
  });

  it("admits a DECLARED area beside an ABSENT one, and leaves the absence absent", async () => {
    const response = clone(await client().attention(DEMO));
    const item = response.payload!.items[0]!;
    const contested = item.evidence_refs.items[0]!;
    response.source_refs = listOf(
      [reference(contested.ref_id, undefined, contested.ref_kind)],
      response.as_of_time,
    ) as typeof response.source_refs;
    const admitted = admit("AttentionList", attentionListEnvelope, response, "PUBLIC_EDGE");
    // ABSENT states nothing, so there is nothing for it to disagree with...
    expect(admitted.payload!.items[0]!.evidence_refs.items[0]!.owning_area).toBe("DATA_QUALITY");
    // ...and it is not filled in from the declaration beside it either.
    expect(admitted.source_refs.items[0]!.owning_area).toBeUndefined();
    expect(owningAreaDestination(admitted.source_refs.items[0]!)).toBeNull();
  });

  it("distinguishes a different KIND from a contradiction", () => {
    // A shared ref_id under two kinds names two targets, and R8 compares BOTH.
    expect(
      owningAreaContradiction({
        items: [
          reference("shared-1", "DATA_QUALITY", "source_fact"),
          reference("shared-1", "ALERTS", "evidence"),
        ],
      }),
    ).toBeNull();
  });

  it("terminates on a self-referential payload rather than walking forever", () => {
    const cyclic: Record<string, unknown> = { items: [reference("fact-1", "ALERTS")] };
    cyclic.self = cyclic;
    expect(owningAreaContradiction(cyclic)).toBeNull();
  });
});

/* ============================================================== the restored destinations */

describe("the four intended attention destinations are restored", () => {
  const load = async () => {
    const attention = await client().attention(DEMO);
    return prepareAttention(attention.payload?.items ?? []).visible;
  };

  it("routes each visible item to the area that owns its recorded fact", async () => {
    const routed = (await load()).map((item) => [
      item.item_id,
      item.evidence_refs.items.map((entry) => owningAreaDestination(entry)?.href),
    ]);
    expect(Object.fromEntries(routed)).toEqual({
      "demo-attention-1": ["/strategy/health"],
      "demo-attention-2": ["/system/data-quality"],
      "demo-attention-3": ["/risk/short-side"],
      "demo-attention-4": ["/execution/reconciliation"],
    });
  });

  it("changed no evidence kind to obtain any of them", async () => {
    for (const item of await load()) {
      for (const entry of item.evidence_refs.items) {
        expect(entry.ref_kind, item.item_id).toBe("source_fact");
      }
    }
  });

  it("keeps target navigation and area navigation as different answers", async () => {
    for (const item of await load()) {
      for (const entry of item.evidence_refs.items) {
        const target = referenceDestination(entry);
        const area = owningAreaDestination(entry);
        expect(target, item.item_id).not.toBeNull();
        expect(area, item.item_id).not.toBeNull();
        // Every one of these four is owned by an area that is not the Audit Trail.
        expect(target!.href).toBe("/governance/audit");
        expect(area!.href).not.toBe("/governance/audit");
      }
    }
  });

  it("gives What Changed its own areas, and declares none where none is catalogued", async () => {
    const changed = await client().whatChanged(DEMO);
    const routed = (changed.payload?.entries ?? []).map((entry) => [
      entry.change_id,
      entry.evidence_refs.items.map((item) => owningAreaDestination(item)?.href ?? null),
    ]);
    expect(Object.fromEntries(routed)).toEqual({
      "demo-change-1": ["/strategy/health"],
      "demo-change-2": ["/system/operations"],
      // A recorded risk fact: the closed vocabulary has no risk member, so it declares NONE
      // rather than being pushed to the nearest catalogued page.
      "demo-change-3": [null],
    });
  });
});

/* ================================================ two references, two areas, one item */

describe("references in one item keep their own areas", () => {
  it("resolves two areas from two references in a single attention item", async () => {
    const response = clone(await client().attention(DEMO));
    const item = response.payload!.items[0]!;
    const asOf = response.as_of_time;
    item.evidence_refs = listOf(
      [
        reference("multi-fact-quality", "DATA_QUALITY"),
        reference("multi-fact-borrow", "SHORT_SIDE"),
      ],
      asOf,
    ) as typeof item.evidence_refs;
    const admitted = admit("AttentionList", attentionListEnvelope, response, "PUBLIC_EDGE");
    const areas = admitted.payload!.items[0]!.evidence_refs.items.map(
      (entry) => owningAreaDestination(entry)!.href,
    );
    expect(areas).toEqual(["/system/data-quality", "/risk/short-side"]);
  });

  it("survives filtering, truncation and reordering without reassociating", async () => {
    const attention = await client().attention(DEMO);
    const items = attention.payload?.items ?? [];
    const before = new Map(
      items.flatMap((item) =>
        item.evidence_refs.items.map(
          (entry) => [entry.ref_id, entry.owning_area] as const,
        ),
      ),
    );

    // Deduplicated and ranked, which reorders and drops rows...
    const ranked = prepareAttention(items).visible;
    // ...and filtered, which drops more.
    const filtered = prepareAttention(items, {
      severities: ["MEDIUM"],
      evidenceKinds: [],
    }).visible;
    for (const item of [...ranked, ...filtered]) {
      for (const entry of item.evidence_refs.items) {
        expect(entry.owning_area, entry.ref_id).toBe(before.get(entry.ref_id));
      }
    }
    // The association travels in the reference, so a reversed list is still correct.
    for (const entry of [...ranked].reverse().flatMap((item) => item.evidence_refs.items)) {
      expect(entry.owning_area, entry.ref_id).toBe(before.get(entry.ref_id));
    }
  });
});

/* ===================================================== the access boundary is untouched */

describe("an area link authorizes nothing", () => {
  const denied: ResolvingContext = {
    environment: "RESEARCH",
    provenance: "SYNTHETIC",
    heldScopes: ["portfolio:read"],
    readableClassifications: ["PUBLIC_SAFE"],
  };

  it("leaves a caller without the scope denied, area link or no area link", () => {
    const withArea = reference("fact-1", "DATA_QUALITY");
    const withoutArea = reference("fact-1");
    const outcome = (candidate: Ref) =>
      followReference("AttentionItem.evidence_refs", candidate, { ...denied, declaredScope: "system:read" }, {
        producer: "IMPLEMENTED",
        located: {
          kind: "source_fact",
          id: "fact-1",
          labels: {
            environment: "RESEARCH",
            provenance: "SYNTHETIC",
            classification: "PUBLIC_SAFE",
          },
        },
      });
    expect(outcome(withArea)).toEqual({ status: "REFUSED", code: "SCOPE_INSUFFICIENT" });
    // The denial is identical with and without the area, and the area link still renders.
    expect(outcome(withoutArea)).toEqual(outcome(withArea));
    expect(owningAreaDestination(withArea)).not.toBeNull();
  });

  it("leaves a classification-withheld target withheld", () => {
    const outcome = followReference(
      "AttentionItem.evidence_refs",
      { ...reference("fact-1", "DATA_QUALITY"), classification: "PRIVATE_OPERATIONAL" },
      { ...denied, heldScopes: ["system:read"], declaredScope: "system:read" },
      { producer: "IMPLEMENTED" },
    );
    expect(outcome).toEqual({
      status: "UNAVAILABLE",
      availability: "NOT_AUTHORIZED",
      reason: "CLASSIFICATION_WITHHELD",
    });
  });

  it("offers an area for an UNRESOLVABLE_V1 reference, which resolves nothing", () => {
    const unresolvable: Ref = {
      ...reference("fact-1", "RECONCILIATION"),
      resolution: "UNRESOLVABLE_V1",
    };
    expect(owningAreaDestination(unresolvable)!.href).toBe("/execution/reconciliation");
    // Reference status and area navigability are separate axes: neither moved the other.
    expect(unresolvable.resolution).toBe("UNRESOLVABLE_V1");
  });
});

/* ======================================================== the combined version identity */

describe("the owning-area shape ships inside the coordinated replacement", () => {
  it("carries the same v2 identity as the enforcement half", async () => {
    const response = await client().attention(DEMO);
    expect(response.schema_version).toBe(ATTENTION_LIST_SCHEMA);
    expect(ATTENTION_LIST_SCHEMA).toBe("cockpit.attention_list.v2");
    expect(response.payload!.items[0]!.evidence_refs.items[0]!.owning_area).toBe("DATA_QUALITY");
  });

  it("refuses the superseded version on a payload that carries owning areas", async () => {
    const response = clone(await client().attention(DEMO));
    (response as { schema_version: string }).schema_version = "cockpit.attention_list.v1";
    expect(() =>
      admit("AttentionList", attentionListEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("refuses a v3 nobody published, so the identity is one value and not a range", async () => {
    const response = clone(await client().attention(DEMO));
    (response as { schema_version: string }).schema_version = "cockpit.attention_list.v3";
    expect(() =>
      admit("AttentionList", attentionListEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });
});
