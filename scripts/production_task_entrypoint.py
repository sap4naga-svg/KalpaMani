"""The production task image entrypoint (ADR-0036 §2.9, §2.12). **Never run as a task.**

One process per task, selected by exactly one closed argument -- the task definition's
``command`` token -- and nothing else:

```text
kalpamani-production-acquire         the acquisition actor's entry
kalpamani-research-build             the build actor's entry
kalpamani-production-acquire-verify  the acquisition actor's VERIFICATION entry (ADR-0045)
kalpamani-research-build-verify      the build actor's VERIFICATION entry (ADR-0045)
kalpamani-production-acquire-probe   the acquisition actor's PERMISSION-PROBE entry (prop. ADR-0048)
kalpamani-research-build-probe       the build actor's PERMISSION-PROBE entry (prop. ADR-0048)
```

A verification entry composes the accepted bootstrap and stops at the release barrier
(``VERIFIED_BOOTSTRAP``, exit 18): its factories build no Secrets Manager client, no
transport and no S3 client, so it performs no secret retrieval, no provider request and
no data-plane operation. The build verification entry makes one bounded provider-origin
probe -- a TCP connect with no bytes sent -- and records the observation; it decides no
isolation verdict.

**An ordinary import does nothing observable.** No environment lookup, no client
construction, no socket, no file read. Every ``kalpamani`` import and every SDK import
sits inside a function body, and the real factories are constructed only inside the
selected entry, after the compiled checks and the credential-environment check have
passed inside :mod:`kalpamani.data.production.sharadar.entry`.

**What this file decides is exactly what ``src/`` cannot**: which real client to build.
The SDK is imported here and only here on the task path (the data platform imports
none), with the pure configuration dictionaries the platform states -- one attempt in
total, finite socket timeouts, the regional STS endpoint. **Credentials come from the
ECS container credential provider and from nothing else, by construction rather than
by exclusion**: every client is created from one fresh ``botocore`` session whose
credential resolver holds exactly one provider, the container provider over the
validated ``/v2/credentials/<id>`` relative URI, so the default chain -- environment
keys, a shared credentials file, a config file, ``credential_process``, assume-role,
web identity, SSO, the instance metadata service -- is never consulted, and
``boto3``'s cached default session is never used. The session's profile, config-file
and credentials-file variables are overridden so no ``AWS_*`` profile or file variable
is read either. A container retrieval that fails, fails closed: no other source is
tried, and no service request is issued. Credentials returned by the agent are
refreshable through the same, and only the same, provider.

**Reliance on the SDK, stated.** ``botocore.session.Session(session_vars=...)``,
``Session.register_component``, ``Session.create_client``,
``botocore.credentials.CredentialResolver``, ``botocore.credentials.ContainerProvider``
and ``botocore.utils.ContainerMetadataFetcher`` are non-underscored botocore classes and
methods; they are the SDK's own container-credential mechanism (the one the documented
default chain uses at its "container credentials" step), but the registry component
name ``credential_provider`` and the ``session_vars`` tuple layout are not part of the
documented public API. The tests cover both directly -- they build a session through
this file's real factory against synthetic files, a seeded default session and a
synthetic HTTP seam, and assert which provider answered and which were never consulted.

The metadata read is a single bounded ``urllib`` request to the URL the platform
validated, through an opener with **no proxy handler**, so an ambient proxy variable
cannot redirect a link-local read. The provider transport is the accepted origin-pinned
one at the production response ceiling.

**The compiled configuration does not exist in this repository.** The values an image
needs beyond the code -- the acquisition secret name, the compiled origin address set,
the build configuration, the code commit -- are generated at the image gate as one
closed file (ADR-0044 §2) and copied into the image at a fixed path. This entrypoint
reads that file, and only that file: it is absent on any workstation and in this
repository, so the entry refuses ``REFUSED_CONFIGURATION`` with zero operations. The
file's SHA-256 is the configuration digest the launch tool binds into the release; the
image's own digest and its task-definition revision are never read from the image,
because an image cannot know them -- the release attests both.

**Every outcome ends in the same receipt, the early refusals included.** An invocation
that selects no entry, and an entry whose compiled configuration is absent, malformed
or compiled for the other actor, each print the allowlisted sentence, the zero counts
the process can prove and exactly one closing ``receipt:`` line (ADR-0044 §4) -- with
no actor invented for an invalid invocation, and the configuration, bootstrap and
binding evidence reported as absent rather than as a placeholder. Neither path
constructs a client, reads the environment or opens a socket.

**No workstation ledger integration.** The task writes its receipt to stdout (the
allowlisted lines) and exits with the closed code; the launch tool records what it can
observe. Completing the ledger row from a task's counts is a later, separately gated
integration (ADR-0043 §5).

**Where it may write.** The working directory is created under ``/work`` -- the task
definitions' tmpfs, the only writable path under their read-only root filesystem -- after
the pre-construction checks and before any factory; a working root that cannot be used is
``REFUSED_DEPENDENCY`` with zero operations. The directory is deleted before exit
regardless of outcome (ADR-0036 §2.12 step 9), and a cleanup failure is reported beside
the outcome, never in place of it.

**This entrypoint has run only inside local, network-disabled verification containers**
built from prepared contexts with synthetic configurations (docs/operations/
production-image-build.md, "Local verification"); it has never run as a task, and
running one is a separate written authorization that has not been given. Image
publication and AWS runtime verification are later gates.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from typing import Any, Final

#: The exit code of an invocation that selects no entry. The receipt that carries it is
#: rendered by the platform (``no_entry_receipt``), and a test holds the two equal.
NO_ENTRY_EXIT_STATUS: Final = 2

#: Where the image carries its compiled configuration. Absent on a workstation, by design.
COMPILED_CONFIGURATION_PATH: Final = "/etc/kalpamani/compiled-configuration.json"

#: The only writable space a task has: the task definitions' tmpfs (``containerPath =
#: "/work"``, infra/aws/research-data-plane/production_compute.tf) under a read-only root
#: filesystem. The working directory is created inside it and nowhere else -- the
#: interpreter's default temporary location is ``/tmp``, which does not exist writable
#: in the task, and the first local container run of the accepted entrypoint died there
#: with a traceback and no receipt. A working root that cannot be used is a dependency
#: that could not be built (``REFUSED_DEPENDENCY``), refused before any client exists.
TASK_WORKING_ROOT: Final = "/work"


def _environment_names() -> list[str]:
    """Variable **names** only; no value is read here."""
    import os

    return list(os.environ.keys())


def _environment(name: str) -> str | None:
    """One named variable's value, for the metadata URI alone."""
    import os

    return os.environ.get(name)


