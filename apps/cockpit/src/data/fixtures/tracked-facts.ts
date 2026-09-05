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
 * A historical success carries its as-of time, and CURRENT RUNTIME HEALTH IS NEVER CLAIMED
 * FROM A PAST QUALIFICATION SUCCESS (ADR-0027 §5).
 */
import type { QualificationStatusPayload } from "@/contracts/read-models";

import { absent, available, reason } from "@/contracts/factories";

/** The repository revision every fact below was read from. */
export const READ_AT_COMMIT = "8950c07dd97b3e54c9db423bd3d66378b6d47889";

/** The date the snapshot was transcribed. Facts age from here. */
export const SNAPSHOT_AS_OF = "2026-09-05";

const CLAUDE_MD = "CLAUDE.md";
const source = (path: string) => ({ path, commit: READ_AT_COMMIT });

const GOV = "kalpamani.governance";

export function qualificationStatusFacts(asOfInstant: string): QualificationStatusPayload {
  return {
    read_at_commit: READ_AT_COMMIT,
    facts: [
      {
        // CLAUDE.md section 6: USD 80,000, AUTHORITATIVE, and separate from broker equity.
        fact_id: "strategy-capital",
        subject: reason("KALPAMANI_STRATEGY_CAPITAL_USD", GOV),
        state: reason("80000", GOV),
        as_of: SNAPSHOT_AS_OF,
        source: source(CLAUDE_MD),
      },
      {
        fact_id: "run-a",
        subject: reason("RUN_A_EMPIRICAL_ACQUISITION", GOV),
        state: reason("COMPLETED_ONCE", GOV),
        as_of: "2026-09-04",
        source: source(CLAUDE_MD),
      },
      {
        fact_id: "run-a-retry",
        subject: reason("RUN_A_RETRY", GOV),
        state: reason("NOT_AUTHORIZED", GOV),
        as_of: SNAPSHOT_AS_OF,
        source: source(CLAUDE_MD),
      },
      {
        fact_id: "provider-selected",
        subject: reason("PRODUCTION_PROVIDER_SELECTION", GOV),
        state: reason("NONE", GOV),
        as_of: SNAPSHOT_AS_OF,
        source: source(CLAUDE_MD),
      },
      {
        fact_id: "data-quality",
        subject: reason("DATA_CORRECTNESS_AND_QUALITY", GOV),
        state: reason("NOT_ESTABLISHED", GOV),
        as_of: SNAPSHOT_AS_OF,
        source: source(CLAUDE_MD),
      },
      {
        fact_id: "backtesting",
        subject: reason("BACKTESTING", GOV),
        state: reason("NOT_STARTED", GOV),
        as_of: SNAPSHOT_AS_OF,
        source: source(CLAUDE_MD),
      },
      {
        fact_id: "control-publication",
        subject: reason("CONTROL_PUBLICATION", GOV),
        state: reason("DEFERRED", GOV),
        as_of: SNAPSHOT_AS_OF,
        source: source(CLAUDE_MD),
      },
      {
        fact_id: "inc-0002",
        subject: reason("INC_0002", GOV),
        state: reason("OPEN", GOV),
        as_of: SNAPSHOT_AS_OF,
        source: source("docs/incidents/INC-0002-account-binding-digest-exposure.md"),
      },
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
        adr: "ADR-0026",
        state: reason("ACCEPTED_IN_FORCE", GOV),
        source: source(
          "docs/decisions/ADR-0026-strategy-brain-architecture-and-governance.md",
        ),
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
          "CALENDAR_DAYS",
        ),
        source: source(CLAUDE_MD),
      },
      {
        run: reason("RUN_B", GOV),
        authorization: reason("NOT_AUTHORIZED", GOV),
        // The earliest APPROVED TARGET. Eligibility is not permission.
        date_gate: available({
          metricId: "governance.run_b_earliest_target",
          unit: "CALENDAR_DAYS",
          value: "2026-09-12",
          asOf: asOfInstant,
        }),
        source: source(CLAUDE_MD),
      },
      {
        run: reason("COMBINED_ASSESSMENT", GOV),
        authorization: reason("NOT_AUTHORIZED", GOV),
        date_gate: absent(
          "NOT_YET_AVAILABLE",
          "UPSTREAM_INPUT_MISSING",
          "governance.run_date_gate",
          "CALENDAR_DAYS",
        ),
        source: source(CLAUDE_MD),
      },
    ],
    phase_state: reason("PHASE_3_NOT_COMPLETE", GOV),
    live_trading: reason("HARD_DISABLED", GOV),
  };
}
