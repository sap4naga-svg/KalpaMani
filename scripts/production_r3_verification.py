"""The R-3 verification tool (ADR-0036 §2.7 / §3; proposed ADR-0046). **Refuses by default.**

R-3 is the application-gate prerequisite: proof, by a single refused request under the
otherwise-authorized **control principal** (the foundation's Terraform-apply profile,
``kalpamani-foundation``), that S3 itself refuses an object-creating ``PutObject`` without
``If-None-Match``, a copy-shaped put and a multipart creation under the production
prefixes -- with a **fresh positive control** in the same session, and a **failure-path
cleanup** budgeted at ten operations. The procedure, its nine counted rows, its expected
classes and its cleanup table are transcribed in
:mod:`kalpamani.data.production.sharadar.r3_verification`; this tool composes them with the
foundation identity gate, the environment binding (ADR-0024: the bucket and the account),
the declared bucket-policy statements it runs beside, one S3 client built only inside the
authorized branch, and the private-artifact writer.

```text
plan         (no flag) print the expected-path matrix and the budgets; NOTHING is performed:
             no client, no gate, no file, no network
check        --check-record: parse the record the environment names, compute whether it
             attests to the CURRENT declared statements, print its result and digest;
             nothing external
execute      (flag) automation refused; the foundation identity gate (AWS_PROFILE pinned to
             kalpamani-foundation; sts:GetCallerIdentity compared with the local account
             binding -- PASS/FAIL only); the environment binding loaded and its account held
             to the governed one; the S3 client built for this profile and region with ONE
             attempt and finite timeouts; the nine rows, then cleanup if any deviated; the
             sanitized record written exclusively under the private root; the result and
             the counts printed, and the record digest ONLY when VERIFIED
```

**What the record binds to.** The digest of the environment binding that named the
bucket, the digest of the tracked ``infra/aws/research-data-plane/storage.tf`` (the
declared statements), the partition and region, and the session stamp. A record made
against other statements, or another binding, attests to nothing here (``--check-record``
says so), and readiness §4.6's re-verification rule is checked, not remembered.

**What this tool never does.** It never mutates a bucket policy, moves a stage, changes
an assignment or reads a policy back; it issues no operation outside the nine rows and
the cleanup table; it never retries a request (one attempt, finite timeouts); it prints
no key, bucket, account, ARN or message text -- a refused request's message names the
caller ARN and is classified, then dropped. **It has never run against AWS.** Every
result beside it is a fake's.

Refused by name: ``--bucket``, ``--profile``, ``--aws-profile``, ``--stage``,
``--apply``, ``--force``, ``--retry``, ``--skip-cleanup``, ``--record-dir``,
``--environment-binding``, ``--token``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
for _entry in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(_entry) not in sys.path:  # pragma: no cover - import bootstrap
        sys.path.insert(0, str(_entry))

from kalpamani.data.contracts.canonical import sha256_hex  # noqa: E402
from kalpamani.data.production.sharadar import r3_verification as r3  # noqa: E402
from kalpamani.data.production.sharadar.vocabulary import (  # noqa: E402
    EXPECTED_PARTITION,
    EXPECTED_REGION,
)
from kalpamani.data.qualify.sharadar.runtime_binding import (  # noqa: E402
    ENVIRONMENT_BINDING_ENV_VAR,
    QualificationEnvironmentBinding,
    canonical_binding_bytes,
)

AUTHORIZATION_FLAG: Final = "--i-am-the-owner-authorizing-one-r3-verification"
#: Where the sanitized record is created (a directory under the private root); the
#: record to check. Private paths arrive from the environment, never from argv.
RECORD_DIR_ENV_VAR: Final = "KALPAMANI_PRODUCTION_R3_RECORD_DIR"
RECORD_FILE_ENV_VAR: Final = "KALPAMANI_PRODUCTION_R3_RECORD_FILE"
#: The tracked declaration the record binds to.
POLICY_DECLARATION_PATH: Final = REPO_ROOT / "infra" / "aws" / "research-data-plane" / "storage.tf"
#: One attempt, finite timeouts -- the client configuration of the authorized branch.
CONNECT_TIMEOUT_SECONDS: Final = 10
READ_TIMEOUT_SECONDS: Final = 30

REFUSED_OPTIONS: Final[dict[str, str]] = {
    "--bucket": "the bucket comes from the environment binding, never from argv",
    "--profile": "the control principal is the compiled foundation profile",
    "--aws-profile": "same as --profile",
    "--stage": "this tool moves no stage; stage b is a separate governed apply",
    "--apply": "this tool applies nothing",
    "--force": "a deviation is a result; nothing is forced",
    "--retry": "no request is retried; a timeout is a classified row",
    "--skip-cleanup": "the failure-path cleanup is not optional",
    "--record-dir": "the record directory is named by a fixed environment variable",
    "--environment-binding": "a private path would enter every process listing",
    "--token": "no token is accepted, read, stored or bound by this command",
}

EXIT_PLANNED: Final = 0
EXIT_VERIFIED: Final = 0
EXIT_REFUSED_ARGUMENTS: Final = 2
EXIT_REFUSED_EXECUTION_CONTEXT: Final = 3
EXIT_REFUSED_IDENTITY: Final = 4
EXIT_REFUSED_BINDING: Final = 5
EXIT_REFUSED_DECLARATION: Final = 6
EXIT_REFUSED_DEPENDENCY: Final = 7
EXIT_REFUSED_RECORD_WRITE: Final = 8
EXIT_NOT_VERIFIED: Final = 9
EXIT_CLEANUP_UNRESOLVED: Final = 10
EXIT_CHECKED: Final = 0
EXIT_CHECK_REFUSED: Final = 11

SENTENCES: Final[dict[str, str]] = {
    "planned": "r3 plan printed; nothing was performed",
    "refused_arguments": "r3 verification refused: the arguments were not admitted",
    "refused_execution_context": "r3 verification refused: execution context",
    "refused_identity": "r3 verification refused: the foundation identity gate did not pass",
    "refused_binding": "r3 verification refused: the environment binding was refused",
    "refused_declaration": "r3 verification refused: the declared statements could not be read",
    "refused_dependency": "r3 verification refused: the client could not be built",
    "refused_record_write": "r3 verification refused: the record was not written",
    "verified": "r3 verified; the record digest above is production_r3_verification_digest",
    "not_verified": "r3 NOT verified; the gate stays closed",
    "cleanup_unresolved": "r3 NOT verified and cleanup unresolved; residue named in the record",
    "not_exercised": "r3 not exercised",
    "checked": "r3 record checked",
    "check_refused": "r3 record check refused: the record or the declaration was not admitted",
}


class R3ToolRefusalError(Exception):
    """A closed refusal: one sentence key and one exit code."""

    def __init__(self, key: str, exit_code: int) -> None:
        super().__init__(key)
        self.key = key
        self.exit_code = exit_code


def running_under_automation(env: Mapping[str, str], modules: Mapping[str, object]) -> bool:
    """Whether this is a test runner or CI, where R-3 must never execute."""
    if "pytest" in modules:
        return True
    return any(
        env.get(name, "").strip()
        for name in ("CI", "CONTINUOUS_INTEGRATION", "GITHUB_ACTIONS", "BUILD_NUMBER")
    )


def plan_lines() -> list[str]:
    """The expected-path matrix and budgets, printable offline."""
    lines = [
        f"control_principal={r3.CONTROL_PROFILE} prefix={r3.VERIFICATION_PREFIX}/<stamp>/",
        f"expected_path_operations={r3.EXPECTED_PATH_OPERATIONS} "
        f"failure_path_budget={r3.FAILURE_PATH_BUDGET} identity_calls=1",
    ]
    for row in r3.EXPECTED_PATH:
        expected = "|".join(c.value for c in row.expected)
        lines.append(f"row={row.number} {row.operation.value} {row.key_suffix} expects={expected}")
    return lines


def policy_declaration_digest(path: Path = POLICY_DECLARATION_PATH) -> str:
    """SHA-256 of the tracked declaration file the record binds to."""
    return sha256_hex(path.read_bytes())


def current_binding(
    environment: QualificationEnvironmentBinding,
    *,
    declaration_path: Path = POLICY_DECLARATION_PATH,
) -> r3.R3Binding:
    """The binding a record made now would carry."""
    return r3.R3Binding(
        environment_binding_sha256=environment.digest,
        policy_declaration_sha256=policy_declaration_digest(declaration_path),
        partition=environment.partition,
        region=environment.region,
    )


def execute_r3(
    *,
    env: Mapping[str, str],
    modules: Mapping[str, object],
    identity_gate: Callable[[], str | None],
    expected_account: Callable[[], str | None],
    load_environment_binding: Callable[..., QualificationEnvironmentBinding],
    client_factory: Callable[[str, str], r3.R3Client],
    write_record: Callable[[str, bytes], Path],
    now: Callable[[], datetime],
    declaration_path: Path = POLICY_DECLARATION_PATH,
) -> tuple[r3.R3Record, Path]:
    """The authorized branch, on injected seams. Returns the record and where it was written.

    Order: automation refused → identity gate (one STS call, PASS/FAIL) → environment
    binding (account held to the governed one; partition and region held to the compiled
    ones) → declaration digest → client (only now) → the procedure → the record written
    exclusively → returned. An identity gate that does not pass writes nothing and
    performs no S3 operation: R-3 is then **not exercised**, and this tool says so rather
    than recording a session that never happened.
    """
    if running_under_automation(env, modules):
        raise R3ToolRefusalError("refused_execution_context", EXIT_REFUSED_EXECUTION_CONTEXT)
    if env.get("AWS_PROFILE", "") != r3.CONTROL_PROFILE:
        raise R3ToolRefusalError("refused_identity", EXIT_REFUSED_IDENTITY)
    try:
        reason = identity_gate()
    except Exception:
        raise R3ToolRefusalError("refused_identity", EXIT_REFUSED_IDENTITY) from None
    if reason is not None:
        raise R3ToolRefusalError("refused_identity", EXIT_REFUSED_IDENTITY)
    source = env.get(ENVIRONMENT_BINDING_ENV_VAR, "")
    try:
        account = expected_account()
        environment = load_environment_binding(path=source, expected_account=account)
    except Exception:
        raise R3ToolRefusalError("refused_binding", EXIT_REFUSED_BINDING) from None
    if (
        type(environment) is not QualificationEnvironmentBinding
        or type(account) is not str
        or environment.target_account_id != account
        or environment.partition != EXPECTED_PARTITION
        or environment.region != EXPECTED_REGION
    ):
        raise R3ToolRefusalError("refused_binding", EXIT_REFUSED_BINDING)
    try:
        binding = current_binding(environment, declaration_path=declaration_path)
    except OSError:
        raise R3ToolRefusalError("refused_declaration", EXIT_REFUSED_DECLARATION) from None
    try:
        client = client_factory(environment.licensed_bucket_name, environment.region)
    except Exception:
        raise R3ToolRefusalError("refused_dependency", EXIT_REFUSED_DEPENDENCY) from None
    record = r3.run_r3(client, binding=binding, now=now)
    payload = canonical_binding_bytes(record.document())
    try:
        written = write_record(f"r3-verification-{record.stamp}.json", payload)
    except Exception:
        raise R3ToolRefusalError("refused_record_write", EXIT_REFUSED_RECORD_WRITE) from None
    return record, written


def result_lines(record: r3.R3Record) -> list[str]:
    """Sanitized result lines: the result, the counts, the digest only when VERIFIED."""
    lines = [
        f"r3_result={record.result.value} "
        f"expected_path_operations={record.expected_path_operations} "
        f"failure_path_operations={record.failure_path_operations} "
        f"residue_count={len(record.residue)}",
    ]
    if record.result is r3.R3Result.VERIFIED:
        lines.append(f"r3_verification_digest={record.digest}")
    return lines


def check_record(
    *,
    env: Mapping[str, str],
    read_record: Callable[[str], bytes],
    expected_account: Callable[[], str | None],
    load_environment_binding: Callable[..., QualificationEnvironmentBinding],
    declaration_path: Path = POLICY_DECLARATION_PATH,
) -> tuple[r3.R3Record, bool]:
    """Parse the named record and decide whether it attests to the current binding."""
    try:
        record = r3.parse_r3_record(read_record(env.get(RECORD_FILE_ENV_VAR, "")))
        environment = load_environment_binding(
            path=env.get(ENVIRONMENT_BINDING_ENV_VAR, ""), expected_account=expected_account()
        )
        binding = current_binding(environment, declaration_path=declaration_path)
    except Exception:
        raise R3ToolRefusalError("check_refused", EXIT_CHECK_REFUSED) from None
    return record, r3.record_attests(record, binding=binding)


# ---------------------------------------------------------------------------
# The real seams -- built only inside the authorized branch
# ---------------------------------------------------------------------------


def _identity_gate() -> str | None:
    from aws_foundation_verify import identity_gate

    return identity_gate()


def _expected_account() -> str | None:
    from aws_foundation_verify import expected_account

    return expected_account()


def _load_environment_binding(*, path: str, expected_account: str | None) -> Any:
    from kalpamani.data.qualify.sharadar.runtime_binding import load_environment_binding

    return load_environment_binding(path=path, expected_account=expected_account)


def _write_record(name: str, payload: bytes) -> Path:
    """Create the record under the directory the environment names, exclusively."""
    import os

    from qualification_private_artifacts import write_private_artifact

    directory = os.environ.get(RECORD_DIR_ENV_VAR, "")
    if not directory.strip():
        raise ValueError("no record directory")
    return write_private_artifact(destination=str(Path(directory) / name), payload=payload)


def _read_record(path: str) -> bytes:
    from kalpamani.data.qualify.sharadar.runtime_binding import (
        MAX_RUNTIME_BINDING_BYTES,
        private_root,
        read_private_document,
        windows_file_security,
    )

    # Read under the private-artifact rules; re-encode canonically for the parser.
    document = read_private_document(
        path, private_root(), windows_file_security, MAX_RUNTIME_BINDING_BYTES
    )
    payload: bytes = canonical_binding_bytes(document)
    return payload


class _Boto3R3Client:
    """The nine operations over one boto3 S3 client. One attempt, finite timeouts.

    Every answer is an :class:`r3.Observation`; nothing raises past this class. The
    conditional ``CopyObject`` header is injected for that single call only.
    """

    def __init__(
        self, bucket: str, region: str, *, session_factory: Callable[[str], Any] | None = None
    ) -> None:
        """Build the one client from the control profile's session (``session_factory`` is a
        test seam: no test builds a session from the workstation's profiles or discovers a
        credential). ``total_max_attempts`` counts the initial request -- botocore's
        ``max_attempts`` counts retries after it and would have permitted a second attempt;
        the accepted contract is one attempt per row.
        """
        from botocore.config import Config  # type: ignore[import-untyped]

        self._bucket = bucket
        session = (
            self._control_session(region) if session_factory is None else session_factory(region)
        )
        self._client = session.client(
            "s3",
            config=Config(
                retries={"total_max_attempts": 1, "mode": "standard"},
                connect_timeout=CONNECT_TIMEOUT_SECONDS,
                read_timeout=READ_TIMEOUT_SECONDS,
            ),
        )

    @staticmethod
    def _control_session(region: str) -> Any:
        import boto3  # type: ignore[import-untyped]

        return boto3.Session(profile_name=r3.CONTROL_PROFILE, region_name=region)

    def _call(self, operation: str, **kwargs: Any) -> r3.Observation:
        from botocore.exceptions import (  # type: ignore[import-untyped]
            ClientError,
            ConnectTimeoutError,
            EndpointConnectionError,
            NoCredentialsError,
            ReadTimeoutError,
        )

        try:
            response = getattr(self._client, operation)(Bucket=self._bucket, **kwargs)
        except ClientError as error:
            payload = error.response
            return r3.Observation(
                status=payload.get("ResponseMetadata", {}).get("HTTPStatusCode"),
                code=str(payload.get("Error", {}).get("Code", "")),
                message=str(payload.get("Error", {}).get("Message", "")),
            )
        except (ConnectTimeoutError, ReadTimeoutError):
            return r3.Observation(status=None, transport_failure="timeout")
        except EndpointConnectionError:
            return r3.Observation(status=None, transport_failure="network")
        except NoCredentialsError:
            return r3.Observation(status=None, code="NoCredentialsError")
        except Exception:
            return r3.Observation(status=None, code="Exception")
        return r3.Observation(
            status=response.get("ResponseMetadata", {}).get("HTTPStatusCode"),
            upload_id=response.get("UploadId"),
        )

    def put_object(self, key: str, body: bytes, *, if_none_match: bool) -> r3.Observation:
        extra = {"IfNoneMatch": "*"} if if_none_match else {}
        return self._call("put_object", Key=key, Body=body, **extra)

    def head_object(self, key: str) -> r3.Observation:
        return self._call("head_object", Key=key)

    def copy_object(self, source_key: str, key: str, *, if_none_match: bool) -> r3.Observation:
        source = {"Bucket": self._bucket, "Key": source_key}
        if not if_none_match:
            return self._call("copy_object", Key=key, CopySource=source)

        def inject(params: dict[str, Any], **_kwargs: Any) -> None:
            params.setdefault("headers", {})["If-None-Match"] = "*"

        events = self._client.meta.events
        events.register("before-call.s3.CopyObject", inject)
        try:
            return self._call("copy_object", Key=key, CopySource=source)
        finally:
            events.unregister("before-call.s3.CopyObject", inject)

    def create_multipart_upload(self, key: str) -> r3.Observation:
        return self._call("create_multipart_upload", Key=key)

    def delete_object(self, key: str) -> r3.Observation:
        return self._call("delete_object", Key=key)

    def abort_multipart_upload(self, key: str, upload_id: str) -> r3.Observation:
        return self._call("abort_multipart_upload", Key=key, UploadId=upload_id)

    def list_parts(self, key: str, upload_id: str) -> r3.Observation:
        return self._call("list_parts", Key=key, UploadId=upload_id)


def _client_factory(bucket: str, region: str) -> r3.R3Client:
    return _Boto3R3Client(bucket, region)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="production_r3_verification",
        description="R-3 server-side conditional-write verification; refuses by default",
    )
    parser.add_argument(AUTHORIZATION_FLAG, dest="authorized", action="store_true")
    parser.add_argument("--check-record", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    modules: Mapping[str, object] | None = None,
    identity_gate: Callable[[], str | None] | None = None,
    expected_account: Callable[[], str | None] | None = None,
    load_environment_binding: Callable[..., Any] | None = None,
    client_factory: Callable[[str, str], r3.R3Client] | None = None,
    write_record: Callable[[str, bytes], Path] | None = None,
    read_record: Callable[[str], bytes] | None = None,
    now: Callable[[], datetime] | None = None,
    declaration_path: Path = POLICY_DECLARATION_PATH,
) -> int:
    """Plan (default), check a record, or execute one authorized R-3 session.

    The keyword seams exist for tests, which inject fakes for every one of them. With
    none injected the real gate, loader, writer and client are used -- the client built
    only after the flag, the automation check, the identity gate and the binding.
    """
    import os

    arguments = list(sys.argv[1:] if argv is None else argv)
    for token in arguments:
        if token.split("=", 1)[0] in REFUSED_OPTIONS:
            print(SENTENCES["refused_arguments"])
            return EXIT_REFUSED_ARGUMENTS
    try:
        parsed = _parser().parse_args(arguments)
    except SystemExit:
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    if parsed.authorized and parsed.check_record:
        print(SENTENCES["refused_arguments"])
        return EXIT_REFUSED_ARGUMENTS
    environment = dict(os.environ) if env is None else dict(env)
    if parsed.check_record:
        try:
            record, attests = check_record(
                env=environment,
                read_record=_read_record if read_record is None else read_record,
                expected_account=_expected_account
                if expected_account is None
                else expected_account,
                load_environment_binding=(
                    _load_environment_binding
                    if load_environment_binding is None
                    else load_environment_binding
                ),
                declaration_path=declaration_path,
            )
        except R3ToolRefusalError as refusal:
            print(SENTENCES[refusal.key])
            return refusal.exit_code
        print(
            f"r3_record_result={record.result.value} attests_current_declaration={attests} "
            f"r3_record_digest={record.digest}"
        )
        print(SENTENCES["checked"])
        return EXIT_CHECKED
    if not parsed.authorized:
        for line in plan_lines():
            print(line)
        print(SENTENCES["planned"])
        return EXIT_PLANNED
    try:
        record, _written = execute_r3(
            env=environment,
            modules=sys.modules if modules is None else modules,
            identity_gate=_identity_gate if identity_gate is None else identity_gate,
            expected_account=_expected_account if expected_account is None else expected_account,
            load_environment_binding=(
                _load_environment_binding
                if load_environment_binding is None
                else load_environment_binding
            ),
            client_factory=_client_factory if client_factory is None else client_factory,
            write_record=_write_record if write_record is None else write_record,
            now=(lambda: datetime.now(tz=UTC)) if now is None else now,
            declaration_path=declaration_path,
        )
    except R3ToolRefusalError as refusal:
        print(SENTENCES[refusal.key])
        return refusal.exit_code
    for line in result_lines(record):
        print(line)
    if record.result is r3.R3Result.VERIFIED:
        print(SENTENCES["verified"])
        return EXIT_VERIFIED
    if record.result is r3.R3Result.NOT_VERIFIED_CLEANUP_UNRESOLVED:
        print(SENTENCES["cleanup_unresolved"])
        return EXIT_CLEANUP_UNRESOLVED
    print(SENTENCES["not_verified"])
    return EXIT_NOT_VERIFIED


__all__ = [
    "AUTHORIZATION_FLAG",
    "RECORD_DIR_ENV_VAR",
    "RECORD_FILE_ENV_VAR",
    "REFUSED_OPTIONS",
    "SENTENCES",
    "R3ToolRefusalError",
    "check_record",
    "current_binding",
    "execute_r3",
    "main",
    "plan_lines",
    "policy_declaration_digest",
    "result_lines",
]


if __name__ == "__main__":  # pragma: no cover - the owner's console entry
    sys.exit(main())