def _metadata_fetch(url: str, timeout_seconds: float, max_bytes: int) -> bytes:
    """One bounded GET of the validated metadata URL. No proxy, no redirect follow.

    The opener carries no proxy handler and no redirect handler, so the request goes
    to the link-local address the platform admitted and nowhere else. The body is read
    up to ``max_bytes + 1`` so an oversize response is detected rather than truncated.
    """
    import urllib.request

    opener = urllib.request.OpenerDirector()
    opener.add_handler(urllib.request.HTTPHandler())
    if not url.startswith("http://169.254.170.2/v4/"):
        raise ValueError("the metadata URL is not the validated link-local one")
    request = urllib.request.Request(url, method="GET")  # noqa: S310 - scheme and host pinned above
    with opener.open(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise RuntimeError("metadata endpoint did not answer 200")
        return bytes(response.read(max_bytes + 1))


def _resolve_origin(host: str) -> list[str]:
    """Every IPv4 address ``host`` resolves to, through the VPC resolver."""
    import socket

    return sorted({entry[4][0] for entry in socket.getaddrinfo(host, 443, family=socket.AF_INET)})


#: A path no file can have: the session's config and credentials "files". Reading them
#: raises the SDK's own not-found signal, which the session treats as no configuration.
_NO_FILE: Final = "//kalpamani-task-has-no-aws-configuration-file//"

#: The session variables overridden so that **no** environment variable and **no** file
#: can steer the session: no profile, no config file, no credentials file. The tuple is
#: botocore's ``(config_name, env_var, default, converter)``; ``None`` for the first two
#: means neither a config key nor an environment variable is consulted.
_ISOLATED_SESSION_VARS: Final[dict[str, tuple[Any, Any, Any, Any]]] = {
    "profile": (None, None, None, None),
    "config_file": (None, None, _NO_FILE, None),
    "credentials_file": (None, None, _NO_FILE, None),
}


def _isolated_session(environment: Any, *, http: Any = None, sleep: Any = None) -> Any:
    """One fresh session whose only credential source is the ECS container provider.

    ``environment`` is a mapping read for exactly one key -- the container relative
    URI -- which must already be the documented shape; ``http`` is the fetcher's HTTP
    session (the SDK's own when ``None``), ``sleep`` its retry sleeper. The container
    provider is handed a mapping holding **only** the relative URI, so it can see no
    full-URI variant and no authorization token. The retrieval is the SDK's bounded one:
    a 2-second timeout and at most three attempts against the link-local agent, and a
    failure raises the SDK's sanitized retrieval error, which the entry classifies as
    ``REFUSED_DEPENDENCY`` without trying anything else.
    """
    import time

    from botocore.credentials import ContainerProvider, CredentialResolver
    from botocore.session import Session
    from botocore.utils import ContainerMetadataFetcher

    from kalpamani.data.production.sharadar.task_clients import (
        CONTAINER_CREDENTIAL_VARIABLE,
        container_credential_source_refusal,
    )

    if container_credential_source_refusal(environment.get) is not None:
        raise ValueError("the container credential source is not the documented shape")
    relative_uri = environment[CONTAINER_CREDENTIAL_VARIABLE]
    session = Session(session_vars=dict(_ISOLATED_SESSION_VARS))
    fetcher = ContainerMetadataFetcher(session=http, sleep=time.sleep if sleep is None else sleep)
    provider = ContainerProvider(
        environ={CONTAINER_CREDENTIAL_VARIABLE: relative_uri}, fetcher=fetcher
    )
    session.register_component("credential_provider", CredentialResolver(providers=[provider]))
    return session


class _IsolatedClients:
    """Builds every task client from one isolated session, created on first use."""

    __slots__ = ("_environment", "_http", "_session", "_sleep")

    def __init__(self, environment: Any, *, http: Any = None, sleep: Any = None) -> None:
        """Bind the environment mapping; ``http`` and ``sleep`` are test seams only."""
        self._environment = environment
        self._http = http
        self._sleep = sleep
        self._session: Any = None

    def client(self, service: Any) -> Any:
        """One client from the platform's pure construction keywords and the session."""
        from botocore.config import Config

        from kalpamani.data.production.sharadar.task_clients import client_construction_kwargs

        if self._session is None:
            self._session = _isolated_session(self._environment, http=self._http, sleep=self._sleep)
        kwargs = client_construction_kwargs(service)
        config = Config(**kwargs.pop("config"))  # type: ignore[arg-type]
        return self._session.create_client(config=config, **kwargs)


def _client(service: Any, clients: _IsolatedClients) -> Any:
    """One SDK client from the isolated session. Never ``boto3.client``."""
    return clients.client(service)


class _SocketProbe:
    """The build verification entry's probe adapter: one bounded TCP connect, no bytes.

    Constructed only for the build verification entry, after every compiled check and
    the credential-environment check; a plain ``socket`` connect with the compiled
    timeout, closed at once, classified into the closed result vocabulary. Nothing is
    sent on a connection that opens.
    """

    def connect(self, address: str, port: int, timeout_seconds: float) -> Any:
        """Attempt one connection; return the closed observed result; send nothing."""
        import socket

        from kalpamani.data.production.sharadar.probe import ProbeResult

        try:
            with socket.create_connection((address, port), timeout=timeout_seconds):
                return ProbeResult.CONNECTED
        except TimeoutError:
            return ProbeResult.TIMED_OUT
        except ConnectionRefusedError:
            return ProbeResult.CONNECTION_REFUSED
        except OSError:
            return ProbeResult.CONNECTION_ERROR


def _transport() -> Any:
    """The accepted origin-pinned transport at the production response ceiling."""
    from kalpamani.data.ingest.sharadar.transport import UrllibTransport
    from kalpamani.data.production.sharadar.plan import MAX_RESPONSE_BYTES

    return UrllibTransport(max_response_bytes=MAX_RESPONSE_BYTES)


def _working_directory_cleanup(path: Any) -> Any:
    """Delete the task's working directory before exit, regardless of outcome."""
    import shutil

    def cleanup() -> None:
        shutil.rmtree(path)

    return cleanup


def _compiled_configuration(entry: Any, *, path: Any = None) -> Any:
    """The compiled configuration file's entry configuration, or ``None``.

    ``None`` for an absent, unreadable, oversize, malformed or otherwise refused file,
    and for a file compiled for the other entry: the entry then refuses
    ``REFUSED_CONFIGURATION`` before anything else exists. ``path`` is a test seam; the
    image reads the one fixed path.
    """
    from kalpamani.data.production.sharadar.compiled import (
        MAX_COMPILED_CONFIGURATION_BYTES,
        CompiledConfigurationError,
        parse_compiled_configuration,
    )

    location = COMPILED_CONFIGURATION_PATH if path is None else path
    try:
        with open(location, "rb") as handle:
            raw = handle.read(MAX_COMPILED_CONFIGURATION_BYTES + 1)
    except OSError:
        return None
    try:
        configuration, _digest = parse_compiled_configuration(raw)
    except CompiledConfigurationError:
        return None
    if configuration.entry is not entry:
        return None
    return configuration


def _factories(entry: Any, working_directory: Any, *, clients: Any = None) -> Any:
    """The real factories for ``entry``. Constructs nothing; each factory is deferred.

    ``clients`` is a test seam: an :class:`_IsolatedClients` over a synthetic HTTP
    session. The image passes none and gets the real one over ``os.environ``.
    """
    import os
    import time
    from datetime import UTC, datetime

    from kalpamani.data.production.sharadar.entry import (
        PROBE_ENTRIES,
        VERIFICATION_ENTRIES,
        TaskEntry,
    )
    from kalpamani.data.production.sharadar.task_clients import TaskService

    def now() -> datetime:
        return datetime.now(UTC)

    if clients is None:
        clients = _IsolatedClients(os.environ)

    if entry in PROBE_ENTRIES:
        from kalpamani.data.production.sharadar.permission_client import single_service_client
        from kalpamani.data.production.sharadar.permission_probe_entry import (
            PermissionProbeFactories,
        )

        def operation_client(operation: Any) -> Any:
            # The one service the subcell's operation names, over the task's isolated,
            # container-credentialed session; any other service is refused before a
            # client exists (ADR-0048).
            return single_service_client(
                operation, lambda service: _client(TaskService(service), clients)
            )

        return PermissionProbeFactories(
            environment_names=_environment_names,
            environment=_environment,
            metadata_fetch=_metadata_fetch,
            ssm=lambda: _client(TaskService.SSM, clients),
            sts=lambda: _client(TaskService.STS, clients),
            operation_client=operation_client,
            now=now,
            monotonic=time.monotonic,
            sleep=time.sleep,
            cleanup=_working_directory_cleanup(working_directory),
        )

    if entry in VERIFICATION_ENTRIES:
        from kalpamani.data.production.sharadar.verification_entry import VerificationFactories

        return VerificationFactories(
            environment_names=_environment_names,
            environment=_environment,
            metadata_fetch=_metadata_fetch,
            ssm=lambda: _client(TaskService.SSM, clients),
            sts=lambda: _client(TaskService.STS, clients),
            resolve_origin=_resolve_origin,
            probe=_SocketProbe() if entry is TaskEntry.BUILD_VERIFY else None,
            now=now,
            monotonic=time.monotonic,
            sleep=time.sleep,
            cleanup=_working_directory_cleanup(working_directory),
        )
    if entry is TaskEntry.ACQUISITION:
        from kalpamani.data.production.sharadar.acquisition_entry import AcquisitionFactories

        return AcquisitionFactories(
            environment_names=_environment_names,
            environment=_environment,
            metadata_fetch=_metadata_fetch,
            ssm=lambda: _client(TaskService.SSM, clients),
            sts=lambda: _client(TaskService.STS, clients),
            s3=lambda: _client(TaskService.S3, clients),
            secrets=lambda: _client(TaskService.SECRETS_MANAGER, clients),
            transport=_transport,
            resolve_origin=_resolve_origin,
            # The task-side spent-identity source is an owner decision not yet taken
            # (ADR-0043 §3): none is configured, and the accepted registry refuses.
            spent_identities=None,
            now=now,
            monotonic=time.monotonic,
            sleep=time.sleep,
            cleanup=_working_directory_cleanup(working_directory),
        )
    from kalpamani.data.production.sharadar.build_entry import BuildFactories

    return BuildFactories(
        environment_names=_environment_names,
        environment=_environment,
        metadata_fetch=_metadata_fetch,
        ssm=lambda: _client(TaskService.SSM, clients),
        sts=lambda: _client(TaskService.STS, clients),
        s3=lambda: _client(TaskService.S3, clients),
        now=now,
        monotonic=time.monotonic,
        sleep=time.sleep,
        cleanup=_working_directory_cleanup(working_directory),
    )


def _emit(lines: Iterable[str]) -> None:
    for line in lines:
        print(line)


def main(argv: Sequence[str] | None = None) -> int:
    """Select one closed entry, run it once, print the receipt, return its exit code.

    ``0`` means the selected actor's processing completed with every operation
    confirmed; non-zero names what refused or stopped short. **Neither is a data
    verdict.** This function has run only inside local, network-disabled verification
    containers built with synthetic configurations (docs/operations/production-image-build.md);
    it has never run as an ECS task, and never against AWS.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)

    from kalpamani.data.production.sharadar.entry import (
        TaskOutcome,
        no_entry_receipt,
        pre_entry_refusal,
        refusal_receipt,
        run_task_entry,
        select_entry,
    )

    entry = select_entry(arguments)
    if entry is None:
        # Nothing above this line looked anything up or constructed anything. The
        # receipt names no entry and no actor, carries no configuration, bootstrap or
        # binding evidence, and reports the zero counts this process can prove
        # (ADR-0044 s.4): the same one machine-readable line, last, as every outcome.
        receipt = no_entry_receipt()
        _emit(receipt.render())
        return receipt.exit_code

    configuration = _compiled_configuration(entry)
    if configuration is None:
        # No compiled configuration, no working directory, no factory, no client. The
        # receipt names the selected entry and nothing the file would have supplied:
        # code commit and configuration digest are null, never a placeholder.
        receipt = refusal_receipt(entry, TaskOutcome.REFUSED_CONFIGURATION)
        _emit(receipt.render())
        return receipt.exit_code

    # The entry's own pre-construction checks, made here BEFORE the working directory
    # exists: a process that is not a task's (no container credential environment)
    # refuses with nothing created and nothing to clean up. The selected entry repeats
    # exactly the same accepted check on its own path; it is one function, not two rules.
    refused = pre_entry_refusal(
        entry=entry,
        configuration=configuration,
        environment_names=_environment_names,
        environment=_environment,
    )
    if refused is not None:
        receipt = refusal_receipt(entry, refused, configuration=configuration)
        _emit(receipt.render())
        return receipt.exit_code

    import tempfile

    try:
        working_directory = tempfile.mkdtemp(prefix="kalpamani-task-", dir=TASK_WORKING_ROOT)
    except OSError:
        # No usable working root: the task definition's tmpfs is absent or unwritable.
        # Refused before any factory or client exists, with the zero counts that proves.
        receipt = refusal_receipt(
            entry, TaskOutcome.REFUSED_DEPENDENCY, configuration=configuration
        )
        _emit(receipt.render())
        return receipt.exit_code
    receipt = run_task_entry(
        entry=entry,
        configuration=configuration,
        factories=_factories(entry, working_directory),
    )
    _emit(receipt.render())
    return receipt.exit_code


__all__ = ["COMPILED_CONFIGURATION_PATH", "NO_ENTRY_EXIT_STATUS", "TASK_WORKING_ROOT", "main"]


if __name__ == "__main__":  # pragma: no cover - the image's process entry
    sys.exit(main())
