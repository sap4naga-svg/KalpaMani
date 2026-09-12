"""Offline research-build processing: verified inputs, Silver, availability, membership,
Gold, manifest -- on synthetic fixtures written by the real acquisition path.

Every count asserted is what an injected fake was asked; **mocked results are not AWS
verification**. The adversarial cases are ADR-0035 §3.9's, built as fixtures and held to
the outcome the contract states.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import pytest

from fixtures.production_build import (
    ACTIONS_HEADER,
    AS_OF,
    RUN_1,
    RUN_1_AT,
    RUN_2,
    RUN_2_AT,
    SCHEMAS,
    STOCKS_HEADER,
    TICKERS_HEADER,
    ZZAA,
    ZZBB,
    ZZCC,
    ZZDD,
    ZZEE_1,
    ZZEE_2,
    ZZFF,
    ZZGG,
    ZZHH,
    BuildScenario,
    FakeS3Store,
    ShiftedClock,
    acquire,
    calendar,
    configuration,
    csv,
    ledger_row,
    populated_store,
    responses_for_run,
    rule,
    slice_for_run,
    stocks_rows,
    tickers_rows,
)
from fixtures.production_runtime import BUCKET, BUILD_ID, COMMIT
from kalpamani.data.contracts.vocabulary import (
    LimitationToken,
    ProviderBoundDerivation,
    PublicBoundDerivation,
    UniverseExclusionReason,
)
from kalpamani.data.production.sharadar import availability as av
from kalpamani.data.production.sharadar import build_inputs as bi
from kalpamani.data.production.sharadar import build_manifest as bm
from kalpamani.data.production.sharadar import build_processing as bp
from kalpamani.data.production.sharadar import gold as gd
from kalpamani.data.production.sharadar import silver as sv
from kalpamani.data.production.sharadar import universe as uv
from kalpamani.data.production.sharadar.inputs import BuildInput, parse_build_input
from kalpamani.data.production.sharadar.locator import PayloadDisposition, ProductionLocatorReader
from kalpamani.data.production.sharadar.outcomes import RunnerOutcome
from kalpamani.data.qualify.sharadar.parser import schema_digest_of

pytestmark = pytest.mark.unit

CANARIES: Final = (BUCKET, RUN_1, RUN_2, BUILD_ID, COMMIT, "100001", "ZZAA")
MANIFEST_PREFIX: Final = "manifests/sharadar/builds/"


def manifest_of(store: FakeS3Store) -> dict[str, Any]:
    keys = store.keys_under(MANIFEST_PREFIX)
    assert len(keys) == 1, keys
    document: dict[str, Any] = json.loads(store.objects[keys[0]])
    return document


def artifact_rows(report: bp.BuildReport, name: str) -> list[dict[str, Any]]:
    assert report.publication is not None
    for item in report.publication.artifacts:
        if item.artifact.name == name:
            rows: list[dict[str, Any]] = json.loads(item.artifact.content)["rows"]
            return rows
    raise AssertionError(name)


def memberships(report: bp.BuildReport) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (row["session_date"], row["security_id"]): row
        for row in artifact_rows(report, "gold-universe-membership")
    }


def admitted_input(runs: tuple[tuple[str, int, datetime], ...]) -> BuildInput:
    """A parsed build input over ``runs``, valid at ``AS_OF``."""
    from fixtures.production_runtime import build_input_document
    from kalpamani.data.production.sharadar.inputs import ledger_digest

    rows = [ledger_row(run_id, run, at) for run_id, run, at in runs]
    return parse_build_input(
        build_input_document(
            rows,
            ledger_digest=ledger_digest(rows),
            issued_at=(AS_OF - timedelta(hours=1)).isoformat(),
            expires_at=(AS_OF + timedelta(hours=1)).isoformat(),
        ),
        now=AS_OF,
    )


def normalized(store: FakeS3Store, runs: tuple[tuple[str, int, datetime], ...]) -> sv.SilverLayer:
    """Verified inputs and Silver for ``runs``, through the real reader."""
    reader = ProductionLocatorReader(client=store, licensed_bucket=BUCKET)
    return sv.normalize(
        bi.verify_build_inputs(admitted_input(runs), reader=reader), schemas=SCHEMAS
    )


DEFAULT_RUNS: Final = ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT))


def _assert_accounting(scenario: BuildScenario, report: bp.BuildReport) -> None:
    gets, puts = scenario.data_plane_calls()
    assert report.objects_read == gets
    assert report.counts.s3_operations == gets + puts
    assert report.counts.secret_retrievals == 0 and report.counts.provider_requests == 0
    rendered = repr(report) + repr(report.counts) + repr(report.bootstrap)
    if report.publication is not None:
        rendered += repr(report.publication) + "".join(
            repr(item.artifact) for item in report.publication.artifacts
        )
    for canary in CANARIES:
        assert canary not in rendered, canary


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_one_build_completes_with_silver_then_gold_then_the_manifest_last(self) -> None:
        store = populated_store()
        bronze_payload_digests = {
            key.rsplit("/", 1)[1] for key in store.objects if "/production/objects/sha256/" in key
        }
        scenario = BuildScenario(store)
        report = scenario.run()
        assert report.status is bp.BuildStatus.COMPLETED, report.defect
        assert report.bootstrap.outcome is RunnerOutcome.RELEASED
        assert report.manifest is bm.ManifestDisposition.PUBLISHED
        assert report.artifacts_written == 7 and report.artifacts_already_present == 0
        assert not report.publication_state_unknown
        # Reads: two locators and every object they name; writes: seven artifacts, one manifest.
        assert report.objects_read == 2 + 2 * (16 + 32)
        assert scenario.data_plane_calls() == (98, 8)
        _assert_accounting(scenario, report)
        puts = store.puts[-8:]
        assert [key.split("/")[0] for key in puts] == ["silver"] * 3 + ["gold"] * 4 + ["manifests"]
        for key in puts:
            assert key.startswith(("silver/sharadar/", "gold/sharadar/", MANIFEST_PREFIX))
        # The manifest binds the delivered inputs, the versions and the outputs exactly.
        manifest = manifest_of(store)
        assert manifest["schema_version"] == bm.MANIFEST_SCHEMA_VERSION
        assert manifest["build_id"] == BUILD_ID and manifest["classification"] == "LICENSED"
        consumed = {d for run in manifest["build_input"]["runs"] for d in run["payload_digests"]}
        assert consumed == bronze_payload_digests
        assert manifest["build_input"]["objects_read"] == 98
        assert manifest["source_versions"]["source_schema_version"] == "sharadar-csv-production-v1"
        assert manifest["source_versions"]["observed_schema_digests"] == {
            "tickers": [schema_digest_of(TICKERS_HEADER)],
            "stocks": [schema_digest_of(STOCKS_HEADER)],
            "actions": [schema_digest_of(ACTIONS_HEADER)],
        }
        transformation = manifest["transformation"]
        assert transformation["commit"] == COMMIT
        assert transformation["configuration_digest"] == scenario.config.digest
        assert transformation["universe_rule"]["universe_rule_version"] == "breakout-long-v1"
        assert transformation["adjustment_policy"] == "SPLIT_ONLY"
        assert transformation["adjustment_convention"] == "FORWARD_BASE_NORMALIZED"
        assert manifest["resolved_profile"] == "PROVIDER_REALISTIC_PIT"
        for output in manifest["outputs"]:
            key = output["key"].removeprefix("licensed/")
            assert store.objects[key] == next(
                item.artifact.content
                for item in report.publication.artifacts  # type: ignore[union-attr]
                if item.artifact.name == output["artifact"]
            )
            assert output["key"].endswith(output["sha256"])
            assert output["disposition"] == "WRITTEN"
        assert set(manifest["limitations"]) == {
            "SINGLE_SOURCE_UNVERIFIED",
            "PROVIDER_AVAILABILITY_UNKNOWN",
            "PROVIDER_TIME_BOUNDED",
        }
        assert manifest["quality"]["plan_version"] == "breakout-long-ingest-v1"
        assert set(manifest["quality"]["checks_run"]) | set(
            manifest["quality"]["checks_not_run"]
        ) == {check.value for check in gd.QualityCheck}
        assert manifest["empty_reason"] is None

    def test_reads_are_exactly_the_locators_and_what_they_name(self) -> None:
        store = populated_store()
        scenario = BuildScenario(store)
        scenario.run()
        gets = store.gets[-98:]
        locators = {f"bronze/sharadar/_indexes/{run}.json" for run in (RUN_1, RUN_2)}
        named: set[str] = set()
        for locator_key in locators:
            document = json.loads(store.objects[locator_key])
            for entry in document["entries"]:
                named.add(entry["payload_key"].removeprefix("licensed/"))
                named.add(entry["record_key"].removeprefix("licensed/"))
        assert set(gets) == locators | named
        assert gets[0] in locators
        assert not hasattr(bp.BuildAdapters, "secrets") and not hasattr(
            bp.BuildAdapters, "provider"
        )

    def test_membership_is_decided_per_session_at_the_cutoff(self) -> None:
        report = BuildScenario(populated_store()).run()
        rows = memberships(report)
        expected = {
            ("2026-09-14", ZZAA.security_id): (True, None),
            ("2026-09-14", ZZBB.security_id): (False, "HISTORY"),  # C-2
            ("2026-09-14", ZZCC.security_id): (False, "EXCHANGE"),
            ("2026-09-14", ZZDD.security_id): (False, "SECURITY_TYPE"),
            ("2026-09-14", ZZFF.security_id): (False, "UNRESOLVED_CORPORATE_ACTION"),
            ("2026-09-14", ZZGG.security_id): (False, "PRICE"),
            ("2026-09-14", ZZHH.security_id): (True, None),  # C-3: delisting dated d
            ("2026-09-15", ZZAA.security_id): (True, None),
            ("2026-09-15", ZZBB.security_id): (True, None),
            ("2026-09-15", ZZHH.security_id): (False, "HISTORY"),  # C-3: excluded from d+1
        }
        for key, (member, reason) in expected.items():
            assert (rows[key]["is_member"], rows[key]["exclusion_reason"]) == (member, reason), key
        assert rows[("2026-09-14", ZZFF.security_id)]["exclusion_vocabulary"] == "proposed-adr-0039"
        assert rows[("2026-09-14", ZZCC.security_id)]["exclusion_vocabulary"] == "accepted"
        # No clause reads session d's bar: every consumed bar is dated before d.
        for (session, _), row in rows.items():
            for bar in row["bars_consumed"]:
                assert bar.split(":")[0] < session
        assert rows[("2026-09-14", ZZAA.security_id)]["price_at_eval"] == "10.60"
        assert rows[("2026-09-14", ZZAA.security_id)]["history_sessions_at_eval"] == 4

    def test_split_only_forward_normalized_and_spinoff_excluded_from_its_ex_date(self) -> None:
        report = BuildScenario(populated_store()).run()
        bars = {
            (row["security_id"], row["session_date"]): row
            for row in artifact_rows(report, "gold-adjusted-bars")
        }
        # Before the ex-date the factor is 1; on and after it the 2:1 split doubles.
        assert bars[(ZZAA.security_id, "2026-09-01")]["close"] == "20.400000"
        assert bars[(ZZAA.security_id, "2026-09-01")]["factor"] == "1"
        assert bars[(ZZAA.security_id, "2026-09-03")]["close"] == "21.000000"
        assert bars[(ZZAA.security_id, "2026-09-03")]["factor"] == "2"
        assert bars[(ZZAA.security_id, "2026-09-03")]["volume"] == "50000"
        # The spinoff security keeps only sessions before its first ex-date.
        zzff = sorted(s for (sid, s) in bars if sid == ZZFF.security_id)
        assert zzff == ["2026-08-31", "2026-09-01", "2026-09-02"]
        actions = artifact_rows(report, "gold-corporate-actions")
        assert any(
            a["action"] == "spinoff" and a["security_id"] == ZZFF.security_id for a in actions
        )
        assert report.publication is not None
        assert report.publication.artifacts[3].artifact.name == "gold-adjusted-bars"
        assert gd.ADJUSTMENT_CONVENTION.value == "FORWARD_BASE_NORMALIZED"

    def test_multi_run_revisions_are_kept_apart_and_the_latest_admissible_is_served(self) -> None:
        store = populated_store()
        report = BuildScenario(store).run()
        silver_stocks = artifact_rows(report, "silver-stocks")
        versions = [
            row for row in silver_stocks if row["row_key"] == [ZZAA.security_id, "2026-09-02"]
        ]
        # At as_of both versions are admissible: the latest revision is served, and the
        # Silver artifact records it as revision 1 with its own first-seen instant.
        assert [v["revision_sequence"] for v in versions] == [1]
        assert versions[0]["fields"]["close"] == "20.90"
        assert versions[0]["system_first_seen_time"] > RUN_2_AT.isoformat()
        assert versions[0]["provenance"]["acquisition_id"] == RUN_2
        manifest = manifest_of(store)
        served = {entry["dataset"]: entry for entry in manifest["served"]}
        assert served["stocks"]["revisions_superseded"] == 1
        assert served["stocks"]["revisions_excluded_by_time"] == 0
        # A later snapshot is a new attribute revision, never a rewrite.
        assert served["tickers"]["revisions_admitted"] == 9
        assert served["tickers"]["revisions_superseded"] == 9
        identity = manifest["identity"]["stocks"]
        assert identity["ambiguous_symbols"] >= 1 and identity["rows_excluded_for_identity"] >= 1

    def test_identical_bytes_re_delivered_count_and_never_become_a_new_revision(self) -> None:
        layer = normalized(populated_store(), DEFAULT_RUNS)
        by_key: dict[tuple[str, ...], list[sv.RowVersion]] = {}
        for row in layer.stocks.rows:
            by_key.setdefault(row.row_key, []).append(row)
        same = by_key[(ZZCC.security_id, "2026-09-03")]
        assert len(same) == 1 and same[0].observation_count == 2
        assert same[0].system_first_seen_time == min(
            same[0].system_first_seen_time, same[0].provenance.retrieved_at
        )
        assert same[0].provenance.run_id == RUN_1
        revised = by_key[(ZZAA.security_id, "2026-09-02")]
        assert [r.revision_sequence for r in revised] == [0, 1]
        assert revised[0].provenance.run_id == RUN_1 and revised[1].provenance.run_id == RUN_2
        assert revised[1].system_first_seen_time > revised[0].system_first_seen_time


# ---------------------------------------------------------------------------
# Availability: T-1, T-2, T-6, V-1, and the gated routes (T-3 .. T-5, D-1 .. D-3)
# ---------------------------------------------------------------------------


def _resolved(
    store: FakeS3Store, *, evidence: av.AvailabilityEvidence | None = None
) -> av.ResolvedLayer:
    layer = normalized(store, DEFAULT_RUNS)
    return av.resolve(
        layer,
        evidence=av.AvailabilityEvidence(version="e0") if evidence is None else evidence,
        calendar=calendar(),
    )


def _versions(resolved: av.ResolvedLayer, key: tuple[str, ...]) -> list[av.ResolvedRow]:
    return sorted(
        (row for row in resolved.stocks if row.row.row_key == key),
        key=lambda row: row.row.revision_sequence,
    )


class TestTimingRevisions:
    KEY: Final = (ZZAA.security_id, "2026-09-02")

    def test_t1_a_build_between_the_two_bounds_serves_v1_only(self) -> None:
        store = populated_store()
        between = datetime(2026, 9, 10, tzinfo=UTC)
        scenario = BuildScenario(store, config=configuration(as_of=between))
        report = scenario.run()
        assert report.status is bp.BuildStatus.COMPLETED, report.defect
        versions = [
            row
            for row in artifact_rows(report, "silver-stocks")
            if row["row_key"] == list(self.KEY)
        ]
        assert [v["revision_sequence"] for v in versions] == [0]
        assert versions[0]["fields"]["close"] == "20.80"
        served = {e["dataset"]: e for e in manifest_of(store)["served"]}
        assert served["stocks"]["revisions_admitted"] >= 1
        assert served["stocks"]["revisions_excluded_by_time"] >= 1
        assert served["stocks"]["revisions_superseded"] == 0

    def test_t1_a_revision_never_inherits_the_earlier_bound(self) -> None:
        v1, v2 = _versions(_resolved(populated_store()), self.KEY)
        b1, b2 = (
            v1.availability.provider_available_upper_bound,
            v2.availability.provider_available_upper_bound,
        )
        assert b1 < b2
        assert b1 >= RUN_1_AT and b2 >= RUN_2_AT
        assert v2.availability.provider_available_upper_bound == v2.row.system_first_seen_time

    def test_t1_serving_a_row_under_a_bound_later_than_as_of_is_refused_not_annotated(self) -> None:
        v1, v2 = _versions(_resolved(populated_store()), self.KEY)
        with pytest.raises(gd.GoldError) as refused:
            gd.verify_served_rows([v1, v2], as_of=datetime(2026, 9, 10, tzinfo=UTC))
        assert refused.value.defect is gd.GoldDefect.REFUSED_TIMING
        gd.verify_served_rows([v1], as_of=datetime(2026, 9, 10, tzinfo=UTC))

    def test_no_row_can_carry_an_inexpressible_derivation(self) -> None:
        with pytest.raises(ValueError):
            av.Availability(
                rule=av.AvailabilityRule.P2_FIRST_SEEN,
                provider_bound_derivation=ProviderBoundDerivation.NONE,
                provider_available_upper_bound=RUN_1_AT,
                public_bound_derivation=PublicBoundDerivation.NONE,
                public_available_upper_bound=None,
                governing_time=RUN_1_AT,
                evidence_digest=None,
                limitations=(),
            )
        for route in av.GatedRoute:
            assert route.value not in {m.value for m in ProviderBoundDerivation}

    def test_t2_a_delivery_schedule_alone_never_admits_a_version(self) -> None:
        schedule = av.VersionEvidence(
            kind=av.EvidenceKind.DELIVERY_SCHEDULE,
            dataset="stocks",
            row_key=self.KEY,
            content_sha256=None,
            instant=datetime(2026, 9, 2, 23, 30, tzinfo=UTC),
            evidence_digest="ab" * 32,
        )
        evidence = av.AvailabilityEvidence(version="e-schedule", items=(schedule,))
        v1, v2 = _versions(_resolved(populated_store(), evidence=evidence), self.KEY)
        for version in (v1, v2):
            assert version.availability.rule is av.AvailabilityRule.P2_FIRST_SEEN
            assert (
                version.availability.provider_bound_derivation
                is ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND
            )
            assert (
                version.availability.provider_available_upper_bound
                == version.row.system_first_seen_time
            )
            assert version.availability.evidence_digest is None

    def test_t6_and_v1_per_version_delivery_evidence_admits_only_the_version_it_names(self) -> None:
        store = populated_store()
        v1, v2 = _versions(_resolved(store), self.KEY)
        delivery_instant = datetime(2026, 9, 3, 4, 30, tzinfo=UTC)
        record = av.VersionEvidence(
            kind=av.EvidenceKind.PER_VERSION_DELIVERY,
            dataset="stocks",
            row_key=self.KEY,
            content_sha256=v1.row.content_sha256,
            instant=delivery_instant,
            evidence_digest="cd" * 32,
        )
        evidence = av.AvailabilityEvidence(version="e-delivery", items=(record,))
        resolved = _resolved(store, evidence=evidence)
        w1, w2 = _versions(resolved, self.KEY)
        assert w1.availability.rule is av.AvailabilityRule.P3_DELIVERY_WINDOW
        assert w1.availability.provider_bound_derivation is ProviderBoundDerivation.DELIVERY_WINDOW
        assert w1.availability.provider_available_upper_bound == delivery_instant
        assert w1.availability.evidence_digest == "cd" * 32
        assert LimitationToken.PROVIDER_AVAILABILITY_UNKNOWN not in w1.availability.limitations
        # v2 has no evidence of its own: P-2 at its own first-seen instant (V-1).
        assert w2.availability.rule is av.AvailabilityRule.P2_FIRST_SEEN
        assert w2.availability.provider_available_upper_bound == v2.row.system_first_seen_time
        counts = {c.dataset: c for c in resolved.counts}
        assert counts["stocks"].p3_delivery_window == 1
        assert counts["stocks"].p2_first_seen == len(resolved.stocks) - 1
        # Every rule yields a bound; no rule writes an exact provider instant.
        for row in resolved.stocks:
            assert row.availability.document()["provider_available_time"] is None

    @pytest.mark.parametrize(
        ("kind", "instant"),
        [
            (av.EvidenceKind.ARCHIVAL_CAPTURE, datetime(2019, 3, 6, 23, 5, tzinfo=UTC)),  # T-3
            (av.EvidenceKind.ARCHIVAL_CAPTURE, datetime(2019, 3, 7, 4, 47, tzinfo=UTC)),  # T-4
            (av.EvidenceKind.ARCHIVAL_CAPTURE, None),  # T-5: date only
            (av.EvidenceKind.VENDOR_DATE, None),  # D-1 .. D-3
        ],
    )
    def test_gated_routes_are_ignored_and_the_row_falls_to_p2(
        self, kind: av.EvidenceKind, instant: datetime | None
    ) -> None:
        store = populated_store()
        v1, _ = _versions(_resolved(store), self.KEY)
        item = av.VersionEvidence(
            kind=kind,
            dataset="stocks",
            row_key=self.KEY,
            content_sha256=v1.row.content_sha256,
            instant=instant,
            evidence_digest="ef" * 32,
        )
        resolved = _resolved(
            store, evidence=av.AvailabilityEvidence(version="e-gated", items=(item,))
        )
        w1, _ = _versions(resolved, self.KEY)
        assert w1.availability.rule is av.AvailabilityRule.P2_FIRST_SEEN
        assert w1.availability.provider_available_upper_bound == v1.row.system_first_seen_time
        assert w1.availability.provider_available_upper_bound != instant
        assert w1.availability.evidence_digest is None
        counts = {c.dataset: c for c in resolved.counts}
        assert counts["stocks"].gated_evidence_ignored == 1
        assert counts["stocks"].p3_delivery_window == 0

    def test_actions_carry_a_public_bound_and_the_later_time_governs(self) -> None:
        resolved = _resolved(populated_store())
        split = next(row for row in resolved.actions if row.row.fields.get("action") == "split")
        assert split.availability.public_bound_derivation is PublicBoundDerivation.DATE_PLUS_LAG
        assert split.availability.public_available_upper_bound == datetime(
            2026, 9, 3, 13, 30, tzinfo=UTC
        )
        assert split.availability.governing_time == max(
            split.availability.public_available_upper_bound,
            split.availability.provider_available_upper_bound,
        )
        for row in resolved.stocks:
            assert row.availability.public_bound_derivation is PublicBoundDerivation.NONE


# ---------------------------------------------------------------------------
# Verified inputs
# ---------------------------------------------------------------------------


class TestVerifiedInputs:
    def _payload_key(self, store: FakeS3Store, run_id: str, ordinal: int) -> str:
        document = json.loads(store.objects[f"bronze/sharadar/_indexes/{run_id}.json"])
        key: str = document["entries"][ordinal]["payload_key"]
        return key.removeprefix("licensed/")

    def test_a_digest_mismatch_refuses_before_any_parse_and_any_write(self) -> None:
        store = populated_store(runs=(1,))
        key = self._payload_key(store, RUN_1, 3)
        original = store.objects[key]
        store.objects[key] = original[:-1] + bytes([original[-1] ^ 1])
        scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),))
        report = scenario.run()
        assert report.status is bp.BuildStatus.REFUSED_INPUTS
        assert report.defect == bi.BuildInputDefect.OBJECT_INTEGRITY.value
        assert (
            scenario.data_plane_calls()[1] == 0
            and report.manifest is bm.ManifestDisposition.NOT_ATTEMPTED
        )
        # The locator, three complete entries, and the fourth entry's payload: 1 + 6 + 1.
        assert report.objects_read == 8
        _assert_accounting(scenario, report)

    def test_a_byte_count_mismatch_refuses_as_integrity(self) -> None:
        store = populated_store(runs=(1,))
        key = self._payload_key(store, RUN_1, 0)
        store.objects[key] = store.objects[key] + b"\r\n"
        report = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),)).run()
        assert report.status is bp.BuildStatus.REFUSED_INPUTS
        assert report.defect == bi.BuildInputDefect.OBJECT_INTEGRITY.value
        assert report.objects_read == 2

    def test_unauthorized_request_coordinates_refuse_before_any_object_is_read(self) -> None:
        store = populated_store(runs=(1,))
        key = f"bronze/sharadar/_indexes/{RUN_1}.json"
        document = json.loads(store.objects[key])
        document["entries"][2]["request"]["page_offset"] = 5000
        store.objects[key] = json.dumps(document).encode()
        scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),))
        report = scenario.run()
        assert report.status is bp.BuildStatus.REFUSED_INPUTS
        assert report.defect == bi.BuildInputDefect.LOCATOR_INVALID.value
        assert report.objects_read == 1 and scenario.data_plane_calls() == (1, 0)

    def test_a_missing_locator_refuses_with_one_read(self) -> None:
        store = populated_store(runs=(1,))
        scenario = BuildScenario(store)  # RUN_2 is in the input and not in the store
        report = scenario.run()
        assert report.status is bp.BuildStatus.REFUSED_INPUTS
        assert report.defect == bi.BuildInputDefect.LOCATOR_UNREADABLE.value
        assert report.objects_read == 1 + 2 * 16 + 1

    def test_the_acquisition_record_must_agree_with_the_locator_and_the_run(self) -> None:
        store = populated_store(runs=(1,))
        reader = ProductionLocatorReader(client=store, licensed_bucket=BUCKET)
        row = admitted_input(((RUN_1, 1, RUN_1_AT),)).runs[0]
        locator = reader.read_run_locator(run_id=RUN_1, ledger_row=row)
        entry = locator.entries[0]
        record = json.loads(reader.read_exact(entry.record))
        assert bi.cross_check_record(
            dict(record), entry=entry, locator=locator
        ) == datetime.fromisoformat(record["retrieved_at"])
        cases = {
            "source_schema_version": ("other-schema", bi.BuildInputDefect.SCHEMA_INCOMPATIBLE),
            "dataset": ("stocks", bi.BuildInputDefect.PROVENANCE_CONTRADICTORY),
            "ingestion_run_id": (RUN_2, bi.BuildInputDefect.PROVENANCE_CONTRADICTORY),
            "content_sha256": ("0" * 64, bi.BuildInputDefect.PROVENANCE_CONTRADICTORY),
            "byte_count": (record["byte_count"] + 1, bi.BuildInputDefect.PROVENANCE_CONTRADICTORY),
            "requested_range": ("SNAPSHOT", bi.BuildInputDefect.PROVENANCE_CONTRADICTORY),
            "acquisition_mode": ("UPDATE", bi.BuildInputDefect.PROVENANCE_CONTRADICTORY),
            "classification": ("CONTROL", bi.BuildInputDefect.PROVENANCE_CONTRADICTORY),
            "retrieved_at": (
                (RUN_1_AT - timedelta(days=1)).isoformat(),
                bi.BuildInputDefect.PROVENANCE_CONTRADICTORY,
            ),
        }
        for field, (value, defect) in cases.items():
            tampered = dict(record)
            tampered[field] = value
            with pytest.raises(bi.BuildInputError) as refused:
                bi.cross_check_record(tampered, entry=entry, locator=locator)
            assert refused.value.defect is defect, field

    def test_bounds_refuse_before_the_read_that_would_exceed_them(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = populated_store(runs=(1,))
        monkeypatch.setattr(bi, "MAX_BUILD_INPUT_BYTES", 256 * 1024 + 10)
        scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),))
        report = scenario.run()
        assert report.status is bp.BuildStatus.REFUSED_INPUTS
        assert report.defect == bi.BuildInputDefect.INPUT_BYTES_EXCEEDED.value
        assert report.objects_read == 1  # the locator was charged, the first payload refused
        monkeypatch.setattr(bi, "MAX_BUILD_INPUT_BYTES", 2 * 1024 * 1024 * 1024)
        monkeypatch.setattr(bi, "MAX_BUILD_OBJECTS", 4)
        report = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),)).run()
        assert report.defect == bi.BuildInputDefect.OBJECT_COUNT_EXCEEDED.value
        assert report.objects_read == 3

    def test_the_deadline_bounds_reads(self) -> None:
        store = populated_store(runs=(1,))
        scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),))
        original = store.get_object

        def slow_get(**kwargs: Any) -> Any:
            scenario.clock.seconds += 700.0
            return original(**kwargs)

        store.get_object = slow_get  # type: ignore[method-assign]
        report = scenario.run()
        assert report.status is bp.BuildStatus.REFUSED_INPUTS
        assert report.defect == bi.BuildInputDefect.DEADLINE_EXHAUSTED.value
        assert scenario.data_plane_calls()[1] == 0


# ---------------------------------------------------------------------------
# Normalization refusals: malformed, drifted, conflicting, truncated, unmapped
# ---------------------------------------------------------------------------


def _store_with_run_1(responses: dict[tuple[str, str, int], bytes]) -> FakeS3Store:
    store = FakeS3Store()
    acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=responses)
    return store


def _run_1_build(store: FakeS3Store) -> bp.BuildReport:
    return BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),)).run()


class TestNormalizationRefusals:
    def test_a_malformed_row_refuses_the_whole_input(self) -> None:
        responses = responses_for_run(1)
        ragged = csv(STOCKS_HEADER, [row[:-1] for row in stocks_rows(date(2026, 9, 1), run=1)])
        responses[("stocks", "2026-09-01/2026-09-01", 0)] = ragged
        report = _run_1_build(_store_with_run_1(responses))
        assert report.status is bp.BuildStatus.REFUSED_NORMALIZATION
        assert report.defect == sv.SilverDefect.PAYLOAD_UNPARSEABLE.value
        assert report.manifest is bm.ManifestDisposition.NOT_ATTEMPTED

    def test_schema_drift_is_a_blocking_finding(self) -> None:
        responses = responses_for_run(1)
        drifted = (*STOCKS_HEADER, "newcolumn")
        rows = [(*row, "x") for row in stocks_rows(date(2026, 9, 1), run=1)]
        responses[("stocks", "2026-09-01/2026-09-01", 0)] = csv(drifted, rows)
        report = _run_1_build(_store_with_run_1(responses))
        assert report.status is bp.BuildStatus.REFUSED_NORMALIZATION
        assert report.defect == sv.SilverDefect.SCHEMA_UNSTABLE.value

    def test_conflicting_observations_in_one_run_are_refused_never_ordered_away(self) -> None:
        responses = responses_for_run(1)
        rows = stocks_rows(date(2026, 9, 1), run=1)
        first = rows[0]
        conflicting = (*first[:5], "99.99", *first[6:])
        responses[("stocks", "2026-09-01/2026-09-01", 0)] = csv(STOCKS_HEADER, [*rows, conflicting])
        report = _run_1_build(_store_with_run_1(responses))
        assert report.status is bp.BuildStatus.REFUSED_NORMALIZATION
        assert report.defect == sv.SilverDefect.ROW_CONFLICT_IN_RUN.value

    def test_an_exact_duplicate_in_one_run_is_counted_not_conflicting(self) -> None:
        responses = responses_for_run(1)
        rows = stocks_rows(date(2026, 9, 1), run=1)
        responses[("stocks", "2026-09-01/2026-09-01", 0)] = csv(STOCKS_HEADER, [*rows, rows[0]])
        report = _run_1_build(_store_with_run_1(responses))
        assert report.status is bp.BuildStatus.COMPLETED, report.defect

    def test_a_full_first_page_is_truncation_and_a_later_data_page_is_unsupported(self) -> None:
        responses = responses_for_run(1)
        filler: list[tuple[str, ...]] = [
            (
                "SEP",
                str(200000 + i),
                f"ZZ{i:05d}",
                "Synthetic",
                "NYSE",
                "N",
                "Domestic Common Stock",
                "",
                "",
                "2026-09-04",
                "2010-01-04",
                "2026-09-14",
            )
            for i in range(10_000)
        ]
        # A full page at the first offset is truncation uncertainty; a data-bearing page
        # at a later offset is the unsupported multi-page delivery, whatever it holds.
        responses[("tickers", "SNAPSHOT", 0)] = csv(TICKERS_HEADER, filler)
        report = _run_1_build(_store_with_run_1(responses))
        assert report.status is bp.BuildStatus.REFUSED_NORMALIZATION
        assert report.defect == sv.SilverDefect.DELIVERY_TRUNCATED.value
        responses = responses_for_run(1)
        responses[("tickers", "SNAPSHOT", 30000)] = csv(TICKERS_HEADER, filler)
        report = _run_1_build(_store_with_run_1(responses))
        assert report.status is bp.BuildStatus.REFUSED_NORMALIZATION
        assert report.defect == sv.SilverDefect.PAGINATION_UNSUPPORTED.value

    def test_stocks_without_a_same_run_snapshot_cannot_be_identified(self) -> None:
        store = FakeS3Store()
        slice_doc = {
            "acquisition_mode": "BACKFILL",
            "datasets": ["stocks"],
            "windows": {"stocks": "2026-09-01/2026-09-01"},
            "request_count": 2,
            "max_response_bytes": 4 * 1024 * 1024,
        }
        responses = {
            ("stocks", "2026-09-01/2026-09-01", 0): csv(
                STOCKS_HEADER, stocks_rows(date(2026, 9, 1), run=1)
            ),
            ("stocks", "2026-09-01/2026-09-01", 10000): csv(STOCKS_HEADER, []),
        }
        import fixtures.production_build as fixture

        original = fixture.slice_for_run
        fixture.slice_for_run = lambda run: slice_doc if run == 3 else original(run)
        try:
            acquire(store, run_id=RUN_1, run=3, at=RUN_1_AT, responses=responses)
            report = BuildScenario(store, runs=((RUN_1, 3, RUN_1_AT),)).run()
        finally:
            fixture.slice_for_run = original
        assert report.status is bp.BuildStatus.REFUSED_NORMALIZATION
        assert report.defect == sv.SilverDefect.IDENTITY_SNAPSHOT_MISSING.value

    def test_an_ambiguous_symbol_blocks_only_its_own_rows(self) -> None:
        store = populated_store(runs=(1,))
        report = _run_1_build(store)
        assert report.status is bp.BuildStatus.COMPLETED
        silver_stocks = artifact_rows(report, "silver-stocks")
        assert not any(
            row["security_id"] in {ZZEE_1.security_id, ZZEE_2.security_id} for row in silver_stocks
        )
        assert any(row["security_id"] == ZZAA.security_id for row in silver_stocks)
        manifest = manifest_of(store)
        finding = next(
            f
            for f in manifest["quality"]["findings"]
            if f["check"] == "IDENTITY_ONE_PERMATICKER_PER_SYMBOL"
        )
        assert finding["severity"] == "BLOCKING" and finding["count"] == 1
        assert manifest["identity"]["stocks"]["ambiguous_symbols"] == 1


# ---------------------------------------------------------------------------
# Universe: C-1, C-2, C-3, A-1, the cutoff boundary, and today's attributes
# ---------------------------------------------------------------------------


class TestUniverse:
    def test_c1_a_missing_session_d_bar_is_not_an_exclusion(self) -> None:
        store = populated_store(runs=(1,))  # no bar for 2026-09-14 exists anywhere
        report = _run_1_build(store)
        rows = memberships(report)
        assert rows[("2026-09-14", ZZAA.security_id)]["is_member"] is True
        assert not any(
            row["session_date"] == "2026-09-14"
            for row in artifact_rows(report, "gold-adjusted-bars")
        )

    def test_c2_a_bar_bounded_after_the_cutoff_is_history_it_cannot_see(self) -> None:
        rows = memberships(BuildScenario(populated_store()).run())
        assert rows[("2026-09-14", ZZBB.security_id)]["exclusion_reason"] == "HISTORY"
        assert rows[("2026-09-14", ZZBB.security_id)]["history_sessions_at_eval"] == 1
        assert rows[("2026-09-15", ZZBB.security_id)]["is_member"] is True

    def test_c3_a_delisting_dated_d_leaves_membership_d_unchanged(self) -> None:
        rows = memberships(BuildScenario(populated_store()).run())
        assert rows[("2026-09-14", ZZHH.security_id)]["is_member"] is True
        assert rows[("2026-09-15", ZZHH.security_id)]["exclusion_reason"] == "HISTORY"

    def test_a1_a_snapshot_first_seen_in_2026_cannot_decide_2019(self) -> None:
        store = populated_store()
        scenario = BuildScenario(store, config=configuration(sessions=(date(2019, 3, 5),)))
        report = scenario.run()
        assert report.status is bp.BuildStatus.COMPLETED, report.defect
        rows = memberships(report)
        assert {row["exclusion_reason"] for row in rows.values()} == {"ATTRIBUTE_UNAVAILABLE"}
        assert {row["exclusion_vocabulary"] for row in rows.values()} == {"proposed-adr-0039"}
        census = manifest_of(store)["census"]
        assert census == [
            {
                "session_date": "2019-03-05",
                "securities": 9,
                "attribute_determinable": 0,
                "attribute_unavailable": 9,
                "members": 0,
            }
        ]

    def test_the_decision_cutoff_is_inclusive_and_exact(self) -> None:
        from dataclasses import replace

        store = populated_store(runs=(1,))
        layer = normalized(store, ((RUN_1, 1, RUN_1_AT),))
        cal = calendar()
        resolved = av.resolve(layer, evidence=av.AvailabilityEvidence(version="e0"), calendar=cal)
        cutoff = cal.decision_time(date(2026, 9, 14), margin=rule().decision_margin)
        assert cutoff is not None

        def with_bound(bound: datetime) -> av.ResolvedLayer:
            stocks = tuple(
                replace(
                    row,
                    availability=replace(
                        row.availability,
                        provider_available_upper_bound=bound,
                        governing_time=bound,
                    ),
                )
                if row.row.row_key == (ZZAA.security_id, "2026-09-04")
                else row
                for row in resolved.stocks
            )
            return replace(resolved, stocks=stocks)

        def decide(bound: datetime) -> uv.MembershipRow:
            snapshot = uv.build_universe(
                with_bound(bound),
                rule=rule(),
                calendar=cal,
                sessions=(date(2026, 9, 14),),
                as_of=AS_OF,
            )
            return next(r for r in snapshot.rows if r.security_id == ZZAA.security_id)

        exactly = decide(cutoff)
        assert exactly.is_member and exactly.decision_time == cutoff
        one_second_late = decide(cutoff + timedelta(seconds=1))
        assert one_second_late.exclusion_reason is uv.BuildExclusionReason.HISTORY
        assert one_second_late.history_sessions_at_eval == 3

    def test_an_undecidable_session_is_recorded_not_guessed(self) -> None:
        store = populated_store(runs=(1,))
        cfg = configuration(
            sessions=(date(2026, 8, 24), date(2026, 9, 5), date(2026, 9, 14)),
            session_calendar=calendar(with_2019=False),
        )
        scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),), config=cfg)
        report = scenario.run()
        assert report.status is bp.BuildStatus.COMPLETED
        manifest = manifest_of(store)
        # 08-24 has no previous session; 09-05 is not a session.
        assert manifest["undecidable_sessions"] == ["2026-08-24", "2026-09-05"]
        assert [c["session_date"] for c in manifest["census"]] == ["2026-09-14"]

    def test_the_accepted_exclusion_vocabulary_is_neither_widened_nor_redefined(self) -> None:
        assert {m.value for m in UniverseExclusionReason} == {
            "PRICE",
            "MARKET_CAP",
            "ADDV",
            "HISTORY",
            "EXCHANGE",
            "SECURITY_TYPE",
        }
        assert {m.value for m in uv.ACCEPTED_EXCLUSIONS} == {
            m.value for m in UniverseExclusionReason
        }
        assert {m.value for m in uv.PROPOSED_EXCLUSIONS} == {
            "ATTRIBUTE_UNAVAILABLE",
            "UNRESOLVED_CORPORATE_ACTION",
        }
        assert {m.value for m in ProviderBoundDerivation} == {
            "FIRST_SEEN_UPPER_BOUND",
            "DELIVERY_WINDOW",
            "NONE",
        }


# ---------------------------------------------------------------------------
# Quality and Gold
# ---------------------------------------------------------------------------


class TestQualityAndGold:
    def test_the_plan_is_total_and_every_check_is_run_or_not_run(self) -> None:
        assert set(gd.QUALITY_PLAN) == set(gd.QualityCheck)
        store = populated_store()
        BuildScenario(store).run()
        quality = manifest_of(store)["quality"]
        assert set(quality["checks_run"]) | set(quality["checks_not_run"]) == {
            c.value for c in gd.QualityCheck
        }
        assert not set(quality["checks_run"]) & set(quality["checks_not_run"])
        assert "CROSS_PROVIDER" in quality["checks_not_run"]

    def test_adjustment_reconciliation_flags_a_vendor_series_that_is_not_proportional(self) -> None:
        responses = responses_for_run(1)
        rows = stocks_rows(date(2026, 9, 4), run=1)
        # ZZAA's vendor closeadj on 09-04 disagrees with the split-only reconstruction.
        broken = [(*row[:7], "9.00", *row[8:]) if row[0] == ZZAA.symbol else row for row in rows]
        responses[("stocks", "2026-09-04/2026-09-04", 0)] = csv(STOCKS_HEADER, broken)
        store = _store_with_run_1(responses)
        report = _run_1_build(store)
        assert report.status is bp.BuildStatus.COMPLETED
        findings = manifest_of(store)["quality"]["findings"]
        assert {
            "check": "ADJUSTMENT_RECONCILIATION",
            "severity": "WARNING",
            "scope": ZZAA.security_id,
            "count": 1,
            "effective_from": None,
        } in findings

    def test_market_data_findings_are_warnings_with_counts(self) -> None:
        responses = responses_for_run(1)
        rows = stocks_rows(date(2026, 9, 2), run=1)
        bad = []
        for row in rows:
            if row[0] == ZZGG.symbol:
                # high below close, and a negative volume
                bad.append((*row[:3], "1.00", row[4], row[5], "-5", *row[7:]))
            else:
                bad.append(row)
        responses[("stocks", "2026-09-02/2026-09-02", 0)] = csv(STOCKS_HEADER, bad)
        store = _store_with_run_1(responses)
        _run_1_build(store)
        findings = {(f["check"], f["scope"]): f for f in manifest_of(store)["quality"]["findings"]}
        assert findings[("MARKET_OHLC_CONSISTENT", ZZGG.security_id)]["count"] == 1
        assert findings[("MARKET_VOLUME_NON_NEGATIVE", ZZGG.security_id)]["count"] == 1
        assert findings[("MARKET_OHLC_CONSISTENT", ZZGG.security_id)]["severity"] == "WARNING"

    def test_a_bar_dated_on_or_after_t_blocks_its_security(self) -> None:
        store = FakeS3Store()
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)
        late = datetime(2026, 9, 14, 20, 0, tzinfo=UTC)
        acquire(store, run_id=RUN_2, run=2, at=late)
        cfg = configuration(
            as_of=datetime(2026, 9, 14, 22, 0, tzinfo=UTC), sessions=(date(2026, 9, 14),)
        )
        scenario = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT), (RUN_2, 2, late)), config=cfg)
        report = scenario.run()
        assert report.status is bp.BuildStatus.COMPLETED, report.defect
        bars = artifact_rows(report, "gold-adjusted-bars")
        served_ids = {row["security_id"] for row in bars}
        assert ZZAA.security_id not in served_ids and ZZHH.security_id in served_ids
        findings = {(f["check"], f["scope"]): f for f in manifest_of(store)["quality"]["findings"]}
        assert (
            findings[("TEMPORAL_NO_SESSION_AFTER_T_MINUS_1", ZZAA.security_id)]["severity"]
            == "BLOCKING"
        )
        assert ZZAA.security_id in manifest_of(store)["quality"]["restricted_securities"]
        # The membership decision stands as decided; the restriction sits beside it.
        assert any(
            row["security_id"] == ZZAA.security_id
            for row in artifact_rows(report, "gold-universe-membership")
        )
        restrictions = artifact_rows(report, "gold-eligibility-restrictions")
        affected = {
            r["security_id"]
            for r in restrictions
            if r["check"] == "TEMPORAL_NO_SESSION_AFTER_T_MINUS_1"
        }
        assert ZZAA.security_id in affected and ZZHH.security_id not in affected

    def test_a_valid_empty_result_is_stated_and_not_readiness(self) -> None:
        store = populated_store(runs=(1,))
        cfg = configuration(as_of=datetime(2026, 9, 1, tzinfo=UTC))
        report = BuildScenario(store, runs=((RUN_1, 1, RUN_1_AT),), config=cfg).run()
        assert report.status is bp.BuildStatus.COMPLETED
        assert report.empty_reason == "NO_ROW_VERSION_ADMISSIBLE_AT_AS_OF"
        assert artifact_rows(report, "gold-adjusted-bars") == []
        assert artifact_rows(report, "gold-corporate-actions") == []
        rows = memberships(report)
        assert rows and not any(row["is_member"] for row in rows.values())
        assert {row["exclusion_reason"] for row in rows.values()} == {"ATTRIBUTE_UNAVAILABLE"}
        manifest = manifest_of(store)
        assert manifest["empty_reason"] == "NO_ROW_VERSION_ADMISSIBLE_AT_AS_OF"
        served = {e["dataset"]: e for e in manifest["served"]}
        assert served["stocks"]["revisions_admitted"] == 0
        assert served["stocks"]["revisions_excluded_by_time"] > 0

    def test_a_build_scoped_blocking_finding_refuses_gold(self) -> None:
        store = populated_store(runs=(1,))
        layer = normalized(store, ((RUN_1, 1, RUN_1_AT),))
        resolved = av.resolve(
            layer, evidence=av.AvailabilityEvidence(version="e0"), calendar=calendar()
        )
        snapshot = uv.build_universe(
            resolved, rule=rule(), calendar=calendar(), sessions=(date(2026, 9, 14),), as_of=AS_OF
        )
        # A membership row claiming to have consumed session d's bar is the look-ahead
        # the plan forbids; it is refused rather than published.
        forged = uv.MembershipRow(
            session_date=date(2026, 9, 14),
            security_id=ZZAA.security_id,
            decision_time=snapshot.rows[0].decision_time,
            is_member=True,
            exclusion_reason=None,
            price_at_eval=None,
            addv_at_eval=None,
            history_sessions_at_eval=4,
            attribute_revision=None,
            bars_consumed=("2026-09-14:" + "0" * 64,),
        )
        tampered = uv.UniverseSnapshot(
            rule=snapshot.rule,
            rows=(*snapshot.rows, forged),
            census=snapshot.census,
            undecidable_sessions=(),
        )
        with pytest.raises(gd.GoldError) as refused:
            gd.build_gold(
                resolved, universe=tampered, calendar=calendar(), as_of=AS_OF, identity_blocking=0
            )
        assert refused.value.defect is gd.GoldDefect.REFUSED_QUALITY

    def test_no_strategy_signal_order_or_backtest_exists_in_the_build(self) -> None:
        import pathlib

        for module in (
            "build_processing",
            "gold",
            "universe",
            "silver",
            "availability",
            "build_manifest",
        ):
            text = pathlib.Path(bp.__file__).with_name(f"{module}.py").read_text(encoding="utf-8")
            body = text.split('"""', 2)[2]  # skip the module docstring
            for forbidden in (
                "submit_order",
                "position_size",
                "backtest(",
                "signal(",
                "BrokerAdapter",
            ):
                assert forbidden not in body, (module, forbidden)


