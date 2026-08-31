"""One private assessment of one retained acquisition (ADR-0018). **Refused by default.**

**This command has never been run, and running it is a separate written
authorization that has not been given.** It is also a *different* authorization from
the acquisition command's: the two never share a flag, a capability object or a
session, because the whole point of splitting them is that neither can do the
other's work.

**This process reaches no provider and no credential, and that is structural.**
There is no secret identifier, no Secrets Manager factory, no provider transport and
no credential source anywhere in this module -- not behind a flag, not in a helper,
not in an unused import. A static test proves the absence. *A provider failure cannot
be converted into an assessment result*, because this process cannot contact a
provider at all.

**An ordinary import does nothing observable.** No environment lookup, no client
construction, no socket, no file read and no state read. Every ``kalpamani`` import
sits inside a function body.

```text
 1  require a DIFFERENT singleton authorization
 2  refuse under automation, CI, pytest and import-only contexts
 3  pin the governed AWS profile
 4  pass the governed identity gate
 5  resolve only the LICENSED bucket
 6  accept the owner-known execution identity privately
 7  derive the exact locator key -- WITHOUT LISTING
 8  retrieve and validate the locator
 9  retrieve only the exact referenced records and payloads
10  verify checksum and byte count BEFORE parsing
11  parse in the isolated qualification package
12  evaluate P1-P9 under compiled ceilings
13  publish ONE owner-only private report
14  emit only a closed public result
```

**Nothing this command prints is a finding.** No P-status, no measurement, no
security name, no key, no digest, no identity, no report content and no
recommendation. The output is one allowlisted sentence and a set of operation
counts, and the exit status is a command status rather than a verdict.

**There is no local report copy and no path option.** The report is serialized in
memory and published conditionally to the licensed prefix; an uncontrolled local copy
is structurally impossible rather than discouraged.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Any, Final

#: The one flag that turns a refusal into one private assessment. **Distinct from the
#: acquisition command's**, so neither authorization can be pasted into the other.
AUTHORIZATION_FLAG: Final = "--i-am-the-operator-authorizing-qualification-assessment"

#: The profile and region the governed foundation is pinned to.
EXPECTED_PROFILE: Final = "kalpamani-foundation"
EXPECTED_REGION: Final = "us-east-1"

#: The Terraform output holding the licensed research bucket. The control bucket has
#: a different output key and this module never names it.
LICENSED_BUCKET_OUTPUT: Final = "licensed_bucket_name"

#: Options refused by name, each with the reason.
REFUSED_OPTIONS: Final[dict[str, str]] = {
    "--run": "there is no run mode; this command is one assessment or a refusal",
    "--live": "there is no live mode, and nothing here can construct one",
    "--execute": "the authorization flag is the only way to execute; there is no alias",
    "--force": "nothing here is forceable; a refusal is a refusal",
    "--api-key": "this process reaches no provider; no credential is accepted anywhere",
    "--secret-id": "this process retrieves no secret; there is no secrets boundary here",
    "--secret": "same as --secret-id: no secret is read, and none can be",
    "--arn": "an ARN names an account; it is never supplied and never printed",
    "--profile": "the governed profile is pinned in code and compared, never supplied",
    "--aws-profile": "same as --profile: the pin is not an operator choice",
    "--bucket": "the licensed bucket is resolved from governed state, never supplied",
    "--endpoint": "no endpoint is accepted; the SDK resolves the governed one",
    "--list": "no listing exists anywhere in this architecture, and none will be added",
    "--list-locators": "there is deliberately no index of locators; naming one is the only route",
    "--prefix": "no prefix enumeration exists; an object is reached by exact key or not at all",
    "--scan": "same as --list: nothing here can search the store",
    "--subject": "no security name is accepted, and none is printed",
    "--ticker": "same as --subject: no security name is accepted on the command line",
    "--output": "no local report copy is written, and no path option exists",
    "--report-path": "same as --output: the report is published to the licensed prefix only",
    "--print-report": "the report is never printed; it is owner-only private material",
    "--show-findings": "no finding is ever emitted publicly, by any option",
    "--verdict": "no aggregate verdict exists anywhere in this architecture",
    "--recommend": "no provider-selection recommendation exists; that decision is G1",
    "--select-provider": "provider selection is an owner decision and is not a program output",
    "--control": "CONTROL publication is deferred and forbidden; this writes LICENSED only",
    "--retry": "the report write is never retried; a new assessment identity is the remedy",
    "--fetch": "this process makes no provider request and cannot be made to",
}


class _AssessmentAuthorization:
    """Proof that the assessment flag was parsed. **Exactly one exists.**

    A separate class from the acquisition command's, in a separate module, so there is
    no object either command could accept from the other. ``__slots__`` is empty, so
    there is no state to copy; admission is identity against the single module-level
    instance, and every route to a second object is closed.
    """

    __slots__ = ()

    def __new__(cls) -> _AssessmentAuthorization:
        """Refuse a second construction once the singleton exists."""
        if "_ASSESSMENT_AUTHORIZATION" in globals():
            raise TypeError("the assessment authorization is a singleton")
        return super().__new__(cls)

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse subclassing: a subclass instance is a second bearer."""
        raise TypeError("the assessment authorization may not be subclassed")

    def __copy__(self) -> _AssessmentAuthorization:
        """Refuse copying, so no copy operation yields an object at all."""
        raise TypeError("the assessment authorization may not be copied")

    def __deepcopy__(self, memo: object) -> _AssessmentAuthorization:
        """Refuse deep copying, for the same reason."""
        raise TypeError("the assessment authorization may not be copied")

    def __reduce__(self) -> object:
        """Refuse pickling, which is copying with extra steps."""
        raise TypeError("the assessment authorization may not be pickled")


