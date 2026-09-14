"""The launch tool's records (proposed ADR-0045), on synthetic documents only.

One identity, one authorization: an identity in the ledger is consumed for both kinds; a
verification identity carries the reserved prefix and a production one may not; a
materialized input carries the ledger's whole identity set; only a receipt-verified
COMPLETED production acquisition row is buildable; a provisional row is what an exit
code can support and no more; completion needs a receipt bound to the launch record.
**Mocked results are not AWS verification.**
"""

from __future__ import annotations

import dataclasses
import json
from datetime import timedelta
from typing import Any, Final

import pytest

from fixtures.production_build import RUN_1, RUN_1_AT, configuration, slice_for_run
from fixtures.production_entry import ORIGIN_ADDRESSES, AcquisitionHarness, VerificationHarness
from fixtures.production_launch import (
    ACQ,
    BLD,
    GENERATION_RECORD_DIGESTS,
    R3_DIGEST,
    authorization_document,
    launch_inputs_document,
    ledger_document,
    ledger_row,
    specification_digest_for,
    specification_for,
    target_document,
    task_definition_document,
)
from fixtures.production_runtime import (
    BUILD_ID,
    CANARIES,
    COMMIT,
    CONFIGURATION_DIGEST,
    IMAGE_DIGEST,
    INTERFACE_ID,
    NOW,
    OTHER_RUN_ID,
    OTHER_SECURITY_GROUP,
    PLAN_DIGEST,
    RUN_ID,
    SECURITY_GROUPS,
    SUBNET_ID,
    TASK_ARN,
    TREE,
    compiled_task,
    encode,
    revision_arn,
    slice_document,
    verification_revision_arn,
)
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar.compiled import (
    build_compiled_configuration,
    configuration_digest_of,
)
from kalpamani.data.production.sharadar.entry import TaskEntry, TaskOutcome
from kalpamani.data.production.sharadar.inputs import (
    InputError,
    input_digest,
    parse_acquisition_input,
    parse_build_input,
    parse_slice,
)
from kalpamani.data.production.sharadar.receipts import ReceiptError, collect_and_verify
from kalpamani.data.production.sharadar.vocabulary import ProductionActor, constants_for

pytestmark = pytest.mark.unit

VERIFY_ID: Final = "verify-" + RUN_ID
OTHER_VERIFY_ID: Final = "verify-" + OTHER_RUN_ID


def _ledger(*rows: dict[str, Any]) -> lr.OwnerLedger:
    return lr.parse_owner_ledger(encode(ledger_document(list(rows))))


def _refuses(defect: lr.LaunchRecordDefect) -> Any:
    return pytest.raises(lr.LaunchRecordError, match=defect.value)


# ---------------------------------------------------------------------------
# The ledger and identity rules
# ---------------------------------------------------------------------------


class TestOwnerLedger:
    def test_an_empty_ledger_is_a_ledger(self) -> None:
        ledger = _ledger()
        assert ledger.rows == () and ledger.identities == frozenset()
        assert lr.parse_owner_ledger(encode(ledger.document())) == ledger

    def test_rows_round_trip_and_every_identity_is_consumed(self) -> None:
        ledger = _ledger(
            ledger_row(RUN_ID),
            ledger_row(VERIFY_ID, kind="verification", outcome="VERIFIED"),
            ledger_row(BUILD_ID, actor=BLD, outcome="HALTED", evidence="EXIT_CODE_ONLY"),
        )
        assert ledger.identities == {RUN_ID, VERIFY_ID, BUILD_ID}
        assert lr.parse_owner_ledger(encode(ledger.document())) == ledger
        row = ledger.row(RUN_ID)
        assert row is not None and row.buildable
        verified = ledger.row(VERIFY_ID)
        assert verified is not None and not verified.buildable
        assert ledger.row("never-launched") is None

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d["rows"].append(ledger_row(RUN_ID)),  # duplicate identity
            lambda d: d["rows"].__setitem__(0, ledger_row(RUN_ID, kind="verification")),
            lambda d: d["rows"].__setitem__(0, ledger_row(VERIFY_ID, kind="production")),
            lambda d: d["rows"].__setitem__(0, ledger_row(RUN_ID, outcome="PASSED")),
            lambda d: d["rows"].__setitem__(0, ledger_row(RUN_ID, evidence="HEARSAY")),
            lambda d: d["rows"].__setitem__(0, ledger_row(RUN_ID, actor=BLD, with_slice=True)),
            lambda d: d["rows"].__setitem__(0, ledger_row(RUN_ID, plan_digest=None)),
            lambda d: d["rows"].__setitem__(0, ledger_row("bad identity!")),
            lambda d: d["rows"][0].__setitem__(
                "completed_at", (NOW - timedelta(days=9)).isoformat()
            ),
            lambda d: d["rows"][0].__setitem__("extra", 1),
            lambda d: d.__setitem__("contract_id", "kalpamani-owner-ledger/v2"),
            lambda d: d.__setitem__("rows", {}),
        ],
    )
    def test_a_malformed_ledger_is_refused_whole(self, mutate: Any) -> None:
        document = ledger_document([ledger_row(RUN_ID)])
        mutate(document)
        with pytest.raises(lr.LaunchRecordError):
            lr.parse_owner_ledger(encode(document))

    def test_a_build_row_may_not_carry_a_slice_and_an_acquisition_row_must(self) -> None:
        with pytest.raises(lr.LaunchRecordError):
            _ledger(ledger_row(BUILD_ID, actor=BLD, with_slice=True))
        # A build row is well-formed without one; an acquisition row without one parses
        # but is never buildable.
        ledger = _ledger(ledger_row(RUN_ID, with_slice=False))
        row = ledger.row(RUN_ID)
        assert row is not None and not row.buildable
        with _refuses(lr.LaunchRecordDefect.ROW_NOT_BUILDABLE):
            row.build_input_row()

    def test_a_document_over_the_ceiling_is_refused_before_parsing(self) -> None:
        with _refuses(lr.LaunchRecordDefect.DOCUMENT_MALFORMED):
            lr.parse_owner_ledger(b" " * (lr.MAX_RECORD_BYTES + 1))


