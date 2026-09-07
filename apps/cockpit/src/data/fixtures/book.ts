/**
 * THE SYNTHETIC DEMONSTRATION BOOK.
 *
 * One deterministic, repository-owned book of fictional securities, strategy versions,
 * trades, positions and daily marks, from which **every** C5 number is projected. Positions,
 * exposure, the trade ledger, per-strategy results, the risk snapshot, the short-side
 * snapshot and the equity curve are all read from THIS, so they agree with each other by
 * construction rather than by coincidence.
 *
 * `cockpit-v1-specification.md` §5 asks for exactly that: "internally consistent — the
 * trades, positions, candidates and metrics agree with each other; **a demonstration whose
 * numbers contradict each other teaches the wrong thing**."
 *
 * WHAT IT IS NOT.
 *
 *   NOT A RESULT           no strategy exists, none has ever run, and no figure here is an
 *                          outcome of anything. It is arithmetic over a fixed table
 *   NOT A SIMULATION       there is no model, no alpha, no market and no assumption about
 *                          how a real security behaves. A fixed seed walks a fixed step
 *                          function between endpoints that were chosen by hand
 *   NOT REAL               every security is obviously fictional, and **the owner's real
 *                          manual trades and holdings are never used as demonstration
 *                          inputs** (§5). No provider row, no broker record, no account, no
 *                          private identifier and no real ticker appears anywhere in it
 *
 * EVERY VALUE IS AN INTEGER NUMBER OF CENTS. §4.2 requires "decimal string, never binary
 * floating point", and a book accumulates: a rounding error in one trade is carried by every
 * total that trade contributes to. Arithmetic happens in integers and rounding happens once,
 * at the point a decimal string is produced.
 *
 * THE GOVERNED RESEARCH VALUES ARE OBEYED, NOT CHANGED. Position sizes are chosen so each
 * trade's initial planned risk sits at or under the `CLAUDE.md` §6 research parameters —
 * 0.50% of capital long, 0.25% short — and so no position exceeds roughly 8–10% of capital
 * and gross short stays well inside 25%. **Those values are reproduced for display context
 * and are changed nowhere**, and a fixture obeying them is not a claim that anything enforced
 * them.
 */

/** The authoritative strategy capital of `CLAUDE.md` §6, in cents. Never broker equity. */
export const STRATEGY_CAPITAL_CENTS = 80_000_00;

/** The retained extent, in sessions. Matches `PERIOD_TRADING_DAYS.ALL`. */
export const SESSION_COUNT = 504;

/** The session the one external cash flow lands on, counted from the oldest retained one. */
const DEPOSIT_SESSION = 470;
const DEPOSIT_CENTS = 5_000_00;

/* ------------------------------------------------------------------- securities */

export interface BookSecurity {
  readonly symbol: string;
  readonly displayName: string;
  readonly sector: string;
  readonly industry: string;
  readonly factorBucket: string;
  readonly correlationCluster: string;
  /** The entry-to-invalidation distance a generated trade is sized against, in cents. */
  readonly stopDistanceCents: number;
  readonly basePriceCents: number;
  /** Whether an earnings-style binary event sits inside the demonstration window. */
  readonly eventInWindow: boolean;
}

/**
 * Eight fictional demonstration subjects.
 *
 * The `DEMO.` prefix is part of the symbol rather than a badge beside it, so a screenshot of
 * a single cell still shows that the subject is invented. None of these is a real security,
 * a real issuer or a real ticker.
 */
export const SECURITIES: readonly BookSecurity[] = [
  {
    symbol: "DEMO.ARB",
    displayName: "Arbor Materials",
    sector: "MATERIALS",
    industry: "CONSTRUCTION_MATERIALS",
    factorBucket: "HIGH_MOMENTUM",
    correlationCluster: "CYCLICAL_INDUSTRIAL",
    stopDistanceCents: 275,
    basePriceCents: 41_85,
    eventInWindow: false,
  },
  {
    symbol: "DEMO.NVL",
    displayName: "Novelle Health",
    sector: "HEALTH_CARE",
    industry: "BIOTECHNOLOGY",
    factorBucket: "HIGH_VOLATILITY",
    correlationCluster: "HEALTHCARE_INNOVATION",
    stopDistanceCents: 310,
    basePriceCents: 62_40,
    eventInWindow: true,
  },
  {
    symbol: "DEMO.CIR",
    displayName: "Cirrus Logistics",
    sector: "INDUSTRIALS",
    industry: "AIR_FREIGHT_AND_LOGISTICS",
    factorBucket: "MID_MOMENTUM",
    correlationCluster: "CYCLICAL_INDUSTRIAL",
    stopDistanceCents: 410,
    basePriceCents: 88_20,
    eventInWindow: true,
  },
  {
    symbol: "DEMO.HLX",
    displayName: "Helix Semiconductor",
    sector: "INFORMATION_TECHNOLOGY",
    industry: "SEMICONDUCTORS",
    factorBucket: "HIGH_VOLATILITY",
    correlationCluster: "SEMICONDUCTOR_COMPLEX",
    stopDistanceCents: 620,
    basePriceCents: 118_40,
    eventInWindow: false,
  },
  {
    symbol: "DEMO.PLM",
    displayName: "Palomar Retail",
    sector: "CONSUMER_DISCRETIONARY",
    industry: "SPECIALTY_RETAIL",
    factorBucket: "LOW_MOMENTUM",
    correlationCluster: "CONSUMER_CYCLICAL",
    stopDistanceCents: 280,
    basePriceCents: 44_30,
    eventInWindow: true,
  },
  {
    symbol: "DEMO.KTN",
    displayName: "Keystone Energy",
    sector: "ENERGY",
    industry: "OIL_AND_GAS_EXPLORATION",
    factorBucket: "HIGH_MOMENTUM",
    correlationCluster: "ENERGY_COMPLEX",
    stopDistanceCents: 340,
    basePriceCents: 71_50,
    eventInWindow: false,
  },
  {
    symbol: "DEMO.MRD",
    displayName: "Meridian Financial",
    sector: "FINANCIALS",
    industry: "REGIONAL_BANKS",
    factorBucket: "VALUE",
    correlationCluster: "FINANCIAL_RATE_SENSITIVE",
    stopDistanceCents: 190,
    basePriceCents: 39_60,
    eventInWindow: false,
  },
  {
    symbol: "DEMO.SOL",
    displayName: "Solstice Utilities",
    sector: "UTILITIES",
    industry: "ELECTRIC_UTILITIES",
    factorBucket: "LOW_VOLATILITY",
    correlationCluster: "DEFENSIVE_INCOME",
    stopDistanceCents: 160,
    basePriceCents: 54_80,
    eventInWindow: false,
  },
];