_ASSESSMENT_AUTHORIZATION: Final = _AssessmentAuthorization()


def _is_authorized(candidate: object) -> bool:
    """Whether ``candidate`` **is** the one authorization this module holds."""
    return candidate is _ASSESSMENT_AUTHORIZATION


class AssessmentOutcome(StrEnum):
    """Every sentence this command may print. A fixed allowlist.

    **None reports a finding, a measurement, a P-status, a verdict, a provider
    selection or a readiness value.** Those live only in the private report, and a
    word implying one here would be read as permission.
    """

    REFUSED_NOT_AUTHORIZED = "qualification assessment refused: not authorized"
    REFUSED_OPTION = "qualification assessment refused: this option is not accepted"
    REFUSED_EXECUTION_CONTEXT = "qualification assessment refused: execution context"
    REFUSED_PROFILE = "qualification assessment refused: the governed profile did not match"
    REFUSED_IDENTITY = "qualification assessment refused: the AWS identity gate did not pass"
    REFUSED_LICENSED_BUCKET = "qualification assessment refused: licensed configuration"
    REFUSED_IDENTIFIERS = "qualification assessment refused: execution or assessment identity"
    REFUSED_DEPENDENCY = "qualification assessment refused: a local dependency was unavailable"
    REFUSED_LOCATOR = "qualification assessment refused: the locator was refused"
    REFUSED_INTEGRITY = "qualification assessment refused: a referenced object did not verify"
    REFUSED_EVIDENCE = "qualification assessment refused: retained evidence could not be parsed"
    REFUSED_REPORT = "qualification assessment refused: the private report was not published"
    REFUSED_UNCLASSIFIED = "qualification assessment refused: unclassified"
    COMPLETED = "qualification assessment completed; the private report was published"


#: The exit status each outcome maps to. **Total, and checked by a test.**
EXIT_STATUS: Final[dict[AssessmentOutcome, int]] = {
    AssessmentOutcome.COMPLETED: 0,
    AssessmentOutcome.REFUSED_NOT_AUTHORIZED: 1,
    AssessmentOutcome.REFUSED_OPTION: 2,
    AssessmentOutcome.REFUSED_EXECUTION_CONTEXT: 3,
    AssessmentOutcome.REFUSED_PROFILE: 4,
    AssessmentOutcome.REFUSED_IDENTITY: 5,
    AssessmentOutcome.REFUSED_LICENSED_BUCKET: 6,
    AssessmentOutcome.REFUSED_IDENTIFIERS: 7,
    AssessmentOutcome.REFUSED_DEPENDENCY: 8,
    AssessmentOutcome.REFUSED_LOCATOR: 9,
    AssessmentOutcome.REFUSED_INTEGRITY: 10,
    AssessmentOutcome.REFUSED_EVIDENCE: 11,
    AssessmentOutcome.REFUSED_REPORT: 12,
    AssessmentOutcome.REFUSED_UNCLASSIFIED: 13,
}

