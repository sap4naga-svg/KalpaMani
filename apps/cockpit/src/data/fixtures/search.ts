/**
 * The search index behind the command palette — Area 30.
 *
 * **It is an INDEX OF READ MODELS, and it is not a search of anything else.** Every row is
 * built from a payload this application already serves, so a row can only name something a
 * screen already shows. Nothing here reads the filesystem, walks a route table, scans
 * repository text or reaches a network: "resolution by prefix or naming convention, or by a
 * runtime filesystem, module or route search, is REFUSED" (§4.3), and the way to hold that is
 * to have no code that could do it.
 *
 * **A term FILTERS an index; it is not a query language.** It is compared, lower-cased,
 * against three closed fields of each row — the row's own identifier, its title code and its
 * subject code. It is never interpolated into a route, an expression, a pattern or a
 * template, and it never reaches the payload: §4.5 requires `query_echo` to be "the parsed,
 * typed query, never the raw string", so what travels is a closed code saying which parse
 * happened.
 *
 * **Every row carries its own labels.** Environment, provenance and classification are stated
 * per row, which is what lets this read model index facts of more than one provenance without
 * either becoming the other (§4.3.1, §7.1).
 *
 * **The governance-derived entries §7.1 authorizes here are deliberately not produced**, and
 * the reason is a navigation one rather than a policy one: ADR-0030 R10's `RefKind` allowlist
 * and ADR-0031 A2's `OwningArea` vocabulary contain no member that lands on the Project and
 * Qualification Governance area, so a governance row could be indexed but not opened —
 * and mapping one onto the Audit Trail is exactly the *an Audit page owns every fact* claim
 * §4.3.2 exists to stop. Adding a member is an ADR's act, not an implementation's. The
 * palette's navigation group reaches that area directly, which is what a reader needs.
 */
import {
  SEARCH_MAX_READ_MODELS,
  SEARCH_PAGE_SIZE,
  type SearchResult,
  type SearchResultPagePayload,
} from "@/contracts/ask-models";
import { count, demoRef, demoReason } from "./common";
import type { Environment, RefKind } from "@/contracts/vocabularies";
import type { TradeSummaryPayload } from "@/contracts/portfolio-models";
import type { CandidateSummaryPayload } from "@/contracts/signal-models";
import type { StrategyVersionPayload } from "@/contracts/strategy-models";
import type {
  HypothesisRegistrationPayload,
  ResearchRunPayload,
} from "@/contracts/research-models";
import type {
  AlertPayload,
  DataQualityPayload,
  SystemIncidentPayload,
} from "@/contracts/operations-models";
import type { ReconciliationPayload } from "@/contracts/execution-quality-page";

/** The read models this index draws from. Nine, against a declared bound of twenty (§5.1). */
export const INDEXED_READ_MODELS = [
  "TradeSummary",
  "CandidateSummary",
  "StrategyVersion",
  "HypothesisRegistration",
  "ResearchRun",
  "SystemIncident",
  "Alert",
  "DataQuality",
  "ReconciliationStatus",
] as const;

export interface SearchSources {
  readonly trades?: TradeSummaryPayload;
  readonly candidates?: CandidateSummaryPayload;
  readonly strategyVersions?: StrategyVersionPayload;
  readonly hypotheses?: HypothesisRegistrationPayload;
  readonly researchRuns?: ResearchRunPayload;
  readonly incidents?: SystemIncidentPayload;
  readonly alerts?: AlertPayload;
  readonly dataQuality?: DataQualityPayload;
  readonly reconciliation?: ReconciliationPayload;
}

function row(
  resultId: string,
  refKind: RefKind,
  subject: string,
  title: string,
  environment: Environment,
): SearchResult {
  return {
    /*
     * `ENDPOINT` is the truthful resolution here: each of these kinds has a catalogued route
     * and this application serves it for the SYNTHETIC scope (§4.3, ADR-0030 R6). No row
     * declares an `owning_area`, because a search row already names the record itself and an
     * area control would be a second, weaker affordance beside a working one.
     */
    ref: demoRef(resultId, refKind, "ENDPOINT"),
    title: demoReason(title),
    subject: demoReason(subject),
    result_id: resultId,
    environment,
    provenance: "SYNTHETIC",
    classification: "PUBLIC_SAFE",
  };
}

/**
 * Every indexable row, in one canonical order.
 *
 * The order is subject then identifier, and it is derived rather than incidental: §6 requires
 * a declared sort with a deterministic tiebreak, "so two identical requests return identical
 * order".
 */
