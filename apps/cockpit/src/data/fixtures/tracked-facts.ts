/**
 * REAL governance facts, read from tracked repository authority.
 *
 * Provenance `REPOSITORY_TRACKED`, classification `PUBLIC_SAFE`. These are REAL FACTS and
 * are NEVER relabelled `SYNTHETIC` (read-model-contracts.md §2.2).
 *
 * Every fact below carries the exact tracked path and the exact repository commit it was
 * read at, and the recorded as-of date. THE APPLICATION NEVER FETCHES GITHUB, AWS, A
 * PROVIDER OR A BROKER TO REFRESH THESE — they are a SNAPSHOT, transcribed at the commit
 * named in `READ_AT_COMMIT`, and they age. A later cycle refreshes them by re-reading the
 * tracked sources under its own authorization.
 *
 * THREE DATES ARE KEPT APART, because collapsing them dates every fact to the day someone
 * copied it:
 *
 *   each fact's `as_of`     when the SOURCE records that the fact became true
 *   SNAPSHOT_AS_OF          the state of the tracked sources this snapshot reflects
 *   SNAPSHOT_EXTRACTED_ON   the day the transcription was made
 *
 * A historical success carries its as-of time, and CURRENT RUNTIME HEALTH IS NEVER CLAIMED
 * FROM A PAST QUALIFICATION SUCCESS (ADR-0027 §5).
 */
import type { QualificationStatusPayload } from "@/contracts/read-models";

import { absent, available, reason } from "@/contracts/factories";

/**
 * The repository revision every fact below was read from.
 *
 * Refreshed by C4 from `8950c07d…` — the pre-merge parent C3 transcribed at — to the merge
 * commit of PR #74, which is the current `main`. It was verified during the session that
 * wrote this file: its full SHA, its tree, and both of its ordered parents.
 */
export const READ_AT_COMMIT = "74790b82b9939e3a8f21e4ed71425717318288ad";

/**
 * The as-of date the tracked SOURCE CONTENT itself records. Facts age from here.
 *
 * The commit was merged early on 2026-09-06 UTC, and the status it records is dated
 * 2026-09-05 — so this is the source's own as-of, and NOT the timestamp of the merge that
 * happened to carry it.
 */
export const SNAPSHOT_AS_OF = "2026-09-05";

/**
 * The day the transcription was made — NOT the day any fact became true.
 *
 * Separate from `SNAPSHOT_AS_OF` by contract (`QualificationStatus.snapshot_extracted_on`),
 * because a governance record's age is measured from when it became true and not from when
 * it was copied. The tracked sources record their status as of 2026-09-05; the transcription
 * was made on 2026-09-06.
 */
export const SNAPSHOT_EXTRACTED_ON = "2026-09-06";

const CLAUDE_MD = "CLAUDE.md";
const source = (path: string) => ({ path, commit: READ_AT_COMMIT });

const GOV = "kalpamani.governance";

/** A recorded fact, defaulting to the snapshot's as-of where the source records no other. */
const fact = (
  factId: string,
  subject: string,
  state: string,
  options: { readonly asOf?: string; readonly path?: string } = {},
) => ({
  fact_id: factId,
  subject: reason(subject, GOV),
  state: reason(state, GOV),
  as_of: options.asOf ?? SNAPSHOT_AS_OF,
  source: source(options.path ?? CLAUDE_MD),
});

