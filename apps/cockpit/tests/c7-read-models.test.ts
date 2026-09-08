import { describe, expect, it } from "vitest";

import {
  aiContributionEnvelope,
  championChallengerEnvelope,
  feedbackPipelineEnvelope,
  hypothesisRegistrationEnvelope,
  researchQueueEnvelope,
  researchRunEnvelope,
} from "@/contracts/research-models";
import {
  decisionRecordEnvelope,
  governancePacketEnvelope,
} from "@/contracts/governance-models";
import {
  DEGRADATION_HEALTH_STATES,
  strategyHealthEnvelope,
  strategyVersionEnvelope,
} from "@/contracts/strategy-models";
import { REFERENCE_FIELDS } from "@/contracts/references";
import { producerStateFor } from "@/contracts/reference-access";
import { C3_METRIC_DICTIONARY } from "@/contracts/values";
import { isValueBearing } from "@/contracts/validity";
import { STRATEGY_HEALTH_STATES } from "@/contracts/vocabularies";
import { ContractViolationError, admit } from "@/data/client/read-client";
import { readModelKey } from "@/data/client/query-keys";
import {
  GOVERNANCE_PACKET_IDENTITY,
  RESEARCH_RUN_IDENTITY,
  STRATEGY_HEALTH_IDENTITY,
} from "@/data/client/read-model-identity";
import { FixtureReadClient } from "@/data/fixtures/adapter";
import { BOOK } from "@/data/fixtures/book";
import {
  CHALLENGERS,
  LINEAGE_BUDGET,
  OWN_TRIALS,
  QUEUE_ITEMS,
  REGISTRATIONS,
  RUNS,
} from "@/data/fixtures/lineage";
import { referenceDestination, owningAreaDestination } from "@/lib/reference-navigation";
import { fixedClock } from "@/lib/clock";
import { DEFAULT_SCOPE } from "@/lib/scope";

/**
 * The C7 read models, their invariants, and the synthetic lineage they are projected from.
 *
 * EVERY EXPECTED VALUE IS DERIVED INDEPENDENTLY of the projection that produced it: the
 * lineage constants, the demonstration book and the accepted vocabularies are the comparands,
 * never the payload restated. Where a rule is error-prone in one specific direction — a
 * renamed registration looking like a fresh budget, a reproduction spending a trial, a
 * readiness reading as an approval — the test carries a NEGATIVE CONTROL that reintroduces the
 * defect on a cloned payload and asserts the boundary REFUSES it, so the assertion
 * distinguishes the two rules rather than passing under both.
 */

const ORIGIN = "2026-09-08T13:00:00.000Z";
const DEMO = { ...DEFAULT_SCOPE, scenario: "demo" as const };
const PROJECT = DEFAULT_SCOPE;