const SECURITY_BY_SYMBOL = new Map(SECURITIES.map((entry) => [entry.symbol, entry]));

export function securityOf(symbol: string): BookSecurity {
  const found = SECURITY_BY_SYMBOL.get(symbol);
  if (found === undefined) {
    throw new RangeError(`unknown demonstration security ${symbol}`);
  }
  return found;
}

/* ------------------------------------------------------------------- strategies */

export interface BookStrategyVersion {
  /** The exact version every result produced by it is attributed to. */
  readonly versionId: string;
  readonly module: string;
  readonly family: string;
  readonly template: string;
  readonly direction: "LONG" | "SHORT";
  readonly entryReason: string;
  readonly healthState: string;
  readonly healthReason: string;
  /** The lifecycle stage of the version itself, so a retired one reads as retired. */
  readonly lifecycle: "PRODUCTION" | "SUPERSEDED";
}

/**
 * Six exact versions across five modules.
 *
 * **Breakout Long appears twice**, at two versions, because that is the case the contract
 * cares about: results are attributed to the exact version that produced them, and a
 * superseded version's record is not folded into its successor's. Breakout and Pullback keep
 * separate module attribution and share a family context — **whether they are economically
 * distinct is open gate G7, and nothing here decides it.**
 */
export const STRATEGY_VERSIONS: readonly BookStrategyVersion[] = [
  {
    versionId: "breakout-long-v3",
    module: "BREAKOUT_LONG",
    family: "TREND_CONTINUATION",
    template: "RANGE_EXPANSION",
    direction: "LONG",
    entryReason: "RANGE_EXPANSION_CONFIRMED",
    healthState: "HEALTHY",
    healthReason: "WITHIN_RESEARCHED_BEHAVIOUR",
    lifecycle: "PRODUCTION",
  },
  {
    versionId: "breakout-long-v2",
    module: "BREAKOUT_LONG",
    family: "TREND_CONTINUATION",
    template: "RANGE_EXPANSION",
    direction: "LONG",
    entryReason: "RANGE_EXPANSION_CONFIRMED",
    healthState: "RETIRED",
    healthReason: "SUPERSEDED_BY_A_LATER_VERSION",
    lifecycle: "SUPERSEDED",
  },
  {
    versionId: "pullback-long-v2",
    module: "PULLBACK_LONG",
    family: "TREND_CONTINUATION",
    template: "TREND_PULLBACK",
    direction: "LONG",
    entryReason: "PULLBACK_INTO_TREND_SUPPORT",
    healthState: "WATCH",
    healthReason: "ROLLING_EXPECTANCY_BELOW_RESEARCHED_BAND",
    lifecycle: "PRODUCTION",
  },
  {
    versionId: "pead-long-v1",
    module: "PEAD_LONG",
    family: "EVENT_DRIFT",
    template: "POST_EARNINGS_DRIFT",
    direction: "LONG",
    entryReason: "POSITIVE_SURPRISE_DRIFT_WINDOW",
    healthState: "HEALTHY",
    healthReason: "WITHIN_RESEARCHED_BEHAVIOUR",
    lifecycle: "PRODUCTION",
  },
  {
    versionId: "pead-short-v1",
    module: "PEAD_SHORT",
    family: "EVENT_DRIFT",
    template: "POST_EARNINGS_FADE",
    direction: "SHORT",
    entryReason: "NEGATIVE_SURPRISE_DRIFT_WINDOW",
    healthState: "NEW_ENTRIES_REDUCED",
    healthReason: "BORROW_AVAILABILITY_INCIDENTS_RECORDED",
    lifecycle: "PRODUCTION",
  },
  {
    versionId: "deterioration-short-v1",
    module: "DETERIORATION_SHORT",
    family: "DETERIORATION",
    template: "FUNDAMENTAL_DETERIORATION",
    direction: "SHORT",
    entryReason: "FUNDAMENTAL_DETERIORATION_CONFIRMED",
    healthState: "HEALTHY",
    healthReason: "WITHIN_RESEARCHED_BEHAVIOUR",
    lifecycle: "PRODUCTION",
  },
];

const VERSION_BY_ID = new Map(STRATEGY_VERSIONS.map((entry) => [entry.versionId, entry]));

export function strategyVersionOf(versionId: string): BookStrategyVersion {
  const found = VERSION_BY_ID.get(versionId);
  if (found === undefined) {
    throw new RangeError(`unknown demonstration strategy version ${versionId}`);
  }
  return found;
}