class TestIdentityRules:
    def test_the_reserved_prefix_decides_the_kind(self) -> None:
        assert lr.identity_kind(RUN_ID) is lr.LaunchKind.PRODUCTION
        assert lr.identity_kind(VERIFY_ID) is lr.LaunchKind.VERIFICATION

    def test_a_production_identity_cannot_be_launched_for_verification_or_vice_versa(
        self,
    ) -> None:
        ledger = _ledger()
        assert lr.admit_identity(ledger, RUN_ID, kind=lr.LaunchKind.PRODUCTION) == RUN_ID
        assert lr.admit_identity(ledger, VERIFY_ID, kind=lr.LaunchKind.VERIFICATION) == VERIFY_ID
        with _refuses(lr.LaunchRecordDefect.IDENTITY_KIND_MISMATCH):
            lr.admit_identity(ledger, RUN_ID, kind=lr.LaunchKind.VERIFICATION)
        with _refuses(lr.LaunchRecordDefect.IDENTITY_KIND_MISMATCH):
            lr.admit_identity(ledger, VERIFY_ID, kind=lr.LaunchKind.PRODUCTION)

    def test_an_identity_in_the_ledger_is_consumed_for_every_kind(self) -> None:
        ledger = _ledger(
            ledger_row(RUN_ID, outcome="REFUSED", evidence="EXIT_CODE_ONLY"),
            ledger_row(VERIFY_ID, kind="verification", outcome="VERIFIED"),
        )
        with _refuses(lr.LaunchRecordDefect.IDENTITY_CONSUMED):
            lr.admit_identity(ledger, RUN_ID, kind=lr.LaunchKind.PRODUCTION)
        with _refuses(lr.LaunchRecordDefect.IDENTITY_CONSUMED):
            lr.admit_identity(ledger, VERIFY_ID, kind=lr.LaunchKind.VERIFICATION)

    def test_a_malformed_identity_is_refused_before_the_ledger_is_consulted(self) -> None:
        with _refuses(lr.LaunchRecordDefect.IDENTITY_MALFORMED):
            lr.admit_identity(_ledger(), "", kind=lr.LaunchKind.PRODUCTION)


# ---------------------------------------------------------------------------
# Input materialization
# ---------------------------------------------------------------------------


class TestAcquisitionInput:
    def test_the_input_is_the_task_contracts_own_and_carries_every_ledger_identity(
        self,
    ) -> None:
        ledger = _ledger(
            ledger_row(OTHER_RUN_ID),
            ledger_row(VERIFY_ID, kind="verification", outcome="VERIFIED"),
            ledger_row(BUILD_ID, actor=BLD),
        )
        raw = lr.materialize_acquisition_input(
            ledger,
            identity=RUN_ID,
            kind=lr.LaunchKind.PRODUCTION,
            slice_document=slice_document(),
            now=NOW,
        )
        from kalpamani.data.production.sharadar.documents import decode_document

        document = decode_document(raw, max_bytes=8 * 1024)
        assert document["spent_identities"]["spent"] == sorted([OTHER_RUN_ID, VERIFY_ID, BUILD_ID])
        assert document["plan_digest"] == PLAN_DIGEST
        admitted = parse_acquisition_input(document, now=NOW)
        assert admitted.run_identity == RUN_ID
        # The task's own contract is what refuses the spent identities it carries.
        for spent in (OTHER_RUN_ID, VERIFY_ID):
            with pytest.raises(InputError):
                parse_acquisition_input({**document, "run_identity": spent}, now=NOW)

    def test_a_verification_input_is_the_same_document_under_a_verification_identity(
        self,
    ) -> None:
        raw = lr.materialize_acquisition_input(
            _ledger(ledger_row(RUN_ID)),
            identity=VERIFY_ID,
            kind=lr.LaunchKind.VERIFICATION,
            slice_document=slice_document(),
            now=NOW,
        )
        from kalpamani.data.production.sharadar.documents import decode_document

        document = decode_document(raw, max_bytes=8 * 1024)
        assert document["run_identity"] == VERIFY_ID
        assert document["spent_identities"]["spent"] == [RUN_ID]
        assert parse_acquisition_input(document, now=NOW).run_identity == VERIFY_ID

    def test_a_consumed_identity_a_malformed_slice_and_too_many_spent_are_refused(
        self,
    ) -> None:
        with _refuses(lr.LaunchRecordDefect.IDENTITY_CONSUMED):
            lr.materialize_acquisition_input(
                _ledger(ledger_row(RUN_ID)),
                identity=RUN_ID,
                kind=lr.LaunchKind.PRODUCTION,
                slice_document=slice_document(),
                now=NOW,
            )
        with _refuses(lr.LaunchRecordDefect.FIELD_MALFORMED):
            lr.materialize_acquisition_input(
                _ledger(),
                identity=RUN_ID,
                kind=lr.LaunchKind.PRODUCTION,
                slice_document={"datasets": ["stocks"]},
                now=NOW,
            )
        crowded = _ledger(*(ledger_row(f"synthetic-run-{i:04d}") for i in range(129)))
        with _refuses(lr.LaunchRecordDefect.TOO_MANY):
            lr.materialize_acquisition_input(
                crowded,
                identity=RUN_ID,
                kind=lr.LaunchKind.PRODUCTION,
                slice_document=slice_document(),
                now=NOW,
            )


class TestBuildInput:
    def test_only_receipt_verified_completed_production_acquisition_rows_are_buildable(
        self,
    ) -> None:
        ledger = _ledger(
            ledger_row(RUN_ID),
            ledger_row(OTHER_RUN_ID, evidence="EXIT_CODE_ONLY"),
            ledger_row(VERIFY_ID, kind="verification", outcome="VERIFIED"),
            ledger_row("synthetic-run-halted", outcome="HALTED"),
        )
        raw = lr.materialize_build_input(
            ledger,
            identity=BUILD_ID,
            kind=lr.LaunchKind.PRODUCTION,
            run_identities=[RUN_ID],
            now=NOW,
        )
        from kalpamani.data.production.sharadar.documents import decode_document

        document = decode_document(raw, max_bytes=8 * 1024)
        admitted = parse_build_input(document, now=NOW)
        assert admitted.build_identity == BUILD_ID and [r.run_identity for r in admitted.runs] == [
            RUN_ID
        ]
        for unbuildable in (OTHER_RUN_ID, VERIFY_ID, "synthetic-run-halted", "never-launched"):
            with _refuses(lr.LaunchRecordDefect.ROW_NOT_BUILDABLE):
                lr.materialize_build_input(
                    ledger,
                    identity=BUILD_ID,
                    kind=lr.LaunchKind.PRODUCTION,
                    run_identities=[unbuildable],
                    now=NOW,
                )

    def test_duplicates_empties_and_the_ceiling_are_refused(self) -> None:
        ledger = _ledger(ledger_row(RUN_ID))
        with _refuses(lr.LaunchRecordDefect.IDENTITY_DUPLICATE):
            lr.materialize_build_input(
                ledger,
                identity=BUILD_ID,
                kind=lr.LaunchKind.PRODUCTION,
                run_identities=[RUN_ID, RUN_ID],
                now=NOW,
            )
        with _refuses(lr.LaunchRecordDefect.FIELD_MALFORMED):
            lr.materialize_build_input(
                ledger, identity=BUILD_ID, kind=lr.LaunchKind.PRODUCTION, run_identities=[], now=NOW
            )
        with _refuses(lr.LaunchRecordDefect.TOO_MANY):
            lr.materialize_build_input(
                ledger,
                identity=BUILD_ID,
                kind=lr.LaunchKind.PRODUCTION,
                run_identities=[f"synthetic-run-{i:04d}" for i in range(33)],
                now=NOW,
            )

    def test_a_verification_build_needs_a_verification_identity(self) -> None:
        ledger = _ledger(ledger_row(RUN_ID))
        with _refuses(lr.LaunchRecordDefect.IDENTITY_KIND_MISMATCH):
            lr.materialize_build_input(
                ledger,
                identity=BUILD_ID,
                kind=lr.LaunchKind.VERIFICATION,
                run_identities=[RUN_ID],
                now=NOW,
            )
        raw = lr.materialize_build_input(
            ledger,
            identity="verify-" + BUILD_ID,
            kind=lr.LaunchKind.VERIFICATION,
            run_identities=[RUN_ID],
            now=NOW,
        )
        assert b"verify-" in raw