export function qualificationStatusFacts(asOfInstant: string): QualificationStatusPayload {
  return {
    read_at_commit: READ_AT_COMMIT,
    snapshot_extracted_on: SNAPSHOT_EXTRACTED_ON,
    implementation_phase: reason("C4_EXECUTIVE_OVERVIEW_AND_GOVERNANCE", GOV),
    facts: [
      // CLAUDE.md section 6: USD 80,000, AUTHORITATIVE, and separate from broker equity.
      fact("strategy-capital", "KALPAMANI_STRATEGY_CAPITAL_USD", "80000"),

      /*
       * Run A -- a COMMAND OUTCOME, not a provider verdict. Its accounting is recorded
       * because it is the evidence a reader drills into, and because "48 requests completed"
       * and "the provider is qualified" are different statements about the same run.
       */
      fact("run-a", "RUN_A_EMPIRICAL_ACQUISITION", "COMPLETED_ONCE", { asOf: "2026-09-04" }),
      fact("run-a-outcome", "RUN_A_CLOSED_PUBLIC_OUTCOME", "EMPIRICAL_ACQUISITION_COMPLETED", {
        asOf: "2026-09-04",
      }),
      fact("run-a-provider-requests", "RUN_A_PROVIDER_REQUESTS", "48", { asOf: "2026-09-04" }),
      fact("run-a-provider-retries", "RUN_A_PROVIDER_RETRIES", "0", { asOf: "2026-09-04" }),
      fact("run-a-put-object", "RUN_A_LICENSED_S3_PUTOBJECT", "145", { asOf: "2026-09-04" }),
      fact("run-a-head-object", "RUN_A_CONDITIONAL_HEADOBJECT", "0", { asOf: "2026-09-04" }),
      fact("run-a-get-object", "RUN_A_OBJECT_BYTE_GETOBJECT", "0", { asOf: "2026-09-04" }),
      fact("run-a-listings", "RUN_A_LISTING_OPERATIONS", "0", { asOf: "2026-09-04" }),
      fact("run-a-control", "RUN_A_CONTROL_OPERATIONS", "0", { asOf: "2026-09-04" }),
      fact("run-a-identifier", "RUN_A_EXECUTION_IDENTIFIER", "PERMANENTLY_RETIRED", {
        asOf: "2026-09-04",
      }),
      fact("run-a-retry", "RUN_A_RETRY", "NOT_AUTHORIZED"),

      // Everything Run A did NOT establish, recorded as its own fact rather than inferred.
      fact("run-b", "RUN_B", "NOT_AUTHORIZED_NOT_RUN"),
      fact("combined-assessment", "COMBINED_ASSESSMENT", "NOT_AUTHORIZED_NOT_RUN"),
      fact("provider-tests", "PROVIDER_TESTS_P1_TO_P9", "UNEVALUATED"),
      fact("provider-selected", "PRODUCTION_PROVIDER_SELECTION", "NONE"),
      fact("data-quality", "DATA_CORRECTNESS_AND_QUALITY", "NOT_ESTABLISHED"),
      fact("provider-entitlement", "PROVIDER_WIDE_ENTITLEMENT", "UNKNOWN"),
      fact("subscription-entitlement", "SUBSCRIPTION_WIDE_ENTITLEMENT", "UNKNOWN"),
      fact("production-ingestion", "PRODUCTION_INGESTION_BACKFILL_UPDATE", "NOT_AUTHORIZED"),
      fact("third-acquisition", "THIRD_ADR_0017_ACQUISITION", "NOT_AUTHORIZED_NOT_RUN"),
      fact("sixth-preflight", "SIXTH_PRIVATE_BINDING_PREFLIGHT", "NOT_AUTHORIZED_NOT_RUN"),
      fact("infrastructure-mutation", "FURTHER_INFRASTRUCTURE_MUTATION", "NOT_AUTHORIZED"),
      fact("backtesting", "BACKTESTING", "NOT_STARTED"),
      fact("control-publication", "CONTROL_PUBLICATION", "DEFERRED"),

      // The subsystems this Cockpit renders the ABSENCE of.
      fact("brain-runtime", "STRATEGY_BRAIN_RUNTIME", "NOT_IMPLEMENTED_NOT_AUTHORIZED"),
      fact("read-api", "COCKPIT_READ_API_AND_PROJECTIONS", "NOT_IMPLEMENTED_NOT_AUTHORIZED"),
      fact("deployment", "COCKPIT_DEPLOYMENT_AND_REAL_SOURCE_WIRING", "NOT_AUTHORIZED"),

      fact("inc-0002", "INC_0002", "OPEN", {
        path: "docs/incidents/INC-0002-account-binding-digest-exposure.md",
      }),
    ],
    /** Each gate is read INDEPENDENTLY. No blanket statement over all seven is correct. */
    gates: [
      {
        gate: "G1",
        state: "OPEN",
        scope: reason("PROVIDER_SELECTION_AND_QUALIFICATION", GOV),
        source: source(CLAUDE_MD),
      },
      {
        gate: "G2",
        state: "OPEN",
        scope: reason("PRODUCTION_INFORMATION_SET_PROFILE", GOV),
        source: source(CLAUDE_MD),
      },
      {
        gate: "G3",
        state: "CLOSED",
        // Closed for the Sharadar personal-use licence AND NOTHING ELSE.
        scope: reason("SHARADAR_PERSONAL_USE_LICENCE_ONLY", GOV),
        source: source(
          "docs/decisions/ADR-0008-sharadar-personal-use-license-and-private-qualification.md",
        ),
      },
      {
        gate: "G4",
        state: "OPEN",
        scope: reason("ANALYST_ESTIMATES_AND_REVISIONS", GOV),
        source: source(CLAUDE_MD),
      },
      {
        gate: "G5",
        state: "OPEN",
        scope: reason("HISTORICAL_BORROW", GOV),
        source: source(CLAUDE_MD),
      },
      {
        gate: "G6",
        state: "OPEN",
        scope: reason("OPTIONS_OVERLAY", GOV),
        source: source(CLAUDE_MD),
      },
      {
        gate: "G7",
        state: "OPEN",
        scope: reason("STRATEGY_TAXONOMY_EVIDENCE", GOV),
        source: source(CLAUDE_MD),
      },
    ],
    adr_states: [
      {
        adr: "ADR-0005",
        state: reason("PROPOSED", GOV),
        source: source("docs/decisions/ADR-0005-point-in-time-data-architecture.md"),
      },
      {
        adr: "ADR-0018",
        state: reason("ACCEPTED_IN_FORCE", GOV),
        source: source(
          "docs/decisions/ADR-0018-bounded-private-empirical-sharadar-qualification.md",
        ),
      },
      {
        adr: "ADR-0019",
        state: reason("ACCEPTED_IN_FORCE", GOV),
        source: source("docs/decisions/ADR-0019-write-only-acquisition-collision-policy.md"),
      },
      {
        adr: "ADR-0020",
        state: reason("ACCEPTED_IN_FORCE", GOV),
        source: source(
          "docs/decisions/ADR-0020-request-scoped-qualification-payload-identity.md",
        ),
      },
      {
        adr: "ADR-0026",
        state: reason("ACCEPTED_IN_FORCE", GOV),
        source: source("docs/decisions/ADR-0026-strategy-brain-architecture-and-governance.md"),
      },
      {
        adr: "ADR-0027",
        state: reason("ACCEPTED_IN_FORCE", GOV),
        source: source(
          "docs/decisions/ADR-0027-cockpit-and-feedback-architecture-and-governance.md",
        ),
      },
      {
        adr: "ADR-0028",
        state: reason("ACCEPTED_IN_FORCE", GOV),
        source: source(
          "docs/decisions/ADR-0028-cockpit-contract-completion-and-boundary-corrections.md",
        ),
      },
      {
        adr: "ADR-0029",
        state: reason("ACCEPTED_IN_FORCE", GOV),
        source: source(
          "docs/decisions/ADR-0029-valid-zero-values-and-cache-freshness-deadlines.md",
        ),
      },
    ],
    /** P1 to P9. UNEVALUATED is the ONLY state this payload can carry today. */
    provider_tests: (["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"] as const).map(
      (test) => ({ test: reason(test, "kalpamani.provider_tests"), state: "UNEVALUATED" as const }),
    ),
    /**
     * Authorization and date eligibility are TWO SEPARATE FACTS, and PASSING A DATE
     * AUTHORIZES NOTHING.
     */
    run_authorizations: [
      {
        run: reason("RUN_A_RETRY", GOV),
        authorization: reason("NOT_AUTHORIZED", GOV),
        date_gate: absent(
          "NOT_APPLICABLE",
          "NOT_DEFINED_FOR_SUBJECT",
          "governance.run_date_gate",
          "DIMENSIONLESS",
        ),
        date_basis: reason("UTC_CALENDAR_DATE", GOV),
        minimum_separation: absent(
          "NOT_APPLICABLE",
          "NOT_DEFINED_FOR_SUBJECT",
          "governance.minimum_separation",
          "CALENDAR_DAYS",
        ),
        source: source(CLAUDE_MD),
      },
      {
        run: reason("RUN_B", GOV),
        authorization: reason("NOT_AUTHORIZED", GOV),
        /*
         * The earliest APPROVED TARGET, and nothing more. ELIGIBILITY IS NOT PERMISSION.
         *
         * A DATE, carried as one: an earlier revision carried it in `CALENDAR_DAYS`, a unit
         * of DURATION, which stated a count of days nobody measured and rendered a calendar
         * date with a "d" suffix beside it.
         */
        date_gate: available({
          metricId: "governance.run_date_gate",
          unit: "DIMENSIONLESS",
          value: "2026-09-12",
          asOf: asOfInstant,
        }),
        date_basis: reason("UTC_CALENDAR_DATE", GOV),
        /** At least eight calendar days after Run A — a genuine duration, in its own unit. */
        minimum_separation: available({
          metricId: "governance.minimum_separation",
          unit: "CALENDAR_DAYS",
          value: 8,
          asOf: asOfInstant,
        }),
        preceded_by: reason("RUN_A_EMPIRICAL_ACQUISITION", GOV),
        source: source(CLAUDE_MD),
      },
      {
        run: reason("COMBINED_ASSESSMENT", GOV),
        authorization: reason("NOT_AUTHORIZED", GOV),
        /** No date exists: it runs after Run B, and Run B has not run. */
        date_gate: absent(
          "NOT_YET_AVAILABLE",
          "UPSTREAM_INPUT_MISSING",
          "governance.run_date_gate",
          "DIMENSIONLESS",
        ),
        date_basis: reason("UTC_CALENDAR_DATE", GOV),
        minimum_separation: absent(
          "NOT_APPLICABLE",
          "NOT_DEFINED_FOR_SUBJECT",
          "governance.minimum_separation",
          "CALENDAR_DAYS",
        ),
        preceded_by: reason("RUN_B", GOV),
        source: source(CLAUDE_MD),
      },
    ],
    /**
     * The chain standing in front of the next gate, each link a RECORDED STATE.
     *
     * Deliberately a chain and NOT a score. No percentage is computed over these: seven gates
     * of unequal scope and nine unevaluated provider tests do not average into a readiness
     * figure, and any number produced from them would be an invention.
     */
    blockers: [
      {
        blocker_id: "blocker-run-b",
        subject: reason("RUN_B_WRITTEN_AUTHORIZATION", GOV),
        state: reason("NOT_GRANTED", GOV),
        blocks: reason("COMBINED_ASSESSMENT", GOV),
        source: source(CLAUDE_MD),
      },
      {
        blocker_id: "blocker-assessment",
        subject: reason("COMBINED_ASSESSMENT", GOV),
        state: reason("NOT_AUTHORIZED_NOT_RUN", GOV),
        blocks: reason("PROVIDER_TESTS_P1_TO_P9", GOV),
        source: source(CLAUDE_MD),
      },
      {
        blocker_id: "blocker-p-tests",
        subject: reason("PROVIDER_TESTS_P1_TO_P9", GOV),
        state: reason("UNEVALUATED", GOV),
        blocks: reason("G1_PROVIDER_SELECTION", GOV),
        source: source(CLAUDE_MD),
      },
      {
        blocker_id: "blocker-provider",
        subject: reason("PRODUCTION_PROVIDER_SELECTION", GOV),
        state: reason("NONE", GOV),
        blocks: reason("BACKTESTING", GOV),
        source: source(CLAUDE_MD),
      },
      {
        blocker_id: "blocker-phase-3",
        subject: reason("PHASE_3_POINT_IN_TIME_DATA_FOUNDATION", GOV),
        state: reason("NOT_COMPLETE", GOV),
        blocks: reason("STRATEGY_BRAIN_RUNTIME", GOV),
        source: source(CLAUDE_MD),
      },
    ],
    /**
     * The next governance event — what must happen, never when it will.
     *
     * Every event in this chain is a human decision, and the Cockpit takes none of them.
     */
    next_required_event: {
      event: reason("RUN_B_WRITTEN_AUTHORIZATION", GOV),
      actor: reason("OWNER", GOV),
      prerequisite: reason("EARLIEST_TARGET_DATE_REACHED_AND_SEPARATE_WRITTEN_DECISION", GOV),
      source: source(CLAUDE_MD),
    },
    phase_state: reason("PHASE_3_NOT_COMPLETE", GOV),
    live_trading: reason("HARD_DISABLED", GOV),
  };
}
