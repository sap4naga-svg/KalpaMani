"""Credential isolation of the task image entrypoint, through its real construction path.

Every client the image builds must obtain credentials from the ECS container credential
provider and from nothing else. These tests drive the script's own ``_isolated_session``,
``_IsolatedClients`` and ``_factories`` with synthetic seams -- a synthetic shared
credentials file and config file the process is pointed at, static keys and a profile in
the process environment, a seeded ``boto3`` default session, and a fake HTTP session
standing in for the agent -- and assert which provider answered and which were never
consulted. **The workstation's own AWS configuration is never read: every file and
variable consulted here is one the test wrote.** No request leaves the process.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_entry import CONTAINER_URI, METADATA_URI, ORIGIN_ADDRESSES
from fixtures.production_runtime import compiled_task
from kalpamani.data.production.sharadar.entry import (
    EntryConfiguration,
    TaskEntry,
    TaskOutcome,
    run_task_entry,
)
from kalpamani.data.production.sharadar.task_clients import TaskService
from kalpamani.data.production.sharadar.vocabulary import ProductionActor

pytestmark = pytest.mark.unit

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = REPO_ROOT / "scripts" / "production_task_entrypoint.py"

FILE_KEY: Final = "AKIASYNTHETICFILE0000"
ENV_KEY: Final = "AKIASYNTHETICENV00000"
SEEDED_KEY: Final = "AKIASYNTHETICSEEDED00"
CONTAINER_KEY: Final = "ASIASYNTHETICCONTAINER"
CONTAINER_URL: Final = "http://169.254.170.2" + CONTAINER_URI


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("production_task_entrypoint_creds", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entrypoint = _module()


class _Response:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.content = body


class FakeAgentHttp:
    """The fetcher's HTTP seam: answers the container URL, records every request."""

    def __init__(
        self,
        *,
        fail: bool = False,
        expires_in: dt.timedelta = dt.timedelta(hours=6),
        first_expires_in: dt.timedelta | None = None,
    ) -> None:
        self.fail = fail
        self.expires_in = expires_in
        self.first_expires_in = first_expires_in
        self.urls: list[str] = []
        self.headers: list[dict[str, str]] = []

    def send(self, request: Any) -> _Response:
        self.urls.append(request.url)
        self.headers.append(dict(request.headers))
        if self.fail:
            return _Response(500, b"synthetic agent failure 000000000000")
        window = self.expires_in
        if self.first_expires_in is not None and len(self.urls) == 1:
            window = self.first_expires_in
        expiry = (dt.datetime.now(dt.UTC) + window).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {
            "AccessKeyId": f"{CONTAINER_KEY}{len(self.urls)}",
            "SecretAccessKey": "synthetic-container-secret",
            "Token": "synthetic-container-token",
            "Expiration": expiry,
        }
        return _Response(200, json.dumps(body).encode())


@pytest.fixture
def ambient(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, str]:
    """A process full of synthetic ambient credential sources, none of them the container.

    Points the SDK's file variables at files this fixture wrote, sets static keys and a
    profile, and seeds ``boto3.DEFAULT_SESSION``. The real workstation configuration is
    shadowed by these variables for the duration of the test and never read.
    """
    credentials = tmp_path / "credentials"
    credentials.write_text(
        f"[default]\naws_access_key_id = {FILE_KEY}\naws_secret_access_key = synthetic-file\n"
        f"[task]\naws_access_key_id = {FILE_KEY}\naws_secret_access_key = synthetic-file\n",
        encoding="utf-8",
    )
    config = tmp_path / "config"
    config.write_text(
        "[default]\nregion = eu-west-1\ncredential_process = synthetic-process\n"
        "[profile task]\nrole_arn = arn:aws:iam::000000000000:role/synthetic\n"
        "source_profile = default\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(credentials))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", ENV_KEY)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-env-secret")
    monkeypatch.setenv("AWS_PROFILE", "task")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_FULL_URI", "http://localhost:9/full")
    monkeypatch.setenv("AWS_CONTAINER_AUTHORIZATION_TOKEN", "synthetic-token")
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", CONTAINER_URI)
    import boto3  # type: ignore[import-untyped]

    seeded = boto3.Session(
        aws_access_key_id=SEEDED_KEY,
        aws_secret_access_key="seeded",  # noqa: S106 - synthetic
        region_name="us-east-1",
    )
    monkeypatch.setattr(boto3, "DEFAULT_SESSION", seeded)
    return dict(os.environ)