# ---------------------------------------------------------------------------
# Publication, replay and conflicts
# ---------------------------------------------------------------------------


class TestPublication:
    def test_a_deterministic_replay_yields_identical_bytes_and_run_id(self) -> None:
        store = populated_store()
        first = BuildScenario(store).run()
        second = BuildScenario(store, build_id="synthetic-production-build-0002").run()
        assert first.status is second.status is bp.BuildStatus.COMPLETED
        assert first.publication is not None and second.publication is not None
        assert [a.artifact.sha256 for a in first.publication.artifacts] == [
            a.artifact.sha256 for a in second.publication.artifacts
        ]
        assert first.publication.run_id == second.publication.run_id
        assert second.artifacts_already_present == 7 and second.artifacts_written == 0
        assert second.manifest is bm.ManifestDisposition.PUBLISHED
        manifests = [json.loads(store.objects[k]) for k in store.keys_under(MANIFEST_PREFIX)]
        assert len(manifests) == 2
        differing = {k for k in manifests[0] if manifests[0][k] != manifests[1][k]}
        assert differing <= {"build_id", "completed_at", "outputs"}
        assert manifests[0]["run_id"] == manifests[1]["run_id"]

    def test_a_changed_configuration_changes_the_run_id(self) -> None:
        store = populated_store()
        first = BuildScenario(store).run()
        changed = configuration(
            universe_rule=uv.UniverseRule(
                history_sessions=2,
                addv_window_sessions=2,
                price_floor=Decimal("5"),
                addv_floor=Decimal("1000000"),
            )
        )
        second = BuildScenario(
            store, build_id="synthetic-production-build-0002", config=changed
        ).run()
        assert first.publication is not None and second.publication is not None
        assert first.publication.run_id != second.publication.run_id

    def test_a_spent_build_identity_is_refused_at_the_manifest_never_adopted(self) -> None:
        store = populated_store()
        BuildScenario(store).run()
        scenario = BuildScenario(store)
        report = scenario.run()
        assert report.status is bp.BuildStatus.MANIFEST_NAME_OCCUPIED
        assert report.artifacts_already_present == 7 and not report.publication_state_unknown
        assert report.manifest is bm.ManifestDisposition.NAME_OCCUPIED
        assert len(store.keys_under(MANIFEST_PREFIX)) == 1
        _assert_accounting(scenario, report)

    def test_a_partial_publication_is_preserved_and_publishes_no_manifest(self) -> None:
        store = populated_store()
        store.fail_put_after = len(store.puts) + 3
        store.fail_put_code = "AccessDenied"
        scenario = BuildScenario(store)
        report = scenario.run()
        assert report.status is bp.BuildStatus.HALTED
        assert report.defect == bm.PublicationHalt.PUBLICATION_REFUSED.value
        assert report.artifacts_written == 3 and not report.publication_state_unknown
        assert report.manifest is bm.ManifestDisposition.NOT_ATTEMPTED
        assert store.keys_under(MANIFEST_PREFIX) == []
        assert scenario.data_plane_calls()[1] == 4  # three confirmed, one refused, nothing retried
        _assert_accounting(scenario, report)

    def test_an_ambiguous_artifact_write_is_uncertain_state_with_no_manifest(self) -> None:
        store = populated_store()
        store.fail_put_after = len(store.puts) + 5
        scenario = BuildScenario(store)
        report = scenario.run()
        assert report.status is bp.BuildStatus.HALTED
        assert report.defect == bm.PublicationHalt.PUBLICATION_STATE_UNKNOWN.value
        assert report.publication_state_unknown is True
        assert report.manifest is bm.ManifestDisposition.NOT_ATTEMPTED
        assert store.keys_under(MANIFEST_PREFIX) == []

    def test_an_ambiguous_manifest_write_is_reported_as_unknown_never_as_success(self) -> None:
        store = populated_store()
        store.fail_put_after = len(store.puts) + 7
        report = BuildScenario(store).run()
        assert report.status is bp.BuildStatus.MANIFEST_STATE_UNKNOWN
        assert report.publication_state_unknown is True
        assert report.artifacts_written == 7
        store2 = populated_store()
        store2.fail_put_after = len(store2.puts) + 7
        store2.fail_put_code = "AccessDenied"
        report2 = BuildScenario(store2).run()
        assert report2.status is bp.BuildStatus.MANIFEST_REFUSED
        assert report2.publication_state_unknown is False

    def test_the_deadline_halts_publication_with_the_state_known(self) -> None:
        store = populated_store()
        scenario = BuildScenario(store)
        original = store.put_object

        def slow_put(**kwargs: Any) -> Any:
            scenario.clock.seconds += 3000.0
            return original(**kwargs)

        store.put_object = slow_put  # type: ignore[method-assign]
        report = scenario.run()
        assert report.status is bp.BuildStatus.HALTED
        assert report.defect == bm.PublicationHalt.DEADLINE_EXHAUSTED.value
        assert not report.publication_state_unknown
        assert report.manifest is bm.ManifestDisposition.NOT_ATTEMPTED

    def test_a_report_cannot_claim_completion_without_a_published_manifest(self) -> None:
        report = BuildScenario(populated_store()).run()
        from dataclasses import replace

        with pytest.raises(ValueError):
            replace(report, manifest=bm.ManifestDisposition.NOT_ATTEMPTED)
        with pytest.raises(ValueError):
            replace(report, publication_state_unknown=True)
        with pytest.raises(ValueError):
            replace(report, status=bp.BuildStatus.HALTED)


