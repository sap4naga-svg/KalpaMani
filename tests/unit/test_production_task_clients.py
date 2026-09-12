"""The task-side metadata source, client boundaries and the proposed spent-identity document.

Pure functions and injected fakes throughout. **No socket, no SDK: nothing here is AWS
or provider verification.**
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from fixtures.production_entry import METADATA_URI, FakeSts
from fixtures.production_runtime import (
    ACCOUNT,
    OTHER_TASK_ARN,
    TASK_ARN,
    FakeSsm,
    encode,
    metadata_document,
    task_identity_arn,
)
from kalpamani.data.ingest.sharadar.transport import ALLOWED_HOST
from kalpamani.data.production.sharadar import spent_source, task_clients
from kalpamani.data.production.sharadar.identities import (
    SpentStatus,
    UnavailableSpentIdentities,
    spent_status_of,
)
from kalpamani.data.production.sharadar.metadata import parse_task_metadata
from kalpamani.data.production.sharadar.parameters import SsmParameterAdapter
from kalpamani.data.production.sharadar.task_clients import (
    CONTAINER_CREDENTIAL_VARIABLE,
    IdentityUnavailableError,
    PutOnlyS3Client,
    ReadWriteS3Client,
    StsCallerIdentityAdapter,
    TaskService,
    client_config_kwargs,
    client_construction_kwargs,
    compiled_origin_addresses,
    container_credential_source_refusal,
    container_credentials_url,
    origin_address_refusal,
    sts_endpoint_url,
    task_credential_environment_refusal,
)
from kalpamani.data.production.sharadar.task_metadata import (
    MAX_METADATA_BYTES,
    METADATA_HOST,
    METADATA_TIMEOUT_SECONDS,
    TaskMetadataDefect,
    TaskMetadataError,
    contradiction_refusal,
    decode_task_document,
    fetch_task_metadata,
    task_metadata_url,
)
from kalpamani.data.production.sharadar.vocabulary import ProductionActor
from kalpamani.data.qualify.sharadar.plan import s3_client_config_kwargs

pytestmark = pytest.mark.unit

ACQ: Final = ProductionActor.ACQUISITION
NOW: Final = datetime(2026, 9, 12, 20, 0, tzinfo=UTC)
PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Task metadata
# ---------------------------------------------------------------------------


class TestTaskMetadataUrl:
    def test_the_documented_uri_yields_the_task_path(self) -> None:
        assert task_metadata_url(METADATA_URI) == METADATA_URI + "/task"

    @pytest.mark.parametrize(
        "uri",
        [
            None,
            "",
            b"http://169.254.170.2/v4/x",
            "https://169.254.170.2/v4/x",
            "http://169.254.170.2.attacker.example/v4/x",
            "http://attacker.example/v4/x",
            "http://user:pw@169.254.170.2/v4/x",
            "http://169.254.170.2:8080/v4/x",
            "http://169.254.170.2/v3/x",
            "http://169.254.170.2/v4/",
            "http://169.254.170.2/v4/x/",
            "http://169.254.170.2/v4/x?y=1",
            "http://169.254.170.2/v4/x#frag",
            "http://169.254.170.2/v4/a b",
            "http://[::1]/v4/x",
        ],
    )
    def test_anything_else_is_refused_before_a_fetch(self, uri: object) -> None:
        with pytest.raises(TaskMetadataError) as refusal:
            task_metadata_url(uri)
        assert refusal.value.defect in (
            TaskMetadataDefect.URI_MISSING,
            TaskMetadataDefect.URI_REFUSED,
        )
        assert "169.254" not in str(refusal.value) and "attacker" not in str(refusal.value)


class TestFetchTaskMetadata:
    def _environment(self, uri: str | None = METADATA_URI) -> Any:
        return lambda name: uri if name == "ECS_CONTAINER_METADATA_URI_V4" else None

    def test_one_bounded_read_returns_the_validated_document(self) -> None:
        calls: list[tuple[str, float, int]] = []

        def fetch(url: str, timeout: float, max_bytes: int) -> bytes:
            calls.append((url, timeout, max_bytes))
            return encode(metadata_document(ACQ))

        document = fetch_task_metadata(environment=self._environment(), fetch=fetch)
        assert calls == [(METADATA_URI + "/task", METADATA_TIMEOUT_SECONDS, MAX_METADATA_BYTES)]
        assert parse_task_metadata(document) is not None

    def test_a_missing_variable_refuses_without_fetching(self) -> None:
        calls = 0

        def fetch(url: str, timeout: float, max_bytes: int) -> bytes:
            nonlocal calls
            calls += 1
            return b"{}"

        with pytest.raises(TaskMetadataError) as refusal:
            fetch_task_metadata(environment=self._environment(None), fetch=fetch)
        assert refusal.value.defect is TaskMetadataDefect.URI_MISSING and calls == 0

    def test_a_fetch_failure_is_value_free(self) -> None:
        def fetch(url: str, timeout: float, max_bytes: int) -> bytes:
            raise TimeoutError("synthetic timeout at " + url)

        with pytest.raises(TaskMetadataError) as refusal:
            fetch_task_metadata(environment=self._environment(), fetch=fetch)
        assert refusal.value.defect is TaskMetadataDefect.FETCH_FAILED
        assert "169.254" not in str(refusal.value) and refusal.value.__cause__ is None

    @pytest.mark.parametrize(
        ("raw", "defect"),
        [
            (b"", TaskMetadataDefect.RESPONSE_MALFORMED),
            (b"{" + b" " * MAX_METADATA_BYTES + b"}", TaskMetadataDefect.RESPONSE_TOO_LARGE),
            (b"\xef\xbb\xbf{}", TaskMetadataDefect.RESPONSE_MALFORMED),
            (b"\xff\xfe", TaskMetadataDefect.RESPONSE_MALFORMED),
            (b"[]", TaskMetadataDefect.RESPONSE_MALFORMED),
            (b'{"TaskARN": "a", "TaskARN": "b"}', TaskMetadataDefect.RESPONSE_MALFORMED),
            (b"{}", TaskMetadataDefect.FIELDS_INCOMPLETE),
        ],
        ids=[
            "empty",
            "oversize",
            "bom",
            "not-utf8",
            "not-an-object",
            "duplicate-key",
            "incomplete",
        ],
    )
    def test_malformed_or_incomplete_responses_refuse(
        self, raw: bytes, defect: TaskMetadataDefect
    ) -> None:
        with pytest.raises(TaskMetadataError) as refusal:
            fetch_task_metadata(environment=self._environment(), fetch=lambda *args: raw)
        assert refusal.value.defect is defect

    def test_the_size_ceiling_is_checked_before_decoding(self) -> None:
        oversize = b"\xff" * (MAX_METADATA_BYTES + 1)
        with pytest.raises(TaskMetadataError) as refusal:
            decode_task_document(oversize)
        assert refusal.value.defect is TaskMetadataDefect.RESPONSE_TOO_LARGE

    def test_both_documented_cluster_representations_are_admitted(self) -> None:
        """v4 documents ``Cluster`` as the ARN or the short name; both must agree with TaskARN."""
        arn_form = metadata_document(ACQ)
        assert arn_form["Cluster"].startswith("arn:aws:ecs:")
        name_form = {**metadata_document(ACQ), "Cluster": "synthetic-research-cluster"}
        for document in (arn_form, name_form):
            parsed = parse_task_metadata(document)
            assert parsed is not None
            assert contradiction_refusal(document, parsed) is None
            fetched = fetch_task_metadata(
                environment=self._environment(), fetch=lambda *a, d=document: encode(d)
            )
            assert fetched["Cluster"] == document["Cluster"]

    def test_a_contradictory_cluster_refuses(self) -> None:
        other_account = "arn:aws:ecs:us-east-1:999999999999:cluster/synthetic-research-cluster"
        other_region = f"arn:aws:ecs:eu-west-1:{ACCOUNT}:cluster/synthetic-research-cluster"
        other_partition = f"arn:aws-cn:ecs:us-east-1:{ACCOUNT}:cluster/synthetic-research-cluster"
        other_cluster = f"arn:aws:ecs:us-east-1:{ACCOUNT}:cluster/another-cluster"
        for cluster in (
            other_account,
            other_region,
            other_partition,
            other_cluster,
            "another-cluster",
            "synthetic-research-cluster ",
            "arn:aws:ecs:us-east-1:cluster/synthetic-research-cluster",
            "not an arn",
            7,
        ):
            document = {**metadata_document(ACQ), "Cluster": cluster}
            with pytest.raises(TaskMetadataError) as refusal:
                fetch_task_metadata(
                    environment=self._environment(), fetch=lambda *a, d=document: encode(d)
                )
            assert refusal.value.defect is TaskMetadataDefect.FIELDS_CONTRADICTORY, cluster
        consistent = {k: v for k, v in metadata_document(ACQ).items() if k != "Cluster"}
        assert contradiction_refusal(consistent, parse_task_metadata(consistent)) is None  # type: ignore[arg-type]
        parsed = parse_task_metadata(metadata_document(ACQ))
        assert parsed is not None and parsed.task_arn == TASK_ARN
        assert contradiction_refusal(metadata_document(ACQ), parsed) is None
        assert OTHER_TASK_ARN != TASK_ARN

    def test_no_subnet_or_public_ip_self_check_exists(self) -> None:
        source = (
            PROJECT_ROOT / "src" / "kalpamani" / "data" / "production" / "sharadar"
        ) / "task_metadata.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    node.body = node.body[1:] or [ast.Pass()]
        executable = ast.unparse(tree)
        for name in ("Subnet", "PublicIp", "PrivateIPv4", "Networks", "IPv4Addresses"):
            assert name not in executable


# ---------------------------------------------------------------------------
# Identity adapter and capability wrappers
# ---------------------------------------------------------------------------


class TestIdentityAdapter:
    def test_one_call_returns_the_three_documented_fields_only(self) -> None:
        sts = FakeSts(task_identity_arn(ACQ))
        adapter = StsCallerIdentityAdapter(sts=sts)
        answer = adapter()
        assert set(answer) == {"UserId", "Account", "Arn"} and sts.calls == adapter.calls == 1
        assert "Arn" not in repr(adapter) and ACCOUNT not in repr(adapter)

    def test_a_failure_or_a_malformed_response_is_value_free(self) -> None:
        adapter = StsCallerIdentityAdapter(sts=FakeSts(task_identity_arn(ACQ), failure="Expired"))
        with pytest.raises(IdentityUnavailableError) as refusal:
            adapter()
        assert refusal.value.__cause__ is None and adapter.calls == 1

        class Partial:
            def get_caller_identity(self) -> dict[str, Any]:
                return {"Account": ACCOUNT}

        with pytest.raises(IdentityUnavailableError):
            StsCallerIdentityAdapter(sts=Partial())()
        with pytest.raises(TypeError):
            StsCallerIdentityAdapter(sts=object())  # type: ignore[arg-type]

    def test_the_wrappers_expose_exactly_their_capability(self) -> None:
        class Everything:
            def put_object(self, **kwargs: Any) -> str:
                return "put"

            def get_object(self, **kwargs: Any) -> str:
                return "get"

            def head_object(self, **kwargs: Any) -> str:
                return "head"

            def list_objects_v2(self, **kwargs: Any) -> str:
                return "list"

            def delete_object(self, **kwargs: Any) -> str:
                return "delete"

        put_only = PutOnlyS3Client(Everything())
        assert put_only.put_object(Key="k") == "put"
        for method in ("get_object", "head_object", "list_objects_v2", "delete_object"):
            assert not hasattr(put_only, method)
        read_write = ReadWriteS3Client(Everything())
        assert read_write.get_object(Key="k") == "get" and read_write.put_object(Key="k") == "put"
        for method in ("head_object", "list_objects_v2", "delete_object"):
            assert not hasattr(read_write, method)
        with pytest.raises(TypeError):
            PutOnlyS3Client(object())
        with pytest.raises(TypeError):
            ReadWriteS3Client(PutOnlyS3Client(Everything()))
        assert "Everything" not in repr(put_only) + repr(read_write)


# ---------------------------------------------------------------------------
# Client configuration
# ---------------------------------------------------------------------------


class TestClientConfiguration:
    def test_s3_takes_the_accepted_qualification_configuration_unchanged(self) -> None:
        assert client_config_kwargs(TaskService.S3) == s3_client_config_kwargs()

    @pytest.mark.parametrize("service", list(TaskService))
    def test_every_service_has_one_attempt_in_total_and_finite_timeouts(
        self, service: TaskService
    ) -> None:
        kwargs = client_config_kwargs(service)
        assert kwargs["retries"] == {"total_max_attempts": 1, "mode": "standard"}
        assert "max_attempts" not in kwargs["retries"]  # type: ignore[operator,unused-ignore]
        assert 0 < float(kwargs["connect_timeout"]) < 60  # type: ignore[arg-type]
        assert 0 < float(kwargs["read_timeout"]) < 60  # type: ignore[arg-type]

    def test_construction_keywords_pin_the_region_and_the_regional_sts_endpoint(self) -> None:
        for service in TaskService:
            kwargs = client_construction_kwargs(service)
            assert kwargs["service_name"] == service.value
            assert kwargs["region_name"] == "us-east-1"
            assert kwargs["config"] == client_config_kwargs(service)
            if service is TaskService.STS:
                assert kwargs["endpoint_url"] == "https://sts.us-east-1.amazonaws.com"
            else:
                assert "endpoint_url" not in kwargs
        assert sts_endpoint_url() == "https://sts.us-east-1.amazonaws.com"
        with pytest.raises(ValueError):
            sts_endpoint_url("eu-west-1")
        with pytest.raises(TypeError):
            client_config_kwargs("s3")  # type: ignore[arg-type]

    def test_the_module_names_no_sdk_and_no_profile(self) -> None:
        source = (
            PROJECT_ROOT / "src" / "kalpamani" / "data" / "production" / "sharadar"
        ) / "task_clients.py"
        text = source.read_text(encoding="utf-8")
        assert "import boto3" not in text and "botocore" not in text.replace(
            "botocore ``Config``", ""
        )
        assert "profile_name" not in text


class TestCredentialEnvironment:
    def test_a_task_environment_is_admitted(self) -> None:
        assert (
            task_credential_environment_refusal(
                ["PATH", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_REGION"]
            )
            is None
        )
        assert task_credential_environment_refusal(["AWS_CONTAINER_CREDENTIALS_FULL_URI"])
        assert task_credential_environment_refusal(
            ["AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONTAINER_AUTHORIZATION_TOKEN"]
        )

    def test_the_container_relative_uri_is_validated_by_value(self) -> None:
        good = "/v2/credentials/00000000-0000-4000-8000-000000000000"
        assert (
            container_credential_source_refusal({CONTAINER_CREDENTIAL_VARIABLE: good}.get) is None
        )
        assert container_credentials_url(good) == "http://169.254.170.2" + good
        assert container_credentials_url(good).split("/v2/")[0] == "http://" + METADATA_HOST
        assert "/v4/" not in container_credentials_url(good)
        for bad in (
            None,
            "",
            7,
            "http://169.254.170.2" + good,
            "/v4/abc/task",
            "/v2/credentials/",
            good + "?x=1",
            good + "#f",
            "/v2/credentials/abc/def",
            " " + good,
        ):
            reason = container_credential_source_refusal({CONTAINER_CREDENTIAL_VARIABLE: bad}.get)
            assert reason is not None and "169.254" not in reason, bad
        with pytest.raises(ValueError):
            container_credentials_url("/v4/abc/task")

        def raising(name: str) -> str:
            raise RuntimeError("synthetic")

        assert container_credential_source_refusal(raising) is not None

    @pytest.mark.parametrize(
        "names",
        [
            ["PATH"],
            ["AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_PROFILE"],
            ["AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_ACCESS_KEY_ID"],
            ["AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_SESSION_TOKEN"],
            ["AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_CONFIG_FILE"],
            ["AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_ROLE_ARN"],
            ["AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "AWS_DEFAULT_PROFILE"],
        ],
    )
    def test_a_workstation_or_default_chain_environment_is_refused(self, names: list[str]) -> None:
        reason = task_credential_environment_refusal(names)
        assert reason is not None and "AWS_" not in reason


class TestOrigin:
    def test_the_pinned_host_is_the_transports(self) -> None:
        assert task_clients.PROVIDER_ORIGIN_HOST == ALLOWED_HOST

    def test_resolution_inside_the_compiled_set_is_admitted(self) -> None:
        compiled = compiled_origin_addresses(["192.0.2.10", "192.0.2.11", "192.0.2.10"])
        assert compiled == frozenset({"192.0.2.10", "192.0.2.11"})
        hosts: list[str] = []

        def resolve(host: str) -> list[str]:
            hosts.append(host)
            return ["192.0.2.11"]

        assert origin_address_refusal(compiled=compiled, resolve=resolve) is None
        assert hosts == [ALLOWED_HOST]

    def test_every_other_case_refuses(self) -> None:
        compiled = compiled_origin_addresses(["192.0.2.10"])
        assert origin_address_refusal(compiled=frozenset(), resolve=lambda h: ["192.0.2.10"])
        assert origin_address_refusal(compiled=compiled, resolve=lambda h: [])
        assert origin_address_refusal(compiled=compiled, resolve=lambda h: ["198.51.100.1"])
        assert origin_address_refusal(compiled=compiled, resolve=lambda h: ["192.0.2.10", "::1"])
        assert origin_address_refusal(compiled=compiled, resolve=lambda h: [b"192.0.2.10"])

        def failing(host: str) -> list[str]:
            raise OSError("synthetic")

        assert origin_address_refusal(compiled=compiled, resolve=failing)
        for bad in (["not-an-address"], [7], ["::1"]):
            with pytest.raises(ValueError):
                compiled_origin_addresses(bad)


# ---------------------------------------------------------------------------
# The proposed spent-identity document
# ---------------------------------------------------------------------------


class TestSpentIdentityDocument:
    def _document(self, **overrides: Any) -> dict[str, Any]:
        document = spent_source.build_spent_identity_document(
            ["synthetic-production-run-0002", "synthetic-production-run-0001"],
            issued_at=NOW - timedelta(hours=1),
            expires_at=NOW + timedelta(hours=1),
        )
        document.update(overrides)
        return document

    def test_a_valid_document_yields_the_ledger_registry(self) -> None:
        parsed = spent_source.parse_spent_identity_document(self._document(), now=NOW)
        registry = parsed.registry()
        assert registry.status("synthetic-production-run-0001") is SpentStatus.SPENT
        assert registry.status("synthetic-production-run-0009") is SpentStatus.UNSPENT
        assert "synthetic" not in repr(parsed)

    @pytest.mark.parametrize(
        ("overrides", "defect"),
        [
            ({"extra": 1}, spent_source.SpentDocumentDefect.FIELD_UNKNOWN),
            ({"schema_version": 2}, spent_source.SpentDocumentDefect.SCHEMA_VERSION),
            ({"contract_id": "other"}, spent_source.SpentDocumentDefect.CONTRACT_ID),
            ({"actor": "build"}, spent_source.SpentDocumentDefect.ACTOR),
            ({"issued_at": "yesterday"}, spent_source.SpentDocumentDefect.TIMESTAMP_MALFORMED),
            (
                {"expires_at": (NOW + timedelta(hours=30)).isoformat()},
                spent_source.SpentDocumentDefect.VALIDITY_TOO_LONG,
            ),
            (
                {"expires_at": (NOW - timedelta(minutes=1)).isoformat()},
                spent_source.SpentDocumentDefect.STALE,
            ),
            ({"spent": ["b", "a"]}, spent_source.SpentDocumentDefect.SPENT_MALFORMED),
            (
                {"spent": ["synthetic-production-run-0001"]},
                spent_source.SpentDocumentDefect.DIGEST_MISMATCH,
            ),
        ],
    )
    def test_each_defect_refuses(
        self, overrides: dict[str, Any], defect: spent_source.SpentDocumentDefect
    ) -> None:
        with pytest.raises(spent_source.SpentDocumentError) as refusal:
            spent_source.parse_spent_identity_document(self._document(**overrides), now=NOW)
        assert refusal.value.defect is defect

    def test_a_missing_field_refuses(self) -> None:
        document = self._document()
        del document["spent_digest"]
        with pytest.raises(spent_source.SpentDocumentError) as refusal:
            spent_source.parse_spent_identity_document(document, now=NOW)
        assert refusal.value.defect is spent_source.SpentDocumentDefect.FIELD_MISSING

    def test_every_load_failure_is_unavailable_never_unspent(self) -> None:
        ssm = FakeSsm()
        parameter = "/synthetic/spent"
        for value in (
            None,
            b"",
            b"{not json",
            encode(self._document(actor="build")),
            encode(self._document(expires_at=(NOW - timedelta(minutes=1)).isoformat())),
        ):
            if value is None:
                ssm.values.pop(parameter, None)
            else:
                ssm.values[parameter] = value
            registry = spent_source.load_spent_identities(
                reader=SsmParameterAdapter(ssm=ssm), parameter=parameter, now=lambda: NOW
            )
            assert type(registry) is UnavailableSpentIdentities
            assert (
                spent_status_of(registry, "synthetic-production-run-0001")
                is SpentStatus.UNAVAILABLE
            )
        ssm.values[parameter] = encode(self._document())
        registry = spent_source.load_spent_identities(
            reader=SsmParameterAdapter(ssm=ssm), parameter=parameter, now=lambda: NOW
        )
        assert spent_status_of(registry, "synthetic-production-run-0001") is SpentStatus.SPENT

    def test_the_proposed_source_is_wired_to_nothing(self) -> None:
        production = PROJECT_ROOT / "src" / "kalpamani" / "data" / "production" / "sharadar"
        for path in sorted(production.glob("*.py")):
            if path.name == "spent_source.py":
                continue
            assert "spent_source" not in path.read_text(encoding="utf-8"), path.name
        script = PROJECT_ROOT / "scripts" / "production_task_entrypoint.py"
        assert "spent_source" not in script.read_text(encoding="utf-8")
        assert "spent_identities=None" in script.read_text(encoding="utf-8")
        assert json.dumps(self._document())  # the document is plain JSON