def _session(environment: dict[str, str], http: FakeAgentHttp) -> Any:
    return entrypoint._isolated_session(environment, http=http, sleep=lambda seconds: None)


# ---------------------------------------------------------------------------
# The session
# ---------------------------------------------------------------------------


def test_the_resolver_holds_only_the_container_provider(ambient: dict[str, str]) -> None:
    from botocore.credentials import ContainerProvider  # type: ignore[import-untyped]

    session = _session(ambient, FakeAgentHttp())
    providers = session.get_component("credential_provider").providers
    assert [type(p) for p in providers] == [ContainerProvider]
    names = {type(p).__name__ for p in providers}
    for forbidden in (
        "EnvProvider",
        "SharedCredentialProvider",
        "ConfigProvider",
        "ProcessProvider",
        "AssumeRoleProvider",
        "AssumeRoleWithWebIdentityProvider",
        "SSOProvider",
        "InstanceMetadataProvider",
        "OriginalEC2Provider",
        "BotoProvider",
        "CachedCredentialFetcher",
    ):
        assert forbidden not in names


def test_synthetic_default_files_env_keys_profile_and_seeded_session_supply_nothing(
    ambient: dict[str, str],
) -> None:
    import boto3

    http = FakeAgentHttp()
    session = _session(ambient, http)
    credentials = session.get_credentials()
    assert credentials.method == "container-role"
    assert credentials.access_key.startswith(CONTAINER_KEY)
    assert credentials.access_key not in (FILE_KEY, ENV_KEY, SEEDED_KEY)
    assert http.urls == [CONTAINER_URL]
    assert "Authorization" not in http.headers[0]
    # The session consulted no profile and no file the process names.
    assert session.get_config_variable("profile") is None
    assert not Path(session.get_config_variable("config_file")).exists()
    assert not Path(session.get_config_variable("credentials_file")).exists()
    assert session.full_config == {"profiles": {}}
    # boto3's default session is neither reused nor touched.
    assert boto3.DEFAULT_SESSION.get_credentials().access_key == SEEDED_KEY
    assert session is not boto3.DEFAULT_SESSION._session


def test_the_provider_sees_only_the_relative_uri(ambient: dict[str, str]) -> None:
    session = _session(ambient, FakeAgentHttp())
    provider = session.get_component("credential_provider").providers[0]
    assert dict(provider._environ) == {"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": CONTAINER_URI}


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://localhost:9/full"},
        {"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v4/abc/task"},
        {"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "http://169.254.170.2" + CONTAINER_URI},
        {"AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": ""},
    ],
)
def test_an_invalid_or_absent_container_source_refuses_before_a_session_exists(
    environment: dict[str, str],
) -> None:
    http = FakeAgentHttp()
    with pytest.raises(ValueError) as refusal:
        _session(environment, http)
    assert http.urls == [] and "169.254" not in str(refusal.value)


def test_a_container_failure_is_closed_and_consults_nothing_else(ambient: dict[str, str]) -> None:
    from botocore.exceptions import CredentialRetrievalError  # type: ignore[import-untyped]

    http = FakeAgentHttp(fail=True)
    session = _session(ambient, http)
    with pytest.raises(CredentialRetrievalError):
        session.get_credentials()
    # Three bounded attempts against the agent URL, and no other source.
    assert http.urls == [CONTAINER_URL] * 3


def test_refresh_goes_through_the_same_provider_only(ambient: dict[str, str]) -> None:
    # The first answer expires inside the SDK's mandatory-refresh window, so the first
    # use refreshes; the second answer is long-lived, so nothing refreshes after it.
    http = FakeAgentHttp(first_expires_in=dt.timedelta(minutes=5))
    session = _session(ambient, http)
    credentials = session.get_credentials()
    assert credentials.method == "container-role" and http.urls == [CONTAINER_URL]
    frozen = credentials.get_frozen_credentials()
    assert frozen.access_key == f"{CONTAINER_KEY}2"
    assert http.urls == [CONTAINER_URL, CONTAINER_URL]
    assert credentials.get_frozen_credentials().access_key == f"{CONTAINER_KEY}2"
    assert http.urls == [CONTAINER_URL, CONTAINER_URL]
    providers = session.get_component("credential_provider").providers
    assert [type(p).__name__ for p in providers] == ["ContainerProvider"]


# ---------------------------------------------------------------------------
# The clients and the factories
# ---------------------------------------------------------------------------


