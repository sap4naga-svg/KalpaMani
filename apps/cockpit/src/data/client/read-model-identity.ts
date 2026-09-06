/**
 * Read-model identity — what a response IS, independently of what a viewer selected.
 *
 * A cache key must describe the ACTUAL read-model source (`read-model-contracts.md` §7):
 * `api_version`, `schema_version`, environment, source provenance, access scope,
 * classification and every query parameter. **An environment or provenance omitted from a
 * cache key is a cross-environment leak waiting to happen** — and a provenance DERIVED FROM
 * THE SELECTOR rather than from the source is the same defect wearing the right shape.
 *
 * The scenario selector is not the provenance. `QualificationStatus` reads REAL tracked
 * governance facts in BOTH scenarios, so labelling its cache entry `SYNTHETIC` because the
 * demo scenario is selected states the opposite of the truth; the three operational read
 * models are fixture-adapter output in BOTH scenarios, so labelling them
 * `REPOSITORY_TRACKED` in project scope does the same in the other direction.
 *
 * Provenance is therefore a property of the read model here, exactly as it is in the
 * envelope the adapter produces, and the two are asserted to agree.
 */
import {
  ATTENTION_LIST_SCHEMA,
  EXECUTIVE_OVERVIEW_SCHEMA,
  QUALIFICATION_STATUS_SCHEMA,
  WHAT_CHANGED_SCHEMA,
} from "@/contracts/read-models";
import type { DataClassification, DataProvenance } from "@/contracts/vocabularies";

export interface ReadModelIdentity {
  /** The §7.1 admission name. */
  readonly readModel: string;
  /** The stable cache-key name. */
  readonly queryName: string;
  readonly schemaVersion: string;
  /** Where the numbers COME FROM, never which scenario was selected. */
  readonly provenance: DataProvenance;
  readonly classification: DataClassification;
  /** Which authorization a caller needed — part of the key, so two scopes never share one. */
  readonly accessScope: string;
}

/**
 * Fixture-adapter output in BOTH scenarios: populated in demo, and an absence in project
 * scope. §7.1 admits `REPOSITORY_TRACKED` only from the enumerated governance read models,
 * and this is not one of them.
 */
export const EXECUTIVE_OVERVIEW_IDENTITY: ReadModelIdentity = {
  readModel: "ExecutiveOverview",
  queryName: "executive-overview",
  schemaVersion: EXECUTIVE_OVERVIEW_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "executive:read",
};

export const ATTENTION_IDENTITY: ReadModelIdentity = {
  readModel: "AttentionItem",
  queryName: "attention",
  schemaVersion: ATTENTION_LIST_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "executive:read",
};

export const WHAT_CHANGED_IDENTITY: ReadModelIdentity = {
  readModel: "WhatChangedEntry",
  queryName: "what-changed",
  schemaVersion: WHAT_CHANGED_SCHEMA,
  provenance: "SYNTHETIC",
  classification: "PUBLIC_SAFE",
  accessScope: "executive:read",
};

/**
 * The one read model whose facts are REAL in both scenarios. They are `REPOSITORY_TRACKED`
 * and are never relabelled `SYNTHETIC` to fit a scenario selector (§2.2).
 */
export const QUALIFICATION_IDENTITY: ReadModelIdentity = {
  readModel: "QualificationStatus",
  queryName: "qualification-status",
  schemaVersion: QUALIFICATION_STATUS_SCHEMA,
  provenance: "REPOSITORY_TRACKED",
  classification: "PUBLIC_SAFE",
  accessScope: "governance:read",
};

export const READ_MODEL_IDENTITIES: readonly ReadModelIdentity[] = [
  EXECUTIVE_OVERVIEW_IDENTITY,
  ATTENTION_IDENTITY,
  WHAT_CHANGED_IDENTITY,
  QUALIFICATION_IDENTITY,
];