/* ----------------------------------------------------------------- trade shapes */

/** One entry or add. **Each carries its own initial planned risk record** (§12.4). */
export interface BookStage {
  readonly session: number;
  readonly shares: number;
  readonly priceCents: number;
  /** The invalidation level this stage was sized against. IMMUTABLE once recorded. */
  readonly invalidationCents: number;
  readonly kind: "ENTRY" | "ADD";
}

/** One exit. A partial exit **reduces** a trade; it does not close it. */
export interface BookExit {
  readonly session: number;
  readonly shares: number;
  readonly priceCents: number;
  readonly reason: string;
  /** The realized result of THIS exit, against the average basis at the time. */
  readonly realizedCents: number;
}

export interface BookTrade {
  readonly tradeId: string;
  readonly symbol: string;
  readonly versionId: string;
  readonly direction: "LONG" | "SHORT";
  readonly stages: readonly BookStage[];
  readonly exits: readonly BookExit[];
  readonly status: "OPEN" | "CLOSED" | "PARTIALLY_EXITED";
  /**
   * The whole quantity this trade ever filled — the entry stage PLUS every add.
   *
   * It is deliberately NOT called "shares at entry": the quantity filled at entry is
   * `stages[0].shares`, and a later add never restates it. Read-model contracts 4.5 keeps
   * the two apart, so this book keeps them apart too.
   */
  readonly sharesAcquired: number;
  readonly sharesOpen: number;
  /** The position-weighted per-share basis of the OPEN portion. Exact, never rounded. */
  readonly basisCents: number;
  readonly realizedCents: number;
  readonly unrealizedCents: number;
  /** The last session this trade was observed on — its exit, or the snapshot session. */
  readonly lastSession: number;
  /** The mark at the snapshot session, for an open or partially exited trade. */
  readonly markCents: number | null;
  /** The retained sum of every stage's initial planned risk. A moving stop never moves it. */
  readonly initialRiskCents: number;
  /** Whether the entry-time risk record was ever written. */
  readonly initialRiskRecorded: boolean;
  /** The CURRENT protective level. Moving it changes open planned risk and nothing else. */
  readonly currentStopCents: number | null;
  readonly openPlannedRiskCents: number | null;
  readonly mfeCents: number;
  readonly maeCents: number;
  readonly dataCompleteness: "COMPLETE" | "PARTIAL";
  readonly stopOutcome: string;
  readonly exitReason: string | null;
  /** Session-indexed marks from the first stage to `lastSession`, in cents. */
  readonly path: readonly number[];
  readonly holdingSessions: number;
}

/* ------------------------------------------------------------ deterministic seed */

/**
 * A named linear congruential generator, and not `Math.random`.
 *
 * A fixture that differs between runs cannot be reviewed, screenshotted or asserted on. The
 * constants are the well-known Numerical Recipes ones; nothing about the choice is meaningful
 * beyond "the same input gives the same book".
 */
export function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (Math.imul(state, 1_664_525) + 1_013_904_223) >>> 0;
    return state;
  };
}

/**
 * The R outcomes a generated trade may take, in hundredths of R.
 *
 * A ladder rather than a distribution: it is chosen so the population contains full stop-outs,
 * partial losses, an **exact break-even**, small winners and a few large ones. **It is not a
 * model of anything**, and the expectancy that falls out of it is an arithmetic consequence
 * of this list rather than evidence about any strategy.
 */
const R_LADDER = [
  -100, -100, -100, -100, -100, -100, -100, -100, -100, -100, -100, -95, -95, -80, -80, -60,
  -35, 0, 40, 55, 60, 75, 95, 110, 125, 130, 140, 150, 160, 180, 200, 220,
] as const;

/** How a completed trade's R reads as an exit reason. Derived once, from the outcome. */
function exitReasonFor(rHundredths: number): string {
  if (rHundredths <= -95) return "PROTECTIVE_STOP_HIT";
  if (rHundredths < 0) return "THESIS_INVALIDATED";
  if (rHundredths === 0) return "TIME_STOP_REACHED";
  if (rHundredths < 150) return "TRAILING_STOP_HIT";
  return "PLANNED_TARGET_REACHED";
}

/**
 * The recorded stop outcome, on the SAME thresholds the exit reason uses.
 *
 * The two describe one event and must agree. An earlier revision returned
 * `STOP_TRAILED_THEN_TRIGGERED` for every non-losing outcome, so a trade whose exit reason was
 * `PLANNED_TARGET_REACHED` reported that its trailed stop had triggered, and the exact
 * break-even — exit reason `TIME_STOP_REACHED` — reported the same. A demonstration whose two
 * fields contradict each other "teaches the wrong thing" (`cockpit-v1-specification.md` §5),
 * so the boundaries here are the boundaries of `exitReasonFor` and nothing else.
 *
 *   <= -95   PROTECTIVE_STOP_HIT      -> the stop triggered as planned
 *   <   0    THESIS_INVALIDATED       -> exited before the stop was reached
 *   ==  0    TIME_STOP_REACHED        -> exited before the stop was reached
 *   <  150   TRAILING_STOP_HIT        -> the stop was trailed and then triggered
 *   >= 150   PLANNED_TARGET_REACHED   -> exited before the stop was reached
 */
function stopOutcomeFor(rHundredths: number | null): string {
  if (rHundredths === null) return "PROTECTIVE_ORDER_STILL_WORKING";
  if (rHundredths <= -95) return "STOP_TRIGGERED_AS_PLANNED";
  if (rHundredths <= 0) return "EXITED_BEFORE_STOP";
  if (rHundredths < 150) return "STOP_TRAILED_THEN_TRIGGERED";
  return "EXITED_BEFORE_STOP";
}

