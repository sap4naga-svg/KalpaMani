/**
 * Reference navigation — `read-model-contracts.md` §4.3.1, under ADR-0030 R10.
 *
 * A destination comes from a **closed allowlist keyed by `RefKind`**, and an unknown or
 * unmapped kind yields **no link** — never a guess, never a nearest match, never a first row.
 *
 * ```text
 * PERMITTED   an allowlisted INTERNAL route TEMPLATE selected by RefKind, into which a
 *             ref_id already validated as SafeId is interpolated as a single ENCODED path
 *             segment, and nothing else is interpolated
 * REFUSED     a free-form or absolute URL, any external origin, any destination derived from
 *             free text, a title, a label or other untrusted content
 * REFUSED     a generic resolver, a proxy, an unrestricted fetcher, or a guess for an
 *             unmapped kind
 * ```
 *
 * **A safe allowlisted route template is not a constructed URL, and that distinction is the
 * whole rule.** The allowlist IS keyed by `ref_kind`, and a candidate links a trade by
 * interpolating its `ref_id` into `/portfolio/trades/{ref_id}`: ordinary dynamic internal
 * navigation is not the hazard.
 *
 * Three route maps used to live in three files — two duplicated `EVIDENCE_DESTINATION`
 * literals and one hand-written link. **A closed allowlist that exists in three copies is
 * three allowlists**, so they are one here.
 */
import type { RefKind } from "@/contracts/vocabularies";
import { REFERENCE_FIELDS } from "@/contracts/references";
import type { HostFieldDeclaration, HostFieldKey } from "@/contracts/references";

export interface ReferenceDestination {
  readonly href: string;
  readonly label: string;
}

/** A route into an area that owns a kind, with no per-entity segment. */
interface AreaRoute {
  readonly kind: "AREA";
  readonly path: string;
  readonly label: string;
}

/** A route to ONE entity, whose single encoded path segment is the reference's `ref_id`. */
interface EntityRoute {
  readonly kind: "ENTITY";
  /** Exactly one `{id}` placeholder, and nothing else is ever interpolated. */
  readonly template: `${string}{id}${string}`;
  readonly label: string;
}

type AllowedRoute = AreaRoute | EntityRoute;

/**
 * The allowlist. A kind absent from it has NO destination, and that is deliberate.
 *
 * `brain_decision` is absent on purpose. Its target is the journaled decision status NESTED
 * inside `CandidateDetail`, so the reference carries the DECISION's identifier while the
 * route needs the CONTAINER's candidate id (R8). Interpolating a decision id into the
 * candidate route would navigate to a candidate that does not exist, and substituting the
 * container's id into the reference would compare a decision to the record that carries it.
 * The container route is recorded on the field's `nested` declaration instead, and a host
 * that holds the container id passes it explicitly through `nestedDestination`.
 */
const ROUTES: Partial<Readonly<Record<RefKind, AllowedRoute>>> = {
  candidate: {
    kind: "ENTITY",
    template: "/signals/candidates/{id}",
    label: "Candidate",
  },
  trade: {
    kind: "ENTITY",
    template: "/portfolio/trades/{id}",
    label: "Trade",
  },
  data_quality: { kind: "AREA", path: "/system/data-quality", label: "Data quality" },
  health_transition: { kind: "AREA", path: "/strategy/health", label: "Strategy health" },
  reconciliation: { kind: "AREA", path: "/execution/reconciliation", label: "Reconciliation" },
  execution_quality: { kind: "AREA", path: "/execution/quality", label: "Execution quality" },
  alert: { kind: "AREA", path: "/system/alerts", label: "Alerts" },
  incident: { kind: "AREA", path: "/system/operations", label: "Operations" },
  source_fact: { kind: "AREA", path: "/governance/audit", label: "Audit trail" },
  audit_event: { kind: "AREA", path: "/governance/audit", label: "Audit trail" },
  regime_context: { kind: "AREA", path: "/market/regime", label: "Market regime" },
  strategy_version: { kind: "AREA", path: "/strategy/versions", label: "Strategy versions" },
  research_run: { kind: "AREA", path: "/research/runs", label: "Research runs" },
  registration: { kind: "AREA", path: "/research/hypotheses", label: "Hypotheses" },
  queue_item: { kind: "AREA", path: "/research/queue", label: "Research queue" },
  packet: { kind: "AREA", path: "/governance/packets", label: "Governance packets" },
  decision: { kind: "AREA", path: "/governance/audit", label: "Decisions" },
};

/**
 * `SafeId` as `values.ts` defines it, re-stated as a guard at the navigation boundary.
 *
 * The schema already refused anything else at admission; this is the belt at the point of
 * interpolation, because a route built from an unvalidated identifier is the hazard R10
 * exists to close, and depending on a check three modules away is how that goes wrong.
 */
const SAFE_ID = /^[a-z0-9][a-z0-9._:-]*$/i;

/**
 * The destination for a reference, or `null` where the allowlist maps its kind to none.
 *
 * `null` is a legitimate answer and NEVER a fallback: an unmapped kind, or an identifier that
 * is not a `SafeId`, produces no link at all rather than a misleading one.
 */
export function referenceDestination(reference: {
  readonly ref_kind: string;
  readonly ref_id: string;
}): ReferenceDestination | null {
  const route = ROUTES[reference.ref_kind as RefKind];
  if (route === undefined) {
    return null;
  }
  if (route.kind === "AREA") {
    return { href: route.path, label: route.label };
  }
  if (!SAFE_ID.test(reference.ref_id)) {
    return null;
  }
  return {
    href: route.template.replace("{id}", encodeURIComponent(reference.ref_id)),
    label: route.label,
  };
}

/**
 * The destination for a NESTED target, whose container id the host supplies (R8).
 *
 * The reference's own `ref_id` identifies the nested entity and is deliberately NOT
 * interpolated: the container id is, as a single encoded path segment, and the caller has to
 * hand it over explicitly because no rule can derive it from the reference.
 */
export function nestedDestination(
  key: HostFieldKey,
  containerId: string,
  label: string,
): ReferenceDestination | null {
  const declaration: HostFieldDeclaration = REFERENCE_FIELDS[key];
  const nested = declaration.nested;
  if (nested === undefined || !SAFE_ID.test(containerId)) {
    return null;
  }
  const segment = nested.containerRoute.replace(/\{[a-z_]+\}/, encodeURIComponent(containerId));
  return { href: segment, label };
}

/** Every kind the allowlist maps, for the tests that assert it is closed. */
export const NAVIGABLE_KINDS: readonly RefKind[] = Object.keys(ROUTES) as RefKind[];
