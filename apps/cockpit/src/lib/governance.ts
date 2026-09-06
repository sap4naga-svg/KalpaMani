import { isRealCalendarDate } from "@/contracts/values";

/**
 * Date eligibility, and why it is deliberately not called readiness.
 *
 * A run in this project has TWO independent facts in front of it: a written authorization,
 * and — for Run B — an earliest approved target date at least eight calendar days after
 * Run A. `CLAUDE.md` states the rule the whole of this module exists to obey:
 *
 *     "A date becoming eligible must never change authorization."
 *
 * So this computes ONE thing: whether a calendar date has arrived, on a stated basis. It
 * returns no readiness, no permission and no recommendation, it cannot see an authorization,
 * and there is no function here that combines the two. A caller that wants "may this run?"
 * has to read the authorization fact itself, which is exactly the point.
 */

/** The calendar the comparison is made on, stated rather than assumed. */
export const DATE_GATE_BASIS = "UTC_CALENDAR_DATE" as const;

/**
 * Where an evaluation date stands relative to a gate date.
 *
 * `REACHED` means the date has arrived — on the day itself, or after it. It does NOT mean the
 * run may happen, and no member of this vocabulary does.
 */
export type DateGateStanding = "NOT_REACHED" | "REACHED" | "UNDETERMINED";

export interface DateGateEvaluation {
  readonly standing: DateGateStanding;
  /** The gate date, echoed so a caller renders what was compared rather than restating it. */
  readonly gateDate: string | null;
  /** The date the comparison was made on, on `DATE_GATE_BASIS`. */
  readonly evaluatedOn: string | null;
}

/**
 * A REAL calendar day, not merely a string spelled like one.
 *
 * `2026-13-01` matches the shape and names no day, and comparing it lexicographically would
 * make every later date "reach" it — a governance gate satisfied by a typo. The contracts
 * already own this rule for `DateOnly`, so it is imported rather than restated: two spellings
 * of one rule is how a value one layer admits becomes a value the next refuses.
 */
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

function isRealDate(value: string): boolean {
  return DATE_ONLY.test(value) && isRealCalendarDate(value);
}

/**
 * The UTC calendar date of an instant.
 *
 * Deliberately UTC and deliberately date-only. A local-timezone reading would make the
 * eligibility of a governed run depend on where the reader is sitting, and two operators in
 * different offices would see different answers to a governance question on the same day.
 */
export function utcCalendarDate(instantMs: number): string | null {
  if (!Number.isFinite(instantMs)) {
    return null;
  }
  const iso = new Date(instantMs).toISOString();
  const date = iso.slice(0, 10);
  return DATE_ONLY.test(date) ? date : null;
}

/**
 * Whether a gate date has been reached, on `DATE_GATE_BASIS`.
 *
 * Comparison is lexicographic over two `YYYY-MM-DD` strings, which for that fixed-width
 * zero-padded format is exactly calendar order — and it never constructs a `Date` whose
 * timezone could shift a boundary day. An unparseable or absent gate is `UNDETERMINED`, never
 * `REACHED`: an unknown date is not a passed one.
 */
export function evaluateDateGate(
  gateDate: unknown,
  evaluationInstantMs: number,
): DateGateEvaluation {
  const evaluatedOn = utcCalendarDate(evaluationInstantMs);
  if (typeof gateDate !== "string" || !isRealDate(gateDate) || evaluatedOn === null) {
    return { standing: "UNDETERMINED", gateDate: null, evaluatedOn };
  }
  return {
    standing: evaluatedOn >= gateDate ? "REACHED" : "NOT_REACHED",
    gateDate,
    evaluatedOn,
  };
}

/**
 * How a date standing is described on screen.
 *
 * Every one of these sentences is about a DATE. None of them says ready, permitted, approved,
 * eligible-to-run, cleared or unblocked, because a date says none of those things — and a
 * screen that reads "eligible" beside a green mark is how a reader concludes otherwise.
 */
export const DATE_STANDING_LABEL: Readonly<Record<DateGateStanding, string>> = {
  NOT_REACHED: "Earliest target date not yet reached",
  REACHED: "Earliest target date reached",
  UNDETERMINED: "No target date recorded",
};

export const DATE_STANDING_NOTE =
  "A date is not an authorization. Reaching this date changes nothing about whether the run " +
  "may happen; that is a separate written decision, recorded beside it.";