/* ----------------------------------------------------------------- path building */

/**
 * A daily mark path with EXACT endpoints.
 *
 * The path exists so MFE, MAE, the capture ratio and the equity curve are **read from one
 * set of marks** rather than invented three times. Its first point is the entry price and its
 * last is the exit price or the snapshot mark, so no path can disagree with the trade record
 * it belongs to. Between them it wiggles by a bounded fraction of the security's own stop
 * distance, which is deterministic and means nothing.
 */
export function buildPath(
  fromCents: number,
  toCents: number,
  sessions: number,
  amplitudeCents: number,
  seed: number,
): number[] {
  if (sessions <= 0) {
    return [fromCents];
  }
  const next = lcg(seed);
  const path: number[] = [];
  for (let step = 0; step <= sessions; step += 1) {
    const linear = fromCents + Math.round(((toCents - fromCents) * step) / sessions);
    if (step === 0 || step === sessions) {
      path.push(step === 0 ? fromCents : toCents);
      continue;
    }
    const jitter = Math.round((amplitudeCents * ((next() % 121) - 60)) / 100);
    path.push(Math.max(1, linear + jitter));
  }
  return path;
}

/**
 * The favourable and adverse excursions of a path, in USD cents.
 *
 * **Each session is valued with what the trade actually held on that session**, at the basis
 * it actually carried then. A pyramided trade held its original quantity at its original
 * price until the add filled, so valuing the whole path at the final combined quantity and
 * the final combined basis would report an excursion the position could not have had:
 * §12.4's "the trade's original record is retained unchanged" is a statement about the past,
 * and a later add does not reach back into it.
 *
 * `stages` and `exits` are read per session rather than summed once, so a partial exit
 * reduces the quantity that the remaining path is measured on.
 */
function excursions(
  stages: readonly BookStage[],
  exits: readonly BookExit[],
  path: readonly number[],
  firstSession: number,
  direction: "LONG" | "SHORT",
): { mfeCents: number; maeCents: number } {
  const sign = direction === "LONG" ? 1 : -1;
  let best = 0;
  let worst = 0;
  for (let step = 0; step < path.length; step += 1) {
    const session = firstSession + step;
    const acquired = stages.filter((stage) => stage.session <= session);
    const filled = acquired.reduce((total, stage) => total + stage.shares, 0);
    if (filled === 0) {
      continue;
    }
    const released = exits
      .filter((exit) => exit.session <= session)
      .reduce((total, exit) => total + exit.shares, 0);
    const held = filled - released;
    if (held <= 0) {
      continue;
    }
    const basis =
      acquired.reduce((total, stage) => total + stage.shares * stage.priceCents, 0) / filled;
    const move = (path[step] - basis) * sign * held;
    best = Math.max(best, move);
    worst = Math.min(worst, move);
  }
  return { mfeCents: Math.round(best), maeCents: Math.round(worst) };
}

/* ------------------------------------------------------------- the featured book */

interface FeaturedSpec {
  readonly tradeId: string;
  readonly symbol: string;
  readonly versionId: string;
  readonly stages: readonly Omit<BookStage, "kind">[];
  readonly exits: readonly { session: number; shares: number; priceCents: number; reason: string }[];
  /**
   * The snapshot mark, for a trade that still holds something.
   *
   * `null` on a CLOSED trade, because a closed trade holds nothing to mark. An earlier
   * revision had no closed featured trade and so had no `null` case at all; C6 needs one, and
   * a closed trade carrying a current mark would be a position the ledger says does not exist.
   */
  readonly markCents: number | null;
  /** The CURRENT protective level. `null` once the trade is closed and none is working. */
  readonly currentStopCents: number | null;
}

/**
 * The five open and partially exited trades the position screens are about.
 *
 * Their numbers are chosen by hand rather than generated, because these are the rows a
 * reviewer will read closely: each one demonstrates a distinct contract case, and the case is
 * clearer when the arithmetic is legible.
 *
 *   DEMO.ARB   an ordinary open long, with a **trailed stop** — so initial planned risk and
 *              current open planned risk differ, and only the second one moved
 *   DEMO.NVL   an open long with a **pyramid add**, each stage carrying its own retained
 *              initial risk record, and a **losing** open position
 *   DEMO.CIR   a **PARTIALLY_EXITED** long: realized on the closed portion, unrealized on the
 *              remaining one, and one trade rather than two
 *   DEMO.HLX   a **profitable short**, so a profitable short reads positive
 *   DEMO.PLM   a **losing short** whose **borrow record is unknown**, and whose risk
 *              assessment is **STALE**
 */
