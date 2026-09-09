/**
 * The C9 search and assistant contracts — `read-model-contracts.md` §4.5 *Search and
 * assistant*, §5.1 `/search` and `/ask`, and §10's Ask KalpaMani clause.
 *
 * TWO READ MODELS, AND NEITHER IS A QUERY ENGINE.
 *
 *   `SearchResultPage`  indexed safe identifiers and titles of authorized read models
 *   `AskAnswer`         bounded, TYPED analytics over authorized read models
 *
 * **There is no arbitrary query surface here, and there is no shape one could arrive
 * through.** A request names a member of a CLOSED question class and typed parameters; it
 * carries no expression, no predicate, no field list, no sort, no projection and no free
 * text. §4.5 states the boundary as "a typed, bounded analytical class, never arbitrary SQL
 * or code", and the way to hold it is to have no field in which an expression could be
 * written.
 *
 * **Abstention over invention.** An answer with no citation is not returned, so
 * `AskAnswer.citations` narrows `source_fact`'s `ZERO_OR_MORE` relation to `ONE_OR_MORE` —
 * the one place in the catalogue the stronger relation is meant (§4.3.1, ADR-0030 R7). An
 * answer that could not be computed ABSTAINS, states why in a closed code, and still names
 * the records it consulted; a question the catalogue does not define is not an `AskAnswer` at
 * all, and is reported as a PAYLOADLESS envelope under the §4.1.1 matrix.
 *
 * **No answer is fresher or more certain than its evidence.** Every figure below is lifted
 * from the read model that owns it, as the `MetricValue` that read model produced — its
 * availability, its reason, its unit, its `as_of` and its metric definition intact. Nothing
 * here recomputes a number a screen already reports, because two spellings of one
 * measurement are two values that can disagree.
 */
import { z } from "zod";

import { envelope } from "./envelope";
import { pageMeta } from "./pagination";
import { refListFieldOf, refOf } from "./references";
import { isValueBearing } from "./validity";
import { countValue, metricValue, reasonCoded, safeId, type MetricValue } from "./values";
import { dataClassification, dataProvenance, environment } from "./vocabularies";

/**
 * The CLOSED question vocabulary — `ask.question_class.v1`.
 *
 * §4.5 types `question_class` as a `ReasonCoded` "typed, bounded analytical class" and does
 * not enumerate its members, so the members are enumerated here as the bounded completion
 * that makes the field checkable. **It is closed**: a request naming a code outside this set
 * is refused rather than interpreted, and a new member is a reviewed change to this list
 * rather than something a caller can supply.
 *
 * Every member is answerable from a read model this application already serves, and each
 * one's answer is that read model's own figure. There is no member whose answer would have
 * to be computed by a second engine, because a second engine can disagree with the screen.
 *
 * **There is no governance or qualification member, and its absence is a contract
 * consequence rather than an oversight.** §7.1 admits `REPOSITORY_TRACKED` to `PUBLIC_EDGE`
 * from `QualificationStatus`, `AttentionItem`, `WhatChangedEntry`, `SearchResultPage` and
 * `MaturityStatus` — and `AskAnswer` is not among them, while §2.6 catalogues `AskAnswer` as
 * `SYNTHETIC` with no governance blend. An `AskAnswer` carrying tracked governance facts
 * would therefore have to either mislabel them `SYNTHETIC` or be refused at admission. The
 * tracked facts are reached through `SearchResultPage`, which the catalogue DOES authorize to
 * carry them, and through the governance area that owns them.
 */
export const ASK_QUESTION_CLASSES = [
  "PORTFOLIO_RETURN",
  "PORTFOLIO_DRAWDOWN",
  "STRATEGY_HEALTH",
  "TRADE_OUTCOME",
  "CANDIDATE_PROGRESSION",
  "ATTENTION_SUMMARY",
  "RECORDED_CHANGES",
  "DATA_QUALITY_CONDITION",
  "RECONCILIATION_RESULT",
  "OPEN_ALERTS",
  "RESEARCH_LINEAGE",
] as const;
export type AskQuestionClass = (typeof ASK_QUESTION_CLASSES)[number];

export const ASK_QUESTION_VOCABULARY = "ask.question_class.v1";

