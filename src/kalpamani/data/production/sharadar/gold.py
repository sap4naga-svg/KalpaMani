"""Quality checks and the Gold layer -- ADR-0035 §3.6, §3.7 and §3.8, as accepted.

**What a build serves is decided by ``as_of``, per row version.** A row version is
served only when its governing availability is ``<= as_of``; among the admissible
versions of one key the latest governs, earlier admissible versions are superseded, and
versions bounded after ``as_of`` are excluded by time. The counts of all three are
recorded per dataset, so a manifest states how many revisions it admitted and how many
it excluded -- and a served row whose bound is later than ``as_of`` can never exist,
because the manifest emission re-checks every served row and refuses the build if one
does (T-1).

**Adjustment is ``SPLIT_ONLY`` under ``FORWARD_BASE_NORMALIZED``**, the one policy and
the one convention the accepted arithmetic computes (``curate/adjustment.py``): the
cumulative factor of splits with an ex-date on or before the session re-expresses the
bar in the terms of the series' earliest bar, so settled history is never rewritten by a
later action. The vendor's ``closeadj`` is **evidence, not an input**: it is reconciled
against the repository's reconstruction and never served as the adjusted series.
**Spinoffs are never adjusted for**: a security with a spinoff ex-date on or before
``as_of`` has its adjusted artifact excluded from that session onward, and is flagged
``UNRESOLVED_CORPORATE_ACTION`` (build-local; ADR-0039). Announcement-based use of any
action is gated, and nothing here reads an announcement.

**The quality plan is a closed, versioned list**, and ``checks_run`` plus
``checks_not_run`` together equal it exactly. A BLOCKING finding scoped to a security
excludes that security from Gold; a BLOCKING finding scoped to the build refuses
publication altogether. A WARNING is recorded, with counts. Cross-provider verification
has no second source, so every build carries ``SINGLE_SOURCE_UNVERIFIED``.

**A valid empty result is not a readiness claim.** A Gold layer may legitimately hold
zero adjusted bars and zero members -- every row excluded by time, every attribute
unavailable -- and it says so with a reason, never as success at anything.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum
from typing import Any, Final

from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.vocabulary import (
    AdjustmentConvention,
    AdjustmentPolicy,
    LimitationToken,
    ProviderBoundDerivation,
)
from kalpamani.data.curate.adjustment import require_supported_convention
from kalpamani.data.ingest.sharadar.datasets import SharadarDataset
from kalpamani.data.production.sharadar.availability import (
    EXPRESSIBLE_DERIVATIONS,
    ResolvedLayer,
    ResolvedRow,
)
from kalpamani.data.production.sharadar.sessions import SessionCalendar
from kalpamani.data.production.sharadar.universe import (
    ACTION_DELISTED,
    ACTION_SPINOFF,
    ACTION_SPLIT,
    UniverseSnapshot,
)
from kalpamani.data.qualify.sharadar.parser import date_field, decimal_field

#: The quality plan version and the adjustment policy this build applies.
QUALITY_PLAN_VERSION: Final = "breakout-long-ingest-v1"
ADJUSTMENT_POLICY: Final = AdjustmentPolicy.SPLIT_ONLY
ADJUSTMENT_CONVENTION: Final = AdjustmentConvention.FORWARD_BASE_NORMALIZED

#: The accepted arithmetic's price quantum, matched exactly.
PRICE_QUANTUM: Final = Decimal("0.000001")

#: A close-to-close move beyond this ratio, without a split on the session, is flagged.
DEFAULT_JUMP_RATIO: Final = Decimal("2")

#: Relative tolerance for the vendor ``closeadj`` reconciliation.
DEFAULT_RECONCILIATION_TOLERANCE: Final = Decimal("0.001")


class Severity(StrEnum):
    """The severity the plan assigns a check. Closed."""

    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"


class QualityCheck(StrEnum):
    """Every check the plan names. Closed; the plan is this list and nothing else."""

    STRUCTURAL_DECODE = "STRUCTURAL_DECODE"
    STRUCTURAL_SCHEMA_ACCEPTED = "STRUCTURAL_SCHEMA_ACCEPTED"
    STRUCTURAL_ROW_CONFLICT = "STRUCTURAL_ROW_CONFLICT"
    COMPLETENESS_DELIVERY_TRUNCATED = "COMPLETENESS_DELIVERY_TRUNCATED"
    COMPLETENESS_PLANNED_REQUESTS = "COMPLETENESS_PLANNED_REQUESTS"
    COMPLETENESS_SESSION_ROW_BAND = "COMPLETENESS_SESSION_ROW_BAND"
    TEMPORAL_SESSION_ON_CALENDAR = "TEMPORAL_SESSION_ON_CALENDAR"
    TEMPORAL_NO_SESSION_AFTER_T_MINUS_1 = "TEMPORAL_NO_SESSION_AFTER_T_MINUS_1"
    TEMPORAL_ONE_BOUND_DERIVATION = "TEMPORAL_ONE_BOUND_DERIVATION"
    TEMPORAL_ORDERING_INVARIANT = "TEMPORAL_ORDERING_INVARIANT"
    TEMPORAL_REVISION_OWN_BOUND = "TEMPORAL_REVISION_OWN_BOUND"
    TEMPORAL_MEMBERSHIP_NO_SESSION_D_BAR = "TEMPORAL_MEMBERSHIP_NO_SESSION_D_BAR"
    MARKET_OHLC_CONSISTENT = "MARKET_OHLC_CONSISTENT"
    MARKET_VOLUME_NON_NEGATIVE = "MARKET_VOLUME_NON_NEGATIVE"
    MARKET_ZERO_VOLUME_RUN = "MARKET_ZERO_VOLUME_RUN"
    MARKET_JUMP_WITHOUT_SPLIT = "MARKET_JUMP_WITHOUT_SPLIT"
    MARKET_MISSING_SESSIONS = "MARKET_MISSING_SESSIONS"
    IDENTITY_ONE_PERMATICKER_PER_SYMBOL = "IDENTITY_ONE_PERMATICKER_PER_SYMBOL"
    IDENTITY_BAR_WITHIN_LISTING_BOUNDS = "IDENTITY_BAR_WITHIN_LISTING_BOUNDS"
    IDENTITY_TICKER_CHANGE_CONSISTENT = "IDENTITY_TICKER_CHANGE_CONSISTENT"
    IDENTITY_DELISTING_VS_LAST_BAR = "IDENTITY_DELISTING_VS_LAST_BAR"
    ADJUSTMENT_RECONCILIATION = "ADJUSTMENT_RECONCILIATION"
    ADJUSTMENT_SPINOFF_FLAGGED = "ADJUSTMENT_SPINOFF_FLAGGED"
    CENSUS_HISTORY_ADMISSIBILITY = "CENSUS_HISTORY_ADMISSIBILITY"
    CROSS_PROVIDER = "CROSS_PROVIDER"


#: The plan: every check and its severity. Total; a test asserts it.
QUALITY_PLAN: Final[dict[QualityCheck, Severity]] = {
    QualityCheck.STRUCTURAL_DECODE: Severity.BLOCKING,
    QualityCheck.STRUCTURAL_SCHEMA_ACCEPTED: Severity.BLOCKING,
    QualityCheck.STRUCTURAL_ROW_CONFLICT: Severity.BLOCKING,
    QualityCheck.COMPLETENESS_DELIVERY_TRUNCATED: Severity.BLOCKING,
    QualityCheck.COMPLETENESS_PLANNED_REQUESTS: Severity.BLOCKING,
    QualityCheck.COMPLETENESS_SESSION_ROW_BAND: Severity.WARNING,
    QualityCheck.TEMPORAL_SESSION_ON_CALENDAR: Severity.BLOCKING,
    QualityCheck.TEMPORAL_NO_SESSION_AFTER_T_MINUS_1: Severity.BLOCKING,
    QualityCheck.TEMPORAL_ONE_BOUND_DERIVATION: Severity.BLOCKING,
    QualityCheck.TEMPORAL_ORDERING_INVARIANT: Severity.BLOCKING,
    QualityCheck.TEMPORAL_REVISION_OWN_BOUND: Severity.BLOCKING,
    QualityCheck.TEMPORAL_MEMBERSHIP_NO_SESSION_D_BAR: Severity.BLOCKING,
    QualityCheck.MARKET_OHLC_CONSISTENT: Severity.WARNING,
    QualityCheck.MARKET_VOLUME_NON_NEGATIVE: Severity.WARNING,
    QualityCheck.MARKET_ZERO_VOLUME_RUN: Severity.WARNING,
    QualityCheck.MARKET_JUMP_WITHOUT_SPLIT: Severity.WARNING,
    QualityCheck.MARKET_MISSING_SESSIONS: Severity.WARNING,
    QualityCheck.IDENTITY_ONE_PERMATICKER_PER_SYMBOL: Severity.BLOCKING,
    QualityCheck.IDENTITY_BAR_WITHIN_LISTING_BOUNDS: Severity.WARNING,
    QualityCheck.IDENTITY_TICKER_CHANGE_CONSISTENT: Severity.WARNING,
    QualityCheck.IDENTITY_DELISTING_VS_LAST_BAR: Severity.WARNING,
    QualityCheck.ADJUSTMENT_RECONCILIATION: Severity.WARNING,
    QualityCheck.ADJUSTMENT_SPINOFF_FLAGGED: Severity.BLOCKING,
    QualityCheck.CENSUS_HISTORY_ADMISSIBILITY: Severity.INFO,
    QualityCheck.CROSS_PROVIDER: Severity.INFO,
}

#: Checks the plan names and this build cannot run: no prior-session band exists for a
#: first build, ticker-change history is not built, and there is no second provider.
CHECKS_NOT_RUN: Final[frozenset[QualityCheck]] = frozenset(
    {
        QualityCheck.COMPLETENESS_SESSION_ROW_BAND,
        QualityCheck.MARKET_ZERO_VOLUME_RUN,
        QualityCheck.IDENTITY_TICKER_CHANGE_CONSISTENT,
        QualityCheck.CROSS_PROVIDER,
    }
)

#: The scope token for a finding that concerns the whole build.
BUILD_SCOPE: Final = "build"


class GoldDefect(StrEnum):
    """Why the Gold layer was refused. Closed."""

    REFUSED_TIMING = "REFUSED_TIMING"
    REFUSED_QUALITY = "REFUSED_QUALITY"


class GoldError(Exception):
    """One closed defect, raised ``from None``."""

    __slots__ = ("defect",)

    def __init__(self, defect: GoldDefect) -> None:
        if type(defect) is not GoldDefect:
            raise TypeError("defect must be an exact GoldDefect member")
        self.defect = defect
        super().__init__(f"gold refused: {defect.value}")


@dataclass(frozen=True, slots=True, kw_only=True)
class Finding:
    """One quality finding: a check, its severity, a scope and a count. No value."""

    check: QualityCheck
    severity: Severity
    scope: str
    count: int

    def __repr__(self) -> str:
        """Check, severity and count. **Never the scope**, which may be an identity."""
        return f"Finding({self.check.value}, {self.severity.value}, count={self.count})"

    def document(self) -> dict[str, Any]:
        """The closed finding document."""
        return {
            "check": self.check.value,
            "severity": self.severity.value,
            "scope": self.scope,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class QualityReport:
    """Every check run or not run, every finding, and what they block."""

    plan_version: str
    checks_run: tuple[QualityCheck, ...]
    checks_not_run: tuple[QualityCheck, ...]
    findings: tuple[Finding, ...]
    blocked_securities: tuple[str, ...]
    build_blocking: bool

    def __post_init__(self) -> None:
        if set(self.checks_run) | set(self.checks_not_run) != set(QualityCheck):
            raise ValueError("checks_run and checks_not_run together equal the plan exactly")
        if set(self.checks_run) & set(self.checks_not_run):
            raise ValueError("a check is run or not run, never both")

    def __repr__(self) -> str:
        """Counts only."""
        return (
            f"QualityReport(findings={len(self.findings)}, "
            f"blocked={len(self.blocked_securities)}, build_blocking={self.build_blocking})"
        )

    def document(self) -> dict[str, Any]:
        """The closed report document. Identities appear in scopes; the manifest is LICENSED."""
        return {
            "plan_version": self.plan_version,
            "checks_run": [check.value for check in self.checks_run],
            "checks_not_run": [check.value for check in self.checks_not_run],
            "findings": [finding.document() for finding in self.findings],
            "blocked_securities": list(self.blocked_securities),
            "build_blocking": self.build_blocking,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ServedCounts:
    """Per dataset: how many row versions ``as_of`` admitted, superseded and excluded."""

    dataset: str
    revisions_admitted: int
    revisions_superseded: int
    revisions_excluded_by_time: int

    def document(self) -> dict[str, Any]:
        """The manifest entry."""
        return {
            "dataset": self.dataset,
            "revisions_admitted": self.revisions_admitted,
            "revisions_superseded": self.revisions_superseded,
            "revisions_excluded_by_time": self.revisions_excluded_by_time,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class GoldArtifact:
    """One deterministic Gold artifact: canonical bytes and their digest."""

    name: str
    content: bytes
    sha256: str
    row_count: int

    def __repr__(self) -> str:
        """Name and count. **Never the bytes.**"""
        return f"GoldArtifact(name={self.name!r}, rows={self.row_count})"


@dataclass(frozen=True, slots=True, kw_only=True)
class GoldLayer:
    """The Gold artifacts of one build, the Silver artifacts served, and what they rest on."""

    as_of: datetime
    served: tuple[ServedCounts, ...]
    silver_artifacts: tuple[GoldArtifact, ...]
    gold_artifacts: tuple[GoldArtifact, ...]
    quality: QualityReport
    limitations: tuple[LimitationToken, ...]
    spinoff_excluded_securities: tuple[str, ...]
    empty_reason: str | None

    def __repr__(self) -> str:
        """Counts only."""
        return (
            f"GoldLayer(silver={len(self.silver_artifacts)}, gold={len(self.gold_artifacts)}, "
            f"empty_reason={self.empty_reason!r})"
        )

    @property
    def is_empty(self) -> bool:
        """Whether the build served no adjusted bar and admitted no member -- valid, and
        not readiness. Membership rows recording exclusions may still exist."""
        return self.empty_reason is not None


@dataclass(frozen=True, slots=True, kw_only=True)
class _Served:
    rows: dict[str, dict[tuple[str, ...], ResolvedRow]]
    counts: tuple[ServedCounts, ...]


def _serve(layer: ResolvedLayer, *, as_of: datetime) -> _Served:
    """The latest admissible version per key, per dataset, and the counts."""
    served: dict[str, dict[tuple[str, ...], ResolvedRow]] = {}
    counts: list[ServedCounts] = []
    for dataset in (
        SharadarDataset.TICKERS.value,
        SharadarDataset.STOCKS.value,
        SharadarDataset.ACTIONS.value,
    ):
        by_key: dict[tuple[str, ...], list[ResolvedRow]] = {}
        for row in layer.by_dataset(dataset):
            by_key.setdefault(row.row.row_key, []).append(row)
        chosen: dict[tuple[str, ...], ResolvedRow] = {}
        admitted = superseded = excluded = 0
        for key in sorted(by_key):
            admissible = [row for row in by_key[key] if row.availability.governing_time <= as_of]
            excluded += len(by_key[key]) - len(admissible)
            if not admissible:
                continue
            latest = max(
                admissible,
                key=lambda row: (row.availability.governing_time, row.row.revision_sequence),
            )
            chosen[key] = latest
            admitted += 1
            superseded += len(admissible) - 1
        served[dataset] = chosen
        counts.append(
            ServedCounts(
                dataset=dataset,
                revisions_admitted=admitted,
                revisions_superseded=superseded,
                revisions_excluded_by_time=excluded,
            )
        )
    return _Served(rows=served, counts=tuple(counts))


def verify_served_rows(rows: Iterable[ResolvedRow], *, as_of: datetime) -> None:
    """Refuse if any served row is bounded after ``as_of``, labelled with a derivation the
    contract cannot express, or bounded later than its own first-seen instant.

    Applied to every served row before Gold is assembled and again at manifest
    emission: a row served under a time established only for another version is a
    fact nobody could have held (ADR-0035 §3.9, T-1).

    Raises:
        GoldError: ``REFUSED_TIMING``.
    """
    for row in rows:
        if row.availability.governing_time > as_of:
            raise GoldError(GoldDefect.REFUSED_TIMING)
        if row.availability.provider_bound_derivation not in EXPRESSIBLE_DERIVATIONS:
            raise GoldError(GoldDefect.REFUSED_TIMING)
        if row.availability.provider_available_upper_bound > row.row.system_first_seen_time:
            raise GoldError(GoldDefect.REFUSED_TIMING)


def _verify_served_timing(served: _Served, *, as_of: datetime) -> None:
    for rows in served.rows.values():
        verify_served_rows(rows.values(), as_of=as_of)


def _price(value: Decimal) -> Decimal:
    return value.quantize(PRICE_QUANTUM, rounding=ROUND_HALF_EVEN)


def _split_factors(actions: list[ResolvedRow]) -> list[tuple[date, Decimal]]:
    factors: list[tuple[date, Decimal]] = []
    for row in actions:
        if row.row.fields.get("action") != ACTION_SPLIT:
            continue
        when = date_field(row.row.fields.get("date"))
        ratio = decimal_field(row.row.fields.get("value"))
        if when is None or ratio is None or ratio <= 0:
            continue
        factors.append((when, ratio))
    return sorted(factors)


def _factor(factors: list[tuple[date, Decimal]], session: date) -> Decimal:
    """The cumulative factor for ``session``: every split with an ex-date on or before it."""
    factor = Decimal(1)
    for when, ratio in factors:
        if session >= when:
            factor *= ratio
    return factor


class _Checks:
    """Accumulates findings and blocked scopes."""

    __slots__ = ("build_blocking", "findings", "run", "securities")

    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.securities: set[str] = set()
        self.build_blocking = False
        self.run: set[QualityCheck] = set()

    def ran(self, *checks: QualityCheck) -> None:
        self.run.update(checks)

    def finding(
        self, check: QualityCheck, *, scope: str, count: int, blocks_scope: bool = True
    ) -> None:
        self.run.add(check)
        if count <= 0:
            return
        severity = QUALITY_PLAN[check]
        self.findings.append(Finding(check=check, severity=severity, scope=scope, count=count))
        if severity is Severity.BLOCKING and blocks_scope:
            if scope == BUILD_SCOPE:
                self.build_blocking = True
            else:
                self.securities.add(scope)


def _bars_by_security(
    served: _Served,
) -> dict[str, list[tuple[date, ResolvedRow]]]:
    out: dict[str, list[tuple[date, ResolvedRow]]] = {}
    for row in served.rows[SharadarDataset.STOCKS.value].values():
        session = date_field(row.row.fields.get("date"))
        if session is None:
            continue
        out.setdefault(row.row.security_id, []).append((session, row))
    for bars in out.values():
        bars.sort(key=lambda item: item[0])
    return out


def _actions_by_security(served: _Served) -> dict[str, list[ResolvedRow]]:
    out: dict[str, list[ResolvedRow]] = {}
    for row in served.rows[SharadarDataset.ACTIONS.value].values():
        out.setdefault(row.row.security_id, []).append(row)
    return out


def _run_checks(
    served: _Served,
    *,
    universe: UniverseSnapshot,
    calendar: SessionCalendar,
    as_of: datetime,
    identity_blocking: int,
    jump_ratio: Decimal,
    tolerance: Decimal,
) -> tuple[QualityReport, dict[str, date]]:
    """Every check the build runs, over the served rows. Returns the report and the
    per-security spinoff exclusion date."""
    checks = _Checks()
    # Every check the build runs is run -- over an empty set when there is nothing to
    # check -- so an empty result still reports the whole plan honestly.
    checks.ran(*(check for check in QUALITY_PLAN if check not in CHECKS_NOT_RUN))
    # Structural and completeness checks are enforced by refusal upstream (the parser,
    # the schema set, the same-run conflict rule, the truncation rule, the validated
    # locator); they ran, and a build that reaches here has zero findings from them.
    checks.ran(
        QualityCheck.STRUCTURAL_DECODE,
        QualityCheck.STRUCTURAL_SCHEMA_ACCEPTED,
        QualityCheck.STRUCTURAL_ROW_CONFLICT,
        QualityCheck.COMPLETENESS_DELIVERY_TRUNCATED,
        QualityCheck.COMPLETENESS_PLANNED_REQUESTS,
        QualityCheck.TEMPORAL_ONE_BOUND_DERIVATION,
        QualityCheck.TEMPORAL_ORDERING_INVARIANT,
        QualityCheck.TEMPORAL_REVISION_OWN_BOUND,
        QualityCheck.TEMPORAL_MEMBERSHIP_NO_SESSION_D_BAR,
    )
    # Identity ambiguity is blocking for the affected symbols' rows, which normalization
    # already excluded (ADR-0035 §3.5); it is recorded with its count and blocks
    # nothing further.
    checks.ran(QualityCheck.IDENTITY_ONE_PERMATICKER_PER_SYMBOL)
    if identity_blocking:
        checks.findings.append(
            Finding(
                check=QualityCheck.IDENTITY_ONE_PERMATICKER_PER_SYMBOL,
                severity=Severity.BLOCKING,
                scope="symbols-excluded",
                count=identity_blocking,
            )
        )
    # Membership never reads session d's bar: verified from the rows themselves.
    for membership in universe.rows:
        if any(
            bar.startswith(membership.session_date.isoformat()) for bar in membership.bars_consumed
        ):
            checks.finding(
                QualityCheck.TEMPORAL_MEMBERSHIP_NO_SESSION_D_BAR, scope=BUILD_SCOPE, count=1
            )
    bars = _bars_by_security(served)
    actions = _actions_by_security(served)
    attributes = {
        row.row.security_id: row for row in served.rows[SharadarDataset.TICKERS.value].values()
    }
    t_minus_1 = as_of.date()
    spinoff_from: dict[str, date] = {}
    for security_id in sorted(set(bars) | set(actions)):
        security_bars = bars.get(security_id, [])
        security_actions = actions.get(security_id, [])
        # Temporal.
        off_calendar = sum(1 for session, _ in security_bars if not calendar.is_session(session))
        checks.finding(
            QualityCheck.TEMPORAL_SESSION_ON_CALENDAR, scope=security_id, count=off_calendar
        )
        after = sum(1 for session, _ in security_bars if session >= t_minus_1)
        checks.finding(
            QualityCheck.TEMPORAL_NO_SESSION_AFTER_T_MINUS_1, scope=security_id, count=after
        )
        # Market data.
        ohlc = volume_negative = 0
        for _, bar in security_bars:
            fields = bar.row.fields
            o, h, lo, c = (
                decimal_field(fields.get(name)) for name in ("open", "high", "low", "close")
            )
            v = decimal_field(fields.get("volume"))
            if (
                o is not None
                and h is not None
                and lo is not None
                and c is not None
                and not (lo <= min(o, c) and max(o, c) <= h)
            ):
                ohlc += 1
            if v is not None and v < 0:
                volume_negative += 1
        checks.finding(QualityCheck.MARKET_OHLC_CONSISTENT, scope=security_id, count=ohlc)
        checks.finding(
            QualityCheck.MARKET_VOLUME_NON_NEGATIVE, scope=security_id, count=volume_negative
        )
        factors = _split_factors(security_actions)
        split_dates = {when for when, _ in factors}
        jumps = 0
        previous_close: Decimal | None = None
        for session, bar in security_bars:
            close = decimal_field(bar.row.fields.get("close"))
            if close is not None and previous_close is not None and previous_close != 0:
                ratio = close / previous_close
                if (
                    ratio > jump_ratio or ratio < Decimal(1) / jump_ratio
                ) and session not in split_dates:
                    jumps += 1
            previous_close = close
        checks.finding(QualityCheck.MARKET_JUMP_WITHOUT_SPLIT, scope=security_id, count=jumps)
        missing = 0
        if security_bars:
            present = {session for session, _ in security_bars}
            first, last = security_bars[0][0], security_bars[-1][0]
            missing = sum(
                1
                for session in calendar.sessions
                if first <= session.session_date <= last and session.session_date not in present
            )
        checks.finding(QualityCheck.MARKET_MISSING_SESSIONS, scope=security_id, count=missing)
        # Identity.
        attribute = attributes.get(security_id)
        outside = 0
        delisting_vs_last = 0
        if attribute is not None and security_bars:
            first_price = date_field(attribute.row.fields.get("firstpricedate"))
            last_price = date_field(attribute.row.fields.get("lastpricedate"))
            outside = sum(
                1
                for session, _ in security_bars
                if (first_price is not None and session < first_price)
                or (last_price is not None and session > last_price)
            )
        if security_bars:
            last_bar = security_bars[-1][0]
            delistings = [
                date_field(row.row.fields.get("date"))
                for row in security_actions
                if row.row.fields.get("action") == ACTION_DELISTED
            ]
            delisting_vs_last = sum(
                1 for when in delistings if when is not None and last_bar > when
            )
        checks.finding(
            QualityCheck.IDENTITY_BAR_WITHIN_LISTING_BOUNDS, scope=security_id, count=outside
        )
        checks.finding(
            QualityCheck.IDENTITY_DELISTING_VS_LAST_BAR, scope=security_id, count=delisting_vs_last
        )
        # Adjustment reconciliation: the repository's SPLIT_ONLY reconstruction against the
        # vendor's closeadj must be proportional across the series, within tolerance.
        ratios: list[Decimal] = []
        for session, bar in security_bars:
            close = decimal_field(bar.row.fields.get("close"))
            vendor = decimal_field(bar.row.fields.get("closeadj"))
            if close is None or vendor is None or close == 0:
                continue
            ratios.append(vendor / _price(close * _factor(factors, session)))
        inconsistent = 0
        if ratios:
            low, high = min(ratios), max(ratios)
            if low <= 0 or (high - low) / high > tolerance:
                inconsistent = 1
        checks.finding(
            QualityCheck.ADJUSTMENT_RECONCILIATION, scope=security_id, count=inconsistent
        )
        # Spinoff: flagged, and excluded from the first ex-date onward.
        spinoffs = sorted(
            when
            for when in (
                date_field(row.row.fields.get("date"))
                for row in security_actions
                if row.row.fields.get("action") == ACTION_SPINOFF
            )
            if when is not None and when <= t_minus_1
        )
        if spinoffs:
            spinoff_from[security_id] = spinoffs[0]
        # Blocking from the first ex-date onward -- the artifact keeps its earlier
        # sessions -- so the exclusion is the cutoff, not the whole security.
        checks.finding(
            QualityCheck.ADJUSTMENT_SPINOFF_FLAGGED,
            scope=security_id,
            count=len(spinoffs),
            blocks_scope=False,
        )
    checks.finding(
        QualityCheck.CENSUS_HISTORY_ADMISSIBILITY,
        scope=BUILD_SCOPE,
        count=sum(entry.attribute_unavailable for entry in universe.census),
    )
    report = QualityReport(
        plan_version=QUALITY_PLAN_VERSION,
        checks_run=tuple(sorted(checks.run, key=lambda check: check.value)),
        checks_not_run=tuple(sorted(CHECKS_NOT_RUN, key=lambda check: check.value)),
        findings=tuple(sorted(checks.findings, key=lambda item: (item.check.value, item.scope))),
        blocked_securities=tuple(sorted(checks.securities)),
        build_blocking=checks.build_blocking,
    )
    return report, spinoff_from


def _artifact(name: str, rows: list[dict[str, Any]]) -> GoldArtifact:
    content = canonical_bytes({"artifact": name, "rows": rows})
    return GoldArtifact(name=name, content=content, sha256=sha256_hex(content), row_count=len(rows))


def _silver_document(row: ResolvedRow) -> dict[str, Any]:
    return {
        "row_key": list(row.row.row_key),
        "security_id": row.row.security_id,
        "revision_sequence": row.row.revision_sequence,
        "content_sha256": row.row.content_sha256,
        "fields": {name: row.row.fields[name] for name in sorted(row.row.fields)},
        "provider_last_updated_date": row.row.provider_last_updated_date,
        "system_first_seen_time": row.row.system_first_seen_time.isoformat(),
        "seen_count": row.row.seen_count,
        "provenance": row.row.provenance.document(),
        "availability": row.availability.document(),
    }


def build_gold(
    layer: ResolvedLayer,
    *,
    universe: UniverseSnapshot,
    calendar: SessionCalendar,
    as_of: datetime,
    identity_blocking: int,
    jump_ratio: Decimal = DEFAULT_JUMP_RATIO,
    tolerance: Decimal = DEFAULT_RECONCILIATION_TOLERANCE,
) -> GoldLayer:
    """Serve, check and assemble. Deterministic: identical inputs give identical bytes.

    Raises:
        GoldError: ``REFUSED_TIMING`` if a served row is bounded after ``as_of`` or
            under an inexpressible derivation; ``REFUSED_QUALITY`` on a build-scoped
            BLOCKING finding.
    """
    if type(layer) is not ResolvedLayer or type(universe) is not UniverseSnapshot:
        raise TypeError("layer and universe must be exact")
    if type(as_of) is not datetime or as_of.tzinfo is None:
        raise TypeError("as_of must be an aware datetime")
    require_supported_convention(ADJUSTMENT_CONVENTION)
    served = _serve(layer, as_of=as_of)
    _verify_served_timing(served, as_of=as_of)
    report, spinoff_from = _run_checks(
        served,
        universe=universe,
        calendar=calendar,
        as_of=as_of,
        identity_blocking=identity_blocking,
        jump_ratio=jump_ratio,
        tolerance=tolerance,
    )
    if report.build_blocking:
        raise GoldError(GoldDefect.REFUSED_QUALITY)
    blocked = set(report.blocked_securities)

    # Silver artifacts: every served row version, per dataset, in key order.
    silver_artifacts = tuple(
        _artifact(
            f"silver-{dataset}",
            [_silver_document(row) for _, row in sorted(served.rows[dataset].items())],
        )
        for dataset in (
            SharadarDataset.TICKERS.value,
            SharadarDataset.STOCKS.value,
            SharadarDataset.ACTIONS.value,
        )
    )

    # Gold: adjusted bars for unblocked securities, before any spinoff ex-date.
    bars = _bars_by_security(served)
    actions = _actions_by_security(served)
    adjusted_rows: list[dict[str, Any]] = []
    for security_id in sorted(bars):
        if security_id in blocked:
            continue
        factors = _split_factors(actions.get(security_id, []))
        cutoff = spinoff_from.get(security_id)
        for session, bar in bars[security_id]:
            if cutoff is not None and session >= cutoff:
                continue
            fields = bar.row.fields
            o, h, lo, c = (
                decimal_field(fields.get(name)) for name in ("open", "high", "low", "close")
            )
            v = decimal_field(fields.get("volume"))
            if None in (o, h, lo, c, v):
                continue
            factor = _factor(factors, session)
            adjusted_rows.append(
                {
                    "security_id": security_id,
                    "session_date": session.isoformat(),
                    "open": str(_price(o * factor)),  # type: ignore[operator]
                    "high": str(_price(h * factor)),  # type: ignore[operator]
                    "low": str(_price(lo * factor)),  # type: ignore[operator]
                    "close": str(_price(c * factor)),  # type: ignore[operator]
                    "volume": str((v / factor).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)),  # type: ignore[operator]
                    "factor": str(factor),
                    "source_content_sha256": bar.row.content_sha256,
                    "revision_sequence": bar.row.revision_sequence,
                    "governing_time": bar.availability.governing_time.isoformat(),
                }
            )
    membership_rows = [row.document() for row in universe.rows if row.security_id not in blocked]
    action_rows = [
        {
            "security_id": row.row.security_id,
            "row_key": list(row.row.row_key),
            "action": row.row.fields.get("action"),
            "date": row.row.fields.get("date"),
            "value": row.row.fields.get("value"),
            "source_content_sha256": row.row.content_sha256,
            "governing_time": row.availability.governing_time.isoformat(),
        }
        for _, row in sorted(served.rows[SharadarDataset.ACTIONS.value].items())
        if row.row.security_id not in blocked
    ]
    gold_artifacts = (
        _artifact("gold-adjusted-bars", adjusted_rows),
        _artifact("gold-universe-membership", membership_rows),
        _artifact("gold-corporate-actions", action_rows),
    )
    limitations: list[LimitationToken] = [LimitationToken.SINGLE_SOURCE_UNVERIFIED]
    if any(
        row.availability.provider_bound_derivation is ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND
        for rows in served.rows.values()
        for row in rows.values()
    ):
        limitations.extend(
            [LimitationToken.PROVIDER_AVAILABILITY_UNKNOWN, LimitationToken.PROVIDER_TIME_BOUNDED]
        )
    empty_reason: str | None = None
    if not adjusted_rows and not any(row.is_member for row in universe.rows):
        if not any(count.revisions_admitted for count in served.counts):
            empty_reason = "NO_ROW_VERSION_ADMISSIBLE_AT_AS_OF"
        elif universe.census and all(
            entry.attribute_determinable == 0 for entry in universe.census
        ):
            empty_reason = "ATTRIBUTES_UNAVAILABLE_FOR_EVERY_SESSION"
        else:
            empty_reason = "NO_MEMBER_AND_NO_ADJUSTED_BAR"
    return GoldLayer(
        as_of=as_of,
        served=served.counts,
        silver_artifacts=silver_artifacts,
        gold_artifacts=gold_artifacts,
        quality=report,
        limitations=tuple(limitations),
        spinoff_excluded_securities=tuple(sorted(spinoff_from)),
        empty_reason=empty_reason,
    )


__all__ = [
    "ADJUSTMENT_CONVENTION",
    "ADJUSTMENT_POLICY",
    "BUILD_SCOPE",
    "CHECKS_NOT_RUN",
    "DEFAULT_JUMP_RATIO",
    "DEFAULT_RECONCILIATION_TOLERANCE",
    "PRICE_QUANTUM",
    "QUALITY_PLAN",
    "QUALITY_PLAN_VERSION",
    "Finding",
    "GoldArtifact",
    "GoldDefect",
    "GoldError",
    "GoldLayer",
    "QualityCheck",
    "QualityReport",
    "ServedCounts",
    "Severity",
    "build_gold",
    "verify_served_rows",
]