const FEATURED: readonly FeaturedSpec[] = [
  {
    tradeId: "demo-trade-arb-0001",
    symbol: "DEMO.ARB",
    versionId: "breakout-long-v3",
    stages: [{ session: SESSION_COUNT - 39, shares: 145, priceCents: 41_85, invalidationCents: 39_10 }],
    exits: [],
    markCents: 45_20,
    currentStopCents: 43_60,
  },
  {
    tradeId: "demo-trade-nvl-0002",
    symbol: "DEMO.NVL",
    versionId: "pullback-long-v2",
    stages: [
      { session: SESSION_COUNT - 53, shares: 60, priceCents: 62_40, invalidationCents: 59_30 },
      { session: SESSION_COUNT - 23, shares: 40, priceCents: 66_10, invalidationCents: 60_80 },
    ],
    exits: [],
    markCents: 61_95,
    currentStopCents: 60_80,
  },
  {
    tradeId: "demo-trade-cir-0003",
    symbol: "DEMO.CIR",
    versionId: "pead-long-v1",
    stages: [{ session: SESSION_COUNT - 47, shares: 96, priceCents: 88_20, invalidationCents: 84_10 }],
    exits: [
      {
        session: SESSION_COUNT - 10,
        shares: 40,
        priceCents: 95_40,
        reason: "PARTIAL_TARGET_REACHED",
      },
    ],
    markCents: 93_75,
    currentStopCents: 90_10,
  },
  {
    tradeId: "demo-trade-hlx-0004",
    symbol: "DEMO.HLX",
    versionId: "deterioration-short-v1",
    stages: [{ session: SESSION_COUNT - 28, shares: 32, priceCents: 118_40, invalidationCents: 124_60 }],
    exits: [],
    markCents: 112_10,
    currentStopCents: 116_20,
  },
  {
    tradeId: "demo-trade-plm-0005",
    symbol: "DEMO.PLM",
    versionId: "pead-short-v1",
    stages: [{ session: SESSION_COUNT - 14, shares: 71, priceCents: 44_30, invalidationCents: 47_10 }],
    exits: [],
    markCents: 46_05,
    currentStopCents: 47_10,
  },
];

/**
 * The C6 addition: a CLOSED long that was reduced twice before it closed.
 *
 * Every other featured trade is open or partially exited, and every generated one has exactly
 * one entry and one exit. Neither shape can demonstrate the case Area 36.4 is most explicit
 * about -- **several partial exits, and then a final close** -- so one trade is added for it,
 * by hand, with legible arithmetic.
 *
 * `GENERATED_TRADES` drops by one in exchange, so the ledger population stays at exactly its
 * declared page size and the trade history's `truncated` flag keeps the value C5 established.
 * The generated ordinals are unchanged; the highest one simply no longer exists.
 */
const MULTI_EXIT_TRADE_SPEC: FeaturedSpec = {
  tradeId: "demo-trade-sol-0006",
  symbol: "DEMO.SOL",
  versionId: "breakout-long-v3",
  stages: [
    { session: SESSION_COUNT - 96, shares: 115, priceCents: 54_80, invalidationCents: 53_20 },
  ],
  exits: [
    { session: SESSION_COUNT - 78, shares: 40, priceCents: 57_35, reason: "PARTIAL_TARGET_REACHED" },
    { session: SESSION_COUNT - 61, shares: 30, priceCents: 59_10, reason: "PARTIAL_TARGET_REACHED" },
    { session: SESSION_COUNT - 44, shares: 45, priceCents: 55_00, reason: "TRAILING_STOP_HIT" },
  ],
  markCents: null,
  currentStopCents: null,
};

/** The one closed trade that was reduced twice and then closed by its remaining balance. */
export const MULTI_EXIT_TRADE = MULTI_EXIT_TRADE_SPEC.tradeId;

/** The one open position whose risk assessment is deliberately STALE. */
export const STALE_ASSESSMENT_TRADE = "demo-trade-plm-0005";
/** The one open position the gap and event model applies to. */
export const GAP_EVENT_TRADE = "demo-trade-nvl-0002";
/** The one closed trade whose entry-time risk record was never written. */
export const MISSING_RISK_RECORD_TRADE = "demo-trade-gen-0001";
/** The one closed trade whose price path is incomplete. */
export const PARTIAL_PATH_TRADE = "demo-trade-gen-0002";

