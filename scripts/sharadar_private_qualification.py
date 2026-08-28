"""Private Sharadar free-sample qualification harness (P1-P9).

**This file is code and methodology only. It contains no vendor data, no empirical
result, no private credential and no AWS identifier -- which is why it is safe to
commit to a PUBLIC repository.** What it produces is not.

Sharadar Terms s.8 restricts disclosure of conclusions drawn from testing or evaluating
the Services or the Services Data -- not only publication, but disclosure to any outside
individual or entity. [ADR-0008] accepts the Personal Use License and records the
consequence: **empirical qualification output is private**. It lives in the licensed S3
bucket and in git-ignored ``.runtime/``, and it reaches Git, a pull request, a GitHub
issue, a commit message or an AI session **never**.

That constraint shapes every design decision below, and the shape is deliberate:

1. **Network is off by default.** A live run needs ``--private-live-run``, and the
   fetching functions cannot be called without a ``LiveRunAuthorization`` that only
   :func:`authorize_live_run` can mint. This is structural, not a checked flag: there is
   no code path from ``import`` to a socket.
2. **It refuses to run from automation.** ``pytest``, CI and a plain import are all
   refused before the AWS gate is even reached, because a provider conclusion appearing
   in a CI log is exactly the disclosure s.8 forbids.
3. **The exit code carries no verdict.** It reports whether the *harness* worked. A run
   that completes and privately concludes ``REJECT_FOR_PHASE3A`` exits ``0``, identically
   to one that concludes ``PROCEED``. :func:`operational_exit_code` is given an outcome
   object that has no field for a recommendation, so the channel does not exist.
4. **stdout is an allowlist.** :func:`console_lines` returns a fixed set of lines. No
   P-status, no recommendation, no bucket name, no URL, no vendor row can reach a
   terminal, a log or an AI transcript through it.
5. **Nothing about the request is ever logged.** The API key travels in the query string
   (``PSR-SHD-109``), so URLs and query strings are redacted everywhere and error text is
   built from an allowlist -- stage, table name, sanitized code. Response bodies never
   enter an exception. The key used here is the vendor's *published* test key and is not
   a secret; the redaction exists because the same code path is the template for a client
   that will one day carry a private one.

**Credential.** Only the vendor-published public test key documented at
``https://sharadar.com/docs/auth`` (``PSR-SHD-109``), which that page states may be used
to query tables for AAPL. No account, no subscription, no trial, no private key, no
Secrets Manager entry.

**Honesty about what a single-name, five-year public test-key probe can settle.**
Most of the nine tests
cannot be answered by it at all, and the vocabulary in :data:`STATUSES` exists so that they
are not quietly recorded as passes. :func:`validate_findings` enforces the ceilings
structurally -- P2 can only ever be ``NOT_TESTABLE_WITH_PUBLIC_SAMPLE``, P7 and P8 only
``DEFERRED``, P4 only ``DOCUMENTATION_RESOLVED`` and never without
``CLASSIFICATION_STATIC``, and P9 can never yield ``PUBLIC_PIT`` eligibility from sample
values.

**The probe is one security, not thirty.** The vendor publishes two different free
surfaces and they are easy to conflate: a *sample subscription* covering 30 DJIA names over
five years, which requires signing in, and the *published test key*, which requires no
account and is documented for a single security. This harness uses the second. Everything
below is therefore a **single-name, five-year public test-key probe**, and the ceilings in
:data:`STATUS_CEILING` are calibrated to that and not to the wider sample.

**The correction that matters most is that honesty runs both ways.** An earlier revision
recorded the vendor's dividend and spinoff adjustment formulas as *unpublished*. The vendor
published them on 2026-07-29 (`PSR-SHD-120`), so that statement became false, and a
pessimism that has stopped being true is as much a defect as an unearned pass. P5 is now
decomposed into split, cash-dividend and spinoff limbs, each reported on its own evidence.
P5 still cannot reach ``TESTED`` -- but for the correct reason: the spinoff ratio needs the
spun-off entity's opening price and share counts, which are another security's data, so the
full mechanism is never exercised end to end.

**This harness is not a provider adapter.** It writes nothing under ``src/``, adds no
runtime dependency, imports no AWS SDK, and builds no Parquet, DuckDB or ingestion path.
Those are separate authorizations under CLAUDE.md s.8.

Run (by the owner, manually, after the pull request is merged)::

    $env:AWS_PROFILE="kalpamani-foundation"
    .venv\\Scripts\\python.exe scripts\\sharadar_private_qualification.py --private-live-run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Container, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "aws_foundation_verify.py"

#: The private, git-ignored area the owner reads the report from. Nothing under it is
#: ever committed; `.runtime/` is git-ignored in full.
RUNTIME_ROOT = REPO_ROOT / ".runtime" / "phase3" / "sharadar"

#: The AWS profile a live run must be pinned to. CLAUDE.md s.4.24: this workstation holds
#: profiles for an unrelated project, and `default` is what an unpinned command hits.
EXPECTED_PROFILE = "kalpamani-foundation"

#: **A vendor-PUBLISHED PUBLIC TEST TOKEN, not a credential.** Documented at
#: https://sharadar.com/docs/auth, which states it may be used to query tables for AAPL
#: (`PSR-SHD-109`). It is published by the vendor, is not secret, was not issued to this
#: project, and grants no subscription. It is committed deliberately and is the single
#: literal the repository's secret guards allowlist by name.
PUBLIC_TEST_API_KEY = "test-api-key"

API_BASE = "https://api.sharadar.com/v1.0/data"

#: A deterministic, honest identifier. No published rate limit exists (`PSR-SHD-109`), so
#: this is courtesy and identification, not compliance with a stated budget.
USER_AGENT = "KalpaMani-Personal-Research/phase3-qualification"

#: No documented rate limit is not an absent rate limit. One request per second, and a
#: fixed inventory rather than a crawl.
MIN_REQUEST_INTERVAL_SECONDS = 1.0

HTTP_TIMEOUT_SECONDS = 60

#: Relative tolerance for the split-adjustment reconciliation. Vendor prices are rounded
#: to cents, so an exact equality test would fail on rounding rather than on method.
SPLIT_TOLERANCE = 0.005

#: The single security the published test key documents. Not a choice -- a constraint.
SAMPLE_TICKER = "AAPL"

#: The qualification window, in whole calendar years.
#:
#: **This is not cosmetic.** Every temporal table defaults to `from` = one year ago and
#: `to` = the prior day (`PSR-SHD-121`). An earlier revision of this harness supplied
#: neither, so it would have run a **one-year** probe while the methodology described a
#: five-year sample throughout -- and a one-year window of a single mega-cap is very
#: likely to contain no split at all, which would have quietly reduced the only genuinely
#: empirical check to a trivial agreement.
QUALIFICATION_WINDOW_YEARS = 5

#: Every request this harness will ever make. A fixed inventory, not a crawl. Endpoint
#: path segments and parameter names are from the vendor's own public query examples
#: (`PSR-SHD-118`); nothing here is guessed.
#:
#: The flag is whether the table takes an explicit date window. `tickers` does not, and
#: deliberately: the vendor documents it as a **snapshot** whose 5, 10 and full bulk
#: options return the same table (`PSR-SHD-119`), so a date range there would be a
#: meaningless parameter attached to a table that has no time axis.
REQUEST_INVENTORY: tuple[tuple[str, bool], ...] = (
    ("tickers", False),
    ("stocks", True),
    ("actions", True),
    ("fundamentals", True),
    ("events", True),
)

#: The tables whose evidence the qualification actually depends on being windowed.
WINDOWED_TABLES: tuple[str, ...] = tuple(t for t, windowed in REQUEST_INVENTORY if windowed)

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

TESTED = "TESTED"
PARTIALLY_TESTED = "PARTIALLY_TESTED"
DOCUMENTATION_RESOLVED = "DOCUMENTATION_RESOLVED"
NOT_TESTABLE_WITH_PUBLIC_SAMPLE = "NOT_TESTABLE_WITH_PUBLIC_SAMPLE"
DEFERRED = "DEFERRED"
INCONCLUSIVE = "INCONCLUSIVE"

STATUSES = frozenset(
    {
        TESTED,
        PARTIALLY_TESTED,
        DOCUMENTATION_RESOLVED,
        NOT_TESTABLE_WITH_PUBLIC_SAMPLE,
        DEFERRED,
        INCONCLUSIVE,
    }
)

#: A LIMB-only outcome. P5 decomposes into split, cash-dividend and spinoff limbs, and a
#: limb the sample never gave an event for is neither tested nor inconclusive -- it simply
#: did not run. Keeping it out of :data:`STATUSES` matters: a finding may never carry it,
#: so "the sample had no spinoff" can never be dressed up as a provider-test result.
NOT_EXERCISED = "NOT_EXERCISED"

LIMB_STATUSES = frozenset({TESTED, PARTIALLY_TESTED, INCONCLUSIVE, NOT_EXERCISED})

PROCEED = "PROCEED_TO_PROVIDER_REALISTIC_IMPLEMENTATION"
HOLD = "HOLD_FOR_ADDITIONAL_PRIVATE_SAMPLE"
REJECT = "REJECT_FOR_PHASE3A"

RECOMMENDATIONS = frozenset({PROCEED, HOLD, REJECT})

#: The statuses each test may legitimately reach on a single-name, five-year public
#: test-key probe.
#: This is the anti-optimism guard, and it is enforced rather than documented:
#: :func:`validate_findings` refuses a report whose finding sits outside its ceiling.
#:
#: P2 needs delistings 5/10/15 years back -- unreachable on a 5-year AAPL sample.
#: P7 and P8 need EDGAR acceptance timestamps, which are Phase-3B work.
#: P1 cannot reach TESTED because observing "first appeared" needs two ingestions
#: separated by real calendar time, not one snapshot.
#: P4 is settled by public documentation: the tickers table is a SNAPSHOT -- the vendor
#: states that its 5, 10 and full bulk options all download the same table (`PSR-SHD-119`)
#: -- so it carries no temporal axis and no sample of rows can supply one.
#: P5 cannot reach TESTED because its spinoff limb cannot be exercised from this surface at
#: all: the published formula needs the spun-off entity's opening price and share ratio,
#: which are another security's data, and the meaning of `actions.value` for a spinoff row
#: is undocumented (`PSR-SHD-112`, `PSR-SHD-120`).
STATUS_CEILING: Mapping[str, frozenset[str]] = {
    "P1": frozenset({PARTIALLY_TESTED, INCONCLUSIVE}),
    "P2": frozenset({NOT_TESTABLE_WITH_PUBLIC_SAMPLE}),
    "P3": frozenset({DOCUMENTATION_RESOLVED}),
    "P4": frozenset({DOCUMENTATION_RESOLVED}),
    "P5": frozenset({PARTIALLY_TESTED, INCONCLUSIVE}),
    "P6": frozenset({DOCUMENTATION_RESOLVED}),
    "P7": frozenset({DEFERRED}),
    "P8": frozenset({DEFERRED}),
    "P9": frozenset({DOCUMENTATION_RESOLVED}),
}

TEST_IDS: tuple[str, ...] = tuple(sorted(STATUS_CEILING))

#: P1's gap policy under [contract s.3.3]. `lastupdated` reads as *last changed* and is a
#: date, so exact provider availability is unobtainable and BOUND is the only honest
#: resolution. It is a constant, not a computed value, because no sample can change it.
P1_GAP_POLICY = "BOUND"

#: P9 asks how the bars were produced. That is a fact about the vendor's production
#: process, not about its data, so no sample of values can establish it and public
#: documentation does not state it (`PSR-SHD-110`). The conservative classification
#: therefore stands, and `PUBLIC_PIT` is unreachable from here by construction.
P9_INFORMATION_ORIGIN = "PROVIDER_DERIVED"
P9_ELIGIBLE_PROFILE = "PROVIDER_REALISTIC_PIT"
FORBIDDEN_P9_PROFILE = "PUBLIC_PIT"


# ---------------------------------------------------------------------------
# Redaction -- applied before any string could reach a terminal or a file
# ---------------------------------------------------------------------------

#: Order matters. A whole URL is consumed first (taking its query string and key with
#: it), then a bare `api_key=...`, then a bare query string. Reversing the order would
#: leave a scheme-qualified host in place.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"https?://\S*"), "<url-redacted>"),
    (re.compile(r"api[_-]?key\s*=\s*\S*", re.IGNORECASE), "api_key=<redacted>"),
    (re.compile(r"\?[^\s]*=\S*"), "?<query-redacted>"),
    (re.compile(re.escape(PUBLIC_TEST_API_KEY), re.IGNORECASE), "<redacted>"),
)


def redact(text: str) -> str:
    """Strip URLs, query strings and anything key-shaped out of ``text``.

    Applied to every string this harness is capable of emitting. The published test key
    is redacted along with everything else -- not because it is secret, but so that the
    redaction is exercised on every run rather than first exercised on the day a private
    key is introduced.
    """
    out = text
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


class SafeHarnessError(Exception):
    """An operational failure, describable without disclosing anything.

    Its message is *assembled from an allowlist* -- a stage name, a table name and a
    sanitized code -- rather than redacted after the fact. A response body, a URL, a
    query string, a bucket name and an ARN have no path into it, because none of them is
    ever passed in.
    """

    def __init__(self, stage: str, code: str, table: str | None = None) -> None:
        self.stage = redact(stage)
        self.code = redact(code)
        self.table = redact(table) if table else None
        detail = f"{self.stage}: {self.code}"
        if self.table:
            detail = f"{self.stage} [{self.table}]: {self.code}"
        super().__init__(detail)


def classify_http_status(status: int) -> str:
    """A sanitized category for an HTTP status. Never the body, never the URL."""
    if status == 401 or status == 403:
        return "HTTP_AUTHORIZATION_REFUSED"
    if status == 404:
        return "HTTP_ENDPOINT_NOT_FOUND"
    if status == 429:
        return "HTTP_RATE_LIMITED"
    if 400 <= status < 500:
        return "HTTP_CLIENT_ERROR"
    if 500 <= status < 600:
        return "HTTP_SERVER_ERROR"
    return "HTTP_UNEXPECTED_STATUS"


# ---------------------------------------------------------------------------
# Authorization -- the only mint for a network-capable token
# ---------------------------------------------------------------------------

_GRANT = object()


class LiveRunAuthorization:
    """Proof that a deliberate, gated live run was authorized.

    It cannot be constructed directly: the constructor demands a module-private sentinel
    that only :func:`authorize_live_run` holds. Every function capable of opening a
    socket requires an instance, so "network is off unless the flag was passed and the
    gates passed" is a property of the type system rather than of a remembered check.
    """

    __slots__ = ("profile",)

    def __init__(self, grant: object, profile: str) -> None:
        if grant is not _GRANT:
            raise SafeHarnessError("authorize", "LIVE_RUN_AUTHORIZATION_NOT_GRANTABLE")
        self.profile = profile


def running_under_automation(env: Mapping[str, str], modules: Mapping[str, Any]) -> str | None:
    """Reason this looks like automation, or None.

    A provider conclusion in a CI log is precisely the disclosure Terms s.8 forbids, so
    the harness refuses to run anywhere its output could be captured automatically.
    """
    if "PYTEST_CURRENT_TEST" in env or "pytest" in modules:
        return "refusing to run under pytest -- this harness is a manual owner action"
    for marker in ("CI", "GITHUB_ACTIONS", "BUILD_ID", "TF_BUILD"):
        if env.get(marker):
            return "refusing to run under CI -- this harness is a manual owner action"
    return None


def aws_identity_gate(verifier: Any = None) -> str | None:
    """Run the existing, fail-closed AWS identity gate. Returns a reason, or None.

    Deliberately *reused* rather than reimplemented: ``scripts/aws_foundation_verify.py``
    already pins the profile, compares STS against the local account binding, and never
    prints the account id, an ARN or an SSO URL. A second copy of that logic would be a
    second thing to get wrong.
    """
    module = verifier if verifier is not None else load_foundation_verifier()
    reason = module.identity_gate()
    return None if reason is None else redact(str(reason))


def load_foundation_verifier() -> Any:
    """Import the read-only foundation verifier by path. It has no import side effects."""
    spec = importlib.util.spec_from_file_location("kalpamani_aws_foundation_verify", VERIFY_SCRIPT)
    if spec is None or spec.loader is None:
        raise SafeHarnessError("authorize", "FOUNDATION_VERIFIER_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def authorize_live_run(
    argv: Sequence[str],
    env: Mapping[str, str],
    modules: Mapping[str, Any] | None = None,
    identity_gate: Callable[[], str | None] | None = None,
) -> LiveRunAuthorization:
    """Grant network authority, or raise. The gates run in this order and stop at the first failure.

    1. ``--private-live-run`` present -- absent, the harness does nothing over the network
    2. not pytest, not CI, not an import
    3. ``AWS_PROFILE`` pinned to the KalpaMani foundation profile
    4. the AWS identity gate passes

    Order is itself a control, exactly as it is in the foundation verifier: the identity
    check happens before anything reads remote state or touches the network.
    """
    if "--private-live-run" not in tuple(argv):
        raise SafeHarnessError("authorize", "NETWORK_REFUSED_PRIVATE_LIVE_RUN_FLAG_ABSENT")

    automation = running_under_automation(env, modules if modules is not None else sys.modules)
    if automation is not None:
        raise SafeHarnessError("authorize", "NETWORK_REFUSED_AUTOMATED_CONTEXT")

    profile = env.get("AWS_PROFILE", "")
    if profile != EXPECTED_PROFILE:
        raise SafeHarnessError("authorize", "NETWORK_REFUSED_AWS_PROFILE_NOT_PINNED")

    gate = identity_gate if identity_gate is not None else aws_identity_gate
    reason = gate()
    if reason is not None:
        raise SafeHarnessError("authorize", "NETWORK_REFUSED_AWS_IDENTITY_CHECK_FAILED")

    return LiveRunAuthorization(_GRANT, profile)


# ---------------------------------------------------------------------------
# Buckets -- resolved in memory, never printed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResearchBuckets:
    """Bucket names from Terraform remote state. Held in memory; never printed."""

    licensed: str
    control: str


def resolve_buckets(authorization: LiveRunAuthorization, verifier: Any = None) -> ResearchBuckets:
    """Read the two research buckets from Terraform remote state.

    Requires an authorization for the same reason the fetchers do: reading remote state
    is an authenticated action against the pinned account, and it must not be reachable
    from an import or a test.
    """
    if not isinstance(authorization, LiveRunAuthorization):  # pragma: no cover - type guard
        raise SafeHarnessError("resolve_buckets", "AUTHORIZATION_REQUIRED")
    module = verifier if verifier is not None else load_foundation_verifier()
    try:
        outputs = module.tf_outputs()
    except Exception as exc:
        # Deliberately broad: the exception TEXT may quote a bucket name, so only the
        # exception CLASS survives into the sanitized error.
        raise SafeHarnessError("resolve_buckets", type(exc).__name__) from None
    try:
        return ResearchBuckets(
            licensed=str(outputs["licensed_bucket_name"]),
            control=str(outputs["control_bucket_name"]),
        )
    except (KeyError, TypeError):
        raise SafeHarnessError("resolve_buckets", "TERRAFORM_OUTPUT_MISSING") from None


def assert_licensed_destination(bucket: str, buckets: ResearchBuckets) -> str:
    """Refuse any destination that is not the licensed bucket.

    Qualification evidence is provider-evaluation output under Terms s.8 and vendor rows
    under s.4. Both belong in the licensed store, which is the one inside the deletion
    surface. The control bucket holds manifests and approved non-reconstructable outputs
    and has the opposite durability posture -- writing evaluation material there would
    place it outside the 30-day deletion obligation.
    """
    if bucket == buckets.control:
        raise SafeHarnessError("upload", "CONTROL_BUCKET_IS_NOT_A_QUALIFICATION_DESTINATION")
    if bucket != buckets.licensed:
        raise SafeHarnessError("upload", "UNKNOWN_DESTINATION_BUCKET")
    return bucket


# ---------------------------------------------------------------------------
# Object naming -- deterministic and content-addressed
# ---------------------------------------------------------------------------


def content_address(payload: bytes) -> str:
    """Content address of a raw payload: ``sha256/<hex>``. Deterministic by construction."""
    return f"sha256/{hashlib.sha256(payload).hexdigest()}"


def run_prefix(run_id: str) -> str:
    return f"qualification/sharadar/{run_id}"


def raw_object_key(run_id: str, address: str) -> str:
    """Where one raw vendor payload lands in the LICENSED bucket."""
    return f"{run_prefix(run_id)}/raw/{address}"


def private_report_object_key(run_id: str, filename: str) -> str:
    """Where the PRIVATE empirical report lands -- licensed, never control.

    The report carries provider-quality conclusions, so it is licensed evaluation
    material even though it contains no verbatim vendor row.
    """
    return f"{run_prefix(run_id)}/private-report/{filename}"


def make_run_id(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# HTTP -- paced, identified, and silent
# ---------------------------------------------------------------------------


class Pacer:
    """At most one request per ``min_interval`` seconds.

    Clock and sleep are injected so the pacing is testable without spending the time.
    """

    def __init__(
        self,
        min_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleeper
        self._last: float | None = None

    def wait(self) -> float:
        """Block until the next request is due. Returns the seconds actually slept."""
        now = self._clock()
        slept = 0.0
        if self._last is not None:
            due = self._last + self.min_interval
            if now < due:
                slept = due - now
                self._sleep(slept)
                now = due
        self._last = now
        return slept


def five_year_window(now: datetime) -> tuple[str, str]:
    """The explicit ``(from, to)`` window for every temporal request.

    ``to`` is the prior UTC calendar day, matching the vendor's own documented ``to``
    default; ``from`` is the same calendar date five years earlier. Supplying both is the
    whole point: without them the vendor returns **one year** (`PSR-SHD-121`), and the
    methodology describes a five-year sample.

    29 February has no counterpart five years earlier -- leap years are four apart, so the
    subtraction always lands on a non-leap year -- and it resolves to 28 February. That is
    deterministic and one day narrower, which is the safe direction for a window.
    """
    end = now.astimezone(UTC).date() - timedelta(days=1)
    try:
        start = end.replace(year=end.year - QUALIFICATION_WINDOW_YEARS)
    except ValueError:
        start = end.replace(year=end.year - QUALIFICATION_WINDOW_YEARS, month=2, day=28)
    return start.isoformat(), end.isoformat()


def build_request_params(
    table: str, windowed: bool, window: tuple[str, str], ticker: str = SAMPLE_TICKER
) -> tuple[tuple[str, str], ...]:
    """Query parameters for one request. Named parameters only, never a bulk download.

    ``years=`` is deliberately unused: it triggers a table-wide zip of every security, which
    is neither the small fixed probe authorized here nor something a public test key should
    be pointed at.
    """
    params: list[tuple[str, str]] = [("ticker", ticker)]
    if windowed:
        params.append(("from", window[0]))
        params.append(("to", window[1]))
    return tuple(params)


def build_request_url(table: str, params: Sequence[tuple[str, str]]) -> str:
    """Build one request URL. **Never log, print or store the return value.**"""
    query = urllib.parse.urlencode([("api_key", PUBLIC_TEST_API_KEY), ("format", "csv"), *params])
    return f"{API_BASE}/{table}?{query}"


def fetch_table(
    authorization: LiveRunAuthorization,
    table: str,
    params: Sequence[tuple[str, str]],
    pacer: Pacer,
    opener: Callable[[urllib.request.Request, float], Any] | None = None,
) -> bytes:
    """Fetch one table's payload. Requires an authorization; paces; discloses nothing.

    On failure the response body is **not read**. An error becomes a stage, a table name
    and a sanitized status category -- never a payload, never a URL, never a query string.
    """
    if not isinstance(authorization, LiveRunAuthorization):  # pragma: no cover - type guard
        raise SafeHarnessError("fetch", "AUTHORIZATION_REQUIRED", table)

    url = build_request_url(table, params)
    if not url.startswith("https://"):  # pragma: no cover - constant-driven
        raise SafeHarnessError("fetch", "REFUSING_NON_HTTPS_SCHEME", table)

    pacer.wait()
    headers = {"User-Agent": USER_AGENT}
    request = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
    try:
        if opener is not None:
            response = opener(request, float(HTTP_TIMEOUT_SECONDS))
        else:
            response = urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS)  # noqa: S310
    except urllib.error.HTTPError as exc:
        raise SafeHarnessError("fetch", classify_http_status(int(exc.code)), table) from None
    except urllib.error.URLError:
        raise SafeHarnessError("fetch", "NETWORK_UNREACHABLE", table) from None
    except TimeoutError:
        raise SafeHarnessError("fetch", "NETWORK_TIMEOUT", table) from None

    try:
        with response:
            payload = response.read()
    except OSError:
        raise SafeHarnessError("fetch", "RESPONSE_READ_FAILED", table) from None
    if not isinstance(payload, bytes):  # pragma: no cover - defensive
        raise SafeHarnessError("fetch", "RESPONSE_NOT_BYTES", table)
    return payload


# ---------------------------------------------------------------------------
# Parsing -- an unparseable payload is INCONCLUSIVE, never a pass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TableSample:
    """One retrieved table. ``rows`` are licensed vendor rows and never leave this process."""

    table: str
    columns: tuple[str, ...] = ()
    rows: tuple[Mapping[str, str], ...] = ()
    address: str = ""
    parse_error: str | None = None
    fetch_error: str | None = None

    @property
    def usable(self) -> bool:
        return self.fetch_error is None and self.parse_error is None and bool(self.columns)


def parse_csv_payload(table: str, payload: bytes, address: str) -> TableSample:
    """Parse a CSV payload into a sample. A failure is recorded, never raised."""
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return TableSample(table=table, address=address, parse_error="PAYLOAD_NOT_UTF8")
    reader = csv.DictReader(io.StringIO(text))
    try:
        rows = tuple({k: (v or "") for k, v in row.items() if k is not None} for row in reader)
    except csv.Error:
        return TableSample(table=table, address=address, parse_error="CSV_MALFORMED")
    columns = tuple(reader.fieldnames or ())
    if not columns:
        return TableSample(table=table, address=address, parse_error="CSV_NO_HEADER")
    return TableSample(table=table, columns=columns, rows=rows, address=address)


def _floats(rows: Sequence[Mapping[str, str]], column: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        try:
            out.append(float(row[column]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# P5 -- the split-adjustment reconciliation, the one real empirical check
# ---------------------------------------------------------------------------

#: The convention the vendor documents: adjustment is backward from an action-date price
#: that keeps its traded value, so an action dated ``D`` adjusts rows strictly *before* ``D``
#: (`PSR-SHD-120`). This is the only outcome that counts as the split limb succeeding.
EXCLUSIVE_OF_ACTION_DATE = "EXCLUSIVE_OF_ACTION_DATE"

#: The sample contained no row on an action date, so both conventions fit and neither was
#: distinguished. Agreement by absence of a discriminating row is not a measurement.
CONVENTION_NOT_DISCRIMINATED = "NOT_EMPIRICALLY_DISCRIMINATED"

#: Only the inclusive convention fits -- the data contradicts the vendor's published
#: method. That is a **finding about the data**, and calling it a successful test would
#: record a contradiction as a confirmation.
DOCUMENTATION_DATA_CONTRADICTION = "DOCUMENTATION_DATA_CONTRADICTION"

CONVENTION_UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class SplitReconciliation:
    """Outcome of reconciling the vendor's split-adjusted close against its unadjusted close."""

    status: str
    convention: str
    rows_compared: int
    #: Splits present in the retrieved actions, whether or not they touch a compared row.
    splits_in_range: int
    #: Splits that actually affect at least one compared row. **This is the number that
    #: decides whether the limb was exercised.** A split that predates every price row
    #: adjusts nothing in the sample, so counting it would let the limb report TESTED
    #: while the adjustment mechanism was never applied to anything.
    splits_exercised: int
    exclusive_matches: int
    inclusive_matches: int
    #: Deviation under the BEST-fitting convention, so it reads as "how far from any
    #: explanation", not "how far from the one we happened to try first".
    worst_relative_deviation: float
    #: The earliest compared row date, or "" when nothing was comparable. Used to decide
    #: whether an unmodelled action could have touched the comparison.
    earliest_compared: str
    note: str


