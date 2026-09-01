"""The deterministic private locator: closed schema, exact bindings, fail-closed.

Two kinds of check live here.

**Behavioural.** A real acquisition is driven against synthetic fakes, and the
locator it produces is decoded and cross-checked -- so "every object is bound by exact
key, digest and byte count" is something this file reads back rather than a claim it
repeats.

**Adversarial.** Every field of the schema is corrupted in turn and the refusal is
asserted, because a validator nobody attacked is a validator that has not been tested.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures.sharadar_empirical import (
    EXECUTION_ID,
    LEAK_CANARIES,
    RUN_INSTANT,
    SYNTHETIC_BUCKET,
    SYNTHETIC_SUBJECTS,
    FakeMonotonic,
    FakeS3Client,
    FixedClock,
    PagedTransport,
    credential,
    synthetic_inventory,
)
from kalpamani.data.contracts.canonical import canonical_bytes, sha256_hex
from kalpamani.data.contracts.vocabulary import AcquisitionMode
from kalpamani.data.ingest.bronze import RetrievalMetadata
from kalpamani.data.ingest.publication import bronze_payload_key
from kalpamani.data.ingest.sharadar.datasets import ResponseFormat
from kalpamani.data.objectstore import physical_key
from kalpamani.data.qualify.sharadar.acquisition import (
    AcquisitionStatus,
    run_empirical_acquisition,
)
from kalpamani.data.qualify.sharadar.locator import (
    LOCATOR_ENTRY_FIELDS,
    LOCATOR_FIELDS,
    LOCATOR_SCHEMA_VERSION,
    MAX_LOCATOR_BYTES,
    Completeness,
    LocatorDefect,
    LocatorError,
    ObjectDisposition,
    decode_locator,
    locator_key_segments,
    plan_digest,
    serialize_locator,
    validate_locator_document,
)
from kalpamani.data.qualify.sharadar.plan import build_empirical_plan
from kalpamani.data.qualify.sharadar.publication import (
    qualification_payload_key,
    request_ordinal_map,
)


def _acquire(*, transport: PagedTransport | None = None) -> tuple[FakeS3Client, Any]:
    s3 = FakeS3Client()
    monotonic = FakeMonotonic()
    result = run_empirical_acquisition(
        credential=credential(),
        transport=transport if transport is not None else PagedTransport(),
        monotonic=monotonic,
        sleeper=monotonic.sleep,
        s3_client=s3,
        licensed_bucket=SYNTHETIC_BUCKET,
        clock=FixedClock(),
        inventory=synthetic_inventory(),
        execution_id=EXECUTION_ID,
    )
    return s3, result


def _locator_bytes(s3: FakeS3Client) -> bytes:
    key = "/".join(locator_key_segments(EXECUTION_ID))
    return s3.objects[key]


def _document(s3: FakeS3Client) -> dict[str, Any]:
    decoded: dict[str, Any] = json.loads(_locator_bytes(s3).decode("utf-8"))
    return decoded


def test_the_locator_lives_under_the_licensed_qualification_prefix() -> None:
    assert locator_key_segments(EXECUTION_ID) == (
        "qualification",
        "sharadar",
        "locators",
        f"{EXECUTION_ID}.json",
    )


def test_a_windows_device_name_execution_identity_is_refused_at_key_construction() -> None:
    with pytest.raises(LocatorError) as raised:
        locator_key_segments("con")
    assert raised.value.defect is LocatorDefect.IDENTITY_MISMATCH


def test_exactly_one_locator_is_published_per_execution() -> None:
    s3, _ = _acquire()
    locators = [key for key in s3.objects if key.startswith("qualification/sharadar/locators/")]
    assert len(locators) == 1


def test_the_locator_is_published_last_after_every_acquisition_write() -> None:
    s3, _ = _acquire()
    locator_key = "/".join(locator_key_segments(EXECUTION_ID))
    assert s3.put_calls[-1] == locator_key
    assert locator_key not in s3.put_calls[:-1]


#: ADR-0018 section 7.3, transcribed. **Deliberately a literal**, not
#: :data:`LOCATOR_FIELDS`: comparing the document against the module's own constant
#: proves only that the two agree, which an unauthorized field added to both would
#: satisfy. That is exactly how ``plan_shape_digest`` reached the closed schema.
ACCEPTED_LOCATOR_FIELDS: frozenset[str] = frozenset(
    {
        "schema_version",
        "classification",
        "provider",
        "execution_id",
        "acquisition_mode",
        "profile",
        "plan_digest",
        "inventory_digest",
        "source_schema_version",
        "run_started_at",
        "run_completed_at",
        "completeness",
        "publication_state_unknown",
        "planned_request_count",
        "completed_request_count",
        "entries",
    }
)


def _module_source(module: Any) -> str:
    """A module's own source text, so a check cannot be satisfied by prose here."""
    return Path(module.__file__).read_text(encoding="utf-8")