/** The subject kinds a question may be ABOUT. Closed, and each maps to one typed parameter. */
export const ASK_SUBJECT_KINDS = [
  "TRADE",
  "CANDIDATE",
  "STRATEGY_VERSION",
  "REGISTRATION",
] as const;
export type AskSubjectKind = (typeof ASK_SUBJECT_KINDS)[number];

export const ASK_SUBJECT_VOCABULARY = "ask.subject_kind.v1";

/**
 * Why an answer abstained. CLOSED, and never free text.
 *
 * Each member is a statement about the EVIDENCE, not about the question: a question the
 * catalogue does not define never reaches this vocabulary, because it never becomes an
 * `AskAnswer`.
 */
export const ASK_ABSTENTION_REASONS = [
  /**
   * The record exists and the measurement this class reports does not carry a value.
   *
   * The record's own state and reason are on the screen beside the abstention, so the reader
   * sees WHICH absence it was rather than a single flattened word.
   */
  "MEASUREMENT_UNAVAILABLE",
  /**
   * The record exists and the measurement is below its own declared minimum population.
   *
   * Kept apart from the member above because they are different facts for a reader: one says
   * nobody produced the number, the other says the population was too small to report a ratio
   * over -- §9's `INSUFFICIENT_OBSERVATIONS`, with "no ratio returned".
   */
  "MEASUREMENT_BELOW_MINIMUM_OBSERVATIONS",
] as const;

/*
 * TWO OUTCOMES THAT ARE DELIBERATELY NOT ABSTENTIONS, AND WHY.
 *
 * A PAYLOADLESS PRODUCER is not an abstained answer. Where the read model a class reads
 * carries no payload -- an unpopulated environment, a scenario whose producers do not exist --
 * the ANSWER carries the same availability and reason and NO payload. An abstention would
 * have to cite the records it consulted, and there are none to cite: manufacturing one to
 * satisfy `ONE_OR_MORE` is precisely the fabrication `citations` exists to prevent.
 *
 * AN UNKNOWN SUBJECT is not an abstained answer either. A well-formed identifier that names
 * nothing is ADR-0030 R9's `REFERENT_NOT_FOUND`, reported on the envelope as
 * `NOT_YET_AVAILABLE` + `REFERENT_NOT_FOUND` with no payload -- never `NOT_IMPLEMENTED`,
 * which would assert the producer does not exist, and never an abstention, which would assert
 * evidence was consulted.
 */
export type AskAbstentionReason = (typeof ASK_ABSTENTION_REASONS)[number];

export const ASK_ABSTENTION_VOCABULARY = "ask.abstention.v1";

/**
 * §5.1: `/ask` declares a maximum scanned extent of 100,000 rows.
 *
 * "Every analytical endpoint declares its maximum scanned extent and refuses beyond it. An
 * unbounded analytical query is not a feature" (§6). The declared maximum travels IN the
 * payload beside the extent actually scanned, so a reader can check one against the other
 * rather than take the bound on trust.
 */
export const ASK_MAX_SCANNED_ROWS = 100_000;

/** §5.1: `/search` declares a default page size of 25 and an extent of 20 read models. */
export const SEARCH_PAGE_SIZE = 25;
export const SEARCH_MAX_READ_MODELS = 20;

/* ============================================================== SearchResultPage (§4.5) */

/**
 * One indexed row.
 *
 * **Each row carries its OWN environment, provenance and classification**, which is what
 * authorizes this read model to index facts of more than one provenance (§4.3.1, ADR-0030
 * R8): a tracked governance fact indexed beside a synthetic fixture entity stays labelled as
 * what it is, and **a real fact is never relabelled `SYNTHETIC` to sit in one list**.
 */
export const searchResult = z.object({
  ref: refOf("SearchResultPage.results[].ref"),
  /** What the row IS, as a closed code. Never a free-text snippet of indexed content. */
  title: reasonCoded,
  subject: reasonCoded,
  /** The row's own identifier, shown so a reader can tell two rows of one kind apart. */
  result_id: safeId,
  environment,
  provenance: dataProvenance,
  classification: dataClassification,
});
export type SearchResult = z.infer<typeof searchResult>;