#: How an internal assessment status becomes a public outcome. **Total, and checked**:
#: no ``.get`` default and no ``else``, so a status added later has no mapping and
#: fails loudly rather than silently becoming a completion.
_STATUS_OUTCOME: Final[dict[str, AssessmentOutcome]] = {
    "COMPLETED": AssessmentOutcome.COMPLETED,
    "REFUSED_LOCATOR": AssessmentOutcome.REFUSED_LOCATOR,
    "REFUSED_INTEGRITY": AssessmentOutcome.REFUSED_INTEGRITY,
    "REFUSED_EVIDENCE": AssessmentOutcome.REFUSED_EVIDENCE,
    "REFUSED_REPORT": AssessmentOutcome.REFUSED_REPORT,
}


class QualificationAssessmentError(Exception):
    """A refusal carrying exactly one allowlisted :class:`AssessmentOutcome`.

    Raised ``from None`` everywhere. A backend exception quotes the bucket and the
    key, a parser refusal can be about a vendor row, and a locator refusal is about
    private material. None of it may reach a traceback.
    """

    def __init__(self, outcome: AssessmentOutcome) -> None:
        """Bind the outcome. The message is the allowlisted sentence, nothing more."""
        if type(outcome) is not AssessmentOutcome:  # pragma: no cover - type guard
            raise TypeError("an outcome must be an exact AssessmentOutcome member")
        super().__init__(outcome.value)
        self.outcome = outcome


def _emit(outcome: AssessmentOutcome) -> None:
    """Print one allowlisted sentence.

    Takes a vocabulary member, not a string, so there is no parameter through which a
    key, digest, subject, row, measurement or P-status could arrive.
    """
    print(outcome.value)


def _emit_counts(counts: Any) -> None:
    """Print the operation accounting. **Numbers only, and no identifier.**

    Deliberately includes the two zeros that matter most: this process made no
    provider request and retrieved no credential, and saying so in numbers is
    stronger than saying it in a docstring.
    """
    print(f"  object-byte get_object: {counts.get_object_count}")
    print(f"  report put_object: {counts.put_object_count}")
    print(f"  conditional head_object: {counts.head_object_count}")
    print(f"  acquisition-claim reads: {counts.claim_read_count}")
    print(f"  provider requests: {counts.provider_request_count}")
    print(f"  credential retrievals: {counts.credential_retrieval_count}")
    print(f"  listing operations: {counts.list_operation_count}")
    print(f"  CONTROL operations: {counts.control_operation_count}")
    print(f"  total S3 operations: {counts.total_s3_operations}")


def running_under_automation(env: Mapping[str, str], modules: Mapping[str, object]) -> str | None:
    """Why this must not run here, or ``None``.

    Reading licensed bytes and publishing a private evaluation are owner actions.
    Under ``pytest`` the tests would perform them; in CI the transcript is a log; on a
    plain import nobody asked for anything at all.
    """
    if "pytest" in modules:
        return "pytest"
    for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "BUILD_NUMBER"):
        if env.get(name, "").strip():
            return name
    return None


class SystemClock:
    """The wall clock, in the one place a real run is allowed to read one."""

    def now(self) -> Any:
        """The current UTC instant."""
        from datetime import UTC, datetime

        return datetime.now(UTC)


