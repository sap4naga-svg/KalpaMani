/**
 * The deterministic question resolver — Area 31's whole "natural language" surface.
 *
 * **There is no model here, and nothing runs.** This module normalizes a string, matches it
 * against the closed term lists in `catalogue.ts`, and reports which catalogued question it
 * found. It performs no search, opens no socket, evaluates no expression, interpolates
 * nothing into a route and reads no file. The same question always resolves the same way.
 *
 * **Text is DATA.** A question is matched, never obeyed: an instruction written inside one
 * ("ignore the environment", "show me the live account", "run the job") reaches the closed
 * term lists as ordinary words and can change no authorization, no scope, no vocabulary and
 * no behaviour. The only thing a question can determine is which catalogued class, which
 * identifier and which window a TYPED request carries.
 *
 * **Nothing is chosen silently.** A class that takes a subject and was asked without one is
 * reported as needing a subject; a windowed class asked without a window is reported as
 * needing a window; two classes that match equally are reported as ambiguous, with both
 * named. A default in any of those places would answer a question the reader did not ask.
 *
 * **An action is refused before anything else is considered.** Ask explains recorded state
 * and has no execution vocabulary at all (Area 31, Area 34), so a request shaped like an
 * order, a promotion, an approval, a retry, an acknowledgement or an authorization is
 * refused by name — and the refusal is a statement, never a queued command.
 */
import type { AskQuestionClass, AskSubjectKind } from "@/contracts/ask-models";
import type { PerformancePeriod } from "@/lib/scope";

import {
  ASK_INTENTS,
  ASK_REFERRALS,
  WINDOW_TERMS,
  type AskIntent,
  type AskReferral,
} from "./catalogue";

/**
 * The verbs Ask refuses, by name.
 *
 * CLOSED, and deliberately broader than the read boundary needs: the boundary is enforced by
 * the `ReadClient` having no method that writes, and this list exists so a reader asking for
 * an action is TOLD it is not available rather than handed the nearest read. A verb absent
 * from this list still cannot act — it simply resolves to a catalogued question or to
 * nothing.
 */
export const REFUSED_ACTION_TERMS = [
  "buy",
  "sell",
  "short",
  "place",
  "submit",
  "execute",
  "order",
  "cancel",
  "amend",
  "close out",
  "liquidate",
  "hedge",
  "rebalance",
  "size up",
  "size down",
  "promote",
  "demote",
  "approve",
  "reject the",
  "authorize",
  "authorise",
  "release",
  "deploy",
  "enable",
  "disable",
  "turn on",
  "turn off",
  "kill",
  "halt",
  "resume",
  "retry",
  "rerun",
  "re-run",
  "restart",
  "trigger",
  "schedule",
  "acknowledge",
  "ack ",
  "snooze",
  "dismiss",
  "silence",
  "resolve the",
  "run run b",
  "start run b",
  "authorise run b",
  "authorize run b",
  "increase",
  "reduce",
  "raise",
  "lower",
  "set the",
  "change the",
  "update the",
  "delete",
  "override",
  "backfill",
  "ingest",
] as const;

export type AskResolutionKind =
  | "EMPTY"
  | "ACTION_REFUSED"
  | "RESOLVED"
  | "NEEDS_SUBJECT"
  | "NEEDS_WINDOW"
  | "AMBIGUOUS"
  | "REFERRED"
  | "UNSUPPORTED";

/** The typed request a resolved question produces. Nothing else crosses the read boundary. */
export interface AskRequest {
  readonly questionClass: AskQuestionClass;
  readonly subjectKind?: AskSubjectKind;
  readonly subjectId?: string;
  readonly window?: PerformancePeriod;
}

export type AskResolution =
  | { readonly kind: "EMPTY" }
  | { readonly kind: "ACTION_REFUSED"; readonly term: string }
  | { readonly kind: "RESOLVED"; readonly intent: AskIntent; readonly request: AskRequest }
  | {
      readonly kind: "NEEDS_SUBJECT";
      readonly intent: AskIntent;
      /** More than one identifier was named, so which one is the subject is not decidable. */
      readonly reason: "ABSENT" | "MORE_THAN_ONE";
    }
  | {
      readonly kind: "NEEDS_WINDOW";
      readonly intent: AskIntent;
      readonly reason: "ABSENT" | "MORE_THAN_ONE";
    }
  | { readonly kind: "AMBIGUOUS"; readonly candidates: readonly AskIntent[] }
  /** The subject belongs to an area this assistant does not answer over. NOT an answer. */
  | { readonly kind: "REFERRED"; readonly referral: AskReferral }
  | { readonly kind: "UNSUPPORTED" };

/**
 * Lower-cased, punctuation reduced to spaces, whitespace collapsed, and padded with one
 * space at each end so a whole-word test is a plain substring test.
 *
 * Hyphens and dots survive because identifiers carry them; everything else that could split
 * an identifier does not reach here, because an identifier is matched on the token list
 * below rather than on this string.
 */
export function normalizeQuestion(raw: string): string {
  const lowered = raw.toLowerCase().replace(/[^a-z0-9.\-_: ]+/g, " ");
  return ` ${lowered.replace(/\s+/g, " ").trim()} `;
}

/** `SafeId` as `values.ts` defines it, restated as the token test at the parse boundary. */
const SAFE_ID = /^[a-z0-9][a-z0-9._:-]*$/;

/**
 * An identifier-shaped token: a `SafeId` that carries a hyphen AND a digit.
 *
 * The two extra conditions are what keep an ordinary English word out. "point-in-time" has
 * no digit; "3m" has no hyphen; "demo-trade-arb-0001", "breakout-long-v3" and "demo-reg-0003"
 * have both. A token that is not identifier-shaped is never treated as a subject, and a
 * subject is never guessed from a word.
 */