export const searchResultPagePayload = z
  .object({
    /** §4.5: "the parsed, typed query, never the raw string". */
    query_echo: reasonCoded,
    results: z.array(searchResult),
    /**
     * §4.5: "present on every result and never widened server-side".
     *
     * It states the scope the SEARCH ran under. A row's own labels state what the row is,
     * and the two are separate statements rather than one repeated.
     */
    scoping: z.object({ environment, provenance: dataProvenance }),
    /** §4.5: required, and always true. U18 forbids a combined all-environments result. */
    grouped_by_environment: z.literal(true),
    /** ADDITIVE (§5.1): a page endpoint, and a page that does not say so reads as a population. */
    page: pageMeta,
    /** ADDITIVE (§5.1): the declared extent bound, so 20 read models is checkable. */
    read_models_indexed: countValue,
    read_models_maximum: countValue,
  })
  .superRefine((candidate, ctx) => {
    if (candidate.results.length > candidate.page.page_size) {
      ctx.addIssue({
        code: "custom",
        message: "a search page never carries more rows than its declared page size",
      });
    }
    /*
     * THE SCOPE IS NEVER WIDENED SERVER-SIDE (§4.5).
     *
     * Every delivered row belongs to the environment the search ran under. A row of another
     * environment inside a scoped result IS the widening this clause forbids, and it is
     * refused here rather than filtered by a renderer that could forget.
     */
    for (const row of candidate.results) {
      if (row.environment !== candidate.scoping.environment) {
        ctx.addIssue({
          code: "custom",
          message:
            `a search scoped to ${candidate.scoping.environment} delivers no ` +
            `${row.environment} row`,
        });
        return;
      }
    }
    const indexed = candidate.read_models_indexed.value;
    const maximum = candidate.read_models_maximum.value;
    if (typeof indexed === "number" && typeof maximum === "number" && indexed > maximum) {
      ctx.addIssue({
        code: "custom",
        message: "a search indexes no more read models than its declared extent bound",
      });
    }
  });
export type SearchResultPagePayload = z.infer<typeof searchResultPagePayload>;

/**
 * §5.2 versions a schema PER READ MODEL, and this read model has never been served before,
 * so it carries its own FIRST version. The nineteen coordinated models stay at `v2` and the
 * seventeen C7 and C8 models stay at `v1`; copying a version onto a model with no history
 * would state one it does not have.
 */
export const SEARCH_RESULT_PAGE_SCHEMA = "cockpit.search_result_page.v1";
export const searchResultPageEnvelope = envelope(
  searchResultPagePayload,
  SEARCH_RESULT_PAGE_SCHEMA,
);

/* ==================================================================== AskAnswer (§4.5) */

/**
 * ADDITIVE: what the typed request was resolved TO.
 *
 * The interface must show the interpreted subject and period, because "it did not silently
 * choose a different trade or period" is only checkable when the choice is displayed. The
 * environment and the provenance are NOT repeated here — the envelope already states both,
 * and two spellings of one fact are two facts that can disagree.
 */
export const askInterpretation = z
  .object({
    subject_kind: reasonCoded.optional(),
    subject_id: safeId.optional(),
    /** The analysis window, where the class takes one. Absent where it does not. */
    window: reasonCoded.optional(),
  })
  .superRefine((candidate, ctx) => {
    const kind = candidate.subject_kind !== undefined;
    const id = candidate.subject_id !== undefined;
    if (kind !== id) {
      ctx.addIssue({
        code: "custom",
        message: "an interpreted subject states both its kind and its identifier, or neither",
      });
    }
  });
export type AskInterpretation = z.infer<typeof askInterpretation>;

/** ADDITIVE: one qualifying figure, carried as the owning read model produced it. */
export const askSupportingFigure = z.object({
  label: reasonCoded,
  value: metricValue,
});

