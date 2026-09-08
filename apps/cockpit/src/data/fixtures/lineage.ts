/**
 * THE SYNTHETIC RESEARCH LINEAGE.
 *
 * One deterministic, repository-owned record of a health degradation, the research queue
 * entry it created, the preregistrations that followed, the immutable Challengers, the runs
 * against them, the exposure those runs spent, the comparisons they support and the
 * governance packets assembled from them — from which **every** C7 number is projected.
 * Health, queue, hypotheses, runs, Champion/Challenger, packets and decisions are all read
 * from THIS, so they agree with each other by construction rather than by coincidence.
 *
 * `cockpit-v1-specification.md` §5 asks for exactly that: "internally consistent — the trades,
 * positions, candidates and metrics agree with each other; **a demonstration whose numbers
 * contradict each other teaches the wrong thing**."
 *
 * WHAT IT IS NOT.
 *
 *   NOT RESEARCH          **backtesting is NOT STARTED.** No research engine, learning engine,
 *                         shadow runner or AI agent exists, none has ever run, and no figure
 *                         here is the outcome of an experiment. It is a fixed table
 *   NOT EVIDENCE          **no synthetic figure closes a gate, qualifies a provider, validates
 *                         a strategy or establishes a threshold**, and **no numerical value
 *                         appearing here becomes a production rule** (§5, feedback §3.3)
 *   NOT AN AUTHORIZATION  a recorded decision below authorizes nothing in this repository. It
 *                         is a displayed fact about a fictional packet, and no mechanism
 *                         exists that could act on one
 *
 * IT REUSES THE DEMONSTRATION BOOK RATHER THAN INVENTING A SECOND ONE. The strategy versions,
 * the securities and the open positions are the book's own, so a version's health here and
 * its results on the strategy-performance screen are the same version. **No book economics,
 * ledger figure, risk denominator or trade is changed by this module** — it reads the book and
 * writes nothing back to it.
 */
import { BOOK, STRATEGY_VERSIONS, type BookTrade } from "./book";

/* --------------------------------------------------------------------- identities */

/**
 * The two locked sets, and the overlap between them.
 *
 * A locked set's identity is "derived from its manifest, its information-set profile, its
 * revision view and its evaluation boundary" (§2.7.1), and **two sets with the same identity
 * are the same set, whatever they are called**. `SET_B` is a **re-cut** of `SET_A` with one
 * extra year — a different identity over four-fifths of the same data, which is precisely the
 * case identity alone does not catch.
 */
export const LOCKED_SET_A = "demo-locked-set-2019-2023";
export const LOCKED_SET_B = "demo-locked-set-2019-2024";
/** The MEASURED overlap of `SET_B` with `SET_A`, in hundredths. Measured, never assumed. */
export const SET_B_OVERLAP_HUNDREDTHS = 80;
/** A third set whose extent cannot be compared with either. Incomparable is not disjoint. */
export const LOCKED_SET_C = "demo-locked-set-rolling-recut";

export const QUEUE_ITEMS = {
  pullback: "demo-queue-0001",
  borrow: "demo-queue-0002",
  missed: "demo-queue-0003",
  duplicate: "demo-queue-0004",
  aiExperiment: "demo-queue-0005",
} as const;

export const REGISTRATIONS = {
  /** The original preregistration. Confirmatory, and legitimately so at the time. */
  original: "demo-reg-0001",
  /** A linked AMENDMENT of the original. A design change never edits a preregistration. */
  amendment: "demo-reg-0002",
  /** THE RENAMED REUSE. A new identity over a set the ledger already records as exposed. */
  renamedReuse: "demo-reg-0003",
  /** A confirmatory declaration whose ledger cannot be shown complete. */
  unknownHistory: "demo-reg-0004",
  /** Experiment E of ADR-0026 §23, preregistered and **NOT RUN**. */
  aiExperiment: "demo-reg-0005",
} as const;

export const RUNS = {
  confirmatory: "demo-run-0001",
  failed: "demo-run-0002",
  reuse: "demo-run-0003",
  abandonedLineage: "demo-run-0004",
  abandonedReuse: "demo-run-0005",
  reproduction: "demo-run-0006",
} as const;

export const CHALLENGERS = {
  pullback: "pullback-long-v3-challenger",
  peadShort: "pead-short-v2-challenger",
} as const;