# ---------------------------------------------------------------------------
# Bootstrap refusals and unchanged behaviour
# ---------------------------------------------------------------------------


class TestBootstrapAndCompatibility:
    def test_no_release_means_no_data_plane_operation(self) -> None:
        store = populated_store()
        scenario = BuildScenario(store, release=False)
        report = scenario.run()
        assert report.status is bp.BuildStatus.REFUSED_BOOTSTRAP
        assert report.counts.data_plane_operations == 0
        assert scenario.data_plane_calls() == (0, 0)

    def test_the_bootstrap_only_build_task_still_halts(self) -> None:
        from fixtures.production_runtime import (
            caller_identity,
            compiled_task,
            metadata_document,
            task_identity_arn,
        )
        from kalpamani.data.production.sharadar.identities import LedgerSpentIdentities
        from kalpamani.data.production.sharadar.parameters import SsmParameterAdapter
        from kalpamani.data.production.sharadar.runner import RunnerAdapters, run_build_task
        from kalpamani.data.production.sharadar.vocabulary import ProductionActor

        scenario = BuildScenario(populated_store())
        report = run_build_task(
            compiled=compiled_task(ProductionActor.BUILD),
            adapters=RunnerAdapters(
                environment_names=lambda: ["PATH", "ECS_CONTAINER_METADATA_URI_V4"],
                parameters=SsmParameterAdapter(ssm=scenario.ssm),
                metadata=lambda: metadata_document(ProductionActor.BUILD),
                caller_identity=lambda: caller_identity(task_identity_arn(ProductionActor.BUILD)),
                now=scenario.clock.now,
                monotonic=scenario.clock.monotonic,
                sleep=scenario.clock.sleep,
            ),
            registry=LedgerSpentIdentities([]),
        )
        assert report.outcome is RunnerOutcome.HALTED_PROCESSING_NOT_IMPLEMENTED
        assert report.counts.data_plane_operations == 0

    def test_the_acquisition_that_populates_the_store_is_the_accepted_one(self) -> None:
        store = FakeS3Store()
        report = acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)
        assert report.counts.provider_requests == 16
        assert report.counts.s3_operations == 1 + 3 * 16 + 1
        assert report.reservation is PayloadDisposition.WRITTEN
        assert set(slice_for_run(1)["datasets"]) == {"actions", "stocks", "tickers"}
        assert len(tickers_rows(lastupdated="2026-09-04")) == 9
        assert ShiftedClock(base=RUN_1_AT).now() == RUN_1_AT
        assert ZZEE_1.symbol == ZZEE_2.symbol