def test_the_locator_records_the_accepted_closed_field_set() -> None:
    s3, _ = _acquire()
    assert set(_document(s3)) == LOCATOR_FIELDS


def test_the_closed_field_set_is_exactly_the_one_adr_0018_accepted() -> None:
    # Both directions, so neither an addition nor a removal can pass. The schema is
    # closed and durable: widening it is an ADR change, not an implementation
    # detail, and this is the check that says so.
    s3, _ = _acquire()
    assert LOCATOR_FIELDS == ACCEPTED_LOCATOR_FIELDS
    assert set(_document(s3)) == ACCEPTED_LOCATOR_FIELDS
    assert len(ACCEPTED_LOCATOR_FIELDS) == 16


def test_exactly_one_plan_digest_field_exists_and_it_is_named_plan_digest() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    digest_fields = sorted(name for name in document if name.endswith("_digest"))
    assert digest_fields == ["inventory_digest", "plan_digest"]


def test_no_plan_shape_digest_reaches_a_locator_a_model_or_an_export() -> None:
    """The unauthorized field, absent from every surface it had reached.

    It was in the closed field set, the built document, the validated model, the
    parser and the module's exports, and the combined assessor compared it. Adding a
    field to a closed durable schema is a change to the accepted contract, so it is
    checked out of each of those places rather than out of one.
    """
    from dataclasses import fields as dataclass_fields

    from kalpamani.data.qualify.sharadar import assessment, locator, report

    s3, _ = _acquire()
    document = _document(s3)
    assert "plan_shape_digest" not in document
    assert "plan_shape_digest" not in _locator_bytes(s3).decode("utf-8")

    parsed = decode_locator(_locator_bytes(s3), execution_id=EXECUTION_ID)
    assert not hasattr(parsed, "plan_shape_digest")
    assert "plan_shape_digest" not in {field.name for field in dataclass_fields(parsed)}

    assert not hasattr(locator, "plan_shape_digest")
    assert "plan_shape_digest" not in locator.__all__
    assert "plan_shape_digest" not in {
        field.name for field in dataclass_fields(report.ReportEvidence)
    }
    for module in (locator, assessment, report):
        assert "plan_shape_digest" not in _module_source(module)


def test_every_entry_records_the_accepted_closed_field_set() -> None:
    s3, _ = _acquire()
    for entry in _document(s3)["entries"]:
        assert set(entry) == LOCATOR_ENTRY_FIELDS


def test_the_locator_binds_the_plan_and_the_inventory_by_digest() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    plan = build_empirical_plan(
        inventory=synthetic_inventory(), execution_id=EXECUTION_ID, instant=RUN_INSTANT
    )
    assert document["inventory_digest"] == plan.inventory_digest
    assert len(document["plan_digest"]) == 64


def test_two_executions_of_one_plan_share_the_plan_digest() -> None:
    """The pair rule's precondition, and the reason the digest excludes two values.

    ADR-0018 requires Run A and Run B to record **the same plan digest**, and
    requires them to be distinct executions at least eight calendar days apart. So
    the digest cannot bind the execution identity or the ``T-1`` window: a digest
    that did would differ for every legitimate pair, and no pair could ever be
    admitted.
    """
    run_a = build_empirical_plan(
        inventory=synthetic_inventory(), execution_id="synthetic-empirical-a", instant=RUN_INSTANT
    )
    run_b = build_empirical_plan(
        inventory=synthetic_inventory(),
        execution_id="synthetic-empirical-b",
        instant=RUN_INSTANT + timedelta(days=9),
    )
    assert run_a.plan.execution_id != run_b.plan.execution_id
    ranges_a = [request.requested_range for request in run_a.plan.requests()]
    ranges_b = [request.requested_range for request in run_b.plan.requests()]
    assert ranges_a != ranges_b
    assert plan_digest(run_a) == plan_digest(run_b)