export function searchRows(
  sources: SearchSources,
  environment: Environment,
): readonly SearchResult[] {
  const rows: SearchResult[] = [];
  for (const trade of sources.trades?.items ?? []) {
    rows.push(row(trade.trade_id, "trade", "TRADE", trade.security.symbol, environment));
  }
  for (const candidate of sources.candidates?.items ?? []) {
    rows.push(
      row(
        candidate.candidate_id,
        "candidate",
        "CANDIDATE",
        candidate.security.symbol,
        environment,
      ),
    );
  }
  for (const version of sources.strategyVersions?.items ?? []) {
    rows.push(
      row(
        version.strategy_version,
        "strategy_version",
        "STRATEGY_VERSION",
        version.module.code,
        environment,
      ),
    );
  }
  for (const registration of sources.hypotheses?.items ?? []) {
    rows.push(
      row(
        registration.registration_id,
        "registration",
        "REGISTRATION",
        registration.strategy_module.code,
        environment,
      ),
    );
  }
  for (const run of sources.researchRuns?.items ?? []) {
    rows.push(
      row(run.run_id, "research_run", "RESEARCH_RUN", run.evaluation_class, environment),
    );
  }
  for (const incident of sources.incidents?.items ?? []) {
    rows.push(
      row(incident.incident_id, "incident", "INCIDENT", incident.subject.code, environment),
    );
  }
  for (const alert of sources.alerts?.items ?? []) {
    rows.push(row(alert.alert_id, "alert", "ALERT", alert.condition.code, environment));
  }
  for (const subject of sources.dataQuality?.items ?? []) {
    rows.push(
      row(subject.subject_id, "data_quality", "DATA_QUALITY", subject.subject.code, environment),
    );
  }
  for (const run of sources.reconciliation?.items ?? []) {
    rows.push(
      row(run.run_id, "reconciliation", "RECONCILIATION", run.result.code, environment),
    );
  }
  return rows.sort((left, right) =>
    left.subject.code === right.subject.code
      ? left.result_id.localeCompare(right.result_id)
      : left.subject.code.localeCompare(right.subject.code),
  );
}

/** Whether one row matches a term. Three closed fields, compared, and nothing evaluated. */
export function rowMatches(candidate: SearchResult, term: string): boolean {
  const needle = term.trim().toLowerCase();
  if (needle.length === 0) {
    return true;
  }
  return (
    candidate.result_id.toLowerCase().includes(needle) ||
    candidate.title.code.toLowerCase().includes(needle) ||
    candidate.subject.code.toLowerCase().includes(needle)
  );
}

/**
 * The delivered page.
 *
 * `total` is the number of rows that MATCHED, and `items` is the page of them — so a
 * truncated result is never read as a complete population (§5.2). Nothing is silently cut:
 * `truncated` says so, and the count beside it says how many exist.
 */
export function syntheticSearchPage(
  sources: SearchSources,
  environment: Environment,
  term: string,
  asOf: string,
): SearchResultPagePayload {
  const matched = searchRows(sources, environment).filter((candidate) =>
    rowMatches(candidate, term),
  );
  const delivered = matched.slice(0, SEARCH_PAGE_SIZE);
  return {
    /*
     * THE PARSED QUERY, AND NEVER THE RAW STRING (§4.5).
     *
     * The term the reader typed does not travel in the payload at all: what travels is the
     * closed code for the parse that happened, so nothing a reader wrote can be echoed back
     * into a page, a link or a log.
     */
    query_echo: demoReason(term.trim().length === 0 ? "INDEX_ALL" : "INDEX_TERM_MATCH"),
    results: delivered,
    scoping: { environment, provenance: "SYNTHETIC" },
    grouped_by_environment: true,
    page: {
      page_size: SEARCH_PAGE_SIZE,
      total: count("reference.total", matched.length, asOf),
      truncated: matched.length > SEARCH_PAGE_SIZE,
      sort: demoReason("SUBJECT_THEN_IDENTIFIER"),
      tiebreak: demoReason("RESULT_ID_ASCENDING"),
    },
    read_models_indexed: count(
      "search.read_models_indexed",
      INDEXED_READ_MODELS.length,
      asOf,
    ),
    read_models_maximum: count("search.read_models_maximum", SEARCH_MAX_READ_MODELS, asOf),
  };
}