function client() {
  return new FixtureReadClient({ clock: fixedClock(ORIGIN) });
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

/* ==================================================================== admission */

describe("C7 admission, provenance and scope isolation", () => {
  it("admits all ten research, feedback and governance read models in the demonstration", async () => {
    const read = client();
    const responses = [
      [await read.strategyHealth(DEMO), strategyHealthEnvelope, "StrategyHealth"],
      [await read.strategyVersions(DEMO), strategyVersionEnvelope, "StrategyVersion"],
      [await read.researchRuns(DEMO), researchRunEnvelope, "ResearchRun"],
      [await read.researchQueue(DEMO), researchQueueEnvelope, "ResearchQueueItem"],
      [await read.hypotheses(DEMO), hypothesisRegistrationEnvelope, "HypothesisRegistration"],
      [
        await read.championChallenger(DEMO),
        championChallengerEnvelope,
        "ChampionChallengerComparison",
      ],
      [await read.aiContribution(DEMO), aiContributionEnvelope, "AiContribution"],
      [await read.feedbackPipeline(DEMO), feedbackPipelineEnvelope, "FeedbackPipeline"],
      [await read.governancePackets(DEMO), governancePacketEnvelope, "GovernancePacket"],
      [await read.decisions(DEMO), decisionRecordEnvelope, "DecisionRecord"],
    ] as const;
    for (const [response, schema, name] of responses) {
      expect(response.payload, name).toBeDefined();
      expect(response.provenance, name).toBe("SYNTHETIC");
      expect(response.classification, name).toBe("PUBLIC_SAFE");
      /* The whole response passes the REAL admission path, not a bare schema parse. */
      expect(() => admit(name, schema, response, "PUBLIC_EDGE")).not.toThrow();
    }
  });

  it("answers project scope with a payloadless NOT_IMPLEMENTED for every one of them", async () => {
    const read = client();
    for (const response of [
      await read.strategyHealth(PROJECT),
      await read.strategyVersions(PROJECT),
      await read.researchRuns(PROJECT),
      await read.researchQueue(PROJECT),
      await read.hypotheses(PROJECT),
      await read.championChallenger(PROJECT),
      await read.aiContribution(PROJECT),
      await read.feedbackPipeline(PROJECT),
      await read.governancePackets(PROJECT),
      await read.decisions(PROJECT),
    ]) {
      expect(response.payload).toBeUndefined();
      expect(response.availability).toBe("NOT_IMPLEMENTED");
      expect(response.availability_reason).toBe("PRODUCER_NOT_IMPLEMENTED");
      /*
       * The RESEARCH scope IS populated as a scope -- it simply has no producer for these ten
       * read models -- so it keeps the maturity stage the accepted mapping pairs with it. The
       * unpopulated ENVIRONMENTS below are the case that carries none.
       */
      expect(response.maturity_stage).toBe("RESEARCH");
    }
  });

  it("answers Paper and Live with an absence rather than the same record rebadged", async () => {
    const read = client();
    for (const environment of ["PAPER", "LIVE"] as const) {
      const response = await read.researchRuns({ ...DEMO, environment });
      expect(response.payload).toBeUndefined();
      expect(response.availability).toBe("NOT_IMPLEMENTED");
      expect(response.environment).toBe(environment);
      /* Nothing has reached AUTOMATED_PAPER, so no stage is claimed for these scopes. */
      expect(response.maturity_stage).toBeUndefined();
    }
  });

  it("keys the three access scopes apart, so no scope serves another's payload", () => {
    const health = readModelKey(STRATEGY_HEALTH_IDENTITY, DEMO);
    const runs = readModelKey(RESEARCH_RUN_IDENTITY, DEMO);
    const packets = readModelKey(GOVERNANCE_PACKET_IDENTITY, DEMO);
    expect(health).toContain("strategy:read");
    expect(runs).toContain("research:read");
    expect(packets).toContain("governance:read");
    expect(new Set([health, runs, packets].map((key) => JSON.stringify(key))).size).toBe(3);
  });

  it("registers every metric it emits in the closed dictionary", async () => {
    const read = client();
    const payloads = [
      await read.strategyHealth(DEMO),
      await read.strategyVersions(DEMO),
      await read.researchRuns(DEMO),
      await read.researchQueue(DEMO),
      await read.hypotheses(DEMO),
      await read.championChallenger(DEMO),
      await read.aiContribution(DEMO),
      await read.feedbackPipeline(DEMO),
      await read.governancePackets(DEMO),
      await read.decisions(DEMO),
    ];
    const seen = new Set<string>();
    const walk = (node: unknown): void => {
      if (Array.isArray(node)) {
        node.forEach(walk);
        return;
      }
      if (typeof node !== "object" || node === null) {
        return;
      }
      const record = node as Record<string, unknown>;
      if (typeof record.metric_id === "string" && typeof record.unit === "string") {
        seen.add(record.metric_id);
      }
      Object.values(record).forEach(walk);
    };
    payloads.forEach(walk);
    expect(seen.size).toBeGreaterThan(20);
    for (const metricId of seen) {
      expect(C3_METRIC_DICTIONARY[metricId], metricId).toBeDefined();
    }
  });
});

/* ================================================================== Area 5 — health */

describe("strategy health renders the seven states and causes no transition", () => {
  it("delivers the closed vocabulary and carries only its members", async () => {
    const payload = (await client().strategyHealth(DEMO)).payload!;
    expect(payload.health_states).toEqual([...STRATEGY_HEALTH_STATES]);
    for (const entry of payload.items) {
      expect(STRATEGY_HEALTH_STATES).toContain(entry.state);
      for (const transition of entry.transitions) {
        expect(STRATEGY_HEALTH_STATES).toContain(transition.from);
        expect(STRATEGY_HEALTH_STATES).toContain(transition.to);
      }
    }
  });

  it("ends every transition chain on the state the record reports", async () => {
    const payload = (await client().strategyHealth(DEMO)).payload!;
    for (const entry of payload.items) {
      const last = entry.transitions[entry.transitions.length - 1];
      if (last !== undefined) {
        expect(last.to, entry.strategy_version).toBe(entry.state);
      }
      for (let index = 1; index < entry.transitions.length; index += 1) {
        expect(entry.transitions[index].from).toBe(entry.transitions[index - 1].to);
        expect(entry.transitions[index].at > entry.transitions[index - 1].at).toBe(true);
      }
    }
  });

  /* NEGATIVE CONTROL: a history that lands somewhere else is refused, not rendered. */
  it("refuses a transition chain that ends on a different state", async () => {
    const response = clone(await client().strategyHealth(DEMO));
    const subject = response.payload!.items.find((entry) => entry.transitions.length > 0)!;
    subject.transitions[subject.transitions.length - 1].to =
      subject.state === "HEALTHY" ? "SUSPENDED" : "HEALTHY";
    expect(() =>
      admit("StrategyHealth", strategyHealthEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("shows the research queue entry every recorded degradation created", async () => {
    const payload = (await client().strategyHealth(DEMO)).payload!;
    const degraded = payload.items.filter((entry) =>
      DEGRADATION_HEALTH_STATES.includes(entry.state),
    );
    expect(degraded.length).toBeGreaterThan(0);
    for (const entry of degraded) {
      expect(entry.queue_item_ref, entry.strategy_version).toBeDefined();
      expect(entry.queue_item_ref!.ref_kind).toBe("queue_item");
    }
    /* A supersession is not a degradation, and carries no queue entry. */
    const retired = payload.items.find((entry) => entry.state === "RETIRED")!;
    expect(retired.queue_item_ref).toBeUndefined();
  });

  /* NEGATIVE CONTROL: removing the queue reference from a degradation is refused. */
  it("refuses a recorded degradation that names no research queue entry", async () => {
    const response = clone(await client().strategyHealth(DEMO));
    const subject = response.payload!.items.find((entry) =>
      DEGRADATION_HEALTH_STATES.includes(entry.state),
    )!;
    delete (subject as { queue_item_ref?: unknown }).queue_item_ref;
    expect(() =>
      admit("StrategyHealth", strategyHealthEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/research queue entry/);
  });

  it("reports the observation count AND the minimum where the minimum is unmet", async () => {
    const payload = (await client().strategyHealth(DEMO)).payload!;
    const short = payload.items.filter((entry) => !entry.minimum_observations_met);
    expect(short.length).toBeGreaterThan(0);
    for (const entry of short) {
      expect(isValueBearing(entry.observation_count.availability)).toBe(true);
      expect(isValueBearing(entry.minimum_observations.availability)).toBe(true);
      expect(entry.observation_count.value as number).toBeLessThan(
        entry.minimum_observations.value as number,
      );
    }
  });

  it("keeps the health figures a performance summary owns identical to that summary", async () => {
    const read = client();
    const health = (await read.strategyHealth(DEMO)).payload!;
    const performance = (await read.strategyPerformance(DEMO)).payload!;
    for (const entry of health.items) {
      const matching = performance.items.find(
        (row) => row.strategy_version === entry.strategy_version,
      )!;
      /* One builder, one answer: the two screens cannot report two expectancies. */
      const expectancy = entry.health_inputs.find(
        (input) => input.input.code === "EXPECTANCY",
      )!;
      expect(expectancy.value, entry.strategy_version).toEqual(matching.summary.expectancy);
      expect(entry.observation_count).toEqual(matching.summary.observation_count);
    }
  });

  it("states the recovery authority without widening it", async () => {
    const payload = (await client().strategyHealth(DEMO)).payload!;
    const reduced = payload.items.find((entry) => entry.state === "NEW_ENTRIES_REDUCED")!;
    expect(reduced.recovery_authority.code).toContain("RESTORATION_REQUIRES_HUMAN_AUTHORITY");
    expect(reduced.recovery_requirements.length).toBeGreaterThan(0);
  });
});

/* ================================================================ Area 20 — versions */

describe("the version registry pins open positions to the versions that opened them", () => {
  it("carries every open book position under the exact version that opened it", async () => {
    const payload = (await client().strategyVersions(DEMO)).payload!;
    const pinned = payload.items.flatMap((entry) =>
      entry.open_positions.map((position) => ({
        version: entry.strategy_version,
        trade: position.trade_ref.ref_id,
      })),
    );
    const expected = BOOK.openTrades.map((trade) => ({
      version: trade.versionId,
      trade: trade.tradeId,
    }));
    expect(pinned.sort((a, b) => a.trade.localeCompare(b.trade))).toEqual(
      expected.sort((a, b) => a.trade.localeCompare(b.trade)),
    );
    for (const entry of payload.items) {
      for (const position of entry.open_positions) {
        expect(position.pinned.strategy_version).toBe(entry.strategy_version);
      }
    }
  });

  /* NEGATIVE CONTROL: a position pinned to another version is not this version's. */
  it("refuses an open position pinned to a different strategy version", async () => {
    const response = clone(await client().strategyVersions(DEMO));
    const subject = response.payload!.items.find((entry) => entry.open_positions.length > 0)!;
    subject.open_positions[0].pinned.strategy_version = "some-other-version";
    expect(() =>
      admit("StrategyVersion", strategyVersionEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/pinned to another strategy version/);
  });

  it("gives a Challenger no open position and no order authority", async () => {
    const payload = (await client().strategyVersions(DEMO)).payload!;
    const challengers = payload.items.filter((entry) => entry.role.code === "CHALLENGER");
    expect(challengers.map((entry) => entry.strategy_version).sort()).toEqual(
      [CHALLENGERS.pullback, CHALLENGERS.peadShort].sort(),
    );
    for (const challenger of challengers) {
      expect(challenger.open_positions).toEqual([]);
      expect(challenger.open_position_refs.total.availability).toBe("AVAILABLE");
      expect(challenger.open_position_refs.total.value).toBe(0);
      expect(challenger.maturity_stage).toBe("SHADOW");
    }
  });

  it("reaches no order-producing maturity stage anywhere in the registry", async () => {
    const payload = (await client().strategyVersions(DEMO)).payload!;
    for (const entry of payload.items) {
      expect(["RESEARCH", "SHADOW"], entry.strategy_version).toContain(entry.maturity_stage);
    }
  });

  it("records no rollback at all, and does not invent one", async () => {
    const payload = (await client().strategyVersions(DEMO)).payload!;
    expect(payload.items.filter((entry) => entry.rollback_of !== undefined)).toEqual([]);
  });
});

/* ==================================================================== Area 14 — runs */

describe("a run without a resolvable named baseline renders incomplete", () => {
  it("carries the reference and reports the comparison as an availability state", async () => {
    const payload = (await client().researchRuns(DEMO)).payload!;
    const incomplete = payload.items.find((entry) => entry.run_id === RUNS.abandonedReuse)!;
    /* The reference stays VISIBLE — §4.3 keeps a join a reader can see. */
    expect(incomplete.baseline_ref.ref_kind).toBe("strategy_version");
    expect(incomplete.baseline_state.availability).toBe("NOT_YET_AVAILABLE");
    expect(incomplete.baseline_state.reason).toBe("REFERENT_NOT_FOUND");
    for (const measure of incomplete.baseline_comparison) {
      expect(measure.value.value).toBeUndefined();
    }
  });

  it("names a baseline the registry does not hold, which is why it is incomplete", async () => {
    const read = client();
    const runs = (await read.researchRuns(DEMO)).payload!;
    const versions = (await read.strategyVersions(DEMO)).payload!;
    const known = new Set(versions.items.map((entry) => entry.strategy_version));
    const incomplete = runs.items.find((entry) => entry.run_id === RUNS.abandonedReuse)!;
    expect(known.has(incomplete.baseline_ref.ref_id)).toBe(false);
    const complete = runs.items.find((entry) => entry.run_id === RUNS.confirmatory)!;
    expect(known.has(complete.baseline_ref.ref_id)).toBe(true);
  });

  /* NEGATIVE CONTROL: a clean comparison against an unresolved baseline is refused. */
  it("refuses a comparison value on a run whose baseline did not resolve", async () => {
    const response = clone(await client().researchRuns(DEMO));
    const subject = response.payload!.items.find(
      (entry) => entry.run_id === RUNS.abandonedReuse,
    )!;
    subject.baseline_comparison[0].value = {
      ...subject.baseline_comparison[0].value,
      availability: "AVAILABLE",
      reason: "NONE",
      as_of: ORIGIN,
      value: "0.00",
    };
    expect(() =>
      admit("ResearchRun", researchRunEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("counts every terminal run except the deterministic reproduction", async () => {
    const payload = (await client().researchRuns(DEMO)).payload!;
    const failed = payload.items.find((entry) => entry.run_id === RUNS.failed)!;
    const abandoned = payload.items.find((entry) => entry.run_id === RUNS.abandonedLineage)!;
    const reproduction = payload.items.find((entry) => entry.run_id === RUNS.reproduction)!;
    expect(failed.state).toBe("FAILED");
    expect(failed.counts_against_budget).toBe(true);
    expect(abandoned.state).toBe("ABANDONED");
    expect(abandoned.counts_against_budget).toBe(true);
    expect(reproduction.state).toBe("COMPLETED");
    expect(reproduction.evaluation_class).toBe("DETERMINISTIC_REPRODUCTION");
    expect(reproduction.counts_against_budget).toBe(false);
    /* The lineage budget is the number of trials the runs actually spent. */
    expect(payload.items.filter((entry) => entry.counts_against_budget).length).toBe(
      LINEAGE_BUDGET.consumed,
    );
  });

  /* NEGATIVE CONTROL: a failed run that spends no trial is refused. */
  it("refuses a failed run that does not count against the budget", async () => {
    const response = clone(await client().researchRuns(DEMO));
    const subject = response.payload!.items.find((entry) => entry.run_id === RUNS.failed)!;
    subject.counts_against_budget = false;
    expect(() => admit("ResearchRun", researchRunEnvelope, response, "PUBLIC_EDGE")).toThrow(
      /trial budget/,
    );
  });

  /* NEGATIVE CONTROL: and a reproduction that DOES spend one is refused too. */
  it("refuses a deterministic reproduction that spends a trial", async () => {
    const response = clone(await client().researchRuns(DEMO));
    const subject = response.payload!.items.find(
      (entry) => entry.run_id === RUNS.reproduction,
    )!;
    subject.counts_against_budget = true;
    expect(() => admit("ResearchRun", researchRunEnvelope, response, "PUBLIC_EDGE")).toThrow(
      /deterministic reproduction/,
    );
  });

  it("carries the evaluation class on every run and never derives it from the state", async () => {
    const payload = (await client().researchRuns(DEMO)).payload!;
    const byClass = new Map(payload.items.map((entry) => [entry.run_id, entry.evaluation_class]));
    /* Two runs share a state and differ in class; one class covers two states. */
    expect(byClass.get(RUNS.confirmatory)).toBe("CONFIRMATORY");
    expect(byClass.get(RUNS.reuse)).toBe("EXPLORATORY_REUSE");
    expect(byClass.get(RUNS.reproduction)).toBe("DETERMINISTIC_REPRODUCTION");
    expect(byClass.get(RUNS.abandonedReuse)).toBe("CONFIRMATORY");
    for (const entry of payload.items) {
      if (entry.evaluation_class === "EXPLORATORY_REUSE") {
        expect(entry.exposure_disclosure.length, entry.run_id).toBeGreaterThan(0);
      }
    }
  });

  it("declares the provider-realistic profile and never a public point-in-time one", async () => {
    const payload = (await client().researchRuns(DEMO)).payload!;
    for (const entry of payload.items) {
      expect(entry.reproducibility.profile.code).toBe("PROVIDER_REALISTIC_PIT");
    }
  });
});

/* ============================================================== Area 18 — hypotheses */

describe("exposure and budget are read across the lineage, and a rename resets neither", () => {
  it("gives every registration of one lineage the same budget, and its own count beside it", async () => {
    const payload = (await client().hypotheses(DEMO)).payload!;
    const lineage = payload.items.filter((entry) =>
      Object.keys(OWN_TRIALS).includes(entry.registration_id),
    );
    expect(lineage.length).toBe(4);
    for (const entry of lineage) {
      expect(entry.trial_budget.granted.value, entry.registration_id).toBe(
        LINEAGE_BUDGET.granted,
      );
      expect(entry.trial_budget.consumed.value, entry.registration_id).toBe(
        LINEAGE_BUDGET.consumed,
      );
      expect(entry.trial_budget.remaining.value, entry.registration_id).toBe(
        LINEAGE_BUDGET.remaining,
      );
      expect(entry.own_trial_count.value, entry.registration_id).toBe(
        OWN_TRIALS[entry.registration_id],
      );
    }
    /* The renamed registration ran ONE trial of its own against a lineage that spent five. */
    const renamed = lineage.find(
      (entry) => entry.registration_id === REGISTRATIONS.renamedReuse,
    )!;
    expect(renamed.own_trial_count.value).toBeLessThan(
      renamed.trial_budget.consumed.value as number,
    );
  });

  /* NEGATIVE CONTROL: a lineage consumption smaller than the identity's own count. */
  it("refuses a lineage consumption smaller than the registration's own trials", async () => {
    const response = clone(await client().hypotheses(DEMO));
    const subject = response.payload!.items.find(
      (entry) => entry.registration_id === REGISTRATIONS.original,
    )!;
    subject.trial_budget.consumed.value = 1;
    subject.trial_budget.remaining.value = (subject.trial_budget.granted.value as number) - 1;
    expect(() =>
      admit("HypothesisRegistration", hypothesisRegistrationEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/never smaller than them/);
  });

  it("refuses a confirmatory declaration over a set the ledger records as exposed", async () => {
    const payload = (await client().hypotheses(DEMO)).payload!;
    const renamed = payload.items.find(
      (entry) => entry.registration_id === REGISTRATIONS.renamedReuse,
    )!;
    expect(renamed.declared_evaluation_class).toBe("CONFIRMATORY");
    expect(renamed.exposure_ledger.refusal?.code).toBe("OUT_OF_SAMPLE_ALREADY_CONSUMED");
    /* The prior entries it is refused against were written by OTHER registrations. */
    const priorAuthors = renamed.exposure_ledger.entries
      .filter((entry) => entry.at < renamed.registered_at)
      .map((entry) => entry.registration_ref.ref_id);
    expect(priorAuthors).toContain(REGISTRATIONS.original);
    expect(priorAuthors).toContain(REGISTRATIONS.amendment);
  });

  it("refuses a confirmatory declaration whose ledger cannot be shown complete", async () => {
    const payload = (await client().hypotheses(DEMO)).payload!;
    const unknown = payload.items.find(
      (entry) => entry.registration_id === REGISTRATIONS.unknownHistory,
    )!;
    expect(unknown.exposure_ledger.completeness).toBe("UNKNOWN");
    expect(unknown.exposure_ledger.refusal?.code).toBe("EXPOSURE_HISTORY_UNKNOWN");
    /* Incomparable is not disjoint: the overlap is UNKNOWN and never a zero. */
    const unmeasurable = unknown.exposure_ledger.entries.filter(
      (entry) => entry.measured_overlap.value === undefined,
    );
    expect(unmeasurable.length).toBeGreaterThan(0);
    for (const entry of unmeasurable) {
      expect(entry.measured_overlap.availability).toBe("NOT_YET_AVAILABLE");
      expect(entry.measured_overlap.reason).toBe("EXTENT_NOT_DETERMINABLE");
    }
  });

  /* NEGATIVE CONTROL: dropping the refusal readmits the renamed reuse as confirmation. */
  it("refuses a renamed confirmatory registration that carries no ledger refusal", async () => {
    const response = clone(await client().hypotheses(DEMO));
    const subject = response.payload!.items.find(
      (entry) => entry.registration_id === REGISTRATIONS.renamedReuse,
    )!;
    delete (subject.exposure_ledger as { refusal?: unknown }).refusal;
    expect(() =>
      admit("HypothesisRegistration", hypothesisRegistrationEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/carries its refusal/);
  });

  it("leaves an untouched first confirmatory declaration unrefused", async () => {
    const payload = (await client().hypotheses(DEMO)).payload!;
    const original = payload.items.find(
      (entry) => entry.registration_id === REGISTRATIONS.original,
    )!;
    expect(original.declared_evaluation_class).toBe("CONFIRMATORY");
    expect(original.exposure_ledger.refusal).toBeUndefined();
    /* Nothing preceded it: every ledger entry was written after it was registered. */
    for (const entry of original.exposure_ledger.entries) {
      expect(entry.at >= original.registered_at).toBe(true);
    }
  });

  it("keeps registrations immutable and links amendments rather than editing them", async () => {
    const payload = (await client().hypotheses(DEMO)).payload!;
    for (const entry of payload.items) {
      expect(entry.immutable, entry.registration_id).toBe(true);
      expect(entry.failure_criteria.length, entry.registration_id).toBeGreaterThan(0);
    }
    const original = payload.items.find(
      (entry) => entry.registration_id === REGISTRATIONS.original,
    )!;
    const amendment = payload.items.find(
      (entry) => entry.registration_id === REGISTRATIONS.amendment,
    )!;
    expect(original.lineage.amendment_chain.items.map((ref) => ref.ref_id)).toContain(
      REGISTRATIONS.amendment,
    );
    expect(amendment.lineage.parent_registration?.ref_id).toBe(REGISTRATIONS.original);
    /* Results APPEND: every run of the amendment names the amendment, not the parent. */
    expect(amendment.linked_results.items.map((ref) => ref.ref_id).sort()).toEqual(
      [RUNS.reuse, RUNS.abandonedLineage, RUNS.reproduction].sort(),
    );
  });

  it("traces every registration back to a recorded queue item", async () => {
    const read = client();
    const payload = (await read.hypotheses(DEMO)).payload!;
    const queue = (await read.researchQueue(DEMO)).payload!;
    const known = new Set(queue.items.map((entry) => entry.item_id));
    for (const entry of payload.items) {
      expect(entry.trigger_ref.ref_kind).toBe("queue_item");
      expect(known.has(entry.trigger_ref.ref_id), entry.registration_id).toBe(true);
    }
  });
});

/* ================================================================== Area 17 — queue */

describe("a queue entry is not an authorization", () => {
  it("names at least one outstanding authorization on every open item", async () => {
    const payload = (await client().researchQueue(DEMO)).payload!;
    const open = payload.items.filter((entry) => entry.state !== "WITHDRAWN");
    expect(open.length).toBeGreaterThan(0);
    for (const entry of open) {
      expect(entry.awaiting_authorizations.length, entry.item_id).toBeGreaterThan(0);
    }
    const withdrawn = payload.items.find((entry) => entry.state === "WITHDRAWN")!;
    expect(withdrawn.awaiting_authorizations).toEqual([]);
    expect(withdrawn.withdrawal_reason).toBeDefined();
  });

  /* NEGATIVE CONTROL: an open item that awaits nothing reads as one that may proceed. */
  it("refuses an open queue item that names no authorization", async () => {
    const response = clone(await client().researchQueue(DEMO));
    const subject = response.payload!.items.find((entry) => entry.state !== "WITHDRAWN")!;
    subject.awaiting_authorizations = [];
    expect(() =>
      admit("ResearchQueueItem", researchQueueEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/waiting on/);
  });

  it("carries the health trigger's owning area on the reference, not in its kind", async () => {
    const payload = (await client().researchQueue(DEMO)).payload!;
    const health = payload.items.find((entry) => entry.item_id === QUEUE_ITEMS.pullback)!;
    /* The kind is the catalogue's; the AREA is the second, separate attribute. */
    expect(health.trigger_ref.ref_kind).toBe("source_fact");
    expect(health.trigger_ref.owning_area).toBe("STRATEGY_HEALTH");
    expect(owningAreaDestination(health.trigger_ref)?.href).toBe("/strategy/health");
    /* And a trigger with no determined area declares none, and gets no area control. */
    const missed = payload.items.find((entry) => entry.item_id === QUEUE_ITEMS.missed)!;
    expect(missed.trigger_ref.owning_area).toBeUndefined();
    expect(owningAreaDestination(missed.trigger_ref)).toBeNull();
  });

  it("links the health degradation to the queue entry it created, in both directions", async () => {
    const read = client();
    const health = (await read.strategyHealth(DEMO)).payload!;
    const queue = (await read.researchQueue(DEMO)).payload!;
    const watched = health.items.find(
      (entry) => entry.queue_item_ref?.ref_id === QUEUE_ITEMS.pullback,
    )!;
    const item = queue.items.find((entry) => entry.item_id === QUEUE_ITEMS.pullback)!;
    expect(item.baseline_ref.ref_id).toBe(watched.strategy_version);
    expect(item.registration_ref?.ref_id).toBe(REGISTRATIONS.original);
  });
});

/* ================================================= Area 15 — Champion / Challenger */

describe("readiness is displayed and never conferred", () => {
  it("carries a readiness that says what is missing, and never that it is approved", async () => {
    const payload = (await client().championChallenger(DEMO)).payload!;
    expect(payload.items.length).toBeGreaterThan(0);
    for (const entry of payload.items) {
      const readiness = entry.readiness.code;
      expect(readiness).toMatch(/^NOT_READY_/);
      for (const forbidden of ["APPROVED", "AUTHORIZED", "PROMOTED", "PROCEED"]) {
        expect(readiness, forbidden).not.toContain(forbidden);
      }
    }
  });

  it("gives a Challenger no realized outcome at all", async () => {
    const payload = (await client().championChallenger(DEMO)).payload!;
    for (const entry of payload.items) {
      expect(isValueBearing(entry.realized_outcomes.availability)).toBe(false);
    }
  });

  /* NEGATIVE CONTROL: a Challenger with a realized outcome claims it traded. */
  it("refuses a comparison carrying a value-bearing realized outcome", async () => {
    const response = clone(await client().championChallenger(DEMO));
    response.payload!.items[0].realized_outcomes = {
      availability: "AVAILABLE",
      reason: "NONE",
    };
    expect(() =>
      admit("ChampionChallengerComparison", championChallengerEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/realized outcome/);
  });

  it("states the comparable population, and refuses a ratio where none is defined", async () => {
    const payload = (await client().championChallenger(DEMO)).payload!;
    const incomparable = payload.items.find(
      (entry) => entry.evidence_completeness === "UNKNOWN",
    )!;
    expect(incomparable.comparable_population.code).toContain("NO_COMPARABLE_POPULATION");
    for (const measure of incomparable.overlap) {
      expect(measure.value.availability).toBe("INSUFFICIENT_OBSERVATIONS");
    }
  });

  it("discloses exploratory reuse on every comparison that rests on it", async () => {
    const payload = (await client().championChallenger(DEMO)).payload!;
    for (const entry of payload.items) {
      if (entry.evaluation_class === "EXPLORATORY_REUSE") {
        expect(entry.data_exposure_disclosure.length, entry.challenger_version).toBeGreaterThan(
          0,
        );
      }
    }
  });

  /* NEGATIVE CONTROL: dropping the disclosure presents reuse as fresh evidence. */
  it("refuses an exploratory comparison with an empty disclosure", async () => {
    const response = clone(await client().championChallenger(DEMO));
    const subject = response.payload!.items.find(
      (entry) => entry.evaluation_class === "EXPLORATORY_REUSE",
    )!;
    subject.data_exposure_disclosure = [];
    expect(() =>
      admit("ChampionChallengerComparison", championChallengerEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/disclosed/);
  });

  it("keeps hypothetical shadow economics out of every realized metric identifier", async () => {
    const payload = (await client().championChallenger(DEMO)).payload!;
    for (const entry of payload.items) {
      for (const measure of entry.shadow_economics) {
        expect(measure.value.metric_id).toBe("comparison.shadow_hypothetical_return");
        expect(measure.value.unit).not.toBe("USD");
      }
    }
  });
});

/* =========================================================== Area 21 — AI contribution */

describe("AI contribution reports a rule rather than a difference it cannot support", () => {
  it("reports no arm outcome where the matched population is below the minimum", async () => {
    const payload = (await client().aiContribution(DEMO)).payload!;
    const short = payload.items.find((entry) => !entry.minimum_observations_met)!;
    for (const arm of short.arms) {
      expect(arm.outcome.availability).toBe("INSUFFICIENT_OBSERVATIONS");
      expect(arm.outcome.value).toBeUndefined();
    }
    expect(short.minimum_observations.value).toBeGreaterThan(
      short.arms[0].population.value as number,
    );
  });

  it("reports no arm outcome where the arms are not matched", async () => {
    const payload = (await client().aiContribution(DEMO)).payload!;
    const unmatched = payload.items.find((entry) => !entry.matched)!;
    for (const arm of unmatched.arms) {
      expect(arm.outcome.value).toBeUndefined();
    }
  });

  /* NEGATIVE CONTROL: an outcome under an unmet minimum is the ratio the rule refuses. */
  it("refuses an arm outcome below the declared minimum observations", async () => {
    const response = clone(await client().aiContribution(DEMO));
    const subject = response.payload!.items.find(
      (entry) => !entry.minimum_observations_met,
    )!;
    subject.arms[0].outcome = {
      ...subject.arms[0].outcome,
      availability: "AVAILABLE",
      reason: "NONE",
      as_of: ORIGIN,
      value: "0.31",
    };
    expect(() =>
      admit("AiContribution", aiContributionEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/INSUFFICIENT_OBSERVATIONS/);
  });

  it("carries an uncertainty in the same unit beside every reported outcome", async () => {
    const payload = (await client().aiContribution(DEMO)).payload!;
    const reportable = payload.items.find(
      (entry) => entry.matched && entry.minimum_observations_met,
    )!;
    for (const arm of reportable.arms) {
      expect(arm.outcome.value).toBeDefined();
      expect(arm.uncertainty.value).toBeDefined();
      expect(arm.uncertainty.unit).toBe(arm.outcome.unit);
    }
  });

  /* NEGATIVE CONTROL: a point estimate with no interval is a claim. */
  it("refuses a reported outcome with no stated uncertainty", async () => {
    const response = clone(await client().aiContribution(DEMO));
    const subject = response.payload!.items.find(
      (entry) => entry.matched && entry.minimum_observations_met,
    )!;
    subject.arms[0].uncertainty = {
      ...subject.arms[0].uncertainty,
      availability: "INSUFFICIENT_OBSERVATIONS",
      reason: "BELOW_MINIMUM_OBSERVATIONS",
    };
    delete (subject.arms[0].uncertainty as { value?: unknown }).value;
    delete (subject.arms[0].uncertainty as { as_of?: unknown }).as_of;
    expect(() =>
      admit("AiContribution", aiContributionEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/stated uncertainty/);
  });

  it("makes no causal claim, and names the gate that owns the question", async () => {
    const payload = (await client().aiContribution(DEMO)).payload!;
    for (const entry of payload.items) {
      expect(entry.causal_attribution.availability).toBe("UNEVALUATED");
      expect(entry.causal_attribution.gate.code).toContain("EXPERIMENT_E_HAS_NOT_BEEN_RUN");
    }
  });
});

/* =================================================================== Area 16 — the loop */

describe("the feedback loop is read and never driven", () => {
  it("carries ten stages, of which exactly one is human-only and it is the tenth", async () => {
    const payload = (await client().feedbackPipeline(DEMO)).payload!;
    expect(payload.stages).toHaveLength(10);
    const humanOnly = payload.stages.filter((stage) => !stage.automatable);
    expect(humanOnly).toHaveLength(1);
    expect(payload.stages[9].automatable).toBe(false);
    expect(payload.human_only_stage.code).toBe(payload.stages[9].stage.code);
  });

  /* NEGATIVE CONTROL: an automatable tenth stage is self-governance. */
  it("refuses a loop whose tenth stage may run without a human", async () => {
    const response = clone(await client().feedbackPipeline(DEMO));
    response.payload!.stages[9].automatable = true;
    expect(() =>
      admit("FeedbackPipeline", feedbackPipelineEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(ContractViolationError);
  });

  it("names an outstanding authorization on every stage, and blocks no more than it holds", async () => {
    const payload = (await client().feedbackPipeline(DEMO)).payload!;
    for (const stage of payload.stages) {
      expect(stage.awaiting_authorizations.length, stage.stage.code).toBeGreaterThan(0);
      expect(stage.blocked_count.value as number).toBeLessThanOrEqual(
        stage.item_count.value as number,
      );
    }
  });

  it("enumerates queue-item references only, and says so where the list is empty", async () => {
    const read = client();
    const payload = (await read.feedbackPipeline(DEMO)).payload!;
    const queue = (await read.researchQueue(DEMO)).payload!;
    const known = new Set(queue.items.map((entry) => entry.item_id));
    for (const stage of payload.stages) {
      expect(stage.item_reference_scope.code).toContain("QUEUE_ITEM");
      for (const reference of stage.item_refs.items) {
        expect(reference.ref_kind).toBe("queue_item");
        expect(known.has(reference.ref_id), reference.ref_id).toBe(true);
      }
    }
    /* The journal stage holds items and enumerates no queue item, which is a true answer. */
    const journal = payload.stages[0];
    expect(journal.item_refs.items).toEqual([]);
    expect(journal.item_refs.total.availability).toBe("AVAILABLE");
    expect(journal.item_count.value as number).toBeGreaterThan(0);
  });
});

/* ================================================================ Area 19 — governance */

describe("a packet is evidence for a decision, and never the decision", () => {
  it("keeps recommendation, readiness, decision and execution as four separate facts", async () => {
    const read = client();
    const packets = (await read.governancePackets(DEMO)).payload!;
    const decisions = (await read.decisions(DEMO)).payload!;
    const ready = packets.items.find((entry) => entry.state === "READY_FOR_HUMAN_REVIEW")!;
    /* A recommendation is a closed code, and it is never an approval verb. */
    expect(ready.recommendation.code).toMatch(/^RECOMMEND_|^NO_RECOMMENDATION/);
    expect(ready.decision_authority.code).toContain("HUMAN");
    /* Readiness is a state; a decision is a separate record with its own identity. */
    const undecided = packets.items.find((entry) => entry.decision_ref === undefined)!;
    expect(undecided.state).toBe("READY_FOR_HUMAN_REVIEW");
    expect(
      decisions.items.some((entry) => entry.packet_ref.ref_id === undecided.packet_id),
    ).toBe(false);
  });

  it("names what an assembling packet is missing, and misses nothing when ready", async () => {
    const payload = (await client().governancePackets(DEMO)).payload!;
    const assembling = payload.items.find((entry) => entry.state === "ASSEMBLING")!;
    expect(assembling.missing_evidence.map((code) => code.code)).toContain("EVIDENCE_INCOMPLETE");
    expect(assembling.trial_count.value).toBeUndefined();
    for (const entry of payload.items.filter(
      (packet) => packet.state === "READY_FOR_HUMAN_REVIEW",
    )) {
      expect(entry.missing_evidence, entry.packet_id).toEqual([]);
      expect(entry.trial_count.value, entry.packet_id).toBeDefined();
      for (const criterion of entry.criteria_evaluation) {
        expect(criterion.verdict, entry.packet_id).toBeDefined();
      }
    }
  });

  /* NEGATIVE CONTROL: a ready packet that is still missing something. */
  it("refuses a packet marked ready for review while evidence is missing", async () => {
    const response = clone(await client().governancePackets(DEMO));
    const subject = response.payload!.items.find(
      (entry) => entry.state === "READY_FOR_HUMAN_REVIEW",
    )!;
    subject.missing_evidence = [
      { code: "EVIDENCE_INCOMPLETE", vocabulary: "kalpamani.demo", vocabulary_version: "v1" },
    ];
    expect(() =>
      admit("GovernancePacket", governancePacketEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/missing nothing/);
  });

  /* NEGATIVE CONTROL: a ready packet with an unevaluated criterion. */
  it("refuses a packet marked ready for review with an unevaluated criterion", async () => {
    const response = clone(await client().governancePackets(DEMO));
    const subject = response.payload!.items.find(
      (entry) => entry.state === "READY_FOR_HUMAN_REVIEW",
    )!;
    subject.criteria_evaluation[0].outcome = {
      availability: "UNEVALUATED",
      reason: "NOT_YET_ASSESSED",
    };
    delete (subject.criteria_evaluation[0] as { verdict?: unknown }).verdict;
    expect(() =>
      admit("GovernancePacket", governancePacketEnvelope, response, "PUBLIC_EDGE"),
    ).toThrow(/evaluated every stated criterion/);
  });

  it("records no approved decision anywhere, and still delivers the whole vocabulary", async () => {
    const payload = (await client().decisions(DEMO)).payload!;
    expect(payload.decision_outcomes).toEqual([
      "APPROVED",
      "REJECTED",
      "MORE_EVIDENCE_REQUESTED",
    ]);
    expect(payload.items.map((entry) => entry.outcome)).not.toContain("APPROVED");
    for (const entry of payload.items) {
      expect(entry.immutable).toBe(true);
      expect(entry.authorized_action.code).toContain("NOTHING_WAS_AUTHORIZED");
      expect(entry.reasoning.length).toBeGreaterThan(0);
    }
  });

  it("attaches every recorded decision to a packet that exists", async () => {
    const read = client();
    const packets = (await read.governancePackets(DEMO)).payload!;
    const decisions = (await read.decisions(DEMO)).payload!;
    const known = new Set(packets.items.map((entry) => entry.packet_id));
    for (const decision of decisions.items) {
      expect(known.has(decision.packet_ref.ref_id), decision.decision_id).toBe(true);
      const packet = packets.items.find(
        (entry) => entry.packet_id === decision.packet_ref.ref_id,
      )!;
      expect(packet.decision_ref?.ref_id).toBe(decision.decision_id);
    }
  });
});

/* ============================================================== references and producers */

describe("C7 references declare their catalogued kinds and reach their own destinations", () => {
  it("records a producer for every C7 host field this cycle emits", () => {
    for (const key of [
      "StrategyHealth.queue_item_ref",
      "StrategyVersion.open_positions[].trade_ref",
      "ResearchRun.registration_ref",
      "ResearchQueueItem.trigger_ref",
      "HypothesisRegistration.exposure_ledger.entries[].registration_ref",
      "ChampionChallengerComparison.evidence_refs",
      "AiContribution.experiment_ref",
      "FeedbackPipeline.stages[].item_refs",
      "GovernancePacket.decision_ref",
      "DecisionRecord.affected_versions",
    ] as (keyof typeof REFERENCE_FIELDS)[]) {
      expect(producerStateFor(key), key).toBe("IMPLEMENTED");
    }
  });

  it("resolves every emitted reference through the closed target allowlist or none", async () => {
    const read = client();
    const payloads = [
      (await read.strategyHealth(DEMO)).payload,
      (await read.strategyVersions(DEMO)).payload,
      (await read.researchRuns(DEMO)).payload,
      (await read.researchQueue(DEMO)).payload,
      (await read.hypotheses(DEMO)).payload,
      (await read.championChallenger(DEMO)).payload,
      (await read.aiContribution(DEMO)).payload,
      (await read.feedbackPipeline(DEMO)).payload,
      (await read.governancePackets(DEMO)).payload,
      (await read.decisions(DEMO)).payload,
    ];
    const references: { ref_kind: string; ref_id: string }[] = [];
    const walk = (node: unknown): void => {
      if (Array.isArray(node)) {
        node.forEach(walk);
        return;
      }
      if (typeof node !== "object" || node === null) return;
      const record = node as Record<string, unknown>;
      if (
        typeof record.ref_id === "string" &&
        typeof record.ref_kind === "string" &&
        typeof record.resolution === "string"
      ) {
        references.push({ ref_kind: record.ref_kind, ref_id: record.ref_id });
      }
      Object.values(record).forEach(walk);
    };
    payloads.forEach(walk);
    expect(references.length).toBeGreaterThan(40);
    for (const reference of references) {
      const destination = referenceDestination(reference);
      if (destination === null) {
        /* `evidence` is the one kind the allowlist deliberately maps nowhere. */
        expect(["evidence"], reference.ref_kind).toContain(reference.ref_kind);
        continue;
      }
      expect(destination.href.startsWith("/"), reference.ref_id).toBe(true);
      expect(destination.href).not.toMatch(/^https?:|^\/\//);
    }
  });

  it("declares an owning area only where one is determined, and never AUDIT_TRAIL by default", async () => {
    const read = client();
    const health = (await read.strategyHealth(DEMO)).payload!;
    const areas = health.items
      .flatMap((entry) => entry.failure_clusters)
      .flatMap((cluster) => cluster.evidence_refs.items)
      .map((reference) => reference.owning_area);
    expect(areas.filter((area) => area === "SHORT_SIDE").length).toBeGreaterThan(0);
    expect(areas.filter((area) => area === "DATA_QUALITY").length).toBeGreaterThan(0);
    expect(areas).not.toContain("AUDIT_TRAIL");
    const undeclared = health.items
      .flatMap((entry) => entry.failure_clusters)
      .flatMap((cluster) => cluster.evidence_refs.items)
      .filter((reference) => reference.owning_area === undefined);
    for (const reference of undeclared) {
      expect(owningAreaDestination(reference)).toBeNull();
    }
  });
});