def run_qualification_assessment(
    *,
    authorization: object,
    execution_id: str | None,
    assessment_id: str | None,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    profile_of: Callable[[], str],
    identity_gate: Callable[[], str | None],
    resolve_licensed_bucket: Callable[[], str],
    s3_client_factory: Callable[[], Any],
    clock: Any,
) -> tuple[AssessmentOutcome, Any]:
    """Retrieve, verify, parse, evaluate and publish exactly one private report.

    **There is no credential parameter and no transport parameter**, and adding one
    would be the change a reviewer should refuse: this process must remain unable to
    reach a provider, so the dependency simply does not exist in the signature.

    Returns:
        One allowlisted outcome and the observed operation accounting.

    Raises:
        QualificationAssessmentError: one allowlisted :class:`AssessmentOutcome`. The
            cause is always suppressed.
    """
    # 1. Authorization. A capability this module minted after parsing its own flag.
    if not _is_authorized(authorization):
        raise QualificationAssessmentError(AssessmentOutcome.REFUSED_NOT_AUTHORIZED) from None

    # 2. Execution context. Refused before anything is read or resolved.
    if running_under_automation(env, modules) is not None:
        raise QualificationAssessmentError(AssessmentOutcome.REFUSED_EXECUTION_CONTEXT) from None

    # 3. The profile, before any AWS call is attempted at all.
    try:
        profile = profile_of()
    except Exception:
        raise QualificationAssessmentError(AssessmentOutcome.REFUSED_PROFILE) from None
    if profile != EXPECTED_PROFILE:
        raise QualificationAssessmentError(AssessmentOutcome.REFUSED_PROFILE) from None

    # 4. The account identity gate. Its reason string can name an account, so it is
    #    consumed as a pass/fail and never printed.
    try:
        reason = identity_gate()
    except Exception:
        raise QualificationAssessmentError(AssessmentOutcome.REFUSED_IDENTITY) from None
    if reason is not None:
        raise QualificationAssessmentError(AssessmentOutcome.REFUSED_IDENTITY) from None

    # 5. The licensed bucket, from governed state. Never the control one.
    try:
        licensed_bucket = resolve_licensed_bucket()
    except Exception:
        raise QualificationAssessmentError(AssessmentOutcome.REFUSED_LICENSED_BUCKET) from None

    # 6. The two identities, held privately. Neither is printed, here or anywhere.
    if type(execution_id) is not str or type(assessment_id) is not str:
        raise QualificationAssessmentError(AssessmentOutcome.REFUSED_IDENTIFIERS) from None

    try:
        from kalpamani.data.qualify.sharadar.assessment import run_assessment
        from kalpamani.data.qualify.sharadar.read import LicensedObjectReader

        reader = LicensedObjectReader(client=s3_client_factory(), licensed_bucket=licensed_bucket)
    except Exception:
        raise QualificationAssessmentError(AssessmentOutcome.REFUSED_DEPENDENCY) from None

    # 7-13. The locator key, the locator, the exact reads, the parse, the evaluation
    #       and the one report, all inside the composition that enforces their order.
    try:
        result = run_assessment(
            reader=reader,
            execution_id=execution_id,
            assessment_id=assessment_id,
            clock=clock,
        )
    except Exception as failure:
        name = getattr(getattr(failure, "status", None), "name", None)
        if type(name) is str and name in _STATUS_OUTCOME:
            raise QualificationAssessmentError(_STATUS_OUTCOME[name]) from None
        raise QualificationAssessmentError(AssessmentOutcome.REFUSED_UNCLASSIFIED) from None

    # 14. One closed outcome. The nine test results stay in the private report.
    status_name = getattr(result.status, "name", None)
    if type(status_name) is not str or status_name not in _STATUS_OUTCOME:
        raise QualificationAssessmentError(AssessmentOutcome.REFUSED_UNCLASSIFIED) from None
    return _STATUS_OUTCOME[status_name], result.counts


def build_parser() -> argparse.ArgumentParser:
    """The executable CLI surface. **Exactly three arguments, and no aliases.**"""
    parser = argparse.ArgumentParser(
        prog="sharadar_qualification_assessment",
        description=(
            "One private assessment of one retained acquisition. Refused by default. "
            "No provider is contacted, no credential is read, and no finding is printed."
        ),
    )
    parser.add_argument(
        AUTHORIZATION_FLAG,
        dest="authorization_flag_present",
        action="store_true",
        help="authorize ONE private assessment, and nothing else",
    )
    parser.add_argument(
        "--execution-id",
        dest="execution_id",
        default=None,
        help="the owner-known execution identity whose locator is assessed",
    )
    parser.add_argument(
        "--assessment-id",
        dest="assessment_id",
        default=None,
        help="the single-use identity this assessment's private report is filed under",
    )
    return parser