def test_the_plan_digest_binds_every_stable_plan_property() -> None:
    """Change one comparable property, and the digest changes.

    Each case alters exactly one thing the two runs of a pair are required to hold
    in common -- the subject inventory, the schema version, the response format, a
    page limit, a page count, and each byte ceiling -- and the digest must move for
    every one of them. A digest that ignored any of these would let the combined
    assessor admit two runs that asked different questions.
    """
    plan = build_empirical_plan(
        inventory=synthetic_inventory(), execution_id=EXECUTION_ID, instant=RUN_INSTANT
    )
    baseline = plan_digest(plan)

    other_subjects = tuple(f"ZZ-OTHER-{index:02d}" for index in range(1, 9))
    variants = [
        replace(
            plan, plan=replace(plan.plan, subjects=synthetic_inventory(other_subjects).subjects)
        ),
        replace(plan, plan=replace(plan.plan, source_schema_version="sharadar-empirical-v2")),
        replace(plan, plan=replace(plan.plan, response_format=ResponseFormat.JSON)),
        replace(
            plan,
            plan=replace(
                plan.plan,
                datasets=(
                    replace(plan.plan.datasets[0], page_limit=99),
                    *plan.plan.datasets[1:],
                ),
            ),
        ),
        replace(
            plan,
            plan=replace(
                plan.plan,
                datasets=(
                    replace(plan.plan.datasets[0], max_pages=1),
                    *plan.plan.datasets[1:],
                ),
            ),
        ),
        replace(
            plan,
            plan=replace(
                plan.plan,
                limits=replace(plan.plan.limits, max_response_bytes=1024),
            ),
        ),
        replace(
            plan,
            plan=replace(plan.plan, limits=replace(plan.plan.limits, max_run_bytes=1024)),
        ),
    ]
    digests = [plan_digest(variant) for variant in variants]
    assert baseline not in digests
    assert len(set(digests)) == len(digests)


def test_the_plan_digest_ignores_only_the_two_values_a_pair_must_differ_in() -> None:
    # Stated as its own check so the exclusion is deliberate rather than incidental:
    # the digest document names neither the execution identity nor a requested range,
    # and the locator binds both in fields of its own.
    plan = build_empirical_plan(
        inventory=synthetic_inventory(), execution_id=EXECUTION_ID, instant=RUN_INSTANT
    )
    s3, _ = _acquire()
    document = _document(s3)
    assert document["execution_id"] == EXECUTION_ID
    assert all(entry["requested_range"] for entry in document["entries"])

    only_identity_differs = build_empirical_plan(
        inventory=synthetic_inventory(), execution_id="synthetic-empirical-b", instant=RUN_INSTANT
    )
    only_window_differs = build_empirical_plan(
        inventory=synthetic_inventory(),
        execution_id=EXECUTION_ID,
        instant=RUN_INSTANT + timedelta(days=9),
    )
    assert plan_digest(plan) == plan_digest(only_identity_differs)
    assert plan_digest(plan) == plan_digest(only_window_differs)


def test_the_locator_records_the_planned_and_completed_counts() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    assert document["planned_request_count"] == 48
    assert document["completed_request_count"] == 48
    assert document["completeness"] == Completeness.COMPLETE.value
    assert document["publication_state_unknown"] is False


def test_the_locator_declares_the_qualification_mode_and_the_permitted_profile() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    assert document["acquisition_mode"] == AcquisitionMode.QUALIFICATION.value
    assert document["profile"] == "PROVIDER_REALISTIC_PIT"
    assert document["classification"] == "LICENSED"


def test_public_pit_is_not_expressible_in_a_locator() -> None:
    s3, _ = _acquire()
    assert "PUBLIC_PIT" not in _locator_bytes(s3).decode("utf-8")