# ---------------------------------------------------------------------------
# Launch inputs -> CompiledLaunch
# ---------------------------------------------------------------------------


class TestLaunchInputs:
    def test_both_kinds_compile_for_both_actors(self) -> None:
        inputs = lr.parse_launch_inputs(encode(launch_inputs_document()))
        for actor in ProductionActor:
            compiled, target = lr.compile_launch(inputs, actor=actor, kind=lr.LaunchKind.PRODUCTION)
            assert compiled.actor is actor and not compiled.verification
            assert compiled.task_definition_arn == revision_arn(actor)
            assert compiled.assign_public_ip is (actor is ACQ)
            verify, _ = lr.compile_launch(inputs, actor=actor, kind=lr.LaunchKind.VERIFICATION)
            assert verify.verification and verify.task_definition_arn == verification_revision_arn(
                actor
            )
            # Same placement, same roles, same key: only the revision differs.
            assert (
                dataclasses.replace(verify, task_definition_arn=compiled.task_definition_arn)
                == compiled
            )
            assert target.code_commit == COMMIT
        assert "LaunchInputs()" == repr(inputs)

    def test_task_definition_evidence_is_bound_to_its_target(self) -> None:
        mutate: Any
        for mutate in (
            lambda td: td.__setitem__("revision", 99),
            lambda td: td.__setitem__("family", "kalpamani-research-build"),
            lambda td: td.__setitem__("image_digest", "sha256:" + "00" * 32),
            lambda td: td.__setitem__("command", "kalpamani-research-build"),
            lambda td: td.__setitem__(
                "task_role_arn", task_definition_document(BLD)["task_role_arn"]
            ),
        ):
            document = launch_inputs_document()
            mutate(document["actors"]["acquisition"]["production"]["task_definition"])
            with _refuses(lr.LaunchRecordDefect.ACTOR_MISMATCH):
                lr.parse_launch_inputs(encode(document))
        for mutate in (
            lambda td: td.__setitem__("user", "root"),
            lambda td: td.__setitem__("network_mode", "bridge"),
            lambda td: td.__setitem__("readonly_root_filesystem", "true"),
            lambda td: td.pop("work_tmpfs"),
            lambda td: td.__setitem__("cpu", 0),
        ):
            document = launch_inputs_document()
            mutate(document["actors"]["acquisition"]["production"]["task_definition"])
            with _refuses(lr.LaunchRecordDefect.FIELD_MALFORMED):
                lr.parse_launch_inputs(encode(document))
        document = launch_inputs_document()
        document["actors"]["acquisition"]["production"].pop("task_definition")
        with _refuses(lr.LaunchRecordDefect.FIELD_MALFORMED):
            lr.parse_launch_inputs(encode(document))
        document = launch_inputs_document()
        document["actors"]["acquisition"]["production"]["generation_record_digest"] = "x"
        with _refuses(lr.LaunchRecordDefect.FIELD_MALFORMED):
            lr.parse_launch_inputs(encode(document))
        inputs = lr.parse_launch_inputs(encode(launch_inputs_document()))
        target = inputs.targets[(ACQ, lr.LaunchKind.PRODUCTION)]
        assert target.family == "kalpamani-production-acquire" and target.revision == 7
        assert target.generation_record_digest == GENERATION_RECORD_DIGESTS[(ACQ, False)]
        assert inputs.r3_verification_digest == R3_DIGEST
        assert (
            lr.parse_launch_inputs(
                encode(launch_inputs_document(r3_verification_digest=None))
            ).r3_verification_digest
            is None
        )

    def test_a_missing_verification_target_refuses_only_the_verification_launch(self) -> None:
        inputs = lr.parse_launch_inputs(encode(launch_inputs_document(verification=False)))
        lr.compile_launch(inputs, actor=ACQ, kind=lr.LaunchKind.PRODUCTION)
        with _refuses(lr.LaunchRecordDefect.FIELD_MISSING):
            lr.compile_launch(inputs, actor=ACQ, kind=lr.LaunchKind.VERIFICATION)

    def test_a_target_of_the_wrong_family_is_refused(self) -> None:
        document = launch_inputs_document()
        document["actors"]["acquisition"]["production"] = target_document(BLD)
        with _refuses(lr.LaunchRecordDefect.ACTOR_MISMATCH):
            lr.parse_launch_inputs(encode(document))
        document = launch_inputs_document()
        document["actors"]["acquisition"]["verification"] = target_document(ACQ)
        with _refuses(lr.LaunchRecordDefect.ACTOR_MISMATCH):
            lr.parse_launch_inputs(encode(document))

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.__setitem__("platform_version", "LATEST"),
            lambda d: d.__setitem__("cluster_arn", "arn:aws:ecs:us-east-1:0:cluster/x"),
            lambda d: d.__setitem__("binding_key_arn", "alias/synthetic"),
            lambda d: d["actors"].pop("build"),
            lambda d: d["actors"]["build"].__setitem__("security_group_ids", []),
            lambda d: d["actors"]["build"].__setitem__("subnet_id", "subnet-x"),
            lambda d: d["actors"]["build"]["production"].__setitem__("image_digest", "ef" * 32),
            lambda d: d["actors"]["build"]["production"].__setitem__("code_commit", "abc"),
            lambda d: d["actors"]["build"].__setitem__("extra", 1),
        ],
    )
    def test_malformed_launch_inputs_are_refused(self, mutate: Any) -> None:
        document = launch_inputs_document()
        mutate(document)
        with pytest.raises(lr.LaunchRecordError):
            lr.parse_launch_inputs(encode(document))


# ---------------------------------------------------------------------------
# Configuration equivalence
# ---------------------------------------------------------------------------