function buildFeatured(spec: FeaturedSpec): BookTrade {
  const security = securityOf(spec.symbol);
  const version = strategyVersionOf(spec.versionId);
  const stages: BookStage[] = spec.stages.map((stage, index) => ({
    ...stage,
    kind: index === 0 ? "ENTRY" : "ADD",
  }));
  const sharesAcquired = stages.reduce((total, stage) => total + stage.shares, 0);
  const costCents = stages.reduce((total, stage) => total + stage.shares * stage.priceCents, 0);
  if (costCents % sharesAcquired !== 0) {
    /*
     * A weighted basis that does not divide exactly would force a rounded per-share figure,
     * and every P/L derived from it would disagree with the cost it came from by a cent.
     * The fixture is chosen so it divides; this refuses rather than rounding.
     */
    throw new RangeError(`${spec.tradeId} has a weighted basis that is not an exact cent`);
  }
  const basisCents = costCents / sharesAcquired;
  const sign = version.direction === "LONG" ? 1 : -1;

  const exits: BookExit[] = spec.exits.map((exit) => ({
    ...exit,
    realizedCents: exit.shares * (exit.priceCents - basisCents) * sign,
  }));
  const exited = exits.reduce((total, exit) => total + exit.shares, 0);
  const sharesOpen = sharesAcquired - exited;
  const realizedCents = exits.reduce((total, exit) => total + exit.realizedCents, 0);
  const closed = sharesOpen === 0;
  if (closed !== (spec.markCents === null)) {
    /*
     * A closed trade holds nothing to mark, and an open one must be markable. Refusing the
     * combination here is what keeps `markCents` from becoming a price for a position the
     * ledger says does not exist.
     */
    throw new RangeError(`${spec.tradeId} must carry a mark exactly while it holds something`);
  }
  const unrealizedCents =
    spec.markCents === null ? 0 : sharesOpen * (spec.markCents - basisCents) * sign;

  const initialRiskCents = stages.reduce(
    (total, stage) => total + stage.shares * Math.abs(stage.priceCents - stage.invalidationCents),
    0,
  );
  /*
   * A CLOSED TRADE HAS NO REMAINING EXPOSURE FOR THE QUESTION TO BE ABOUT (4.4).
   *
   * Its `CurrentOpenPlannedRisk` record is ABSENT with `NOT_APPLICABLE`, and its retained
   * `InitialPlannedRisk` is unchanged. A zero here would be an assessment of nothing.
   */
  const openPlannedRiskCents =
    spec.markCents === null || spec.currentStopCents === null
      ? null
      : sharesOpen * Math.abs(spec.currentStopCents - spec.markCents);

  const firstSession = stages[0].session;
  /** A closed trade's path ends at its FINAL exit; an open one's ends at the snapshot. */
  const lastSession = closed ? exits[exits.length - 1].session : SESSION_COUNT - 1;
  const finalPriceCents = closed ? exits[exits.length - 1].priceCents : (spec.markCents as number);
  const path = buildPath(
    stages[0].priceCents,
    finalPriceCents,
    lastSession - firstSession,
    security.stopDistanceCents,
    firstSession * 7919 + spec.symbol.length,
  );
  /** The outcome in hundredths of R, so the exit reason and the stop outcome agree (12.4). */
  const rHundredths = closed
    ? Math.round((realizedCents * 100) / initialRiskCents)
    : null;
  const { mfeCents, maeCents } = excursions(
    stages,
    exits,
    path,
    firstSession,
    version.direction,
  );
  /*
   * THE EXIT REASON AND THE STOP OUTCOME DESCRIBE ONE EVENT AND MUST AGREE.
   *
   * `stopOutcomeFor` is derived from the outcome; a hand-written final exit reason is not, so
   * the two can drift into a trade whose reason says a trailing stop triggered while its stop
   * outcome says it exited before the stop was reached. That contradiction is exactly what
   * `cockpit-v1-specification.md` 5 calls a demonstration teaching the wrong thing, so this
   * refuses it rather than rendering it.
   */
  if (rHundredths !== null && exits[exits.length - 1].reason !== exitReasonFor(rHundredths)) {
    throw new RangeError(
      `${spec.tradeId} states a final exit reason its outcome does not produce`,
    );
  }

  return {
    tradeId: spec.tradeId,
    symbol: spec.symbol,
    versionId: spec.versionId,
    direction: version.direction,
    stages,
    exits,
    status: closed ? "CLOSED" : exited > 0 ? "PARTIALLY_EXITED" : "OPEN",
    sharesAcquired,
    sharesOpen,
    basisCents,
    realizedCents,
    unrealizedCents,
    lastSession,
    markCents: spec.markCents,
    initialRiskCents,
    initialRiskRecorded: true,
    currentStopCents: spec.currentStopCents,
    openPlannedRiskCents,
    mfeCents,
    maeCents,
    dataCompleteness: "COMPLETE",
    stopOutcome: stopOutcomeFor(rHundredths),
    exitReason: closed ? exits[exits.length - 1].reason : null,
    path,
    holdingSessions: lastSession - firstSession,
  };
}

/* ------------------------------------------------------------ the closed ledger */

/**
 * How many closed trades the ledger carries.
 *
 * The number is chosen so the minimum-observation rules of §12.3 are **exercised in both
 * directions**: most versions clear the 20-trade and 30-trade thresholds, the superseded
 * Breakout version does not, and every narrow slice falls below them. A book too small to
 * clear any threshold would render one screen of `INSUFFICIENT_OBSERVATIONS` and demonstrate
 * only half the rule.
 *
 * C6 lowered it by one and added one featured trade in exchange, so the ledger population is
 * unchanged at 200 -- exactly the declared page size -- and the generated ordinals below it
 * are untouched.
 */
const GENERATED_TRADES = 194;