def test_every_entry_binds_three_objects_by_key_digest_and_byte_count() -> None:
    s3, _ = _acquire()
    for entry in _document(s3)["entries"]:
        for role in ("claim", "payload", "record"):
            key = entry[f"{role}_key"]
            digest = entry[f"{role}_sha256"]
            count = entry[f"{role}_bytes"]
            assert key.startswith("licensed/bronze/")
            assert len(digest) == 64
            assert count >= 0
            stored = s3.objects[key.removeprefix("licensed/")]
            assert len(stored) == count
            if role == "payload":
                assert sha256_hex(stored) == digest


def test_every_recorded_key_and_digest_matches_what_was_actually_stored() -> None:
    s3, _ = _acquire()
    for entry in _document(s3)["entries"]:
        for role in ("claim", "record"):
            stored = s3.objects[entry[f"{role}_key"].removeprefix("licensed/")]
            assert sha256_hex(stored) == entry[f"{role}_sha256"]


def test_every_recorded_payload_key_is_the_adr_0020_key_that_was_actually_written() -> None:
    # Replaces the superseded builder-agreement check, and asserts more than it did.
    # That test bound the locator's payload name to ``bronze_payload_key``; ADR-0020 is
    # precisely the amendment that separates the two, so agreeing with it would now be
    # the defect. Three things are asserted instead: the recorded name is the
    # request-scoped reconstruction, an object exists under it in the store the run
    # actually wrote to, and it is **not** the pre-amendment content-addressed name.
    s3, _ = _acquire()
    document = _document(s3)
    entries = document["entries"]
    assert len(entries) == 48
    ordinals = request_ordinal_map(
        [(entry["dataset"], entry["subject"], entry["page_skip"]) for entry in entries]
    )
    for entry in entries:
        coordinate = (entry["dataset"], entry["subject"], entry["page_skip"])
        expected = qualification_payload_key(
            dataset=entry["dataset"],
            execution_id=EXECUTION_ID,
            request_ordinal=ordinals[coordinate],
            content_sha256=entry["payload_sha256"],
        )
        assert entry["payload_key"] == expected.logical_key
        assert physical_key(expected) in s3.objects

        superseded = bronze_payload_key(
            retrieval=RetrievalMetadata(
                provider="sharadar",
                dataset=entry["dataset"],
                requested_range=entry["requested_range"],
                retrieved_at=RUN_INSTANT,
                source_schema_version=document["source_schema_version"],
                ingestion_run_id=entry["acquisition_id"],
                acquisition_mode=AcquisitionMode.QUALIFICATION,
            ),
            payload=s3.objects[physical_key(expected)],
        )
        assert entry["payload_key"] != superseded.logical_key
        assert physical_key(superseded) not in s3.objects


def test_every_entry_carries_a_distinct_acquisition_identity() -> None:
    s3, _ = _acquire()
    identities = [entry["acquisition_id"] for entry in _document(s3)["entries"]]
    assert len(set(identities)) == len(identities) == 48


def test_dispositions_are_the_closed_two_member_vocabulary() -> None:
    s3, _ = _acquire()
    permitted = {member.value for member in ObjectDisposition}
    assert permitted == {"WRITTEN", "ALREADY_PRESENT"}
    for entry in _document(s3)["entries"]:
        for role in ("claim", "payload", "record"):
            assert entry[f"{role}_disposition"] in permitted