def _cumulative_factor(
    splits: Sequence[tuple[str, float]], row_date: str, inclusive: bool
) -> float:
    factor = 1.0
    for action_date, value in splits:
        if value <= 0:
            continue
        if action_date > row_date or (inclusive and action_date == row_date):
            factor *= value
    return factor


def _relative_deviation(
    unadjusted: float,
    close: float,
    splits: Sequence[tuple[str, float]],
    row_date: str,
    inclusive: bool,
) -> float:
    """How far the vendor's adjusted close sits from the one this convention predicts."""
    expected = unadjusted / _cumulative_factor(splits, row_date, inclusive)
    return abs(expected - close) / close


def reconcile_split_adjustment(
    rows: Sequence[Mapping[str, str]],
    splits: Sequence[tuple[str, float]],
    tolerance: float = SPLIT_TOLERANCE,
) -> SplitReconciliation:
    """Does ``close`` equal ``closeunadj`` divided by the cumulative later split factor?

    The vendor publishes that OHLCV is split-adjusted and ``closeunadj`` is unadjusted
    (`PSR-SHD-110`, `PSR-SHD-111`), so this relationship is specified well enough to test.

    **The documented direction is exclusive of the action date**: adjustment is backward,
    the action-date price stays as traded, and preceding history is adjusted
    (`PSR-SHD-120`). Both conventions are still evaluated -- not to resolve an ambiguity
    the vendor has settled, but so the observation can *disagree* with the documentation
    rather than being assumed to match it. An INCLUSIVE result would be a finding about
    the data, not a discovery about the convention.
    """
    compared_dates: list[str] = []
    exclusive_ok = 0
    inclusive_ok = 0
    worst = 0.0
    for row in rows:
        try:
            close = float(row["close"])
            unadjusted = float(row["closeunadj"])
            row_date = str(row["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if close <= 0 or unadjusted <= 0:
            continue
        compared_dates.append(row_date)
        exclusive_deviation = _relative_deviation(unadjusted, close, splits, row_date, False)
        inclusive_deviation = _relative_deviation(unadjusted, close, splits, row_date, True)
        if exclusive_deviation <= tolerance:
            exclusive_ok += 1
        if inclusive_deviation <= tolerance:
            inclusive_ok += 1
        # The deviation under the BEST-fitting convention: how far the vendor's adjusted
        # close is from any explanation we can offer. Reporting only the exclusive
        # convention's error would overstate the gap whenever the vendor uses the other.
        worst = max(worst, min(exclusive_deviation, inclusive_deviation))

    compared = len(compared_dates)
    in_range = sum(1 for _, value in splits if value > 0)
    earliest = min(compared_dates) if compared_dates else ""
    # A split adjusts rows that PRECEDE it. One dated at or before every compared row
    # therefore touches nothing in this comparison, however real it is.
    exercised = sum(1 for date, value in splits if value > 0 and date > earliest) if earliest else 0

    if compared == 0:
        # NOT a reconciliation failure. Nothing was compared, so nothing disagreed --
        # and only a disagreement between the vendor's own two series may reject it.
        return SplitReconciliation(
            status=NOT_EXERCISED,
            convention=CONVENTION_UNRESOLVED,
            rows_compared=0,
            splits_in_range=in_range,
            splits_exercised=0,
            exclusive_matches=0,
            inclusive_matches=0,
            worst_relative_deviation=0.0,
            earliest_compared="",
            note=(
                "no row carried a date with both an adjusted and an unadjusted close, so "
                "the limb did not run; this is missing evidence, not a failed comparison"
            ),
        )

    exclusive_all = exclusive_ok == compared
    inclusive_all = inclusive_ok == compared

    if exercised == 0:
        return SplitReconciliation(
            status=PARTIALLY_TESTED,
            convention=CONVENTION_UNRESOLVED,
            rows_compared=compared,
            splits_in_range=in_range,
            splits_exercised=0,
            exclusive_matches=exclusive_ok,
            inclusive_matches=inclusive_ok,
            worst_relative_deviation=worst,
            earliest_compared=earliest,
            note=(
                "no split affects any compared row -- either none occurred in the window, "
                "or every one predates the whole price sample -- so adjusted and unadjusted "
                "agree trivially and the adjustment method is not exercised"
            ),
        )
    # The vendor's published direction is exclusive of the action date. Only that outcome
    # is a success; the others are each a different kind of not-yet-established.
    if exclusive_all and inclusive_all:
        convention, status = CONVENTION_NOT_DISCRIMINATED, PARTIALLY_TESTED
        note = (
            "both conventions fit because no compared row falls on an action date, so the "
            "documented direction was never distinguished from its opposite"
        )
    elif exclusive_all:
        convention, status = EXCLUSIVE_OF_ACTION_DATE, TESTED
        note = (
            "the vendor's split-adjusted close reconciles against raw prices and actions "
            "under the documented backward direction"
        )
    elif inclusive_all:
        convention, status = DOCUMENTATION_DATA_CONTRADICTION, INCONCLUSIVE
        note = (
            "only the inclusive convention reconciles, which contradicts the vendor's "
            "published backward-from-the-action-date method; a contradiction is a finding "
            "about the data, not a successful test"
        )
    else:
        convention, status = CONVENTION_UNRESOLVED, INCONCLUSIVE
        note = (
            "neither the inclusive nor the exclusive action-date convention reconciles "
            "every row; the adjustment method is not established"
        )
    return SplitReconciliation(
        status=status,
        convention=convention,
        rows_compared=compared,
        splits_in_range=in_range,
        splits_exercised=exercised,
        exclusive_matches=exclusive_ok,
        inclusive_matches=inclusive_ok,
        worst_relative_deviation=worst,
        earliest_compared=earliest,
        note=note,
    )


# ---------------------------------------------------------------------------
# P5 -- the cash-dividend limb, against the vendor's published ratio
# ---------------------------------------------------------------------------

#: Candidate models for the cash-dividend adjustment.
#:
#: **One axis, not two.** The vendor's worked example computes the ratio from
#: ``current_close`` -- the close **on the action date itself** -- and divides the
#: *preceding* history by it (`PSR-SHD-120`). That settles the date question: the
#: action-date row keeps its traded price, and adjustment runs backward from it. An
#: earlier revision of this harness used the *prior* row as the base and carried an
#: inclusive/exclusive model axis to cover an ambiguity the vendor had already resolved.
#: Both are corrected: keeping a model axis the source has closed is not caution, it is
#: noise that makes a wrong model look like a legitimate alternative.
#:
#: What genuinely remains unresolved is the **share basis** of ``actions.value``. When a
#: later split exists, the action-date ``close`` is split-adjusted while ``closeunadj`` is
#: not, and the vendor does not say which one the recorded dividend amount is expressed
#: against. That is observed rather than assumed.
DIVIDEND_BASIS_UNADJUSTED = "UNADJUSTED_BASIS"
DIVIDEND_BASIS_SPLIT_ADJUSTED = "SPLIT_ADJUSTED_BASIS"

DIVIDEND_MODELS: tuple[tuple[str, str], ...] = (
    (DIVIDEND_BASIS_UNADJUSTED, "closeunadj"),
    (DIVIDEND_BASIS_SPLIT_ADJUSTED, "close"),
)

DIVIDEND_MODEL_UNRESOLVED = "UNRESOLVED"
DIVIDEND_MODELS_AGREE = "AMBIGUOUS_MODELS_AGREE"
DIVIDEND_LITERAL_UNIDENTIFIED = "ACTION_LITERAL_NOT_IDENTIFIED"
DIVIDEND_NOT_IN_RANGE = "NO_DIVIDEND_IN_USABLE_RANGE"
DIVIDEND_NO_COMPARABLE_ROWS = "NO_COMPARABLE_ROWS"


@dataclass(frozen=True)
class DividendReconciliation:
    """Outcome of reconciling the fully adjusted close against the split-adjusted close."""

    status: str
    model: str
    rows_compared: int
    events_applied: int
    worst_relative_deviation: float
    note: str


def _numeric_rows(rows: Sequence[Mapping[str, str]]) -> list[dict[str, float | str]]:
    """Rows carrying a date and all three closes, parsed. Anything else is dropped."""
    out: list[dict[str, float | str]] = []
    for row in rows:
        try:
            parsed: dict[str, float | str] = {
                "date": str(row["date"]),
                "close": float(row["close"]),
                "closeadj": float(row["closeadj"]),
                "closeunadj": float(row["closeunadj"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if any(parsed[key] <= 0 for key in ("close", "closeadj", "closeunadj")):
            continue
        out.append(parsed)
    return sorted(out, key=lambda r: str(r["date"]))


def action_date_base(
    rows_by_date: Mapping[str, Mapping[str, float | str]], event_date: str, column: str
) -> float | None:
    """The close ON an action date, or None when the sample has no row for that date.

    The vendor's ratio is computed from the action-date close, so a missing row makes the
    event **unexercisable**. Substituting the nearest earlier close would silently answer a
    different question and would reconcile only by luck.
    """
    row = rows_by_date.get(event_date)
    if row is None:
        return None
    value = row.get(column)
    return float(value) if isinstance(value, (int, float)) and float(value) > 0 else None


def reconcile_dividend_adjustment(
    rows: Sequence[Mapping[str, str]],
    dividends: Sequence[tuple[str, float]],
    spinoff_dates: Sequence[str],
    literal_identified: bool,
    tolerance: float = SPLIT_TOLERANCE,
) -> DividendReconciliation:
    """Does ``close / closeadj`` equal the cumulative later cash-dividend ratio?

    Both series are the vendor's own, so the identity is internal to its data: ``close`` is
    split-adjusted, ``closeadj`` is split, dividend and spinoff adjusted, and adjustment is
    backward (`PSR-SHD-120`). Their ratio at a date is therefore the product of the dividend
    and spinoff ratios that fall after it.

    **The ratio base is the close on the action date**, per the vendor's worked example. An
    event whose date has no price row in the sample is *unexercisable*, and every row it
    would have adjusted is dropped rather than compared against a substituted base.

    **Rows a spinoff could explain are excluded rather than explained away.** A spinoff's
    ratio needs the spun-off entity's opening price, which this sample does not contain, so
    any row a spinoff sits after is dropped. What remains isolates the dividend mechanism,
    or is empty and says so.
    """
    if not literal_identified:
        return DividendReconciliation(
            status=INCONCLUSIVE,
            model=DIVIDEND_LITERAL_UNIDENTIFIED,
            rows_compared=0,
            events_applied=0,
            worst_relative_deviation=0.0,
            note=(
                "the observed action vocabulary does not identify a cash-dividend literal "
                "unambiguously, and the vendor documents no action-type list; guessing one "
                "would be inventing the semantics this test exists to check"
            ),
        )

    ordered = _numeric_rows(rows)
    if not ordered:
        # Missing evidence, not a failed comparison.
        return DividendReconciliation(
            status=NOT_EXERCISED,
            model=DIVIDEND_NO_COMPARABLE_ROWS,
            rows_compared=0,
            events_applied=0,
            worst_relative_deviation=0.0,
            note="no row carried a date and all three close columns, so the limb did not run",
        )

    by_date: dict[str, Mapping[str, float | str]] = {str(r["date"]): r for r in ordered}
    last_spinoff = max(spinoff_dates) if spinoff_dates else None

    # The ratio base is the close ON the action date. A dividend whose date has no price
    # row cannot be computed, and the rows it would have adjusted are dropped rather than
    # compared against a substituted base.
    exercisable: list[tuple[str, float, float, float]] = []
    unexercisable: list[str] = []
    for event_date, amount in sorted(dividends):
        base_unadj = action_date_base(by_date, event_date, "closeunadj")
        base_close = action_date_base(by_date, event_date, "close")
        if base_unadj is None or base_close is None:
            unexercisable.append(event_date)
            continue
        exercisable.append((event_date, amount, base_unadj, base_close))
    blocked = max(unexercisable) if unexercisable else None

    # An event adjusts rows that PRECEDE it, so a row at or after an unexercisable event
    # is unaffected by it and stays comparable.
    usable = [
        r
        for r in ordered
        if (last_spinoff is None or str(r["date"]) > last_spinoff)
        and (blocked is None or str(r["date"]) >= blocked)
    ]
    if not usable:
        return DividendReconciliation(
            status=NOT_EXERCISED,
            model=DIVIDEND_NO_COMPARABLE_ROWS,
            rows_compared=0,
            events_applied=0,
            worst_relative_deviation=0.0,
            note=(
                "every row sits before a spinoff or an unexercisable dividend, so none "
                "isolates the cash-dividend mechanism and the limb did not run"
            ),
        )

    earliest = str(usable[0]["date"])
    events_applied = sum(1 for event_date, _, _, _ in exercisable if event_date > earliest)

    matching: list[str] = []
    model_worsts: list[float] = []
    for name, column in DIVIDEND_MODELS:
        model_worst = 0.0
        matches = 0
        for row in usable:
            factor = 1.0
            for event_date, amount, base_unadj, base_close in exercisable:
                if event_date <= str(row["date"]):
                    continue
                base = base_unadj if column == "closeunadj" else base_close
                factor *= (base + amount) / base
            actual = float(row["close"]) / float(row["closeadj"])
            deviation = abs(factor - actual) / actual
            model_worst = max(model_worst, deviation)
            if deviation <= tolerance:
                matches += 1
        if matches == len(usable):
            matching.append(name)
        model_worsts.append(model_worst)

    # The best model's worst row. An earlier revision seeded this at 0.0 and treated that
    # as "unset", so a genuinely perfect model was overwritten by a worse later one and the
    # private report published the wrong diagnostic.
    worst = min(model_worsts) if model_worsts else 0.0

    if events_applied == 0:
        agrees = all(
            abs(float(r["close"]) / float(r["closeadj"]) - 1.0) <= tolerance for r in usable
        )
        return DividendReconciliation(
            status=PARTIALLY_TESTED if agrees else INCONCLUSIVE,
            model=DIVIDEND_NOT_IN_RANGE,
            rows_compared=len(usable),
            events_applied=0,
            worst_relative_deviation=worst,
            note=(
                "no cash dividend falls in the usable range, so the two series agree "
                "trivially and the dividend mechanism is not exercised"
                if agrees
                else "the two series differ with no dividend or spinoff recorded that "
                "could explain the difference"
            ),
        )

    if not matching:
        return DividendReconciliation(
            status=INCONCLUSIVE,
            model=DIVIDEND_MODEL_UNRESOLVED,
            rows_compared=len(usable),
            events_applied=events_applied,
            worst_relative_deviation=worst,
            note=(
                "neither share basis for the recorded dividend amount "
                "reconciles every row; the adjustment method is not established"
            ),
        )

    return DividendReconciliation(
        status=TESTED,
        model=matching[0] if len(matching) == 1 else DIVIDEND_MODELS_AGREE,
        rows_compared=len(usable),
        events_applied=events_applied,
        worst_relative_deviation=worst,
        note=(
            "the vendor's fully adjusted close reconciles against its split-adjusted close "
            "and the published cash-dividend ratio"
        ),
    )


#: The columns the split and dividend limbs both depend on. Without them the actions table
#: cannot answer anything, and must not be read as answering "nothing happened".
REQUIRED_ACTION_COLUMNS = frozenset({"date", "action", "value"})


def actions_usable(actions: TableSample | None) -> tuple[bool, str]:
    """Can the actions table be used as evidence? Returns ``(usable, reason)``.

    **"No actions table" is not "the actions table says no actions."** That collapse is the
    dangerous one: a failed, malformed or empty response makes every extractor return an
    empty list, which reads downstream as "no split, no dividend, no spinoff" -- and the
    split limb would then reconcile trivially and partially validate P5 on the strength of
    a request that never arrived.

    An **empty** table is refused for the same reason. Over a five-year window a security
    with literally no corporate action is possible but unremarkable-looking, and it is
    indistinguishable from a silently truncated response. The cost of being wrong is a
    false partial validation, so the absence of rows is treated as absence of evidence.
    """
    if actions is None:
        return False, "actions: not requested or not present in the sample"
    if actions.fetch_error is not None:
        return False, f"actions: retrieval failed ({actions.fetch_error})"
    if actions.parse_error is not None:
        return False, f"actions: unparseable ({actions.parse_error})"
    if not actions.columns:
        return False, "actions: no header row"
    present = {column.strip().lower() for column in actions.columns}
    missing = sorted(REQUIRED_ACTION_COLUMNS - present)
    if missing:
        return False, f"actions: missing required column(s) {', '.join(missing)}"
    if not actions.rows:
        return False, (
            "actions: the table returned no rows, which is indistinguishable from a "
            "truncated response and is not read as 'no corporate actions occurred'"
        )
    return True, ""


#: Action literals that plainly cannot change the split-adjusted price relationship. The
#: vendor's own prose names ticker changes, listings and delistings among the event types
#: the table carries (`PSR-SHD-095`), and none of them is a float or price event.
#:
#: The list is short **because it has to be justifiable**. Everything outside it is treated
#: as potentially price-affecting, which is the fail-closed direction: an ADR ratio change,
#: for instance, rescales shares exactly as a split does.
PRICE_NEUTRAL_ACTION_HINTS = ("ticker", "list", "name")


def unmodelled_action_literals(
    vocabulary: Sequence[str], modelled: Container[str]
) -> tuple[str, ...]:
    """Observed literals that are neither modelled nor demonstrably price-neutral.

    The vendor publishes no action-type vocabulary, so an unrecognised literal cannot be
    interpreted -- and that is the reason it confounds rather than the reason to ignore it.
    No semantics are invented for it; its mere presence in the compared window is enough to
    make a split-limb disagreement unattributable.
    """
    return tuple(
        literal
        for literal in vocabulary
        if literal not in modelled
        and not any(hint in literal for hint in PRICE_NEUTRAL_ACTION_HINTS)
    )


def extract_dated_events(actions: TableSample | None, literal: str) -> list[str]:
    """Dates for one action literal, without requiring a parseable ``value``.

    An unmodelled literal may carry a value we cannot read; its *date* is still enough to
    know whether it falls inside the compared window.
    """
    if actions is None or not actions.usable or not literal:
        return []
    return sorted(
        str(row["date"])
        for row in actions.rows
        if str(row.get("action", "")).strip().lower() == literal and row.get("date")
    )


def stock_dividend_literals(vocabulary: Sequence[str]) -> tuple[str, ...]:
    """Observed literals that look like a stock dividend.

    A stock dividend changes the float, so the vendor adjusts it with the *same*
    ``New Float / Old Float`` ratio as a split (`PSR-SHD-120`) -- and the split-adjusted
    close would therefore carry it too. The actions page publishes neither the action-type
    vocabulary nor the per-type meaning of ``value`` (`PSR-SHD-112`), so such an event
    cannot be translated safely. Where one could touch the comparison, the split limb is
    confounded rather than failed.
    """
    return tuple(literal for literal in vocabulary if "dividend" in literal and "stock" in literal)


#: The one action literal the vendor evidences, in its own published query example
#: (`PSR-SHD-118`: `...&action=split&...`). Every other literal must be OBSERVED in the
#: retrieved vocabulary rather than assumed, because the actions page documents neither the
#: action-type list nor the per-type meaning of `value` (`PSR-SHD-112`).
SPLIT_ACTION = "split"


def extract_dated_values(actions: TableSample | None, literal: str) -> list[tuple[str, float]]:
    """Dated numeric values for one action literal. Anything unparseable is dropped."""
    if actions is None or not actions.usable or not literal:
        return []
    out: list[tuple[str, float]] = []
    for row in actions.rows:
        if str(row.get("action", "")).strip().lower() != literal:
            continue
        try:
            out.append((str(row["date"]), float(row["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out)


def extract_splits(actions: TableSample | None) -> list[tuple[str, float]]:
    """Dated split factors. The only action literal the vendor's own examples evidence."""
    return extract_dated_values(actions, SPLIT_ACTION)


def observed_action_vocabulary(actions: TableSample | None) -> tuple[str, ...]:
    """The distinct action literals actually present in the retrieved table.

    The vendor publishes no action-type list, so the vocabulary is **observed** rather than
    assumed. Observing it is evidence; guessing it would be invention.
    """
    if actions is None or not actions.usable:
        return ()
    return tuple(
        sorted({str(row.get("action", "")).strip().lower() for row in actions.rows} - {""})
    )


#: How an action literal resolved against the observed vocabulary. The distinction between
#: ABSENT and AMBIGUOUS is load-bearing: "no dividend occurred in this window" leaves the
#: limb unexercised, while "several dividend-like literals exist" means the harness must not
#: choose one. Collapsing them would turn a quiet sample into a provider finding.
LITERAL_IDENTIFIED = "IDENTIFIED"
LITERAL_ABSENT = "ABSENT"
LITERAL_AMBIGUOUS = "AMBIGUOUS"


def classify_action_literal(
    vocabulary: Sequence[str], include: str, exclude: str = ""
) -> tuple[str | None, str]:
    """Resolve one action literal against the observed vocabulary.

    Returns ``(literal, state)``. A single match is ``IDENTIFIED``; no match is ``ABSENT``;
    several matches are ``AMBIGUOUS`` and the literal is None, because picking a favourite
    would invent exactly the semantics this test exists to check.
    """
    matches = [
        literal
        for literal in vocabulary
        if include in literal and not (exclude and exclude in literal)
    ]
    if len(matches) == 1:
        return matches[0], LITERAL_IDENTIFIED
    if not matches:
        return None, LITERAL_ABSENT
    return None, LITERAL_AMBIGUOUS


def infer_action_literal(vocabulary: Sequence[str], include: str, exclude: str = "") -> str | None:
    """The single observed literal matching a hint, or None if it is absent or ambiguous."""
    literal, _state = classify_action_literal(vocabulary, include, exclude)
    return literal


# ---------------------------------------------------------------------------
# Operational validation -- did the run actually retrieve what it set out to?
# ---------------------------------------------------------------------------

#: Columns each table must carry before the run counts as operationally complete. These are
#: the vendor's own documented column names; requiring them catches a wrong-schema response
#: that arrived with HTTP 200 and would otherwise be indistinguishable from a good one.
REQUIRED_TABLE_COLUMNS: Mapping[str, frozenset[str]] = {
    "tickers": frozenset({"ticker", "permaticker", "name"}),
    "stocks": frozenset({"ticker", "date", "close", "closeadj", "closeunadj", "lastupdated"}),
    "actions": frozenset({"date", "action", "value"}),
    "fundamentals": frozenset({"ticker", "datekey", "reportperiod", "calendardate"}),
    "events": frozenset({"ticker", "date", "eventcodes"}),
}


def validate_retrieved_inventory(
    samples: Mapping[str, TableSample], ticker: str = SAMPLE_TICKER
) -> tuple[bool, tuple[str, ...]]:
    """Is every table in the fixed inventory actually usable? Returns ``(ok, problems)``.

    **HTTP success is not retrieval success**, and the gap between them is where a run
    quietly stops meaning what it claims. A request can return 200 and still yield malformed
    CSV, invalid UTF-8, a header with no rows, a truncated body or an entirely different
    schema. None of those appears in the fetch-error list, so a run built only on that list
    would call itself complete and could reach PROCEED on evidence it never had.

    Problems are phrased from table names and column names only -- the vendor's own public
    schema. **No vendor row, count or value enters a problem string**, because the private
    report is the only place this text is allowed to appear and it should not need to be.
    """
    problems: list[str] = []
    for table, _windowed in REQUEST_INVENTORY:
        sample = samples.get(table)
        if sample is None:
            problems.append(f"{table}: not retrieved")
            continue
        if sample.fetch_error is not None:
            problems.append(f"{table}: retrieval failed ({sample.fetch_error})")
            continue
        if sample.parse_error is not None:
            problems.append(f"{table}: unparseable ({sample.parse_error})")
            continue
        if not sample.columns:
            problems.append(f"{table}: no header row")
            continue

        present = {column.strip().lower() for column in sample.columns}
        missing = sorted(REQUIRED_TABLE_COLUMNS.get(table, frozenset()) - present)
        if missing:
            problems.append(f"{table}: missing documented column(s) {', '.join(missing)}")
            continue
        if not sample.rows:
            problems.append(f"{table}: returned no rows")
            continue

        if table == "tickers" and not any(
            str(row.get("ticker", "")).strip().upper() == ticker.upper() for row in sample.rows
        ):
            problems.append("tickers: no row for the requested security")
        if table == "stocks" and not _numeric_rows(sample.rows):
            problems.append("stocks: no row carried a date with all three close columns")
        if table == "actions":
            usable, reason = actions_usable(sample)
            if not usable:
                problems.append(reason)

    return not problems, tuple(problems)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One provider test's PRIVATE outcome. Never printed, never committed."""

    test_id: str
    title: str
    status: str
    observations: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    attributes: Mapping[str, str] = field(default_factory=dict)


def _sample(samples: Mapping[str, TableSample], table: str) -> TableSample | None:
    found = samples.get(table)
    return found if found is not None and found.usable else None


def evaluate_p1(samples: Mapping[str, TableSample]) -> Finding:
    """Provider-availability semantics and origin.

    A single ingestion cannot show that ``lastupdated`` moves on change; that needs two
    ingestions separated by real calendar time. What one snapshot *can* do is corroborate
    or contradict the documented reading, and record the column's resolution. It cannot
    establish ``system_first_seen``, and this function does not pretend otherwise --
    :data:`STATUS_CEILING` keeps it below ``TESTED`` structurally.
    """
    observations: list[str] = []
    status = INCONCLUSIVE
    corroborates = "UNDETERMINED"

    for table in ("stocks", "fundamentals"):
        sample = _sample(samples, table)
        if sample is None:
            observations.append(f"{table}: not retrieved or unparseable")
            continue
        if "lastupdated" not in sample.columns:
            observations.append(f"{table}: no lastupdated column present")
            continue
        values = sorted({str(r.get("lastupdated", "")).strip() for r in sample.rows} - {""})
        dates = sorted({str(r.get("date", "")).strip() for r in sample.rows} - {""})
        day_resolution = bool(values) and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) for v in values)
        observations.append(
            f"{table}: {len(values)} distinct lastupdated value(s) across {len(dates)} "
            f"row date(s); day resolution: {day_resolution}"
        )
        if values and dates:
            status = PARTIALLY_TESTED
            # Many old row dates sharing few recent lastupdated values is what a
            # *last changed* column looks like; a *first appeared* column would track
            # the row date. This corroborates, it does not prove.
            if len(values) < len(dates) and max(values) > min(dates):
                corroborates = "CONSISTENT_WITH_LAST_CHANGED"
            else:
                corroborates = "NOT_DISTINGUISHED_BY_THIS_SAMPLE"

    return Finding(
        test_id="P1",
        title="Provider-availability semantics and origin",
        status=status,
        observations=tuple(observations),
        limitations=("PROVIDER_AVAILABILITY_UNKNOWN", "PROVIDER_TIME_BOUNDED"),
        attributes={
            "gap_policy": P1_GAP_POLICY,
            "sample_corroboration": corroborates,
            "why_not_tested": (
                "first availability needs two ingestions separated by a real vendor "
                "update; one snapshot cannot observe a change"
            ),
        },
    )


def evaluate_p2() -> Finding:
    """Delisted coverage is real.

    Takes no sample argument, and that is the guard. A single-name, five-year probe of a
    listed mega-cap contains no security delisted 5, 10 or 15 years ago, so there is no
    input from which a pass could be computed and no way for one to be manufactured.
    """
    return Finding(
        test_id="P2",
        title="Delisted coverage is real",
        status=NOT_TESTABLE_WITH_PUBLIC_SAMPLE,
        observations=(
            "the public test surface covers a single listed security; delisted coverage "
            "at 5, 10 and 15 years cannot be sampled from it",
        ),
        limitations=("SURVIVORSHIP_CONTROL_UNVERIFIED",),
        attributes={
            "requires": "Full History tier plus an independently sourced delisted name list",
            "blocking": "yes -- Phase 3 acceptance criterion 2 fails on zero delisted members",
        },
    )


def evaluate_p3(samples: Mapping[str, TableSample]) -> Finding:
    """Corporate-action announcement timing -- already settled by public documentation."""
    actions = _sample(samples, "actions")
    observations: list[str] = []
    announce_like = ()
    if actions is None:
        observations.append("actions: not retrieved or unparseable; documentation stands alone")
    else:
        announce_like = tuple(
            c
            for c in actions.columns
            if any(token in c.lower() for token in ("announce", "declar", "exdate", "ex_date"))
        )
        observations.append(
            f"actions: {len(actions.columns)} column(s); "
            f"{len(announce_like)} announcement/declaration-like column(s)"
        )
    return Finding(
        test_id="P3",
        title="Corporate-action announcement timing",
        status=DOCUMENTATION_RESOLVED,
        observations=tuple(observations),
        limitations=("CORPORATE_ACTION_ANNOUNCE_APPROXIMATED",),
        attributes={
            "public_documentation": "seven columns, one date, no announcement or declaration date",
            "consequence": "the contract s.9 lag applies and the token is declared",
            "still_open": "what the single date column means per action type is undocumented",
        },
    )


def evaluate_p4() -> Finding:
    """Classification history -- settled by public documentation, and settled adversely.

    Takes no sample argument, and the reason is the correction that produced this version.
    The tickers table is a **snapshot**: the vendor states that its 5, 10 and full bulk
    options all download the same table (`PSR-SHD-119`), and the schema carries no dated
    classification series (`PSR-SHD-113`). A table with no temporal axis cannot be given one
    by the rows it returns.

    An earlier version read *differing* sector/industry values across snapshot rows for one
    issuer as evidence of history. That was wrong, and wrong in the dangerous direction: it
    could **drop** the conservative `CLASSIFICATION_STATIC` limitation on the strength of
    undated metadata inconsistency. Differing values in a snapshot mean the snapshot
    disagrees with itself; they say nothing about when a classification changed. The
    limitation is now a constant, and :func:`validate_findings` refuses a P4 finding without
    it.
    """
    return Finding(
        test_id="P4",
        title="Classification history",
        status=DOCUMENTATION_RESOLVED,
        observations=(
            "the tickers table is a documented snapshot -- the 5, 10 and full bulk options "
            "all download the same table, so it carries no historical axis",
            "no dated sector/industry series is documented or obtainable",
            "differing classification values across snapshot rows would indicate "
            "inconsistent current metadata, never a dated change, and are not read as one",
        ),
        limitations=("CLASSIFICATION_STATIC",),
        attributes={
            "source_shape": "SNAPSHOT",
            "consequence": (
                "CLASSIFICATION_STATIC is declared on every dependent result and never "
                "silently used"
            ),
            "how_it_could_change": (
                "a dated classification source, not a larger sample of this table"
            ),
        },
    )


def evaluate_p5(samples: Mapping[str, TableSample]) -> Finding:
    """Adjusted/raw reconciliation -- three limbs, reported separately.

    **This test was rewritten when the vendor published its adjustment methodology**
    (`PSR-SHD-120`, 2026-07-29). An earlier version recorded the dividend and spinoff
    formulas as *unpublished*; that is no longer true, and leaving it would have been a
    different kind of dishonesty from the one the original wording guarded against.

    Publishing a formula is not the same as making it exercisable, so the correction does
    not swing the other way. Each limb is reported on its own evidence:

    ``split``
        Genuinely testable. ``close`` and ``closeunadj`` are the same series under two
        adjustment policies, and ``action=split`` is the one action literal the vendor's own
        query examples evidence.
    ``cash dividend``
        Testable *if* the observed action vocabulary names cash dividends unambiguously and
        no spinoff confounds the window. The published ratio is
        ``(Close + Dividend) / Close`` on the **action-date** close, with preceding
        history adjusted backward from it; which price series the dividend amount is
        expressed against is not stated, so both candidates are evaluated and the answer
        is observed.
    ``spinoff``
        **Never testable from this surface.** The published ratio needs the spun-off
        entity's opening price and share counts -- another security's data -- and the
        meaning of ``actions.value`` on a spinoff row is undocumented. It is ``NOT_EXERCISED``
        when absent and ``INCONCLUSIVE`` when present, and it is why P5 cannot reach
        ``TESTED``: the full mechanism is never genuinely exercised.
    """
    stocks = _sample(samples, "stocks")
    actions = samples.get("actions")
    if stocks is None:
        # Nothing ran, so no limb FAILED. The distinction matters downstream: a REJECT is
        # reserved for the vendor's own series contradicting each other, and that verdict
        # must never be reachable from a table we simply could not retrieve.
        return Finding(
            test_id="P5",
            title="Adjusted/raw reconciliation",
            status=INCONCLUSIVE,
            observations=(
                "stocks: not retrieved or unparseable, so no limb was exercised",
                "this is missing evidence, not a reconciliation failure",
            ),
            limitations=("ADJUSTMENT_UNVERIFIED",),
            attributes={
                "split_limb": NOT_EXERCISED,
                "dividend_limb": NOT_EXERCISED,
                "spinoff_limb": NOT_EXERCISED,
                "evidence": "STOCKS_NOT_RETRIEVED",
            },
        )

    usable, reason = actions_usable(actions)
    if not usable:
        # Every extractor would return an empty list here, which downstream reads as "no
        # split, no dividend, no spinoff" -- and the split limb would then reconcile
        # trivially. Refusing at the source is the only place this stays honest.
        return Finding(
            test_id="P5",
            title="Adjusted/raw reconciliation",
            status=INCONCLUSIVE,
            observations=(
                reason,
                "no limb was exercised: an unusable actions table is absence of evidence, "
                "not evidence that no corporate action occurred",
            ),
            limitations=("ADJUSTMENT_UNVERIFIED",),
            attributes={
                "split_limb": NOT_EXERCISED,
                "dividend_limb": NOT_EXERCISED,
                "spinoff_limb": NOT_EXERCISED,
                "evidence": "ACTIONS_NOT_USABLE",
            },
        )

    vocabulary = observed_action_vocabulary(actions)
    splits = extract_splits(actions)
    split_result = reconcile_split_adjustment(stocks.rows, splits)

    spinoff_literal, spinoff_state = classify_action_literal(vocabulary, "spin")
    spinoffs = extract_dated_values(actions, spinoff_literal or "")
    dividend_literal, dividend_state = classify_action_literal(
        vocabulary, "dividend", exclude="stock"
    )
    dividends = extract_dated_values(actions, dividend_literal or "")

    # ABSENT is not AMBIGUOUS. With no dividend literal at all there is nothing to
    # misidentify, and the reconciliation still checks the weaker claim that the two series
    # agree where no event could separate them.
    dividend_result = reconcile_dividend_adjustment(
        stocks.rows,
        dividends,
        [date for date, _ in spinoffs],
        dividend_state != LITERAL_AMBIGUOUS,
    )

    # The spinoff limb has no computable form here, so it is not "run and failed" -- it is
    # either absent from the sample or present and unanswerable. Both are recorded as such.
    if spinoff_state == LITERAL_AMBIGUOUS:
        # Several spin-like literals. Treating that as "no spinoff" would collapse
        # AMBIGUOUS into ABSENT and let the dividend limb compare rows a spinoff may sit
        # after -- the exact confusion the dividend limb was already fixed to avoid.
        spinoff_status = INCONCLUSIVE
        spinoff_note = (
            "the observed action vocabulary names several spin-like literals and the vendor "
            "publishes no action-type list, so which rows are spinoffs cannot be determined "
            "and no row can be trusted to be free of one"
        )
    elif spinoffs:
        spinoff_status = INCONCLUSIVE
        spinoff_note = (
            "a spinoff falls in the sampled range and its adjustment ratio needs the "
            "spun-off entity's opening price and share counts, which this sample does not "
            "contain; actions.value semantics for a spinoff row are undocumented"
        )
    else:
        spinoff_status = NOT_EXERCISED
        spinoff_note = "no spinoff falls in the sampled range, so the limb did not run"

    # Any observed literal we do not model could be another float-changing event -- an ADR
    # ratio change behaves like a split, and the vendor publishes no action-type list at
    # all. Where such an event could touch the comparison, a split-limb disagreement has an
    # innocent explanation and must not be read as vendor corruption. Nothing is *assumed*
    # about an unknown literal; it is precisely because nothing can be assumed that it
    # confounds.
    modelled = {SPLIT_ACTION}
    if dividend_literal:
        modelled.add(dividend_literal)
    if spinoff_literal:
        modelled.add(spinoff_literal)
    confounders = tuple(
        literal
        for literal in unmodelled_action_literals(vocabulary, modelled)
        if split_result.earliest_compared
        and any(
            date > split_result.earliest_compared for date in extract_dated_events(actions, literal)
        )
    )
    split_status = INCONCLUSIVE if confounders else split_result.status
    split_convention = "CONFOUNDED" if confounders else split_result.convention

    # The split and dividend limbs are REQUIRED evidence: a limb that did not run leaves P5
    # inconclusive rather than partially satisfied. Only the spinoff limb may legitimately
    # be NOT_EXERCISED, because it can never run from this surface at all.
    required = (split_status, dividend_result.status)
    status = (
        INCONCLUSIVE
        if spinoff_status == INCONCLUSIVE
        or any(limb not in (TESTED, PARTIALLY_TESTED) for limb in required)
        else PARTIALLY_TESTED
    )
    # PARTIALLY_TESTED is the ceiling and TESTED is unreachable, because the spinoff limb is
    # NOT_EXERCISED at best. That is deliberate: a mechanism never run end to end is not
    # proven by the parts of it that did run.

    limitations: list[str] = []
    if split_status != TESTED:
        limitations.append("ADJUSTMENT_UNVERIFIED")
    if confounders:
        limitations.append("SPLIT_ADJUSTMENT_CONFOUNDED_BY_UNMODELLED_ACTION")
    if dividend_result.status != TESTED:
        limitations.append("DIVIDEND_ADJUSTMENT_UNVERIFIED")
    limitations.append(
        "SPINOFF_ADJUSTMENT_INPUTS_UNAVAILABLE" if spinoffs else "SPINOFF_ADJUSTMENT_UNEXERCISED"
    )

    return Finding(
        test_id="P5",
        title="Adjusted/raw reconciliation",
        status=status,
        observations=(
            f"observed action vocabulary: {len(vocabulary)} literal(s); "
            f"cash-dividend literal {dividend_state}",
            f"split limb: {split_status} ({split_convention}); "
            f"rows compared {split_result.rows_compared}, "
            f"splits present {split_result.splits_in_range}, "
            f"splits actually exercised {split_result.splits_exercised}",
            f"unmodelled split-like action literals touching the comparison: {len(confounders)}",
            f"split exclusive matches {split_result.exclusive_matches}, "
            f"inclusive matches {split_result.inclusive_matches}, "
            f"worst relative deviation {split_result.worst_relative_deviation:.6f}",
            split_result.note,
            f"cash-dividend limb: {dividend_result.status} ({dividend_result.model}); "
            f"rows compared {dividend_result.rows_compared}, "
            f"dividends applied {dividend_result.events_applied}",
            dividend_result.note,
            f"spinoff limb: {spinoff_status} -- {spinoff_note}",
        ),
        limitations=tuple(limitations),
        attributes={
            "split_limb": split_status,
            "split_convention": split_convention,
            "split_confounded": "true" if confounders else "false",
            "dividend_limb": dividend_result.status,
            "dividend_model": dividend_result.model,
            "spinoff_limb": spinoff_status,
            "tolerance": f"{SPLIT_TOLERANCE}",
            "why_not_tested": (
                "the spinoff limb cannot be exercised from this surface, so the full "
                "adjustment mechanism is never verified end to end"
            ),
        },
    )


def evaluate_p6() -> Finding:
    """Known-restatement qualification -- settled adversely by public documentation.

    Takes no sample argument. The public surface cannot supply a documented multi-step
    restatement chronology, because the vendor does not model one: AR excludes
    restatements and MR is updated in place (`PSR-SHD-115`).
    """
    return Finding(
        test_id="P6",
        title="Known-restatement qualification",
        status=DOCUMENTATION_RESOLVED,
        observations=(
            "as-reported excludes restatements; most-recent-reported is updated in place "
            "and indexed to the report period, so a restated value carries no time at "
            "which it became knowable",
            "the public test surface cannot exhibit a multi-step restatement chronology",
        ),
        limitations=("REVISION_CHRONOLOGY_INCOMPLETE",),
        attributes={
            "revision_chronology_completeness": "FIRST_AND_LATEST_ONLY",
            "as_known_at_as_of": "requires EDGAR -- not obtainable from this provider alone",
        },
    )


def evaluate_p7(samples: Mapping[str, TableSample]) -> Finding:
    """Filing linkage -- schema only here; acceptance-time linkage is Phase 3B."""
    fundamentals = _sample(samples, "fundamentals")
    observations: list[str] = []
    if fundamentals is None:
        observations.append("fundamentals: not retrieved or unparseable")
    else:
        date_like = tuple(
            c
            for c in fundamentals.columns
            if any(token in c.lower() for token in ("date", "period", "quarter"))
        )
        observations.append(f"fundamentals: {len(date_like)} date-like column(s) present")
        observations.append(
            "filingdate column present: "
            f"{'filingdate' in (c.lower() for c in fundamentals.columns)}"
        )
    observations.append(
        "resolving a row to an EDGAR filing with an acceptance timestamp requires EDGAR "
        "access, which is Phase 3B and is unverified from this environment"
    )
    return Finding(
        test_id="P7",
        title="Filing linkage",
        status=DEFERRED,
        observations=tuple(observations),
        limitations=("FILING_LINKAGE_UNVERIFIED",),
        attributes={"deferred_to": "Phase 3B / EDGAR"},
    )


def evaluate_p8(samples: Mapping[str, TableSample]) -> Finding:
    """Earnings timing fidelity -- deferred; this task does not open an EDGAR project."""
    events = _sample(samples, "events")
    observations: list[str] = []
    if events is None:
        observations.append("events: not retrieved or unparseable")
    else:
        time_like = tuple(
            c
            for c in events.columns
            if any(token in c.lower() for token in ("time", "hour", "market", "session"))
        )
        observations.append(
            f"events: {len(events.columns)} column(s); {len(time_like)} time-like column(s)"
        )
    observations.append(
        "comparing vendor timing against 8-K acceptance times requires EDGAR and is "
        "deliberately not started here"
    )
    return Finding(
        test_id="P8",
        title="Earnings timing fidelity",
        status=DEFERRED,
        observations=tuple(observations),
        limitations=("EARNINGS_TIME_APPROXIMATED",),
        attributes={"deferred_to": "Phase 3B / EDGAR"},
    )


def evaluate_p9() -> Finding:
    """Bar construction and origin -- unanswerable from data, by construction.

    Takes no sample argument, and never will. P9 asks a question about the vendor's
    production process; no arrangement of price values answers it, and inferring an
    official-public origin from plausible-looking bars is precisely the error that would
    make every downstream ``PUBLIC_PIT`` claim unfounded.
    """
    return Finding(
        test_id="P9",
        title="Bar construction and origin",
        status=DOCUMENTATION_RESOLVED,
        observations=(
            "public documentation does not state whether the daily bars are officially "
            "disseminated or aggregated by the provider",
            "no sample of values can establish provenance, so none was inferred",
        ),
        limitations=("BAR_ORIGIN_UNSTATED",),
        attributes={
            "information_origin": P9_INFORMATION_ORIGIN,
            "eligible_profile": P9_ELIGIBLE_PROFILE,
            "not_eligible_profile": FORBIDDEN_P9_PROFILE,
            "consequence": (
                "provider-realistic research may continue; public-PIT eligibility for "
                "prices, and for the universe built on them, is not claimed"
            ),
        },
    )


def evaluate_all(samples: Mapping[str, TableSample]) -> tuple[Finding, ...]:
    """Every provider test, in order. Pure: no network, no filesystem, no AWS."""
    return (
        evaluate_p1(samples),
        evaluate_p2(),
        evaluate_p3(samples),
        evaluate_p4(),
        evaluate_p5(samples),
        evaluate_p6(),
        evaluate_p7(samples),
        evaluate_p8(samples),
        evaluate_p9(),
    )


def validate_findings(findings: Sequence[Finding]) -> None:
    """Refuse a findings set that claims more than the public sample can support.

    This is the structural half of the anti-optimism rule. The evaluators are written
    honestly; this makes a *dishonest* one impossible to publish through the report
    builder, however it came to be written or edited later.
    """
    seen = {f.test_id for f in findings}
    missing = tuple(t for t in TEST_IDS if t not in seen)
    if missing:
        raise SafeHarnessError("validate", f"MISSING_FINDINGS_{'_'.join(missing)}")

    for finding in findings:
        if finding.status not in STATUSES:
            raise SafeHarnessError("validate", f"UNKNOWN_STATUS_{finding.test_id}")
        ceiling = STATUS_CEILING.get(finding.test_id)
        if ceiling is None:
            raise SafeHarnessError("validate", f"UNKNOWN_TEST_{finding.test_id}")
        if finding.status not in ceiling:
            raise SafeHarnessError("validate", f"STATUS_ABOVE_CEILING_{finding.test_id}")

        if finding.test_id == "P1" and finding.attributes.get("gap_policy") != P1_GAP_POLICY:
            raise SafeHarnessError("validate", "P1_GAP_POLICY_MUST_REMAIN_BOUND")

        if finding.test_id == "P9":
            if finding.attributes.get("eligible_profile") != P9_ELIGIBLE_PROFILE:
                raise SafeHarnessError("validate", "P9_PROFILE_MUST_REMAIN_PROVIDER_REALISTIC")
            if finding.attributes.get("information_origin") != P9_INFORMATION_ORIGIN:
                raise SafeHarnessError("validate", "P9_ORIGIN_MUST_REMAIN_PROVIDER_DERIVED")

        if finding.test_id == "P4" and "CLASSIFICATION_STATIC" not in finding.limitations:
            # The tickers table is a snapshot. Nothing a sample contains can retire this.
            raise SafeHarnessError("validate", "P4_MUST_RETAIN_CLASSIFICATION_STATIC")

        if finding.test_id == "P5":
            if finding.attributes.get("spinoff_limb") == TESTED:
                # The published spinoff ratio needs another security's opening price. A
                # TESTED spinoff limb would mean the harness had invented that input.
                raise SafeHarnessError("validate", "P5_SPINOFF_LIMB_CANNOT_BE_TESTED")
            missing = [
                limb
                for limb in ("split_limb", "dividend_limb", "spinoff_limb")
                if finding.attributes.get(limb) not in LIMB_STATUSES
            ]
            if missing:
                raise SafeHarnessError("validate", f"P5_LIMB_STATUS_MISSING_{missing[0].upper()}")

        if finding.test_id == "P6" and "REVISION_CHRONOLOGY_INCOMPLETE" not in finding.limitations:
            raise SafeHarnessError("validate", "P6_MUST_RETAIN_REVISION_CHRONOLOGY_LIMITATION")


def private_recommendation(findings: Sequence[Finding], retrieval_complete: bool) -> str:
    """The PRIVATE owner-only recommendation.

    **Never printed, never returned to an AI session, never committed, never in a PR.**
    It exists only inside the private report. It is computed here so the reasoning is
    reviewable in public source while its *result* stays private.

    ``retrieval_complete`` is required rather than defaulted. A report that says "retrieval
    incomplete" and "PROCEED" in the same breath would be self-contradictory, and a default
    would let a caller reach that state by forgetting an argument.

    **REJECT is deliberately unreachable from this harness.** It stays in the vocabulary for
    a future qualification with stronger evidence, but nothing here can earn it. The split
    limb's comparison rests on reading ``actions.value`` as the adjustment ratio, and the
    vendor documents ``value`` only as *numeric* -- it publishes no per-action-type meaning
    (`PSR-SHD-112`). The adjustment *formulas* being published (`PSR-SHD-120`) does not
    establish that this column carries the ratio they take. A failed reconciliation is
    therefore consistent with our interpretation being wrong, and convicting a provider on
    an interpretation we cannot verify is exactly the error this whole harness is shaped to
    avoid. A free single-name probe may return **PROCEED or HOLD**, and nothing else.
    """
    validate_findings(findings)
    by_id = {f.test_id: f for f in findings}

    p5 = by_id["P5"]

    # An incomplete run cannot support any conclusion about the provider. A limb may have
    # failed because of what did not arrive.
    if not retrieval_complete:
        return HOLD

    # **PROCEED requires both runnable limbs to have actually run and reconciled.**
    #
    # This is stricter than it looks, and deliberately so. The probe is a SINGLE security
    # over five years, and the security's most recent split may well fall outside that
    # window -- in which case the split limb reports PARTIALLY_TESTED on a trivial
    # agreement. Allowing that plus a passing dividend limb to reach PROCEED would let the
    # strongest available check be skipped by an accident of the calendar and still produce
    # a favourable answer. If the free surface cannot exercise the split limb, HOLD is the
    # honest result, and widening the window past the authorized five years to go hunting
    # for an old split is not the remedy.
    for limb in ("split_limb", "dividend_limb"):
        if p5.attributes.get(limb) != TESTED:
            return HOLD

    if any(by_id[t].status == INCONCLUSIVE for t in ("P1", "P5")):
        return HOLD
    return PROCEED


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def aws_s3_put(bucket: str, key: str, body: Path, profile: str) -> None:
    """Upload one object with the AWS CLI. Never prints stderr -- it can quote a bucket."""
    try:
        result = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "aws",
                "s3api",
                "put-object",
                "--bucket",
                bucket,
                "--key",
                key,
                "--body",
                str(body),
                "--profile",
                profile,
                "--output",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        raise SafeHarnessError("upload", "UPLOAD_TIMEOUT") from None
    except OSError:
        raise SafeHarnessError("upload", "AWS_CLI_UNAVAILABLE") from None
    if result.returncode != 0:
        raise SafeHarnessError("upload", "UPLOAD_REFUSED_BY_AWS")


@dataclass
class StagedPayload:
    """One raw vendor payload staged locally until it is safely in the licensed bucket."""

    table: str
    path: Path
    address: str
    uploaded: bool = False


def stage_payload(run_dir: Path, table: str, payload: bytes) -> StagedPayload:
    """Write a raw payload to the private staging area and content-address it."""
    address = content_address(payload)
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{table}-{address.split('/', 1)[1]}.csv"
    path.write_bytes(payload)
    return StagedPayload(table=table, path=path, address=address)


def upload_staged(
    staged: Sequence[StagedPayload],
    run_id: str,
    buckets: ResearchBuckets,
    profile: str,
    put: Callable[[str, str, Path, str], None] | None = None,
) -> tuple[StagedPayload, ...]:
    """Upload every staged payload to the LICENSED bucket. Returns the updated records.

    A failed upload is **not** fatal to the local evidence: the staged file is retained so
    the owner can retry, and only successfully uploaded files become eligible for
    deletion. Losing licensed evidence to a transient network fault would be a worse
    outcome than a temporary duplicate.
    """
    sender = put if put is not None else aws_s3_put
    bucket = assert_licensed_destination(buckets.licensed, buckets)
    out: list[StagedPayload] = []
    for item in staged:
        try:
            sender(bucket, raw_object_key(run_id, item.address), item.path, profile)
        except SafeHarnessError:
            out.append(replace(item, uploaded=False))
            continue
        out.append(replace(item, uploaded=True))
    return tuple(out)


def purge_uploaded(staged: Sequence[StagedPayload]) -> tuple[int, int]:
    """Delete local raw files that reached the licensed bucket. Returns (deleted, retained).

    Raw vendor payloads are licensed Services Data. Once they are in the deletion-first
    licensed store there is no reason for a second copy on the workstation, and every
    reason not to have one. Anything that did not upload is kept, deliberately.
    """
    deleted = 0
    retained = 0
    for item in staged:
        if not item.uploaded:
            retained += 1
            continue
        try:
            item.path.unlink(missing_ok=True)
            deleted += 1
        except OSError:
            retained += 1
    return deleted, retained


# ---------------------------------------------------------------------------
# The private report
# ---------------------------------------------------------------------------

REPORT_FILENAME = "private-qualification-report.html"

REPORT_BANNER = (
    "PRIVATE - SHARADAR LICENSED EVALUATION",
    "DO NOT PASTE INTO AI",
    "DO NOT COMMIT",
    "DO NOT POST TO GITHUB",
)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def render_private_report(
    run_id: str,
    findings: Sequence[Finding],
    recommendation: str,
    fetch_errors: Mapping[str, str],
    retained_raw: int,
    inventory_problems: Sequence[str] = (),
) -> str:
    """Render the owner-readable private report.

    It may carry empirical results because it is local and private. The banner is not
    decoration: this file is the one artifact of the run that would breach Terms s.8 if
    it were pasted into a chat, a pull request or an issue.
    """
    rows = []
    for finding in findings:
        observations = "".join(f"<li>{_escape(o)}</li>" for o in finding.observations)
        limitations = ", ".join(finding.limitations) or "none"
        attributes = "".join(
            f"<li><code>{_escape(k)}</code>: {_escape(v)}</li>"
            for k, v in sorted(finding.attributes.items())
        )
        rows.append(
            f"<tr><td><b>{_escape(finding.test_id)}</b><br>{_escape(finding.title)}</td>"
            f"<td><b>{_escape(finding.status)}</b></td>"
            f"<td><ul>{observations}</ul></td>"
            f"<td>{_escape(limitations)}<ul>{attributes}</ul></td></tr>"
        )

    errors = (
        "".join(f"<li>{_escape(t)}: {_escape(c)}</li>" for t, c in sorted(fetch_errors.items()))
        or "<li>none</li>"
    )
    unusable = (
        "".join(f"<li>{_escape(problem)}</li>" for problem in inventory_problems) or "<li>none</li>"
    )
    banner = "<br>".join(_escape(line) for line in REPORT_BANNER)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>PRIVATE - Sharadar qualification {_escape(run_id)}</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.45; }}
 .banner {{ background: #7f1d1d; color: #fff; padding: 1rem 1.25rem; font-weight: 700;
           font-size: 1.05rem; letter-spacing: .02em; border-radius: 6px; }}
 table {{ border-collapse: collapse; width: 100%; margin-top: 1.5rem; }}
 th, td {{ border: 1px solid #d4d4d8; padding: .55rem .7rem; vertical-align: top;
           text-align: left; font-size: .92rem; }}
 th {{ background: #f4f4f5; }}
 ul {{ margin: .3rem 0 0 1rem; padding: 0; }}
 code {{ background: #f4f4f5; padding: 0 .2rem; }}
 .rec {{ margin-top: 1.5rem; padding: 1rem; border: 2px solid #7f1d1d; border-radius: 6px; }}
</style></head><body>
<div class="banner">{banner}</div>

<h1>Sharadar private free-sample qualification</h1>
<p>Run <code>{_escape(run_id)}</code> &middot; public vendor test key only &middot;
no subscription, no vendor account, no private credential.</p>

<h2>P1&ndash;P9</h2>
<table>
<tr><th>Test</th><th>Status</th><th>Observations</th><th>Limitations and attributes</th></tr>
{"".join(rows)}
</table>

<h2>Retrieval problems</h2>
<p>Requests that failed outright:</p>
<ul>{errors}</ul>
<p>Requests that returned but were not usable &mdash; a wrong schema, an empty body or a
truncated response arrives with HTTP success and would otherwise pass unnoticed:</p>
<ul>{unusable}</ul>

<div class="rec">
<h2>Private recommendation</h2>
<p><b>{_escape(recommendation)}</b></p>
<p>This recommendation is PRIVATE. It was not printed to the console, is not encoded in
the program's exit code, and must not be repeated in Git, a pull request, a GitHub issue,
or any AI session.</p>
</div>

<h2>Next private action</h2>
<ul>
<li><b>P2 -- delisted coverage.</b> Untested: the public sample carries no security
delisted 5, 10 or 15 years ago. Exercising it needs paid Full History depth <i>and</i> an
independently sourced delisted-name list, so the vendor's own coverage does not choose the
sample.</li>
<li><b>P6 -- revision chronology. Full History does NOT solve this.</b> It is already
documentation-resolved as a Sharadar limitation: as-reported excludes restatements and
most-recent-reported is updated in place, so no revision chronology exists at any tier.
Buying more history buys more of the same two-view model.
<b>EDGAR / Phase 3B is the required route to <code>AS_KNOWN_AT_AS_OF</code></b>, and no
purchase substitutes for it.</li>
<li>Q7 (bar construction) and Q8 (Full History depth) are still unanswered and are now
unasked. Both must be settled before any purchase.</li>
<li>Locally retained raw payloads awaiting re-upload: {retained_raw}.</li>
<li>G1 remains OPEN. Sharadar is a qualification candidate, not a selected provider.</li>
</ul>

<p><b>{_escape(REPORT_BANNER[0])}</b></p>
</body></html>
"""


# ---------------------------------------------------------------------------
# Outcome, exit code and console
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HarnessOutcome:
    """What the *harness* did. Deliberately has no field for a provider verdict.

    The exit code is derived from this object and from nothing else, so there is no
    expression anywhere that could map a recommendation onto a process status. That is
    the point: an automation log or an AI transcript that sees only the exit code learns
    nothing about the provider.
    """

    ok: bool
    report_path: Path
    retained_raw: int = 0


def operational_exit_code(outcome: HarnessOutcome) -> int:
    """0 when the harness worked, 1 when it did not. Never a provider verdict."""
    return 0 if outcome.ok else 1


def console_lines(outcome: HarnessOutcome) -> tuple[str, ...]:
    """Everything the harness is permitted to say. An allowlist, not a filter.

    No P-status, no recommendation, no bucket name, no account id, no URL, no query
    string and no vendor row can reach a terminal through this function, because none of
    them is ever an input to it.
    """
    lines = [
        "PRIVATE QUALIFICATION RUN COMPLETE"
        if outcome.ok
        else "PRIVATE QUALIFICATION RUN INCOMPLETE",
        f"  local private report: {outcome.report_path}",
        "  This report is PRIVATE licensed evaluation material.",
        "  Do not paste it into an AI session. Do not commit it. Do not post it to GitHub.",
    ]
    if outcome.retained_raw:
        lines.append(
            f"  raw payloads retained locally for re-upload: {outcome.retained_raw} "
            "(they are licensed data -- keep them out of Git)"
        )
    return tuple(lines)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_private_qualification(
    authorization: LiveRunAuthorization,
    buckets: ResearchBuckets,
    now: datetime,
    runtime_root: Path = RUNTIME_ROOT,
    ticker: str = SAMPLE_TICKER,
    fetcher: Callable[[LiveRunAuthorization, str, Sequence[tuple[str, str]], Pacer], bytes]
    | None = None,
    put: Callable[[str, str, Path, str], None] | None = None,
) -> HarnessOutcome:
    """Fetch, qualify, store, report. The only function that does all four."""
    run_id = make_run_id(now)
    run_dir = runtime_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    pacer = Pacer()
    fetch = fetcher if fetcher is not None else fetch_table

    staged: list[StagedPayload] = []
    samples: dict[str, TableSample] = {}
    fetch_errors: dict[str, str] = {}

    window = five_year_window(now)
    for table, windowed in REQUEST_INVENTORY:
        params = build_request_params(table, windowed, window, ticker)
        try:
            payload = fetch(authorization, table, params, pacer)
        except SafeHarnessError as exc:
            fetch_errors[table] = exc.code
            samples[table] = TableSample(table=table, fetch_error=exc.code)
            continue
        item = stage_payload(run_dir, table, payload)
        staged.append(item)
        samples[table] = parse_csv_payload(table, payload, item.address)

    findings = evaluate_all(samples)

    # Operational completeness is judged on whether the responses are USABLE, not on whether
    # the requests returned. A 200 carrying a wrong schema is a failed retrieval that no
    # fetch-error list will ever mention.
    inventory_ok, inventory_problems = validate_retrieved_inventory(samples, ticker)
    retrieval_complete = not fetch_errors and inventory_ok
    recommendation = private_recommendation(findings, retrieval_complete=retrieval_complete)

    uploaded = upload_staged(staged, run_id, buckets, authorization.profile, put=put)
    _, retained = purge_uploaded(uploaded)

    html = render_private_report(
        run_id, findings, recommendation, fetch_errors, retained, inventory_problems
    )
    report_path = run_dir / REPORT_FILENAME
    report_path.write_text(html, encoding="utf-8")
    (runtime_root / REPORT_FILENAME).write_text(html, encoding="utf-8")

    report_uploaded = True
    try:
        sender = put if put is not None else aws_s3_put
        sender(
            assert_licensed_destination(buckets.licensed, buckets),
            private_report_object_key(run_id, REPORT_FILENAME),
            report_path,
            authorization.profile,
        )
    except SafeHarnessError:
        report_uploaded = False

    return HarnessOutcome(
        ok=report_uploaded and retained == 0 and retrieval_complete,
        report_path=report_path,
        retained_raw=retained,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sharadar_private_qualification",
        description=(
            "Private Sharadar free-sample qualification (P1-P9). Network access is OFF "
            "unless --private-live-run is passed. Output is PRIVATE and never printed."
        ),
    )
    parser.add_argument(
        "--private-live-run",
        action="store_true",
        help=(
            "perform the real, paced, public-test-key run. Requires "
            f"AWS_PROFILE={EXPECTED_PROFILE} and a passing AWS identity check."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = tuple(sys.argv[1:] if argv is None else argv)
    build_parser().parse_args(list(args))

    try:
        authorization = authorize_live_run(args, os.environ)
    except SafeHarnessError as exc:
        print("REFUSED")
        print(f"  {exc}")
        print("  Network access is OFF by default. This harness is a manual owner action:")
        print(f"    set AWS_PROFILE={EXPECTED_PROFILE} and pass --private-live-run.")
        return 2

    try:
        buckets = resolve_buckets(authorization)
        outcome = run_private_qualification(authorization, buckets, datetime.now(UTC))
    except SafeHarnessError as exc:
        print("REFUSED")
        print(f"  {exc}")
        return 2

    for line in console_lines(outcome):
        print(line)
    return operational_exit_code(outcome)


if __name__ == "__main__":
    sys.exit(main())