def _compiled(entry: TaskEntry, **overrides: Any) -> bytes:
    fields_: dict[str, Any] = {
        "entry": entry,
        "code_commit": COMMIT,
        "code_tree": TREE,
        "generated_at": NOW,
    }
    if entry is TaskEntry.ACQUISITION:
        fields_["secret_name"] = "synthetic/production/sharadar"  # noqa: S105 - a name
        fields_["origin_addresses"] = sorted(ORIGIN_ADDRESSES)
    elif entry is TaskEntry.BUILD:
        fields_["build_configuration"] = configuration()
    else:
        fields_["origin_addresses"] = sorted(ORIGIN_ADDRESSES)
    fields_.update(overrides)
    return build_compiled_configuration(**fields_)


def _inputs_registering(**files: bytes) -> lr.LaunchInputs:
    """Launch inputs whose targets register the digests of the supplied files."""
    document = launch_inputs_document()
    for key, raw in files.items():
        actor, field = key.split("_", 1)
        document["actors"][actor][field]["configuration_digest"] = configuration_digest_of(raw)
    return lr.parse_launch_inputs(encode(document))


ACQ_PROD: Final = _compiled(TaskEntry.ACQUISITION)
ACQ_VERIFY: Final = _compiled(TaskEntry.ACQUISITION_VERIFY)
BLD_PROD: Final = _compiled(TaskEntry.BUILD)
BLD_VERIFY: Final = _compiled(TaskEntry.BUILD_VERIFY)


def _registered() -> lr.LaunchInputs:
    return _inputs_registering(
        acquisition_production=ACQ_PROD,
        acquisition_verification=ACQ_VERIFY,
        build_production=BLD_PROD,
        build_verification=BLD_VERIFY,
    )


class TestEquivalence:
    def test_the_registered_acquisition_pair_is_equivalent(self) -> None:
        verdict = lr.configuration_equivalence(
            _registered(), actor=ACQ, production=ACQ_PROD, verification=ACQ_VERIFY
        )
        assert verdict is lr.EquivalenceVerdict.EQUIVALENT

    def test_the_build_pair_needs_the_registered_acquisition_file(self) -> None:
        inputs = _registered()
        assert (
            lr.configuration_equivalence(
                inputs, actor=BLD, production=BLD_PROD, verification=BLD_VERIFY
            )
            is lr.EquivalenceVerdict.EVIDENCE_MISSING
        )
        assert (
            lr.configuration_equivalence(
                inputs,
                actor=BLD,
                production=BLD_PROD,
                verification=BLD_VERIFY,
                acquisition=ACQ_PROD,
            )
            is lr.EquivalenceVerdict.EQUIVALENT
        )
        # An acquisition file that is valid but not the registered acquisition target.
        unrelated = _compiled(TaskEntry.ACQUISITION, origin_addresses=["198.51.100.1"])
        assert (
            lr.configuration_equivalence(
                inputs,
                actor=BLD,
                production=BLD_PROD,
                verification=BLD_VERIFY,
                acquisition=unrelated,
            )
            is lr.EquivalenceVerdict.TARGET_MISMATCH
        )
        # The "acquisition" file must be the acquisition entry's.
        assert (
            lr.configuration_equivalence(
                inputs,
                actor=BLD,
                production=BLD_PROD,
                verification=BLD_VERIFY,
                acquisition=BLD_PROD,
            )
            is lr.EquivalenceVerdict.ENTRY_MISMATCH
        )

    def test_an_unrelated_but_valid_production_file_is_refused_against_its_target(self) -> None:
        """PR #104 review finding 3: the production file was never bound to its target."""
        inputs = _registered()
        unrelated_set = ["198.51.100.20", "198.51.100.21"]
        unrelated_production = _compiled(TaskEntry.ACQUISITION, origin_addresses=unrelated_set)
        matching_verification = _compiled(
            TaskEntry.ACQUISITION_VERIFY, origin_addresses=unrelated_set
        )
        # Registering only the verification side (the substitution the review described).
        inputs_with_verify = _inputs_registering(
            acquisition_production=ACQ_PROD,
            acquisition_verification=matching_verification,
            build_production=BLD_PROD,
            build_verification=BLD_VERIFY,
        )
        assert (
            lr.configuration_equivalence(
                inputs_with_verify,
                actor=ACQ,
                production=unrelated_production,
                verification=matching_verification,
            )
            is lr.EquivalenceVerdict.TARGET_MISMATCH
        )
        # And a verification file the record did not register.
        assert (
            lr.configuration_equivalence(
                inputs, actor=ACQ, production=ACQ_PROD, verification=matching_verification
            )
            is lr.EquivalenceVerdict.TARGET_MISMATCH
        )

    def test_a_changed_task_revision_or_deployment_declaration_refuses(self) -> None:
        document = launch_inputs_document()
        document["actors"]["acquisition"]["production"]["configuration_digest"] = (
            configuration_digest_of(ACQ_PROD)
        )
        document["actors"]["acquisition"]["verification"]["configuration_digest"] = (
            configuration_digest_of(ACQ_VERIFY)
        )
        # A different registered revision for the verification family: the ARN and the
        # evidence move together, and the file still binds -- the pair still compares.
        moved = json.loads(json.dumps(document))
        moved["actors"]["acquisition"]["verification"]["task_definition_arn"] = (
            verification_revision_arn(ACQ, 8)
        )
        moved["actors"]["acquisition"]["verification"]["task_definition"]["revision"] = 8
        assert (
            lr.configuration_equivalence(
                lr.parse_launch_inputs(encode(moved)),
                actor=ACQ,
                production=ACQ_PROD,
                verification=ACQ_VERIFY,
            )
            is lr.EquivalenceVerdict.EQUIVALENT
        )
        # A deployment declaration that differs on a shared field refuses.
        for field, value in (
            ("cpu", 2048),
            ("memory", 4096),
            ("readonly_root_filesystem", False),
            ("work_tmpfs", False),
        ):
            changed = json.loads(json.dumps(document))
            changed["actors"]["acquisition"]["verification"]["task_definition"][field] = value
            assert (
                lr.configuration_equivalence(
                    lr.parse_launch_inputs(encode(changed)),
                    actor=ACQ,
                    production=ACQ_PROD,
                    verification=ACQ_VERIFY,
                )
                is lr.EquivalenceVerdict.TASK_DEFINITION_DIFFERS
            ), field
        # A missing verification target is missing evidence, not equivalence.
        assert (
            lr.configuration_equivalence(
                lr.parse_launch_inputs(encode(launch_inputs_document(verification=False))),
                actor=ACQ,
                production=ACQ_PROD,
                verification=ACQ_VERIFY,
            )
            is lr.EquivalenceVerdict.EVIDENCE_MISSING
        )

    def test_every_other_verdict(self) -> None:
        inputs = _registered()
        other_commit = _compiled(TaskEntry.ACQUISITION_VERIFY, code_commit="ab" * 20)
        assert (
            lr.configuration_equivalence(
                _inputs_registering(
                    acquisition_production=ACQ_PROD,
                    acquisition_verification=other_commit,
                    build_production=BLD_PROD,
                    build_verification=BLD_VERIFY,
                ),
                actor=ACQ,
                production=ACQ_PROD,
                verification=other_commit,
            )
            is lr.EquivalenceVerdict.TARGET_MISMATCH
        )  # the registered target names COMMIT; the file names another
        narrower = _compiled(TaskEntry.ACQUISITION_VERIFY, origin_addresses=["192.0.2.10"])
        assert (
            lr.configuration_equivalence(
                _inputs_registering(
                    acquisition_production=ACQ_PROD,
                    acquisition_verification=narrower,
                    build_production=BLD_PROD,
                    build_verification=BLD_VERIFY,
                ),
                actor=ACQ,
                production=ACQ_PROD,
                verification=narrower,
            )
            is lr.EquivalenceVerdict.ORIGIN_DIFFERS
        )
        assert (
            lr.configuration_equivalence(
                inputs, actor=ACQ, production=ACQ_PROD, verification=BLD_VERIFY
            )
            is lr.EquivalenceVerdict.ENTRY_MISMATCH
        )
        assert (
            lr.configuration_equivalence(
                inputs, actor=ACQ, production=ACQ_VERIFY, verification=ACQ_VERIFY
            )
            is lr.EquivalenceVerdict.ENTRY_MISMATCH
        )
        assert (
            lr.configuration_equivalence(
                inputs, actor=ACQ, production=b"{", verification=ACQ_VERIFY
            )
            is lr.EquivalenceVerdict.UNREADABLE
        )
        assert set(lr.TASK_DEFINITION_SHARED_FIELDS) | set(
            lr.TASK_DEFINITION_INTENTIONAL_DIFFERENCES
        ) == set(task_definition_document(ACQ))


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