def test_every_client_keeps_region_endpoint_and_one_attempt(ambient: dict[str, str]) -> None:
    http = FakeAgentHttp()
    clients = entrypoint._IsolatedClients(ambient, http=http, sleep=lambda s: None)
    built = {service: clients.client(service) for service in TaskService}
    for client in built.values():
        assert client.meta.region_name == "us-east-1"  # never the ambient eu-west-1
        assert client.meta.config.retries == {"total_max_attempts": 1, "mode": "standard"}
        assert client.meta.config.connect_timeout == 5.0
        assert client.meta.config.read_timeout == 10.0
        signer_credentials = client._request_signer._credentials
        assert signer_credentials.method == "container-role"
    assert built[TaskService.STS].meta.endpoint_url == "https://sts.us-east-1.amazonaws.com"
    # One session, one retrieval, shared by the four clients.
    assert http.urls == [CONTAINER_URL]


def test_the_real_factories_build_container_credentialed_clients(
    ambient: dict[str, str], tmp_path: Path
) -> None:
    http = FakeAgentHttp()
    clients = entrypoint._IsolatedClients(ambient, http=http, sleep=lambda s: None)
    for entry in TaskEntry:
        factories = entrypoint._factories(entry, str(tmp_path), clients=clients)
        ssm = factories.ssm()
        assert ssm._request_signer._credentials.access_key.startswith(CONTAINER_KEY)
        assert factories.sts().meta.endpoint_url == "https://sts.us-east-1.amazonaws.com"
    assert http.urls == [CONTAINER_URL]


def test_the_script_never_calls_boto3_client_or_reuses_the_default_session() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    executable = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("#", '"""'))
    )
    assert "boto3.client(" not in executable
    assert "boto3.Session(" not in executable and "DEFAULT_SESSION" not in executable
    assert "boto3.setup_default_session" not in executable
    assert (
        "register_component(" in executable
        and "CredentialResolver(providers=[provider])" in executable
    )


# ---------------------------------------------------------------------------
# Through the entry: a container failure refuses closed with zero service requests
# ---------------------------------------------------------------------------


def _configuration(entry: TaskEntry) -> EntryConfiguration:
    if entry is TaskEntry.ACQUISITION:
        return EntryConfiguration(
            entry=entry,
            compiled=compiled_task(ProductionActor.ACQUISITION),
            secret_identifier="synthetic/production/sharadar",  # noqa: S106 - an identifier
            origin_addresses=ORIGIN_ADDRESSES,
        )
    from fixtures.production_build import configuration

    return EntryConfiguration(
        entry=entry,
        compiled=compiled_task(ProductionActor.BUILD),
        build_configuration=configuration(),
    )


@pytest.mark.parametrize("entry", list(TaskEntry))
def test_a_container_failure_through_the_real_entry_is_a_dependency_refusal(
    entry: TaskEntry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The real script factories, a task-shaped environment, an agent that fails."""
    for name in list(os.environ):
        if name.startswith("AWS_") or name.startswith("KALPAMANI_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", CONTAINER_URI)
    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", METADATA_URI)
    monkeypatch.setattr(entrypoint, "_metadata_fetch", _never("metadata fetch"))
    monkeypatch.setattr(entrypoint, "_transport", _never("transport"))
    monkeypatch.setattr(entrypoint, "_resolve_origin", lambda host: sorted(ORIGIN_ADDRESSES))
    http = FakeAgentHttp(fail=True)
    clients = entrypoint._IsolatedClients(dict(os.environ), http=http, sleep=lambda s: None)
    work = tmp_path / "work"
    work.mkdir()
    receipt = run_task_entry(
        entry=entry,
        configuration=_configuration(entry),
        factories=entrypoint._factories(entry, str(work), clients=clients),
    )
    assert receipt.outcome is TaskOutcome.REFUSED_DEPENDENCY and receipt.exit_code == 6
    assert receipt.counts.data_plane_operations == 0 and receipt.counts.identity_calls == 0
    assert http.urls == [CONTAINER_URL] * 3  # the agent only; no service endpoint
    assert not work.exists()  # cleanup ran and the primary outcome was kept
    rendered = "\n".join(receipt.render())
    assert "000000000000" not in rendered and "169.254" not in rendered


def _never(what: str) -> Any:
    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"{what} must not be reached")

    return refuse


def test_importing_the_script_still_loads_no_sdk() -> None:
    before = {name for name in sys.modules if name.split(".")[0] in ("boto3", "botocore")}
    _module()
    after = {name for name in sys.modules if name.split(".")[0] in ("boto3", "botocore")}
    assert after == before