export const askAnswerPayload = z
  .object({
    question_class: reasonCoded,
    /**
     * The answer, as the `MetricValue` the owning read model produced.
     *
     * Its unit, availability, reason, `as_of` and metric definition are that read model's,
     * unchanged. An answer cannot become more certain or fresher than the evidence it
     * summarizes, and the way to guarantee that is to carry the evidence's own value rather
     * than a second copy computed here.
     */
    answer: metricValue,
    /** ADDITIVE: what the answer metric IS, as a closed code rather than a rendered sentence. */
    answer_label: reasonCoded,
    /** ADDITIVE: the figures that qualify the answer, each with its own availability. */
    supporting: z.array(askSupportingFigure),
    /**
     * ADDITIVE: the qualitative context the record itself carries, as CLOSED CODES.
     *
     * A recorded exit reason, a journaled blocking reason, a safety action, an alignment
     * finding: each is a code the producing read model already carries, reproduced unchanged.
     * **There is no free-text field here on purpose** — an assistant that could write a
     * sentence into a payload could write a cause into one, and a recorded reason and an
     * inferred cause are different claims.
     */
    notes: z.array(reasonCoded),
    /** ADDITIVE: the resolved subject and window, so the interpretation is visible. */
    interpretation: askInterpretation,
    /**
     * ADDITIVE: the record the answer is ABOUT, where the class takes a subject.
     *
     * **It is not a citation.** A citation names a source fact the figure came FROM;
     * this names the entity the question was about, and it carries that entity's own kind so
     * it opens the record rather than landing on the nearest area (ADR-0030 R10).
     */
    subject_ref: refOf("AskAnswer.subject_ref").optional(),
    /** §4.5: ONE_OR_MORE, or the answer is not returned (§4.3.1, ADR-0030 R7). */
    citations: refListFieldOf("AskAnswer.citations"),
    abstained: z.boolean(),
    /** §4.5: conditional — required when abstained. */
    abstention_reason: metricValue.optional(),
    /** §4.5: against the endpoint's declared maximum. */
    scanned_extent: countValue,
    /** ADDITIVE: that declared maximum, so the extent is checkable rather than asserted. */
    scanned_extent_maximum: countValue,
  })
  .superRefine((candidate, ctx) => {
    /*
     * ABSTENTION AND ANSWERING ARE ONE QUESTION ASKED TWICE, AND THEY MUST AGREE.
     *
     * An abstained answer carrying a value is an invention wearing an abstention's label, and
     * an answered one with no value is an absence presented as a result. §4.1.1 already pairs
     * a state with the presence of a value; this pairs both with the payload's own
     * `abstained` flag, which is the field a reader actually sees.
     */
    const bearing = isValueBearing(candidate.answer.availability);
    if (candidate.abstained === bearing) {
      ctx.addIssue({
        code: "custom",
        message: candidate.abstained
          ? "an abstained answer carries no value-bearing measurement"
          : "an answer that did not abstain carries a value-bearing measurement",
      });
    }
    /*
     * THE SUBJECT REFERENCE AND THE INTERPRETED SUBJECT ARE ONE SUBJECT, SO THEY AGREE.
     *
     * A reference to a record the interpretation does not name would offer a destination for
     * an entity the answer is not about, which is the silent substitution the interpretation
     * field exists to make visible.
     */
    if (
      candidate.subject_ref !== undefined &&
      candidate.subject_ref.ref_id !== candidate.interpretation.subject_id
    ) {
      ctx.addIssue({
        code: "custom",
        message: "an answer's subject reference names the subject its interpretation states",
      });
    }
    if (candidate.abstained !== (candidate.abstention_reason !== undefined)) {
      ctx.addIssue({
        code: "custom",
        message: "an abstention states its reason, and an answer states none",
      });
    }
    const scanned = candidate.scanned_extent.value;
    const maximum = candidate.scanned_extent_maximum.value;
    if (typeof scanned === "number" && typeof maximum === "number" && scanned > maximum) {
      /*
       * §5.2: "refusal, not truncation". An extent beyond the declared maximum is refused at
       * the boundary rather than served as a shorter answer that looks complete.
       */
      ctx.addIssue({
        code: "custom",
        message: "a bounded analytical answer scans no more than its declared maximum extent",
      });
    }
  });
export type AskAnswerPayload = z.infer<typeof askAnswerPayload>;

export const ASK_ANSWER_SCHEMA = "cockpit.ask_answer.v1";
export const askAnswerEnvelope = envelope(askAnswerPayload, ASK_ANSWER_SCHEMA);

/** Whether a `MetricValue` carries a value an answer may report. */
export function answerIsMeasured(value: MetricValue): boolean {
  return isValueBearing(value.availability);
}