SPEC_DIGEST: Final = specification_digest_for(actor=ACQ, kind="production", identity=RUN_ID)


class TestAuthorization:
    def _parse(self, document: dict[str, Any], **overrides: Any) -> lr.LaunchAuthorizationRecord:
        fields_: dict[str, Any] = {
            "actor": ACQ,
            "kind": lr.LaunchKind.PRODUCTION,
            "identity": RUN_ID,
            "specification_digest": SPEC_DIGEST,
            "now": NOW,
        }
        fields_.update(overrides)
        return lr.parse_authorization(encode(document), **fields_)

    def test_a_matching_valid_authorization_is_admitted(self) -> None:
        record = self._parse(authorization_document(actor=ACQ, kind="production", identity=RUN_ID))
        assert record.identity == RUN_ID and record.kind is lr.LaunchKind.PRODUCTION
        assert record.specification_digest == SPEC_DIGEST and record.valid_at(NOW)

    def test_the_authorization_is_for_one_actor_one_kind_one_identity_one_specification(
        self,
    ) -> None:
        document = authorization_document(actor=ACQ, kind="production", identity=RUN_ID)
        with _refuses(lr.LaunchRecordDefect.AUTHORIZATION_MISMATCH):
            self._parse(document, actor=BLD)
        with _refuses(lr.LaunchRecordDefect.AUTHORIZATION_MISMATCH):
            self._parse(document, kind=lr.LaunchKind.VERIFICATION)
        with _refuses(lr.LaunchRecordDefect.AUTHORIZATION_MISMATCH):
            self._parse(document, identity=OTHER_RUN_ID)
        with _refuses(lr.LaunchRecordDefect.AUTHORIZATION_MISMATCH):
            self._parse(document, specification_digest="cd" * 32)
        with _refuses(lr.LaunchRecordDefect.FIELD_MISSING):
            legacy = {k: v for k, v in document.items() if k != "specification_digest"}
            self._parse(legacy)

    def test_an_expired_a_future_and_an_over_long_authorization_are_refused(self) -> None:
        document = authorization_document(actor=ACQ, kind="production", identity=RUN_ID)
        with _refuses(lr.LaunchRecordDefect.AUTHORIZATION_EXPIRED):
            self._parse(document, now=NOW + timedelta(hours=4))
        with _refuses(lr.LaunchRecordDefect.AUTHORIZATION_EXPIRED):
            self._parse(document, now=NOW - timedelta(hours=2))
        with _refuses(lr.LaunchRecordDefect.FIELD_MALFORMED):
            self._parse(
                authorization_document(
                    actor=ACQ,
                    kind="production",
                    identity=RUN_ID,
                    expires_at=(NOW + timedelta(hours=30)).isoformat(),
                )
            )