def test_the_acquisition_path_can_no_longer_record_already_present() -> None:
    """The inversion ADR-0019 forces, and the schema it deliberately leaves alone.

    Until ADR-0019 this asserted the opposite: identical bytes reused one payload
    object, the shared store proved it identical with a ``HeadObject``, and the entry
    was recorded ``ALREADY_PRESENT``. The write-only publisher has no such proof
    available, so it reaches **one** success -- a write -- and every disposition this
    path can emit is ``WRITTEN``.

    ``ObjectDisposition`` keeps both members. It is the accepted durable locator
    schema, neither ADR-0019 §9 nor ADR-0020 amends any part of it, and narrowing a
    stored vocabulary because one producer can no longer reach a value would be an
    unapproved change to evidence the assessor validates. What changed is what the
    producer can *say*, and that is asserted here rather than in the schema.
    """
    # **Driven on the case that used to produce it, and now over the whole run.**
    # Every subject's completeness probe for one dataset returns the same header-only
    # body, so under ADR-0018 the second and later ones resolved to ``ALREADY_PRESENT``.
    # Under ADR-0019 that write failed closed and the run halted, so only a truncated
    # set of entries could be inspected. ADR-0020 gives each request its own payload
    # name, so the same legitimate repeat now completes -- and the assertion covers all
    # 48 entries and all 144 dispositions rather than a prefix of them. Driving it with
    # byte-distinct responses would still prove nothing: there would be no repeat to
    # record either way.
    s3, result = _acquire(transport=PagedTransport(byte_variant=""))
    assert result.status is AcquisitionStatus.COMPLETED
    entries = _document(s3)["entries"]
    assert len(entries) == 48
    dispositions = [
        entry[f"{role}_disposition"] for entry in entries for role in ("claim", "payload", "record")
    ]
    assert len(dispositions) == 144
    assert set(dispositions) == {ObjectDisposition.WRITTEN.value}
    assert ObjectDisposition.ALREADY_PRESENT.value not in dispositions
    assert result.counts.head_object_count == 0
    assert s3.head_calls == []


def test_the_locator_is_inside_its_size_ceiling() -> None:
    s3, _ = _acquire()
    assert 0 < len(_locator_bytes(s3)) <= MAX_LOCATOR_BYTES


def test_the_locator_serialises_deterministically() -> None:
    first, _ = _acquire()
    second, _ = _acquire()
    assert _locator_bytes(first) == _locator_bytes(second)


def test_the_locator_carries_no_bucket_account_url_or_credential() -> None:
    s3, _ = _acquire()
    text = _locator_bytes(s3).decode("utf-8")
    for canary in LEAK_CANARIES:
        if canary in SYNTHETIC_SUBJECTS:
            # Subjects are legitimate private content of a LICENSED locator.
            continue
        assert canary not in text


def test_the_locator_carries_no_free_text_field() -> None:
    for field in LOCATOR_FIELDS | LOCATOR_ENTRY_FIELDS:
        for forbidden in ("note", "notes", "comment", "message", "description", "reason"):
            assert forbidden not in field


def test_a_size_ceiling_refusal_happens_at_serialisation() -> None:
    oversized = {"padding": "x" * (MAX_LOCATOR_BYTES + 10)}
    with pytest.raises(LocatorError) as raised:
        serialize_locator(oversized)
    assert raised.value.defect is LocatorDefect.TOO_LARGE


# -- adversarial validation --------------------------------------------------


def _refuses(document: object, execution_id: str = EXECUTION_ID) -> LocatorDefect:
    with pytest.raises(LocatorError) as raised:
        validate_locator_document(document, execution_id=execution_id)
    return raised.value.defect


def test_a_valid_locator_round_trips_through_decode() -> None:
    s3, _ = _acquire()
    locator = decode_locator(_locator_bytes(s3), execution_id=EXECUTION_ID)
    assert locator.assessable is True
    assert locator.completeness is Completeness.COMPLETE
    assert len(locator.entries) == 48


def test_an_unknown_top_level_field_is_refused_rather_than_ignored() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["extra"] = "value"
    assert _refuses(document) is LocatorDefect.FIELD_UNKNOWN


def test_a_missing_top_level_field_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    del document["plan_digest"]
    assert _refuses(document) is LocatorDefect.FIELD_MISSING


def test_a_wrong_schema_version_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["schema_version"] = "something-else"
    assert _refuses(document) is LocatorDefect.SCHEMA_VERSION_UNKNOWN


def test_a_locator_describing_another_execution_is_refused() -> None:
    s3, _ = _acquire()
    assert _refuses(_document(s3), execution_id="synthetic-other-x") is (
        LocatorDefect.IDENTITY_MISMATCH
    )


def test_a_public_pit_profile_claim_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["profile"] = "PUBLIC_PIT"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_a_non_qualification_acquisition_mode_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["acquisition_mode"] = "BACKFILL"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_a_control_classification_claim_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["classification"] = "CONTROL"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_an_entry_count_disagreeing_with_the_completed_count_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"] = document["entries"][:-1]
    assert _refuses(document) is LocatorDefect.ENTRY_COUNT_INCONSISTENT