def _refused_option(argv: Sequence[str]) -> str | None:
    """The first refused option in ``argv``, or ``None``."""
    for token in argv:
        name = token.split("=", 1)[0]
        if name in REFUSED_OPTIONS:
            return name
    return None


def main(argv: list[str] | None = None) -> int:
    """Parse, refuse, or perform one private assessment. Returns a command status.

    ``0`` means the private report was published. **It is not a verdict** about the
    provider, the data, P1-P9, or whether a provider should be selected -- the
    evidence is in the private report, and G1 is an owner decision taken by a person.

    **This function has never been run**: implementing it was not authorization to use
    it, and the assessment run remains a separate written authorization that has not
    been given.
    """
    argv = list(sys.argv[1:] if argv is None else argv)

    refused = _refused_option(argv)
    if refused is not None:
        _emit(AssessmentOutcome.REFUSED_OPTION)
        print(f"  {refused}: {REFUSED_OPTIONS[refused]}")
        return EXIT_STATUS[AssessmentOutcome.REFUSED_OPTION]

    parsed = build_parser().parse_args(argv)

    if not parsed.authorization_flag_present:
        # The default path. Nothing above this line looked anything up, constructed
        # anything, or opened anything.
        _emit(AssessmentOutcome.REFUSED_NOT_AUTHORIZED)
        print(f"  pass {AUTHORIZATION_FLAG} to authorize one private assessment")
        print("  that flag authorizes exactly one assessment, never a second")
        return EXIT_STATUS[AssessmentOutcome.REFUSED_NOT_AUTHORIZED]

    import os

    try:
        outcome, counts = run_qualification_assessment(
            # Handed over here, and only here: the flag has parsed.
            authorization=_ASSESSMENT_AUTHORIZATION,
            execution_id=parsed.execution_id,
            assessment_id=parsed.assessment_id,
            env=os.environ,
            modules=sys.modules,
            profile_of=_ambient_profile,
            identity_gate=_governed_identity_gate,
            resolve_licensed_bucket=_governed_licensed_bucket,
            s3_client_factory=_s3_client,
            clock=SystemClock(),
        )
    except QualificationAssessmentError as refusal:
        _emit(refusal.outcome)
        return EXIT_STATUS[refusal.outcome]

    _emit(outcome)
    _emit_counts(counts)
    return EXIT_STATUS[outcome]


def _ambient_profile() -> str:
    """The pinned profile from the process environment. Read, never printed."""
    import os

    return os.environ.get("AWS_PROFILE", "")


def _governed_identity_gate() -> str | None:
    """The existing account identity gate. Not a second implementation of one."""
    from aws_foundation_verify import identity_gate  # type: ignore[import-not-found]

    return identity_gate()  # type: ignore[no-any-return]


def _governed_licensed_bucket() -> str:
    """The licensed bucket from governed Terraform state. Never the control one."""
    from aws_foundation_verify import tf_outputs  # type: ignore[import-not-found]

    return str(tf_outputs()[LICENSED_BUCKET_OUTPUT])


def _s3_client() -> Any:
    """An S3 client, pinned to the governed region.

    **The only AWS client this command constructs.** There is no Secrets Manager
    factory here and no provider transport factory, because this process must remain
    unable to reach either.
    """
    import boto3

    return boto3.client("s3", region_name=EXPECTED_REGION)


#: The public surface, stated so it can be checked rather than inferred.
__all__ = [
    "AUTHORIZATION_FLAG",
    "EXIT_STATUS",
    "REFUSED_OPTIONS",
    "AssessmentOutcome",
    "QualificationAssessmentError",
    "build_parser",
    "main",
    "run_qualification_assessment",
    "running_under_automation",
]


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    sys.exit(main())