function buildGenerated(ordinal: number): BookTrade {
  const next = lcg(0x4b_4d_43_35 + ordinal * 2_654_435_761);
  const security = SECURITIES[next() % SECURITIES.length];
  const production = STRATEGY_VERSIONS.filter((entry) => entry.lifecycle === "PRODUCTION");
  const chosen = production[next() % production.length];
  /*
   * Entries spread across the whole retained extent, close enough to its end that the most
   * recent windows contain closed trades. A book whose last month closed nothing would report
   * INSUFFICIENT_OBSERVATIONS everywhere in that column and teach a reader that the column is
   * broken rather than that the rule is real.
   */
  const entrySession = 4 + ((ordinal * 7 + (next() % 5)) % (SESSION_COUNT - 40));
  /*
   * A VERSION TRANSITION, RATHER THAN A UNIFORM DRAW.
   *
   * Breakout Long ran at `-v2` for the first third of the retained extent and at `-v3` after
   * it. That is what a version registry actually looks like, and it is the case the contract
   * cares about: a superseded version keeps its own results, its own trade count and its own
   * observation rules, and they are not folded into its successor's.
   */
  const supersededEarly =
    chosen.module === "BREAKOUT_LONG" && entrySession < Math.floor(SESSION_COUNT / 3);
  const version = supersededEarly ? strategyVersionOf("breakout-long-v2") : chosen;
  const direction = version.direction;
  const sign = direction === "LONG" ? 1 : -1;

  /*
   * Sized to the governed research parameter for its side: 0.50% of capital long, 0.25%
   * short. The share count is floored, so the risk it produces is at or under the parameter
   * and never over it.
   */
  const targetRiskCents = direction === "LONG" ? 400_00 : 200_00;
  const shares = Math.max(1, Math.floor(targetRiskCents / security.stopDistanceCents));
  const riskCents = shares * security.stopDistanceCents;

  const drift = ((next() % 41) - 20) * security.stopDistanceCents;
  const entryCents = Math.max(
    security.stopDistanceCents * 3,
    security.basePriceCents + Math.round(drift / 10),
  );
  const invalidationCents = entryCents - sign * security.stopDistanceCents;

  const rHundredths = R_LADDER[next() % R_LADDER.length];
  const perShareCents = Math.round((security.stopDistanceCents * rHundredths) / 100);
  const exitCents = Math.max(1, entryCents + sign * perShareCents);
  const realizedCents = shares * perShareCents;

  const holdingSessions = 3 + (next() % 32);
  const exitSession = Math.min(SESSION_COUNT - 2, entrySession + holdingSessions);

  const tradeId = `demo-trade-gen-${String(ordinal).padStart(4, "0")}`;
  const path = buildPath(
    entryCents,
    exitCents,
    exitSession - entrySession,
    security.stopDistanceCents,
    ordinal * 104_729 + entrySession,
  );
  const generatedStages = [
    {
      session: entrySession,
      shares,
      priceCents: entryCents,
      invalidationCents,
      kind: "ENTRY" as const,
    },
  ];
  const generatedExits = [
    {
      session: exitSession,
      shares,
      priceCents: exitCents,
      reason: exitReasonFor(rHundredths),
      realizedCents,
    },
  ];
  const { mfeCents, maeCents } = excursions(
    generatedStages,
    generatedExits,
    path,
    entrySession,
    direction,
  );

  return {
    tradeId,
    symbol: security.symbol,
    versionId: version.versionId,
    direction,
    stages: generatedStages,
    exits: generatedExits,
    status: "CLOSED",
    sharesAcquired: shares,
    sharesOpen: 0,
    basisCents: entryCents,
    realizedCents,
    unrealizedCents: 0,
    lastSession: exitSession,
    markCents: null,
    initialRiskCents: riskCents,
    /** One historical trade's entry-time record was never written (§4.4, case 3). */
    initialRiskRecorded: tradeId !== MISSING_RISK_RECORD_TRADE,
    currentStopCents: null,
    openPlannedRiskCents: null,
    mfeCents,
    maeCents,
    /** One trade's price path is incomplete, so every path-dependent value is PARTIAL. */
    dataCompleteness: tradeId === PARTIAL_PATH_TRADE ? "PARTIAL" : "COMPLETE",
    stopOutcome: stopOutcomeFor(rHundredths),
    exitReason: exitReasonFor(rHundredths),
    path,
    holdingSessions: exitSession - entrySession,
  };
}

/* --------------------------------------------------------------------- the book */

export interface BookCashFlow {
  readonly session: number;
  readonly amountCents: number;
  readonly kind: "DEPOSIT" | "WITHDRAWAL";
}

export interface Book {
  readonly trades: readonly BookTrade[];
  readonly openTrades: readonly BookTrade[];
  readonly closedTrades: readonly BookTrade[];
  readonly cashFlows: readonly BookCashFlow[];
  /** Session-indexed portfolio equity, in cents, over the whole retained extent. */
  readonly equityCents: readonly number[];
  /** Session-indexed realized profit and loss to date, in cents. */
  readonly realizedToDateCents: readonly number[];
  readonly totals: {
    readonly longValueCents: number;
    readonly shortValueCents: number;
    readonly grossValueCents: number;
    readonly netValueCents: number;
    readonly netDirection: "LONG" | "SHORT";
    readonly realizedCents: number;
    readonly unrealizedCents: number;
    readonly openPlannedRiskCents: number;
    readonly initialPlannedRiskOpenCents: number;
    readonly positionCount: number;
  };
}

/** The market value of a trade's open portion at the snapshot session. */
export function positionValueCents(trade: BookTrade): number {
  if (trade.markCents === null) {
    return 0;
  }
  return trade.sharesOpen * trade.markCents;
}

/** How many shares a trade held at the end of a session. */
function sharesHeldAt(trade: BookTrade, session: number): number {
  const acquired = trade.stages
    .filter((stage) => stage.session <= session)
    .reduce((total, stage) => total + stage.shares, 0);
  const released = trade.exits
    .filter((exit) => exit.session <= session)
    .reduce((total, exit) => total + exit.shares, 0);
  return acquired - released;
}

/** The position-weighted basis of a trade's holding at the end of a session. */
function basisAt(trade: BookTrade, session: number): number {
  const stages = trade.stages.filter((stage) => stage.session <= session);
  const shares = stages.reduce((total, stage) => total + stage.shares, 0);
  if (shares === 0) {
    return 0;
  }
  const cost = stages.reduce((total, stage) => total + stage.shares * stage.priceCents, 0);
  return cost / shares;
}

/** The mark a trade's own path carries for a session, or `null` when it held nothing. */
function markAt(trade: BookTrade, session: number): number | null {
  const first = trade.stages[0].session;
  if (session < first || session > trade.lastSession) {
    return null;
  }
  return trade.path[Math.min(session - first, trade.path.length - 1)];
}

/**
 * Builds the whole book, once.
 *
 * **The equity curve is derived, not invented.** For every session it is
 * `strategy capital + realized to date + open unrealized + external flows to date`, with the
 * unrealized part read from each open trade's own mark path. That is why the curve, the
 * ledger, the positions and the per-strategy results cannot disagree: there is one set of
 * numbers and four projections of it.
 */