class TestSpecification:
    """PR #104 review finding 2: the authorization binds the whole launch, not four fields."""

    def _digest(self, **overrides: Any) -> str:
        return specification_digest_for(actor=ACQ, kind="production", identity=RUN_ID, **overrides)

    def test_each_bound_category_changes_the_digest(self) -> None:
        base = self._digest()
        # A changed slice (the workload).
        assert (
            self._digest(
                slice_doc=slice_document(
                    windows={"actions": "2024-01-01/2024-12-31", "tickers": "SNAPSHOT"}
                )
            )
            != base
        )
        # A changed registered target (image, configuration, commit, revision).
        for field, value in (
            ("image_digest", "sha256:" + "00" * 32),
            ("configuration_digest", "c9" * 32),
            ("generation_record_digest", "9a" * 32),
        ):
            document = launch_inputs_document()
            document["actors"]["acquisition"]["production"][field] = value
            if field == "image_digest":
                document["actors"]["acquisition"]["production"]["task_definition"][
                    "image_digest"
                ] = value
            assert self._digest(inputs=document) != base, field
        document = launch_inputs_document()
        document["actors"]["acquisition"]["production"]["task_definition_arn"] = revision_arn(
            ACQ, 8
        )
        document["actors"]["acquisition"]["production"]["task_definition"]["revision"] = 8
        assert self._digest(inputs=document) != base
        # A changed placement.
        document = launch_inputs_document()
        document["actors"]["acquisition"]["subnet_id"] = "subnet-0fedcba9876543210"
        assert self._digest(inputs=document) != base
        document = launch_inputs_document()
        document["platform_version"] = "1.3.0"
        assert self._digest(inputs=document) != base
        # A changed gate-evidence reference.
        assert self._digest(inputs=launch_inputs_document(r3_verification_digest="b3" * 32)) != base
        # A different identity or kind.
        assert specification_digest_for(actor=ACQ, kind="production", identity=OTHER_RUN_ID) != base

    def test_ledger_growth_and_input_instants_do_not_change_the_digest(self) -> None:
        base = self._digest()
        grown = ledger_document(
            [
                ledger_row(OTHER_RUN_ID),
                ledger_row(VERIFY_ID, kind="verification", outcome="VERIFIED"),
            ]
        )
        assert self._digest(ledger=grown) == base
        # The materialized input carries issued_at/expires_at and the spent set; the
        # specification carries neither, so two inputs cut at different instants from
        # different ledgers are one authorized launch.
        ledger = lr.parse_owner_ledger(encode(grown))
        first = lr.materialize_acquisition_input(
            ledger,
            identity=RUN_ID,
            kind=lr.LaunchKind.PRODUCTION,
            slice_document=slice_document(),
            now=NOW,
        )
        second = lr.materialize_acquisition_input(
            ledger,
            identity=RUN_ID,
            kind=lr.LaunchKind.PRODUCTION,
            slice_document=slice_document(),
            now=NOW + timedelta(hours=1),
        )
        assert first != second

    def test_a_specification_parses_back_to_itself_and_names_its_compiled_launch(self) -> None:
        """Second cycle, finding 2: the reservation carries the specification, parsed closed."""
        for actor, kind, identity in (
            (ACQ, "production", RUN_ID),
            (ACQ, "verification", "verify-" + RUN_ID),
            (BLD, "production", BUILD_ID),
            (BLD, "verification", "verify-" + BUILD_ID),
        ):
            specification = specification_for(actor=actor, kind=kind, identity=identity)
            parsed = lr.parse_specification(encode(specification.document()))
            assert parsed == specification and parsed.digest == specification.digest
            assert lr.parse_specification(specification.document()) == specification
            inputs = lr.parse_launch_inputs(encode(launch_inputs_document()))
            compiled, target = lr.compile_launch(inputs, actor=actor, kind=lr.LaunchKind(kind))
            assert parsed.compiled == compiled and parsed.target == target
            assert tuple(parsed.placement["security_group_ids"]) == SECURITY_GROUPS
        for canary in CANARIES:
            assert canary not in repr(specification)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.__setitem__("contract_id", "kalpamani-launch-specification/v2"),
            lambda d: d.__setitem__("extra", 1),
            lambda d: d.pop("placement"),
            lambda d: d.__setitem__("kind", "verification"),  # against a production identity
            lambda d: d.__setitem__("entry", "kalpamani-research-build"),
            lambda d: d.__setitem__("identity", "verify-" + RUN_ID),
            lambda d: d.__setitem__("workload", {"runs": []}),
            lambda d: d["workload"].__setitem__("plan_digest", "00" * 32),
            lambda d: d["workload"]["slice"].__setitem__("request_count", 5),
            lambda d: d["placement"].__setitem__("security_group_ids", []),
            lambda d: d["placement"].__setitem__("security_group_ids", [SECURITY_GROUPS[0]] * 2),
            lambda d: d["placement"].__setitem__("security_group_ids", ["sg-x"]),
            lambda d: d["placement"].__setitem__("subnet_id", "subnet-x"),
            lambda d: d["placement"].__setitem__("assign_public_ip", False),
            lambda d: d["placement"].__setitem__("platform_version", "LATEST"),
            lambda d: d["placement"].pop("binding_key_arn"),
            lambda d: d["placement"].__setitem__(
                "task_role_arn", d["placement"]["execution_role_arn"]
            ),
            lambda d: d["target"].__setitem__("image_digest", "sha256:" + "00" * 32),
            lambda d: d["gate_evidence"].__setitem__("r3_applicable", False),
            lambda d: d["gate_evidence"].__setitem__("r3_verification_digest", None),
            lambda d: d["gate_evidence"].__setitem__("generation_record_digest", "9a" * 32),
        ],
    )
    def test_a_specification_document_that_contradicts_itself_is_refused(self, mutate: Any) -> None:
        document = specification_for(actor=ACQ, kind="production", identity=RUN_ID).document()
        mutate(document)
        with pytest.raises(lr.LaunchRecordError):
            lr.parse_specification(encode(document))

    def test_a_build_specification_document_is_held_to_its_runs(self) -> None:
        document = specification_for(actor=BLD, kind="production", identity=BUILD_ID).document()
        runs = document["workload"]["runs"]
        assert len(runs) == 1
        document["workload"]["runs"] = [runs[0], dict(runs[0])]
        with _refuses(lr.LaunchRecordDefect.IDENTITY_DUPLICATE):
            lr.parse_specification(encode(document))
        document["workload"]["runs"] = [{**runs[0], "outcome": "PASSED"}]
        with _refuses(lr.LaunchRecordDefect.FIELD_MALFORMED):
            lr.parse_specification(encode(document))
        document["workload"] = {"slice": slice_document(), "plan_digest": PLAN_DIGEST}
        with _refuses(lr.LaunchRecordDefect.FIELD_MALFORMED):
            lr.parse_specification(encode(document))
        # A verification specification carries no R-3 reference; a production one must.
        verify = specification_for(
            actor=BLD, kind="verification", identity="verify-" + BUILD_ID
        ).document()
        verify["gate_evidence"]["r3_verification_digest"] = R3_DIGEST
        with _refuses(lr.LaunchRecordDefect.FIELD_MALFORMED):
            lr.parse_specification(encode(verify))
        # A placement naming a group outside the compiled set is a different specification.
        widened = specification_for(actor=BLD, kind="production", identity=BUILD_ID).document()
        widened["placement"]["security_group_ids"].append(OTHER_SECURITY_GROUP)
        parsed = lr.parse_specification(encode(widened))
        assert OTHER_SECURITY_GROUP in parsed.compiled.security_group_ids
        assert (
            parsed.digest
            != specification_for(actor=BLD, kind="production", identity=BUILD_ID).digest
        )

    def test_a_build_specification_carries_the_selected_run_evidence(self) -> None:
        base = specification_digest_for(actor=BLD, kind="production", identity=BUILD_ID)
        # The same run identity with different ledger evidence is a different workload.
        changed = ledger_document([ledger_row(RUN_ID, plan_digest="9e" * 32)])
        assert (
            specification_digest_for(
                actor=BLD, kind="production", identity=BUILD_ID, ledger=changed
            )
            != base
        )
        # An unbuildable run refuses the specification.
        with _refuses(lr.LaunchRecordDefect.ROW_NOT_BUILDABLE):
            specification_digest_for(
                actor=BLD,
                kind="production",
                identity=BUILD_ID,
                ledger=ledger_document([ledger_row(RUN_ID, evidence="EXIT_CODE_ONLY")]),
            )

    def test_the_r3_reference_applies_to_production_and_not_to_verification(self) -> None:
        with _refuses(lr.LaunchRecordDefect.FIELD_MISSING):
            self._digest(inputs=launch_inputs_document(r3_verification_digest=None))
        verification = specification_digest_for(
            actor=ACQ,
            kind="verification",
            identity=VERIFY_ID,
            inputs=launch_inputs_document(r3_verification_digest=None),
        )
        assert len(verification) == 64
        ledger = lr.parse_owner_ledger(encode(ledger_document()))
        inputs = lr.parse_launch_inputs(encode(launch_inputs_document()))
        specification = lr.build_specification(
            ledger=ledger,
            inputs=inputs,
            actor=ACQ,
            kind=lr.LaunchKind.VERIFICATION,
            identity=VERIFY_ID,
            slice_document=slice_document(),
            run_identities=None,
        )
        assert specification.gate_evidence == {
            "r3_verification_digest": None,
            "r3_applicable": False,
            "generation_record_digest": GENERATION_RECORD_DIGESTS[(ACQ, True)],
        }
        assert specification.entry is TaskEntry.ACQUISITION_VERIFY
        document = specification.document()
        assert document["contract_id"] == lr.SPECIFICATION_CONTRACT_ID
        assert "issued_at" not in json.dumps(document) and "spent" not in json.dumps(document)
        for canary in CANARIES:
            assert canary not in repr(specification)