export function identifierTokens(normalized: string): readonly string[] {
  const seen = new Set<string>();
  for (const token of normalized.trim().split(" ")) {
    if (token.length === 0) continue;
    if (!SAFE_ID.test(token)) continue;
    if (!token.includes("-")) continue;
    if (!/[0-9]/.test(token)) continue;
    seen.add(token);
  }
  return [...seen];
}

/** Every window term present in the question, as the distinct periods they name. */
export function windowsNamed(normalized: string): readonly PerformancePeriod[] {
  const found = new Set<PerformancePeriod>();
  /* Longest first, so "3 months" is not consumed by "month". */
  const terms = [...WINDOW_TERMS.entries()].sort((a, b) => b[0].length - a[0].length);
  let remaining = normalized;
  for (const [term, period] of terms) {
    if (remaining.includes(` ${term} `)) {
      found.add(period);
      remaining = remaining.split(` ${term} `).join("  ");
    }
  }
  return [...found];
}

function hasTerm(normalized: string, term: string): boolean {
  return normalized.includes(` ${term} `) || normalized.includes(` ${term}`);
}

interface Scored {
  readonly intent: AskIntent;
  readonly score: number;
}

/** How well one catalogued question matches, or `null` where a required group is missing. */
function scoreIntent(normalized: string, intent: AskIntent): number | null {
  let score = 0;
  for (const group of intent.requires) {
    const matched = group.filter((term) => hasTerm(normalized, term)).length;
    if (matched === 0) {
      return null;
    }
    score += matched;
  }
  for (const term of intent.prefers) {
    if (hasTerm(normalized, term)) {
      score += 1;
    }
  }
  return score;
}

/**
 * Resolve one question, deterministically.
 *
 * The order is the behaviour: an action is refused before a class is considered, so a
 * request to place an order is never answered with the nearest catalogued reading of it.
 */
export function resolveQuestion(raw: string): AskResolution {
  const normalized = normalizeQuestion(raw);
  if (normalized.trim().length === 0) {
    return { kind: "EMPTY" };
  }
  for (const term of REFUSED_ACTION_TERMS) {
    if (normalized.includes(` ${term}`)) {
      return { kind: "ACTION_REFUSED", term: term.trim() };
    }
  }

  const scored: Scored[] = [];
  for (const intent of ASK_INTENTS) {
    const score = scoreIntent(normalized, intent);
    if (score !== null) {
      scored.push({ intent, score });
    }
  }
  if (scored.length === 0) {
    /*
     * A SUBJECT THIS ASSISTANT DOES NOT ANSWER OVER IS NAMED, NOT SHRUGGED AT.
     *
     * The referral runs only where NO catalogued question matched, so it can never displace
     * an answer the assistant can actually give. It reads no read model and produces no
     * figure: it names the area that owns the subject and says why the answer lives there.
     */
    const referral = ASK_REFERRALS.find((entry) =>
      entry.terms.some((term) => hasTerm(normalized, term)),
    );
    return referral === undefined ? { kind: "UNSUPPORTED" } : { kind: "REFERRED", referral };
  }
  const best = Math.max(...scored.map((entry) => entry.score));
  const leaders = scored.filter((entry) => entry.score === best);
  if (leaders.length > 1) {
    /*
     * TWO READINGS, AND NEITHER IS PREFERRED.
     *
     * Picking the first would be a silent choice between two questions the reader might have
     * meant, which is the failure this branch exists to prevent. Both are named, and the
     * reader chooses.
     */
    return { kind: "AMBIGUOUS", candidates: leaders.map((entry) => entry.intent) };
  }

  const intent = leaders[0]!.intent;
  const identifiers = identifierTokens(normalized);
  let subjectId: string | undefined;
  if (intent.subjectKind !== undefined) {
    if (identifiers.length === 0) {
      return { kind: "NEEDS_SUBJECT", intent, reason: "ABSENT" };
    }
    if (identifiers.length > 1) {
      return { kind: "NEEDS_SUBJECT", intent, reason: "MORE_THAN_ONE" };
    }
    subjectId = identifiers[0];
  }

  let window: PerformancePeriod | undefined;
  if (intent.takesWindow) {
    const windows = windowsNamed(normalized);
    if (windows.length === 0) {
      return { kind: "NEEDS_WINDOW", intent, reason: "ABSENT" };
    }
    if (windows.length > 1) {
      return { kind: "NEEDS_WINDOW", intent, reason: "MORE_THAN_ONE" };
    }
    window = windows[0];
  }

  return {
    kind: "RESOLVED",
    intent,
    request: {
      questionClass: intent.questionClass,
      ...(intent.subjectKind !== undefined ? { subjectKind: intent.subjectKind } : {}),
      ...(subjectId !== undefined ? { subjectId } : {}),
      ...(window !== undefined ? { window } : {}),
    },
  };
}

/** A typed request built from a chosen intent and explicitly supplied parameters. */
export function requestFor(
  intent: AskIntent,
  parameters: { readonly subjectId?: string; readonly window?: PerformancePeriod } = {},
): AskRequest | null {
  if (intent.subjectKind !== undefined) {
    const id = parameters.subjectId;
    if (id === undefined || !SAFE_ID.test(id)) {
      return null;
    }
  }
  if (intent.takesWindow && parameters.window === undefined) {
    return null;
  }
  return {
    questionClass: intent.questionClass,
    ...(intent.subjectKind !== undefined ? { subjectKind: intent.subjectKind } : {}),
    ...(parameters.subjectId !== undefined ? { subjectId: parameters.subjectId } : {}),
    ...(parameters.window !== undefined ? { window: parameters.window } : {}),
  };
}