export function buildBook(): Book {
  const featured = [...FEATURED, MULTI_EXIT_TRADE_SPEC].map(buildFeatured);
  const generated = Array.from({ length: GENERATED_TRADES }, (_, index) =>
    buildGenerated(index + 1),
  );
  const trades = [...featured, ...generated];

  const cashFlows: BookCashFlow[] = [
    { session: DEPOSIT_SESSION, amountCents: DEPOSIT_CENTS, kind: "DEPOSIT" },
  ];

  const equityCents: number[] = [];
  const realizedToDateCents: number[] = [];
  for (let session = 0; session < SESSION_COUNT; session += 1) {
    let realized = 0;
    let unrealized = 0;
    for (const trade of trades) {
      const sign = trade.direction === "LONG" ? 1 : -1;
      for (const exit of trade.exits) {
        if (exit.session <= session) {
          realized += exit.realizedCents;
        }
      }
      // A trade contributes no unrealized result before it opened or after it closed.
      if (session < trade.stages[0].session || session > trade.lastSession) {
        continue;
      }
      const held = sharesHeldAt(trade, session);
      if (held <= 0) {
        continue;
      }
      const mark = markAt(trade, session);
      if (mark === null) {
        continue;
      }
      unrealized += held * (mark - basisAt(trade, session)) * sign;
    }
    const flows = cashFlows
      .filter((flow) => flow.session <= session)
      .reduce((total, flow) => total + flow.amountCents, 0);
    realizedToDateCents.push(Math.round(realized));
    equityCents.push(Math.round(STRATEGY_CAPITAL_CENTS + realized + unrealized + flows));
  }

  const openTrades = trades.filter((trade) => trade.status !== "CLOSED");
  const closedTrades = trades.filter((trade) => trade.status === "CLOSED");

  const longValueCents = openTrades
    .filter((trade) => trade.direction === "LONG")
    .reduce((total, trade) => total + positionValueCents(trade), 0);
  const shortValueCents = openTrades
    .filter((trade) => trade.direction === "SHORT")
    .reduce((total, trade) => total + positionValueCents(trade), 0);

  return {
    trades,
    openTrades,
    closedTrades,
    cashFlows,
    equityCents,
    realizedToDateCents,
    totals: {
      longValueCents,
      shortValueCents,
      grossValueCents: longValueCents + shortValueCents,
      netValueCents: Math.abs(longValueCents - shortValueCents),
      netDirection: longValueCents >= shortValueCents ? "LONG" : "SHORT",
      realizedCents: trades.reduce((total, trade) => total + trade.realizedCents, 0),
      unrealizedCents: openTrades.reduce((total, trade) => total + trade.unrealizedCents, 0),
      openPlannedRiskCents: openTrades.reduce(
        (total, trade) => total + (trade.openPlannedRiskCents ?? 0),
        0,
      ),
      initialPlannedRiskOpenCents: openTrades.reduce(
        (total, trade) => total + trade.initialRiskCents,
        0,
      ),
      positionCount: openTrades.length,
    },
  };
}

/**
 * The book, built once per module load.
 *
 * It depends on nothing outside this module — no clock, no scope, no environment — so it is
 * a constant, and two callers reading it are reading the same numbers.
 */
export const BOOK: Book = buildBook();

/* ------------------------------------------------------------ the benchmark index */

/**
 * ONE synthetic benchmark index, over the whole retained extent.
 *
 * It is a single series that every trade's holding window is a SLICE of, rather than a path
 * generated per trade. A per-trade benchmark would be a different index for every comparison,
 * and two trades in the same month would be measured against two different markets.
 *
 * **IT IS NOT A REAL BENCHMARK.** No provider is selected, **G1 is OPEN**, and no benchmark
 * price history is requested from anywhere. It is a fixed step function between two endpoints
 * chosen by hand, in index points scaled like cents, and it models nothing.
 *
 * Its basis is PRICE_RETURN: it pays no dividend and reinvests nothing, exactly like the
 * demonstration securities it is compared against, so the two sides of every comparison are on
 * the same basis (§12.4).
 */
const BENCHMARK_BASE_POINTS = 100_00;
const BENCHMARK_END_POINTS = 118_40;

export const BENCHMARK_INDEX: readonly number[] = buildPath(
  BENCHMARK_BASE_POINTS,
  BENCHMARK_END_POINTS,
  SESSION_COUNT - 1,
  240,
  0x4b_4d_42_4e,
);

/* ---------------------------------------------------------------- session dates */

/** The last `count` weekdays ending on or before `endMs`, oldest first. */
export function sessionDates(endMs: number, count: number): string[] {
  const days: string[] = [];
  const cursor = new Date(endMs);
  cursor.setUTCHours(0, 0, 0, 0);
  while (days.length < count) {
    const weekday = cursor.getUTCDay();
    if (weekday !== 0 && weekday !== 6) {
      days.push(cursor.toISOString().slice(0, 10));
    }
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
  return days.reverse();
}

/**
 * The whole retained extent's session dates, ending at the last completed session.
 *
 * A series ends at **T−1**, never at an in-progress session, so the book's snapshot session
 * is the trading day before the one this application is being read on.
 */
export function bookSessions(originMs: number): string[] {
  return sessionDates(originMs - 86_400_000, SESSION_COUNT);
}

/** A decimal string with exactly two places, from an integer count of cents. */
export function centsToDecimal(cents: number): string {
  const rounded = Math.round(cents);
  const sign = rounded < 0 ? "-" : "";
  const magnitude = Math.abs(rounded);
  return `${sign}${Math.floor(magnitude / 100)}.${String(magnitude % 100).padStart(2, "0")}`;
}

/** A decimal string with exactly two places, from an integer count of hundredths. */
export function hundredthsToDecimal(value: number): string {
  return centsToDecimal(value);
}

/** A percentage of the authoritative strategy capital, in hundredths of a percent. */
export function pctOfCapitalHundredths(cents: number): number {
  return Math.round((cents * 10_000) / STRATEGY_CAPITAL_CENTS);
}