# ---------------------------------------------------------------------------
# Provisional rows, the launch record, and completion
# ---------------------------------------------------------------------------


class TestProvisionalOutcome:
    P: Final = lr.LaunchKind.PRODUCTION
    V: Final = lr.LaunchKind.VERIFICATION

    @pytest.mark.parametrize(
        ("kind", "started", "misplaced", "codes", "expected"),
        [
            (P, True, True, (0,), "MISPLACED"),
            (P, False, False, (), "REFUSED"),
            (P, True, False, (0,), "COMPLETED"),
            (V, True, False, (0,), "HALTED"),  # a verification image never completes a run
            (V, True, False, (18,), "VERIFIED"),
            (P, True, False, (18,), "HALTED"),  # a production image never verifies
            (P, True, False, (14,), "REFUSED"),  # REFUSED_IDENTITY
            (V, True, False, (15,), "REFUSED"),  # REFUSED_NO_RELEASE
            (P, True, False, (2,), "REFUSED"),  # REFUSED_ENTRY, pre-bootstrap
            (P, True, False, (22,), "HALTED"),  # ACQUISITION_HALTED
            (P, True, False, (24,), "HALTED"),  # LOCATOR_STATE_UNKNOWN: ambiguous, not a claim
            (P, True, False, (31,), "REFUSED"),  # REFUSED_NORMALIZATION
            (P, True, False, (None,), "HALTED"),
            (P, True, False, (), "HALTED"),  # observation timed out: no terminal state seen
            (P, True, False, (0, 0), "HALTED"),  # two containers: not the one-container shape
            (P, True, False, (137,), "HALTED"),  # a code the table does not know
        ],
    )
    def test_the_exit_code_supports_exactly_this_much(
        self,
        kind: lr.LaunchKind,
        started: bool,
        misplaced: bool,
        codes: tuple[int | None, ...],
        expected: str,
    ) -> None:
        assert (
            lr.provisional_ledger_outcome(
                kind=kind, task_started=started, misplaced=misplaced, exit_codes=codes
            )
            == expected
        )

    def test_every_refusal_exit_code_maps_to_refused_and_the_table_is_exhaustive(self) -> None:
        from kalpamani.data.production.sharadar.entry import EXIT_STATUS
        from kalpamani.data.production.sharadar.receipts import (
            BOOTSTRAP_REFUSALS,
            PRE_BOOTSTRAP_OUTCOMES,
        )

        for outcome, code in EXIT_STATUS.items():
            row = lr.provisional_ledger_outcome(
                kind=self.P, task_started=True, misplaced=False, exit_codes=(code,)
            )
            if outcome in BOOTSTRAP_REFUSALS or outcome in PRE_BOOTSTRAP_OUTCOMES:
                assert row == "REFUSED", outcome
            assert row in {"COMPLETED", "VERIFIED", "REFUSED", "HALTED"}


def _record(**overrides: Any) -> lr.LaunchRecord:
    fields_: dict[str, Any] = {
        "entry": TaskEntry.ACQUISITION,
        "kind": lr.LaunchKind.PRODUCTION,
        "identity": RUN_ID,
        "task_arn": TASK_ARN,
        "task_definition_arn": revision_arn(ACQ),
        "image_digest": IMAGE_DIGEST,
        "configuration_digest": CONFIGURATION_DIGEST,
        "code_commit": COMMIT,
        "input_digest": "ab" * 32,
        "slice": parse_slice(slice_document()),
        "plan_digest": PLAN_DIGEST,
        "launched_at": NOW,
        "recorded_at": NOW + timedelta(seconds=15),
        "network_interface_id": INTERFACE_ID,
        "subnet_id": SUBNET_ID,
        "security_group_ids": SECURITY_GROUPS,
        "specification_digest": "ab" * 32,
    }
    fields_.update(overrides)
    return lr.LaunchRecord(**fields_)


class TestLaunchRecord:
    def test_round_trip_and_the_expectation_it_establishes(self) -> None:
        record = _record()
        parsed = lr.parse_launch_record(encode(record.document()))
        assert parsed == record and parsed.task_id == TASK_ARN.rsplit("/", 1)[1]
        expectation = parsed.expectation()
        assert expectation.identity == RUN_ID and expectation.entry is TaskEntry.ACQUISITION
        for canary in CANARIES:
            assert canary not in repr(record)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.__setitem__("kind", "verification"),
            lambda d: d.__setitem__("identity", VERIFY_ID),
            lambda d: d.__setitem__("actor", "build"),
            lambda d: d.__setitem__("task_definition_arn", verification_revision_arn(ACQ)),
            lambda d: d.__setitem__("task_arn", "arn:aws:ecs:us-east-1:000000000000:task/x"),
            lambda d: d.__setitem__("slice", None),
            lambda d: d.__setitem__("plan_digest", None),
            lambda d: d.__setitem__("input_digest", "xyz"),
            lambda d: d.__setitem__("network_interface_id", None),  # without its subnet
            lambda d: d.__setitem__("security_group_ids", None),  # without its interface
            lambda d: d.__setitem__("security_group_ids", []),
            lambda d: d.__setitem__("security_group_ids", ["sg-x"]),
            lambda d: d.__setitem__("security_group_ids", [SECURITY_GROUPS[0]] * 2),
            lambda d: d.__setitem__("specification_digest", "xyz"),
            lambda d: d.pop("specification_digest"),
            lambda d: d.__setitem__("recorded_at", (NOW - timedelta(days=1)).isoformat()),
        ],
    )
    def test_a_record_that_contradicts_itself_is_refused(self, mutate: Any) -> None:
        document = _record().document()
        mutate(document)
        with pytest.raises(lr.LaunchRecordError):
            lr.parse_launch_record(encode(document))

    def test_the_verified_placement_is_recorded_whole_or_not_at_all(self) -> None:
        absent = _record(network_interface_id=None, subnet_id=None, security_group_ids=None)
        assert lr.parse_launch_record(encode(absent.document())) == absent
        with pytest.raises(ValueError):
            _record(security_group_ids=None)
        with pytest.raises(ValueError):
            _record(security_group_ids=())
        with pytest.raises(ValueError):
            _record(specification_digest="not-a-digest")

    def test_a_build_record_carries_no_slice(self) -> None:
        record = _record(
            entry=TaskEntry.BUILD,
            identity=BUILD_ID,
            task_definition_arn=revision_arn(BLD),
            slice=None,
            plan_digest=None,
        )
        assert lr.parse_launch_record(encode(record.document())) == record
        document = record.document()
        document["slice"] = slice_document()
        with pytest.raises(lr.LaunchRecordError):
            lr.parse_launch_record(encode(document))