def test_a_duplicated_acquisition_identity_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][1]["acquisition_id"] = document["entries"][0]["acquisition_id"]
    document["entries"][1]["record_key"] = document["entries"][0]["record_key"]
    assert _refuses(document) is LocatorDefect.ENTRY_DUPLICATED


def test_a_completed_count_above_the_planned_count_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["planned_request_count"] = 10
    assert _refuses(document) is LocatorDefect.RESULT_INCONSISTENT


def test_a_complete_locator_that_did_not_complete_every_request_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["planned_request_count"] = 60
    document["completeness"] = Completeness.COMPLETE.value
    assert _refuses(document) is LocatorDefect.RESULT_INCONSISTENT


@pytest.mark.parametrize("field", ["claim_sha256", "payload_sha256", "record_sha256"])
def test_a_malformed_digest_is_refused(field: str) -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][0][field] = "not-a-digest"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


@pytest.mark.parametrize("field", ["claim_bytes", "payload_bytes", "record_bytes"])
def test_a_negative_byte_count_is_refused(field: str) -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][0][field] = -1
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_an_unknown_disposition_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][0]["payload_disposition"] = "MAYBE"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_an_unknown_entry_field_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][0]["note"] = "why"
    assert _refuses(document) is LocatorDefect.FIELD_UNKNOWN


def test_a_completion_instant_before_the_start_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["run_completed_at"] = "1998-01-01T00:00:00+00:00"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_a_naive_instant_is_refused() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["run_started_at"] = "2026-08-30T12:00:00"
    assert _refuses(document) is LocatorDefect.FIELD_MALFORMED


def test_invalid_utf8_locator_bytes_are_refused_rather_than_replaced() -> None:
    with pytest.raises(LocatorError) as raised:
        decode_locator(b"\xff\xfe not json", execution_id=EXECUTION_ID)
    assert raised.value.defect is LocatorDefect.ENCODING_INVALID


def test_locator_bytes_over_the_ceiling_are_refused_before_decoding() -> None:
    with pytest.raises(LocatorError) as raised:
        decode_locator(b"x" * (MAX_LOCATOR_BYTES + 1), execution_id=EXECUTION_ID)
    assert raised.value.defect is LocatorDefect.TOO_LARGE


def test_malformed_json_is_refused() -> None:
    with pytest.raises(LocatorError) as raised:
        decode_locator(b"{not json", execution_id=EXECUTION_ID)
    assert raised.value.defect is LocatorDefect.DOCUMENT_MALFORMED


def test_a_partial_locator_validates_but_is_not_assessable() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["completeness"] = Completeness.PARTIAL.value
    document["planned_request_count"] = 60
    locator = validate_locator_document(document, execution_id=EXECUTION_ID)
    assert locator.completeness is Completeness.PARTIAL
    assert locator.assessable is False


def test_an_ambiguous_publication_state_makes_a_locator_unassessable() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["publication_state_unknown"] = True
    locator = validate_locator_document(document, execution_id=EXECUTION_ID)
    assert locator.assessable is False


def test_no_locator_refusal_carries_a_key_digest_or_subject() -> None:
    s3, _ = _acquire()
    document = _document(s3)
    document["entries"][0]["payload_sha256"] = "x" * 64
    with pytest.raises(LocatorError) as raised:
        validate_locator_document(document, execution_id=EXECUTION_ID)
    rendered = f"{raised.value} {raised.value!r} {raised.value.args}"
    for subject in SYNTHETIC_SUBJECTS:
        assert subject not in rendered
    assert "licensed/" not in rendered
    assert SYNTHETIC_BUCKET not in rendered


def test_the_serialised_locator_is_canonical_bytes_of_its_document() -> None:
    s3, _ = _acquire()
    assert _locator_bytes(s3) == canonical_bytes(_document(s3))


def test_the_schema_version_constant_is_the_one_written() -> None:
    s3, _ = _acquire()
    assert _document(s3)["schema_version"] == LOCATOR_SCHEMA_VERSION