/** The Champions the two Challengers are compared against. Both are the book's own versions. */
export const CHAMPIONS = {
  pullback: "pullback-long-v2",
  peadShort: "pead-short-v1",
} as const;

export const PACKETS = {
  reviewed: "demo-packet-0000",
  ready: "demo-packet-0001",
  assembling: "demo-packet-0002",
  rejected: "demo-packet-0003",
} as const;

export const DECISIONS = {
  moreEvidence: "demo-decision-0001",
  rejected: "demo-decision-0002",
} as const;

/* ------------------------------------------------------------------ the trial budget */

/**
 * The budget of the pullback lineage, **read across it**.
 *
 * `granted` is what the lineage was given; `consumed` counts every terminal run in the
 * lineage, **failed and abandoned included**; `remaining` is the difference. **A new
 * registration identity resets none of the three** — that is the whole of §2.7.1, and the
 * per-registration `own` counts below exist so a reader can see the difference between what
 * one identity spent and what its lineage has.
 */
export const LINEAGE_BUDGET = { granted: 8, consumed: 5, remaining: 3 } as const;

/** What each identity of the pullback lineage spent from that shared budget. */
export const OWN_TRIALS: Readonly<Record<string, number>> = {
  [REGISTRATIONS.original]: 2,
  [REGISTRATIONS.amendment]: 2,
  [REGISTRATIONS.renamedReuse]: 1,
  [REGISTRATIONS.unknownHistory]: 0,
};

/** Experiment E is a SEPARATE lineage, with its own budget and nothing spent from it. */
export const AI_BUDGET = { granted: 6, consumed: 0, remaining: 6 } as const;

/* ------------------------------------------------------------------ session anchors */

/**
 * The retained extent's session indices the lineage is anchored to.
 *
 * Every instant below is derived from the demonstration book's own session dates, so the
 * lineage moves with the book rather than carrying a second, independent calendar.
 */
export const LINEAGE_SESSIONS = {
  healthWatch: 462,
  healthDegraded: 448,
  healthReduced: 470,
  retirement: 300,
  queued: 464,
  registered: 466,
  amended: 476,
  runOne: 468,
  runTwo: 470,
  runThree: 478,
  runFour: 482,
  runFive: 488,
  runSix: 490,
  packetReviewed: 440,
  packetRejected: 452,
  packetReady: 492,
  packetAssembling: 494,
  decisionOne: 444,
  decisionTwo: 456,
} as const;

/* ---------------------------------------------------------------- book-derived rows */

/** The book's open and partially exited trades, grouped by the version that opened them. */
export function openTradesByVersion(): ReadonlyMap<string, readonly BookTrade[]> {
  const grouped = new Map<string, BookTrade[]>();
  for (const version of STRATEGY_VERSIONS) {
    grouped.set(version.versionId, []);
  }
  for (const trade of BOOK.openTrades) {
    const bucket = grouped.get(trade.versionId);
    if (bucket !== undefined) {
      bucket.push(trade);
    }
  }
  return grouped;
}

/**
 * The two Challenger versions, declared HERE and not in the book.
 *
 * **A Challenger produces no order in any environment**, so it has no trades, no positions and
 * no realized economics — and adding one to the book's `STRATEGY_VERSIONS` would have given it
 * a row on the strategy-performance screen with an empty population, which reads as a strategy
 * that traded nothing rather than as one that cannot trade at all.
 */
export interface ChallengerVersion {
  readonly versionId: string;
  readonly module: string;
  readonly family: string;
  /** The Champion it was derived from, and is compared against. */
  readonly championId: string;
  readonly registrationId: string;
  readonly createdSession: number;
}

export const CHALLENGER_VERSIONS: readonly ChallengerVersion[] = [
  {
    versionId: CHALLENGERS.pullback,
    module: "PULLBACK_LONG",
    family: "TREND_CONTINUATION",
    championId: CHAMPIONS.pullback,
    registrationId: REGISTRATIONS.original,
    createdSession: LINEAGE_SESSIONS.registered,
  },
  {
    versionId: CHALLENGERS.peadShort,
    module: "PEAD_SHORT",
    family: "EVENT_DRIFT",
    championId: CHAMPIONS.peadShort,
    registrationId: REGISTRATIONS.unknownHistory,
    createdSession: LINEAGE_SESSIONS.runFive,
  },
];