class TestCompletion:
    def test_a_provisional_row_is_appended_once(self) -> None:
        row = lr.provisional_ledger_row(_record(), outcome="COMPLETED", completed_at=NOW)
        assert row.evidence is lr.LedgerEvidence.EXIT_CODE_ONLY and not row.buildable
        ledger = lr.append_row(_ledger(), row)
        assert ledger.identities == {RUN_ID}
        with _refuses(lr.LaunchRecordDefect.IDENTITY_CONSUMED):
            lr.append_row(ledger, row)
        with _refuses(lr.LaunchRecordDefect.FIELD_MALFORMED):
            lr.provisional_ledger_row(_record(), outcome="PASSED", completed_at=NOW)

    def _acquisition_receipt(self) -> tuple[Any, lr.LaunchRecord]:
        from kalpamani.data.production.sharadar.identities import LedgerSpentIdentities

        harness = AcquisitionHarness(spent=LedgerSpentIdentities([]))
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.COMPLETED
        record = _record(
            identity=RUN_1,
            input_digest=input_digest(harness.input_bytes),
            code_commit=compiled_task(ACQ).code_commit,
            slice=parse_slice(slice_for_run(1)),
            launched_at=RUN_1_AT,
        )
        return receipt, record

    def test_a_verified_completed_receipt_makes_the_row_buildable(self) -> None:
        receipt, record = self._acquisition_receipt()
        ledger = lr.append_row(
            _ledger(),
            lr.provisional_ledger_row(record, outcome="COMPLETED", completed_at=RUN_1_AT),
        )
        verified = collect_and_verify(receipt.render(), expectation=record.expectation())
        completed = lr.complete_ledger_row(ledger, record=record, receipt=verified)
        row = completed.row(RUN_1)
        assert row is not None and row.evidence is lr.LedgerEvidence.RECEIPT_VERIFIED
        assert row.outcome == "COMPLETED" and row.buildable
        # The completed row builds; the provisional one never did.
        lr.materialize_build_input(
            completed,
            identity=BUILD_ID,
            kind=lr.LaunchKind.PRODUCTION,
            run_identities=[RUN_1],
            now=RUN_1_AT,
        )
        with _refuses(lr.LaunchRecordDefect.ROW_NOT_BUILDABLE):
            lr.materialize_build_input(
                ledger,
                identity=BUILD_ID,
                kind=lr.LaunchKind.PRODUCTION,
                run_identities=[RUN_1],
                now=RUN_1_AT,
            )
        # Never rewritten a second time.
        with _refuses(lr.LaunchRecordDefect.ROW_NOT_BUILDABLE):
            lr.complete_ledger_row(completed, record=record, receipt=verified)

    def test_a_receipt_bound_to_another_launch_never_completes_this_row(self) -> None:
        receipt, record = self._acquisition_receipt()
        other = dataclasses.replace(record, input_digest="cd" * 32)
        with pytest.raises(ReceiptError):
            collect_and_verify(receipt.render(), expectation=other.expectation())

    def test_a_verification_receipt_completes_a_verified_row_and_never_a_completed_one(
        self,
    ) -> None:
        harness = VerificationHarness(entry=TaskEntry.ACQUISITION_VERIFY)
        receipt = harness.run()
        assert receipt.outcome is TaskOutcome.VERIFIED_BOOTSTRAP
        record = _record(
            entry=TaskEntry.ACQUISITION_VERIFY,
            kind=lr.LaunchKind.VERIFICATION,
            identity=harness.identity,
            task_definition_arn=verification_revision_arn(ACQ),
            input_digest=input_digest(harness.input_bytes),
            code_commit=compiled_task(ACQ).code_commit,
            slice=parse_slice(slice_for_run(1)),
            launched_at=RUN_1_AT,
        )
        ledger = lr.append_row(
            _ledger(),
            lr.provisional_ledger_row(record, outcome="VERIFIED", completed_at=RUN_1_AT),
        )
        verified = collect_and_verify(receipt.render(), expectation=record.expectation())
        completed = lr.complete_ledger_row(ledger, record=record, receipt=verified)
        row = completed.row(harness.identity)
        assert row is not None and row.outcome == "VERIFIED" and not row.buildable
        assert row.evidence is lr.LedgerEvidence.RECEIPT_VERIFIED
        # The same receipt can never complete a production row: the kinds disagree.
        production = dataclasses.replace(
            record, kind=lr.LaunchKind.PRODUCTION, entry=TaskEntry.ACQUISITION, identity=RUN_ID
        )
        wrong = lr.append_row(
            _ledger(),
            lr.provisional_ledger_row(production, outcome="HALTED", completed_at=RUN_1_AT),
        )
        with _refuses(lr.LaunchRecordDefect.ACTOR_MISMATCH):
            lr.complete_ledger_row(wrong, record=production, receipt=verified)

    def test_the_evidence_document_names_nothing(self) -> None:
        evidence = lr.evidence_document(
            actor=ACQ,
            kind=lr.LaunchKind.PRODUCTION,
            outcome="TASK_TERMINAL",
            counts={"run_task": 1, "describe_tasks": 3},
            incident=None,
            cleanup_failures=["DELETE_INPUT:ACCESS_DENIED"],
            task_started=True,
            exit_codes=[0],
            recorded_at=NOW,
        )
        text = encode(evidence).decode("utf-8")
        for canary in CANARIES:
            assert canary not in text
        assert RUN_ID not in text and TASK_ARN not in text
        with pytest.raises(TypeError):
            lr.evidence_document(
                actor=ACQ,
                kind=lr.LaunchKind.PRODUCTION,
                outcome="TASK_TERMINAL",
                counts={"run_task": -1},
                incident=None,
                cleanup_failures=[],
                task_started=True,
                exit_codes=[0],
                recorded_at=NOW,
            )

    def test_the_constants_the_vocabulary_holds(self) -> None:
        assert lr.VERIFICATION_IDENTITY_PREFIX == "verify-"
        assert lr.MAX_AUTHORIZATION_VALIDITY == timedelta(hours=24)
        assert constants_for(ACQ).launcher_profile == "kalpamani-production-acquisition-launcher"
        assert constants_for(BLD).launcher_profile == "kalpamani-research-build-launcher"
        assert lr.is_ipv4_set(["192.0.2.10"]) and not lr.is_ipv4_set(["example.invalid"])
        assert not lr.is_ipv4_set([])
