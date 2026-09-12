"""PR #97 correction cycle: revision chronology, action selection, adjustment lineage and
membership preservation -- on synthetic stores written by the real acquisition path.

Every count is what an injected fake was asked; mocked results are not AWS verification.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
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
    ZZHH,
    BuildScenario,
    FakeS3Store,
    acquire,
    actions_rows,
    calendar,
    configuration,
    csv,
    ledger_row,
    responses_for_run,
    slice_with_stocks_window,
    stocks_rows,
    tickers_rows,
)
from fixtures.production_runtime import BUCKET, build_input_document
from kalpamani.data.contracts.vocabulary import ProviderBoundDerivation
from kalpamani.data.production.sharadar import availability as av
from kalpamani.data.production.sharadar import build_inputs as bi
from kalpamani.data.production.sharadar import build_processing as bp
from kalpamani.data.production.sharadar import gold as gd
from kalpamani.data.production.sharadar import silver as sv
from kalpamani.data.production.sharadar import universe as uv
from kalpamani.data.production.sharadar.inputs import ledger_digest, parse_build_input
from kalpamani.data.production.sharadar.locator import ProductionLocatorReader

pytestmark = pytest.mark.unit

RUN_3: Final = "synthetic-build-source-run-0003"
RUN_3_AT: Final = datetime(2026, 9, 25, 2, 0, tzinfo=UTC)
KEY_0901: Final = (ZZAA.security_id, "2026-09-01")
WIDE: Final = slice_with_stocks_window(2, "2026-09-01/2026-09-14")
SPLIT_KEY: Final = (ZZAA.security_id, "2026-09-03", "split")

Runs = tuple[tuple[str, int, datetime], ...]


def with_close(
    rows: list[tuple[str, ...]], symbol: str, close: str, adj: str
) -> list[tuple[str, ...]]:
    return [
        (*row[:5], close, row[6], adj, close, row[9]) if row[0] == symbol else row for row in rows
    ]


def with_split_value(rows: list[tuple[str, ...]], value: str) -> list[tuple[str, ...]]:
    return [(*r[:4], value, *r[5:]) if r[1] == "split" else r for r in rows]


def artifact(report: bp.BuildReport, name: str) -> list[dict[str, Any]]:
    assert report.publication is not None
    for item in report.publication.artifacts:
        if item.artifact.name == name:
            rows: list[dict[str, Any]] = json.loads(item.artifact.content)["rows"]
            return rows
    raise AssertionError(name)


def manifest_of(store: FakeS3Store, build_id: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(
        store.objects[f"manifests/sharadar/builds/{build_id}.json"]
    )
    return document


def build(
    store: FakeS3Store,
    runs: Runs,
    *,
    as_of: datetime,
    build_id: str,
    slices: dict[str, dict[str, Any]] | None = None,
    sessions: tuple[date, ...] = (date(2026, 9, 14), date(2026, 9, 15)),
) -> bp.BuildReport:
    scenario = BuildScenario(
        store,
        runs=runs,
        config=configuration(as_of=as_of, sessions=sessions),
        build_id=build_id,
        slices=slices,
    )
    report = scenario.run()
    assert report.status is bp.BuildStatus.COMPLETED, (report.status, report.defect)
    return report


def resolved_layer(
    store: FakeS3Store,
    runs: Runs,
    *,
    slices: dict[str, dict[str, Any]] | None = None,
    evidence: av.AvailabilityEvidence | None = None,
    now: datetime = AS_OF,
) -> av.ResolvedLayer:
    rows = [ledger_row(run_id, run, at, (slices or {}).get(run_id)) for run_id, run, at in runs]
    admitted = parse_build_input(
        build_input_document(
            rows,
            ledger_digest=ledger_digest(rows),
            issued_at=(now - timedelta(hours=1)).isoformat(),
            expires_at=(now + timedelta(hours=1)).isoformat(),
        ),
        now=now,
    )
    reader = ProductionLocatorReader(client=store, licensed_bucket=BUCKET)
    layer = sv.normalize(bi.verify_build_inputs(admitted, reader=reader), schemas=SCHEMAS)
    return av.resolve(
        layer,
        evidence=av.AvailabilityEvidence(version="e0") if evidence is None else evidence,
        calendar=calendar(),
    )


def revisions_of(
    resolved: av.ResolvedLayer, dataset: str, key: tuple[str, ...]
) -> list[av.ResolvedRow]:
    return sorted(
        (row for row in resolved.by_dataset(dataset) if row.row.row_key == key),
        key=lambda row: row.row.revision_sequence,
    )


# ---------------------------------------------------------------------------
# Finding 2: A -> B -> A chronology
# ---------------------------------------------------------------------------


def aba_store() -> tuple[FakeS3Store, Runs, dict[str, dict[str, Any]]]:
    """(ZZAA, 2026-09-01): A in run 1, B in run 2, A again in run 3 (runs 2/3, wide window)."""
    store = FakeS3Store()
    acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)  # A: close 20.40
    r2 = responses_for_run(2, WIDE)
    r2[("stocks", "2026-09-01/2026-09-01", 0)] = csv(
        STOCKS_HEADER,
        with_close(stocks_rows(date(2026, 9, 1), run=2), ZZAA.symbol, "20.41", "10.205"),
    )
    acquire(store, run_id=RUN_2, run=2, at=RUN_2_AT, responses=r2, slice_doc=WIDE)  # B
    r3 = responses_for_run(2, WIDE)
    r3[("stocks", "2026-09-01/2026-09-01", 0)] = csv(
        STOCKS_HEADER,
        with_close(stocks_rows(date(2026, 9, 1), run=2), ZZAA.symbol, "20.40", "10.20"),
    )
    acquire(store, run_id=RUN_3, run=2, at=RUN_3_AT, responses=r3, slice_doc=WIDE)  # A again
    runs: Runs = ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT), (RUN_3, 2, RUN_3_AT))
    return store, runs, {RUN_2: WIDE, RUN_3: WIDE}


class TestRevisionChronology:
    def test_a_return_to_earlier_content_is_a_new_revision_current_after_its_own_observation(
        self,
    ) -> None:
        store, runs, slices = aba_store()
        resolved = resolved_layer(store, runs, slices=slices)
        a1, b, a2 = revisions_of(resolved, "stocks", KEY_0901)
        assert [r.row.fields["close"] for r in (a1, b, a2)] == ["20.40", "20.41", "20.40"]
        assert [r.row.revision_sequence for r in (a1, b, a2)] == [0, 1, 2]
        # Content identity and chronology are kept apart.
        assert a1.row.content_sha256 == a2.row.content_sha256 != b.row.content_sha256
        assert a2.row.is_return and not a1.row.is_return and not b.row.is_return
        assert a2.row.content_first_seen_time == a1.row.system_first_seen_time
        assert a2.row.system_first_seen_time > b.row.system_first_seen_time
        assert a2.availability.provider_available_upper_bound == a2.row.system_first_seen_time
        # Selection at each cutoff: A, B, A.
        expected = {
            datetime(2026, 9, 10, tzinfo=UTC): 0,
            datetime(2026, 9, 20, tzinfo=UTC): 1,
            datetime(2026, 9, 30, tzinfo=UTC): 2,
        }
        for cutoff, sequence in expected.items():
            chosen = av.select_current(resolved.stocks, cutoff=cutoff)[KEY_0901]
            assert chosen.row.revision_sequence == sequence, cutoff

    def test_end_to_end_builds_serve_a_then_b_then_a_and_replay_deterministically(self) -> None:
        store, runs, slices = aba_store()
        served: dict[str, tuple[int, str]] = {}
        run_ids: dict[str, str] = {}
        for label, as_of in (
            ("t1", datetime(2026, 9, 10, tzinfo=UTC)),
            ("t2", datetime(2026, 9, 20, tzinfo=UTC)),
            ("t3", datetime(2026, 9, 30, tzinfo=UTC)),
        ):
            report = build(
                store, runs, as_of=as_of, build_id=f"synthetic-build-aba-{label}", slices=slices
            )
            row = next(
                r for r in artifact(report, "silver-stocks") if r["row_key"] == list(KEY_0901)
            )
            served[label] = (row["revision_sequence"], row["fields"]["close"])
            assert report.publication is not None and report.publication.run_id is not None
            run_ids[label] = report.publication.run_id
        assert served == {"t1": (0, "20.40"), "t2": (1, "20.41"), "t3": (2, "20.40")}
        # Deterministic replay of the t3 build under another identity.
        again = build(
            store,
            runs,
            as_of=datetime(2026, 9, 30, tzinfo=UTC),
            build_id="synthetic-build-aba-t3b",
            slices=slices,
        )
        assert again.publication is not None and again.publication.run_id == run_ids["t3"]
        assert again.artifacts_already_present == 7

    def test_a_returning_observation_does_not_rewrite_what_was_selected_earlier(self) -> None:
        """The t2 build over three runs equals the t2 build over two runs, byte for byte."""
        store, runs, slices = aba_store()
        as_of = datetime(2026, 9, 20, tzinfo=UTC)
        three = build(store, runs, as_of=as_of, build_id="synthetic-build-three", slices=slices)
        two = build(store, runs[:2], as_of=as_of, build_id="synthetic-build-two", slices=slices)
        assert three.publication is not None and two.publication is not None
        assert [a.artifact.sha256 for a in three.publication.artifacts] == [
            a.artifact.sha256 for a in two.publication.artifacts
        ]
        # The run_id legitimately differs: it covers the Bronze set consumed, and the
        # three-run input consumed run 3's bytes even though nothing from them served.
        assert three.publication.run_id != two.publication.run_id
        # And the earlier as_of build over three runs records nothing observed after it.
        row = next(r for r in artifact(three, "silver-stocks") if r["row_key"] == list(KEY_0901))
        assert all(when <= as_of.isoformat() for when in row["observed_at"])

    def test_consecutive_unchanged_deliveries_extend_the_revision_and_create_no_change(
        self,
    ) -> None:
        store, runs, slices = aba_store()
        resolved = resolved_layer(store, runs, slices=slices)
        (only,) = revisions_of(resolved, "stocks", (ZZAA.security_id, "2026-09-04"))
        # Delivered by runs 1, 2 and 3 with identical bytes: one revision, three sightings.
        assert only.row.observation_count == 3 and only.row.revision_sequence == 0
        assert only.row.observed_at == tuple(sorted(only.row.observed_at))
        assert only.row.system_first_seen_time == only.row.observed_at[0]
        assert (
            only.row.observations_through(datetime(2026, 9, 10, tzinfo=UTC))
            == only.row.observed_at[:1]
        )

    def test_content_evidence_bounds_the_first_revision_and_never_a_return(self) -> None:
        store, runs, slices = aba_store()
        plain = resolved_layer(store, runs, slices=slices)
        a1, _, _ = revisions_of(plain, "stocks", KEY_0901)
        record = av.VersionEvidence(
            kind=av.EvidenceKind.PER_VERSION_DELIVERY,
            dataset="stocks",
            row_key=KEY_0901,
            content_sha256=a1.row.content_sha256,
            instant=datetime(2026, 9, 2, 4, 30, tzinfo=UTC),
            evidence_digest="cd" * 32,
        )
        resolved = resolved_layer(
            store,
            runs,
            slices=slices,
            evidence=av.AvailabilityEvidence(version="e-a", items=(record,)),
        )
        w1, w2, w3 = revisions_of(resolved, "stocks", KEY_0901)
        assert w1.availability.provider_bound_derivation is ProviderBoundDerivation.DELIVERY_WINDOW
        assert w1.availability.provider_available_upper_bound == record.instant
        # The same content returning at t3 is P-2 at t3: the evidence says nothing about
        # when the content became current again.
        assert w3.row.content_sha256 == w1.row.content_sha256
        assert (
            w3.availability.provider_bound_derivation
            is ProviderBoundDerivation.FIRST_SEEN_UPPER_BOUND
        )
        assert w3.availability.provider_available_upper_bound == w3.row.system_first_seen_time
        assert w2.availability.rule is av.AvailabilityRule.P2_FIRST_SEEN

    def test_a_same_run_contradiction_is_refused_even_when_the_content_returns(self) -> None:
        store = FakeS3Store()
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)
        r2 = responses_for_run(2, WIDE)
        rows = stocks_rows(date(2026, 9, 1), run=2)
        b_row = with_close(rows, ZZAA.symbol, "20.41", "10.205")[0]
        a_row = with_close(rows, ZZAA.symbol, "20.40", "10.20")[0]
        r2[("stocks", "2026-09-01/2026-09-01", 0)] = csv(STOCKS_HEADER, [*rows[1:], b_row, a_row])
        acquire(store, run_id=RUN_2, run=2, at=RUN_2_AT, responses=r2, slice_doc=WIDE)
        scenario = BuildScenario(
            store, runs=((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT)), slices={RUN_2: WIDE}
        )
        report = scenario.run()
        assert report.status is bp.BuildStatus.REFUSED_NORMALIZATION
        assert report.defect == sv.SilverDefect.ROW_CONFLICT_IN_RUN.value

    def test_attribute_and_action_chronology_return_and_membership_follows_the_cutoff(self) -> None:
        """tickers: ZZAA exchange NYSE -> OTC -> NYSE; actions: split value 2 -> 3 -> 2."""
        store = FakeS3Store()
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)
        r2 = responses_for_run(2)
        otc = [
            (*r[:4], "OTC", *r[5:]) if r[2] == ZZAA.symbol else r
            for r in tickers_rows(lastupdated="2026-09-14")
        ]
        r2[("tickers", "SNAPSHOT", 0)] = csv(TICKERS_HEADER, otc)
        r2[("actions", "2026-08-01/2026-09-14", 0)] = csv(
            ACTIONS_HEADER, with_split_value(actions_rows(run=2), "3")
        )
        acquire(store, run_id=RUN_2, run=2, at=RUN_2_AT, responses=r2)
        r3 = responses_for_run(2)
        r3[("tickers", "SNAPSHOT", 0)] = csv(TICKERS_HEADER, tickers_rows(lastupdated="2026-09-04"))
        r3[("actions", "2026-08-01/2026-09-14", 0)] = csv(
            ACTIONS_HEADER, with_split_value(actions_rows(run=2), "2")
        )
        acquire(store, run_id=RUN_3, run=2, at=RUN_3_AT, responses=r3)
        runs: Runs = ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT), (RUN_3, 2, RUN_3_AT))
        resolved = resolved_layer(store, runs)
        attributes = revisions_of(resolved, "tickers", (ZZAA.security_id,))
        assert [a.row.fields["exchange"] for a in attributes] == ["NYSE", "OTC", "NYSE"]
        assert attributes[2].row.is_return
        splits = revisions_of(resolved, "actions", SPLIT_KEY)
        assert [s.row.fields["value"] for s in splits] == ["2", "3", "2"] and splits[
            2
        ].row.is_return
        # Membership at a cutoff between run 2 and run 3 sees OTC; after run 3, NYSE again.
        sessions = (date(2026, 9, 15),)
        between = uv.build_universe(
            resolved,
            rule=configuration().rule,
            calendar=calendar(),
            sessions=sessions,
            as_of=datetime(2026, 9, 20, tzinfo=UTC),
        )
        after = uv.build_universe(
            resolved,
            rule=configuration().rule,
            calendar=calendar(),
            sessions=sessions,
            as_of=datetime(2026, 9, 30, tzinfo=UTC),
        )
        row_between = next(r for r in between.rows if r.security_id == ZZAA.security_id)
        row_after = next(r for r in after.rows if r.security_id == ZZAA.security_id)
        # decision_time(09-15) = 09-15T13:00Z lies between run 2 (09-15T02:00Z) and run 3.
        assert row_between.exclusion_reason is uv.BuildExclusionReason.EXCHANGE
        assert row_after.exclusion_reason is uv.BuildExclusionReason.EXCHANGE
        assert row_between.attribute_revision == attributes[1].row.content_sha256
        # The split factor follows the chronology too: 2, 3, 2.
        factors = []
        for as_of in (
            datetime(2026, 9, 10, tzinfo=UTC),
            datetime(2026, 9, 20, tzinfo=UTC),
            datetime(2026, 9, 30, tzinfo=UTC),
        ):
            actions = list(av.select_current(resolved.actions, cutoff=as_of).values())
            bar = av.select_current(resolved.stocks, cutoff=as_of)[(ZZAA.security_id, "2026-09-03")]
            adjusted = gd.adjust_bar(
                bar, [a for a in actions if a.row.security_id == ZZAA.security_id], as_of=as_of
            )
            assert adjusted is not None
            factors.append(adjusted["factor"])
        assert factors == ["2", "3", "2"]


# ---------------------------------------------------------------------------
# Finding 3: action revision selection and key-field corrections
# ---------------------------------------------------------------------------


class TestActionRevisionSelection:
    def test_a_same_key_revision_supersedes_and_earlier_cutoffs_keep_the_earlier_one(self) -> None:
        store = FakeS3Store()
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)  # split value 2
        r2 = responses_for_run(2)
        r2[("actions", "2026-08-01/2026-09-14", 0)] = csv(
            ACTIONS_HEADER, with_split_value(actions_rows(run=2), "3")
        )
        acquire(store, run_id=RUN_2, run=2, at=RUN_2_AT, responses=r2)
        runs: Runs = ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT))
        resolved = resolved_layer(store, runs)
        v1, v2 = revisions_of(resolved, "actions", SPLIT_KEY)
        early = av.select_current(resolved.actions, cutoff=datetime(2026, 9, 10, tzinfo=UTC))
        late = av.select_current(resolved.actions, cutoff=datetime(2026, 9, 20, tzinfo=UTC))
        assert early[SPLIT_KEY] is v1 and late[SPLIT_KEY] is v2
        # Never both operative: one lineage entry for the split, at either cutoff.
        for as_of, factor, revision in (
            (datetime(2026, 9, 10, tzinfo=UTC), "2", 0),
            (datetime(2026, 9, 20, tzinfo=UTC), "3", 1),
        ):
            bar = av.select_current(resolved.stocks, cutoff=as_of)[(ZZAA.security_id, "2026-09-03")]
            actions = [
                a
                for a in av.select_current(resolved.actions, cutoff=as_of).values()
                if a.row.security_id == ZZAA.security_id
            ]
            adjusted = gd.adjust_bar(bar, actions, as_of=as_of)
            assert adjusted is not None and adjusted["factor"] == factor
            split_refs = [ref for ref in adjusted["lineage"] if ref["entity"] == "corporate_action"]
            assert len(split_refs) == 1 and split_refs[0]["selector"]["revision_sequence"] == str(
                revision
            )
        # Membership consumes one revision of a delisting, the one current at the cutoff.
        facts = uv._index(resolved)[ZZHH.security_id]
        current = uv._admissible_actions(
            facts.actions, cutoff=datetime(2026, 9, 20, tzinfo=UTC), action="delisted"
        )
        assert [(when.isoformat(), row.row.revision_sequence) for when, row in current] == [
            ("2026-09-14", 0)
        ]

    def test_a_key_field_correction_is_a_distinct_event_with_a_recorded_gap_not_a_deletion(
        self,
    ) -> None:
        """Run 2 delivers the split dated 09-02 instead of 09-03 and ZZHH's delisting dated
        09-15 instead of 09-14; the original keys are not re-delivered."""
        store = FakeS3Store()
        r1 = responses_for_run(1)
        r1[("actions", "2026-08-01/2026-09-14", 0)] = csv(ACTIONS_HEADER, actions_rows(run=2))
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=r1)  # delisting dated 09-14
        r2 = responses_for_run(2)
        rows = [("2026-09-02", *r[1:]) if r[1] == "split" else r for r in actions_rows(run=2)]
        rows = [("2026-09-15", *r[1:]) if r[1] == "delisted" else r for r in rows]
        r2[("actions", "2026-08-01/2026-09-14", 0)] = csv(ACTIONS_HEADER, rows)
        acquire(store, run_id=RUN_2, run=2, at=RUN_2_AT, responses=r2)
        runs: Runs = ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT))
        resolved = resolved_layer(store, runs)
        (original,) = revisions_of(resolved, "actions", SPLIT_KEY)
        (corrected,) = revisions_of(resolved, "actions", (ZZAA.security_id, "2026-09-02", "split"))
        # Two keys, both current: the source has no event identity. The original carries
        # the gap naming the run that covered its date and did not repeat it.
        assert (
            original.row.gaps_through(AS_OF) == (RUN_2,) and corrected.row.gaps_through(AS_OF) == ()
        )
        assert original.row.gaps_through(datetime(2026, 9, 10, tzinfo=UTC)) == ()
        report = build(store, runs, as_of=AS_OF, build_id="synthetic-build-keyfix")
        bars = {
            r["session_date"]: r
            for r in artifact(report, "gold-adjusted-bars")
            if r["security_id"] == ZZAA.security_id
        }
        # 09-02 consumes only the corrected key; 09-03 onward would consume the gapped
        # original as well, and is withheld rather than published on it.
        assert (
            bars["2026-09-02"]["factor"] == "2"
            and "2026-09-03" not in bars
            and "2026-09-04" not in bars
        )
        manifest = manifest_of(store, "synthetic-build-keyfix")
        unresolved = manifest["unresolved_contracts"]["action-event-identity"]
        assert unresolved["action_keys_with_redelivery_gaps"] == 2  # the split and the delisting
        assert unresolved["adjusted_rows_withheld"] == 3  # 09-03, 09-04, 09-14
        findings = {(f["check"], f["scope"]): f for f in manifest["quality"]["findings"]}
        assert (
            findings[("IDENTITY_ACTION_NOT_REDELIVERED", ZZAA.security_id)]["severity"] == "WARNING"
        )
        actions = {tuple(a["row_key"]): a for a in artifact(report, "gold-corporate-actions")}
        assert actions[SPLIT_KEY]["redelivery_gaps"] == [RUN_2]
        # Historical membership: 09-14 decided before run 2 existed is unchanged by the
        # correction; 09-15 consumes both delisting keys (conservatively excluded) and
        # records exactly what it consumed.
        rows_m = {
            (r["session_date"], r["security_id"]): r
            for r in artifact(report, "gold-universe-membership")
        }
        assert rows_m[("2026-09-14", ZZHH.security_id)]["is_member"] is True
        assert rows_m[("2026-09-15", ZZHH.security_id)]["exclusion_reason"] == "HISTORY"
        consumed = rows_m[("2026-09-15", ZZHH.security_id)]["actions_consumed"]
        # At decision_time(09-15) = 13:00Z the corrected key (public by the 09-15 open,
        # 13:30Z) is not yet admissible; the original, gap-flagged key is, and it is
        # what the clause consumed -- recorded exactly.
        assert {c.rsplit("#", 2)[0] for c in consumed} == {
            f"{ZZHH.security_id}/2026-09-14/delisted"
        }
        baseline = build(store, runs[:1], as_of=AS_OF, build_id="synthetic-build-keyfix-base")
        base_rows = {
            (r["session_date"], r["security_id"]): r
            for r in artifact(baseline, "gold-universe-membership")
        }
        for key in (("2026-09-14", ZZAA.security_id), ("2026-09-14", ZZHH.security_id)):
            assert base_rows[key]["is_member"] == rows_m[key]["is_member"]
            assert base_rows[key]["bars_consumed"] == rows_m[key]["bars_consumed"]


# ---------------------------------------------------------------------------
# Finding 4: adjustment lineage and derived availability
# ---------------------------------------------------------------------------


def lineage_store() -> tuple[FakeS3Store, Runs]:
    """Bars at t1 with no split; the split (value 2) at t2; a correction (value 3) at t3."""
    store = FakeS3Store()
    r1 = responses_for_run(1)
    r1[("actions", "2026-08-01/2026-09-14", 0)] = csv(
        ACTIONS_HEADER, [r for r in actions_rows(run=1) if r[1] != "split"]
    )
    acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT, responses=r1)
    acquire(store, run_id=RUN_2, run=2, at=RUN_2_AT)
    r3 = responses_for_run(2)
    r3[("actions", "2026-08-01/2026-09-14", 0)] = csv(
        ACTIONS_HEADER, with_split_value(actions_rows(run=2), "3")
    )
    acquire(store, run_id=RUN_3, run=2, at=RUN_3_AT, responses=r3)
    return store, ((RUN_1, 1, RUN_1_AT), (RUN_2, 2, RUN_2_AT), (RUN_3, 2, RUN_3_AT))


class TestAdjustmentLineage:
    @pytest.mark.parametrize(
        ("as_of", "factor", "derived_after_source", "action_revisions"),
        [
            (datetime(2026, 9, 10, tzinfo=UTC), "1", False, []),
            (datetime(2026, 9, 20, tzinfo=UTC), "2", True, ["0"]),
            (datetime(2026, 9, 30, tzinfo=UTC), "3", True, ["1"]),
        ],
    )
    def test_derived_availability_follows_every_consumed_input(
        self, as_of: datetime, factor: str, derived_after_source: bool, action_revisions: list[str]
    ) -> None:
        store, runs = lineage_store()
        report = build(store, runs, as_of=as_of, build_id=f"synthetic-build-lin-{as_of.day}")
        row = next(
            r
            for r in artifact(report, "gold-adjusted-bars")
            if r["security_id"] == ZZAA.security_id and r["session_date"] == "2026-09-03"
        )
        assert (
            row["factor"] == factor
            and row["derivation_version"] == gd.ADJUSTMENT_DERIVATION_VERSION
        )
        assert row["source_governing_time"] < RUN_2_AT.isoformat()
        assert (
            row["derived_governing_time"] > row["source_governing_time"]
        ) is derived_after_source
        assert [
            ref["selector"]["revision_sequence"] for ref in row["lineage"][1:]
        ] == action_revisions
        assert row["lineage"][0]["entity"] == "price_bar"
        assert row["lineage"][0]["selector"]["content_sha256"] == row["source_content_sha256"]
        # The derived time is exactly the latest consumed input's governing time.
        resolved = resolved_layer(store, runs, now=as_of)
        consumed_times = [
            av.select_current(resolved.stocks, cutoff=as_of)[
                (ZZAA.security_id, "2026-09-03")
            ].availability.governing_time
        ]
        for ref in row["lineage"][1:]:
            action = av.select_current(resolved.actions, cutoff=as_of)[
                tuple(ref["selector"]["row_key"].split("/"))
            ]
            consumed_times.append(action.availability.governing_time)
        assert row["derived_governing_time"] == max(consumed_times).isoformat()
        # A bar before the ex-date consumes no action: derived == source, no action lineage.
        before = next(
            r
            for r in artifact(report, "gold-adjusted-bars")
            if r["security_id"] == ZZAA.security_id and r["session_date"] == "2026-09-01"
        )
        assert before["derived_governing_time"] == before["source_governing_time"]
        assert len(before["lineage"]) == 1 and before["factor"] == "1"

    def test_a_later_correction_can_never_be_labelled_available_before_it(self) -> None:
        store, runs = lineage_store()
        resolved = resolved_layer(store, runs, now=RUN_3_AT + timedelta(days=1))
        v1, v2 = revisions_of(resolved, "actions", SPLIT_KEY)
        for as_of, expected in (
            (datetime(2026, 9, 20, tzinfo=UTC), v1),
            (datetime(2026, 9, 30, tzinfo=UTC), v2),
        ):
            bar = av.select_current(resolved.stocks, cutoff=as_of)[(ZZAA.security_id, "2026-09-03")]
            actions = [
                a
                for a in av.select_current(resolved.actions, cutoff=as_of).values()
                if a.row.security_id == ZZAA.security_id
            ]
            adjusted = gd.adjust_bar(bar, actions, as_of=as_of)
            assert adjusted is not None
            assert (
                adjusted["derived_governing_time"]
                == expected.availability.governing_time.isoformat()
            )
            assert adjusted["derived_governing_time"] >= adjusted["source_governing_time"]

    def test_verification_reconstructs_the_value_and_dependencies_from_the_lineage(self) -> None:
        store, runs = lineage_store()
        as_of = datetime(2026, 9, 30, tzinfo=UTC)
        report = build(store, runs, as_of=as_of, build_id="synthetic-build-verify")
        resolved = resolved_layer(store, runs, now=as_of)
        bars = av.select_current(resolved.stocks, cutoff=as_of)
        actions = av.select_current(resolved.actions, cutoff=as_of)
        rows = artifact(report, "gold-adjusted-bars")
        assert rows and all(
            gd.verify_adjusted_row(r, bars=bars, actions=actions, as_of=as_of) is None for r in rows
        )
        row = next(
            r
            for r in rows
            if r["security_id"] == ZZAA.security_id and r["session_date"] == "2026-09-04"
        )
        tampered = dict(row, close="1.000000")
        assert (
            gd.verify_adjusted_row(tampered, bars=bars, actions=actions, as_of=as_of)
            is gd.AdjustedRowDefect.VALUE_MISMATCH
        )
        earlier = dict(row, derived_governing_time=row["source_governing_time"])
        assert (
            gd.verify_adjusted_row(earlier, bars=bars, actions=actions, as_of=as_of)
            is gd.AdjustedRowDefect.AVAILABILITY_MISMATCH
        )
        dropped = dict(row, lineage=row["lineage"][:1])
        assert (
            gd.verify_adjusted_row(dropped, bars=bars, actions=actions, as_of=as_of)
            is gd.AdjustedRowDefect.CONSUMED_SET_MISMATCH
        )
        stale = dict(
            row,
            lineage=[
                dict(
                    row["lineage"][0],
                    selector=dict(row["lineage"][0]["selector"], revision_sequence="9"),
                ),
                *row["lineage"][1:],
            ],
        )
        assert (
            gd.verify_adjusted_row(stale, bars=bars, actions=actions, as_of=as_of)
            is gd.AdjustedRowDefect.LINEAGE_UNRESOLVABLE
        )
        assert (
            gd.verify_adjusted_row(dict(row, lineage=[]), bars=bars, actions=actions, as_of=as_of)
            is gd.AdjustedRowDefect.LINEAGE_MALFORMED
        )

    def test_manifest_records_the_derivation_and_selection_versions(self) -> None:
        store, runs = lineage_store()
        build(store, runs, as_of=AS_OF, build_id="synthetic-build-versions")
        manifest = manifest_of(store, "synthetic-build-versions")
        transformation = manifest["transformation"]
        assert transformation["adjustment_derivation_version"] == gd.ADJUSTMENT_DERIVATION_VERSION
        assert transformation["action_selection_version"] == av.ACTION_SELECTION_VERSION
        assert transformation["silver_normalization_version"] == "sharadar-silver-v2"
        assert transformation["resolution_policy_version"] == "sharadar-availability-v2"


# ---------------------------------------------------------------------------
# Follow-up: the verifier validates identity, contract, provenance and shape
# ---------------------------------------------------------------------------


class TestAdjustedRowVerification:
    """Every field that establishes an adjusted row's identity, interpretation,
    provenance and availability is validated against the resolved lineage; the
    expectation is derived from the resolved bar, never from the document."""

    AS_OF: Final = datetime(2026, 9, 30, tzinfo=UTC)

    def _context(
        self,
    ) -> tuple[
        dict[str, Any], dict[str, Any], dict[Any, av.ResolvedRow], dict[Any, av.ResolvedRow]
    ]:
        store, runs = lineage_store()
        report = build(store, runs, as_of=self.AS_OF, build_id="synthetic-build-verifier")
        resolved = resolved_layer(store, runs, now=self.AS_OF)
        bars = av.select_current(resolved.stocks, cutoff=self.AS_OF)
        actions = av.select_current(resolved.actions, cutoff=self.AS_OF)
        rows = artifact(report, "gold-adjusted-bars")
        split_row = next(
            r
            for r in rows
            if r["security_id"] == ZZAA.security_id and r["session_date"] == "2026-09-04"
        )
        plain_row = next(
            r
            for r in rows
            if r["security_id"] == ZZAA.security_id and r["session_date"] == "2026-09-01"
        )
        return split_row, plain_row, bars, actions

    def verify(self, document: object, bars: Any, actions: Any) -> gd.AdjustedRowDefect | None:
        return gd.verify_adjusted_row(document, bars=bars, actions=actions, as_of=self.AS_OF)

    def test_positive_controls_reconstruct(self) -> None:
        split_row, plain_row, bars, actions = self._context()
        assert len(split_row["lineage"]) == 2 and split_row["factor"] == "3"
        assert len(plain_row["lineage"]) == 1 and plain_row["factor"] == "1"
        assert self.verify(split_row, bars, actions) is None
        assert self.verify(plain_row, bars, actions) is None
        assert set(split_row) == gd.ADJUSTED_ROW_FIELDS

    def test_the_field_scheme_is_total_over_the_closed_shape(self) -> None:
        compared = {field for field, _ in gd._FIELD_DEFECTS}
        assert compared | {"lineage"} == gd.ADJUSTED_ROW_FIELDS
        assert len(compared) == len(gd._FIELD_DEFECTS)

    @pytest.mark.parametrize(
        ("field", "value", "defect"),
        [
            ("security_id", ZZBB.security_id, gd.AdjustedRowDefect.IDENTITY_MISMATCH),
            ("session_date", "2026-09-03", gd.AdjustedRowDefect.IDENTITY_MISMATCH),
            ("adjustment_policy", "RAW", gd.AdjustedRowDefect.CONTRACT_MISMATCH),
            ("adjustment_convention", "BACK_ADJUSTED", gd.AdjustedRowDefect.CONTRACT_MISMATCH),
            (
                "derivation_version",
                "sharadar-adjusted-bars-v1",
                gd.AdjustedRowDefect.CONTRACT_MISMATCH,
            ),
            ("source_content_sha256", "0" * 64, gd.AdjustedRowDefect.PROVENANCE_MISMATCH),
            ("revision_sequence", 9, gd.AdjustedRowDefect.PROVENANCE_MISMATCH),
            ("revision_sequence", "0", gd.AdjustedRowDefect.PROVENANCE_MISMATCH),
            ("factor", "2", gd.AdjustedRowDefect.VALUE_MISMATCH),
            ("open", "1.000000", gd.AdjustedRowDefect.VALUE_MISMATCH),
            ("volume", "1", gd.AdjustedRowDefect.VALUE_MISMATCH),
            (
                "source_governing_time",
                "2026-09-01T00:00:00+00:00",
                gd.AdjustedRowDefect.AVAILABILITY_MISMATCH,
            ),
            (
                "derived_governing_time",
                "2026-09-01T00:00:00+00:00",
                gd.AdjustedRowDefect.AVAILABILITY_MISMATCH,
            ),
            ("unresolved_action_keys", 1, gd.AdjustedRowDefect.UNRESOLVED_METADATA_MISMATCH),
            ("unresolved_action_keys", "0", gd.AdjustedRowDefect.UNRESOLVED_METADATA_MISMATCH),
        ],
    )
    def test_each_identity_contract_provenance_and_value_field_is_validated(
        self, field: str, value: object, defect: gd.AdjustedRowDefect
    ) -> None:
        split_row, _, bars, actions = self._context()
        assert self.verify(dict(split_row, **{field: value}), bars, actions) is defect

    def test_a_wrong_session_with_the_same_split_set_is_an_identity_mismatch(self) -> None:
        split_row, _, bars, actions = self._context()
        # 09-04 and 09-03 consume the same split; the document's session may not choose
        # the bar it is checked against.
        moved = dict(split_row, session_date="2026-09-03")
        assert self.verify(moved, bars, actions) is gd.AdjustedRowDefect.IDENTITY_MISMATCH
        # A no-split row relabelled to another no-split session is caught the same way.
        _, plain_row, _, _ = self._context()
        assert (
            self.verify(dict(plain_row, session_date="2026-09-02"), bars, actions)
            is gd.AdjustedRowDefect.IDENTITY_MISMATCH
        )

    @pytest.mark.parametrize(
        ("mutate", "defect"),
        [
            (
                lambda row: [
                    dict(row["lineage"][0], dataset_version="other-v9"),
                    *row["lineage"][1:],
                ],
                gd.AdjustedRowDefect.LINEAGE_MISMATCH,
            ),
            (
                lambda row: [
                    row["lineage"][0],
                    dict(row["lineage"][1], dataset_version="other-v9"),
                ],
                gd.AdjustedRowDefect.LINEAGE_MISMATCH,
            ),
            (
                lambda row: [
                    row["lineage"][0],
                    dict(
                        row["lineage"][1], selector=dict(row["lineage"][1]["selector"], ratio="2")
                    ),
                ],
                gd.AdjustedRowDefect.LINEAGE_MISMATCH,
            ),
            (
                lambda row: [
                    dict(
                        row["lineage"][0],
                        selector=dict(row["lineage"][0]["selector"], revision_sequence="9"),
                    ),
                    *row["lineage"][1:],
                ],
                gd.AdjustedRowDefect.LINEAGE_UNRESOLVABLE,
            ),
            (
                lambda row: [
                    dict(
                        row["lineage"][0],
                        selector=dict(row["lineage"][0]["selector"], content_sha256="0" * 64),
                    ),
                    *row["lineage"][1:],
                ],
                gd.AdjustedRowDefect.LINEAGE_UNRESOLVABLE,
            ),
            (
                lambda row: [
                    row["lineage"][0],
                    dict(
                        row["lineage"][1],
                        selector=dict(row["lineage"][1]["selector"], revision_sequence="0"),
                    ),
                ],
                gd.AdjustedRowDefect.LINEAGE_UNRESOLVABLE,
            ),
            (
                lambda row: [
                    row["lineage"][0],
                    dict(
                        row["lineage"][1],
                        selector=dict(row["lineage"][1]["selector"], security_id=ZZBB.security_id),
                    ),
                ],
                gd.AdjustedRowDefect.LINEAGE_UNRESOLVABLE,
            ),
            (lambda row: row["lineage"][:1], gd.AdjustedRowDefect.CONSUMED_SET_MISMATCH),
            (
                lambda row: [*row["lineage"], row["lineage"][1]],
                gd.AdjustedRowDefect.LINEAGE_MALFORMED,
            ),
            (lambda row: [], gd.AdjustedRowDefect.LINEAGE_MALFORMED),
            (lambda row: "nonsense", gd.AdjustedRowDefect.LINEAGE_MALFORMED),
            (
                lambda row: [row["lineage"][1], row["lineage"][0]],
                gd.AdjustedRowDefect.LINEAGE_MALFORMED,
            ),
            (
                lambda row: [dict(row["lineage"][0], entity="security"), *row["lineage"][1:]],
                gd.AdjustedRowDefect.LINEAGE_MALFORMED,
            ),
            (
                lambda row: [dict(row["lineage"][0], extra="x"), *row["lineage"][1:]],
                gd.AdjustedRowDefect.LINEAGE_MALFORMED,
            ),
            (
                lambda row: [
                    {k: v for k, v in row["lineage"][0].items() if k != "dataset_version"},
                    *row["lineage"][1:],
                ],
                gd.AdjustedRowDefect.LINEAGE_MALFORMED,
            ),
            (
                lambda row: [
                    dict(
                        row["lineage"][0],
                        selector={
                            k: v
                            for k, v in row["lineage"][0]["selector"].items()
                            if k != "content_sha256"
                        },
                    ),
                    *row["lineage"][1:],
                ],
                gd.AdjustedRowDefect.LINEAGE_MALFORMED,
            ),
            (
                lambda row: [
                    dict(
                        row["lineage"][0],
                        selector=dict(row["lineage"][0]["selector"], revision_sequence=0),
                    ),
                    *row["lineage"][1:],
                ],
                gd.AdjustedRowDefect.LINEAGE_MALFORMED,
            ),
            (lambda row: [row["lineage"][0], "not-a-ref"], gd.AdjustedRowDefect.LINEAGE_MALFORMED),
            (
                lambda row: [
                    row["lineage"][0],
                    dict(
                        row["lineage"][1],
                        selector=dict(row["lineage"][1]["selector"], row_key="no-slashes"),
                    ),
                ],
                gd.AdjustedRowDefect.LINEAGE_UNRESOLVABLE,
            ),
        ],
    )
    def test_lineage_references_are_closed_resolved_and_complete(
        self, mutate: Any, defect: gd.AdjustedRowDefect
    ) -> None:
        split_row, _, bars, actions = self._context()
        assert self.verify(dict(split_row, lineage=mutate(split_row)), bars, actions) is defect

    @pytest.mark.parametrize(
        "document",
        [
            "not-a-document",
            None,
            [],
            {},
        ],
    )
    def test_a_document_that_is_not_the_closed_shape_is_a_closed_defect(
        self, document: object
    ) -> None:
        _, _, bars, actions = self._context()
        assert self.verify(document, bars, actions) is gd.AdjustedRowDefect.DOCUMENT_MALFORMED

    def test_missing_and_unexpected_fields_are_closed_defects(self) -> None:
        split_row, _, bars, actions = self._context()
        for field in sorted(gd.ADJUSTED_ROW_FIELDS):
            missing = {k: v for k, v in split_row.items() if k != field}
            assert self.verify(missing, bars, actions) is gd.AdjustedRowDefect.DOCUMENT_MALFORMED, (
                field
            )
        assert (
            self.verify(dict(split_row, extra="x"), bars, actions)
            is gd.AdjustedRowDefect.DOCUMENT_MALFORMED
        )

    def test_no_refusal_carries_a_value_and_no_exception_escapes(self) -> None:
        split_row, _, bars, actions = self._context()
        hostile = dict(
            split_row, lineage=[{"entity": None, "dataset_version": 1, "selector": ["x"]}]
        )
        result = self.verify(hostile, bars, actions)
        assert result is gd.AdjustedRowDefect.LINEAGE_MALFORMED
        assert "sharadar:" not in result.value and "2026" not in result.value

    def test_the_production_path_verifies_every_row_before_it_enters_an_artifact(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, runs = lineage_store()
        calls: list[dict[str, Any]] = []
        original = gd.verify_adjusted_row

        def spy(document: Any, **kwargs: Any) -> gd.AdjustedRowDefect | None:
            calls.append(document)
            return original(document, **kwargs)

        monkeypatch.setattr(gd, "verify_adjusted_row", spy)
        report = build(store, runs, as_of=self.AS_OF, build_id="synthetic-build-spy")
        rows = artifact(report, "gold-adjusted-bars")
        assert rows and calls == rows

    def test_a_verification_failure_refuses_the_build_and_publishes_no_manifest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store, runs = lineage_store()
        original = gd.verify_adjusted_row

        def one_bad_row(document: Any, **kwargs: Any) -> gd.AdjustedRowDefect | None:
            if document["session_date"] == "2026-09-04":
                return gd.AdjustedRowDefect.VALUE_MISMATCH
            return original(document, **kwargs)

        monkeypatch.setattr(gd, "verify_adjusted_row", one_bad_row)
        scenario = BuildScenario(
            store,
            runs=runs,
            config=configuration(as_of=self.AS_OF),
            build_id="synthetic-build-refused",
        )
        report = scenario.run()
        assert report.status is bp.BuildStatus.REFUSED_VERIFICATION
        assert report.defect == gd.GoldDefect.REFUSED_VERIFICATION.value
        assert report.manifest.value == "NOT_ATTEMPTED" and report.publication is None
        assert scenario.data_plane_calls()[1] == 0
        assert store.keys_under("manifests/") == [] and store.keys_under("gold/") == []


# ---------------------------------------------------------------------------
# Finding 5: membership preserved when later quality findings arise
# ---------------------------------------------------------------------------


class TestMembershipPreservation:
    def test_a_later_off_calendar_bar_restricts_without_rewriting_earlier_decisions(self) -> None:
        store = FakeS3Store()
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)
        runs_before: Runs = ((RUN_1, 1, RUN_1_AT),)
        before = build(store, runs_before, as_of=AS_OF, build_id="synthetic-build-before")
        # Run 2 delivers a bar dated 2026-09-13, which is not a session.
        bad_slice = slice_with_stocks_window(2, "2026-09-13/2026-09-13")
        r2 = responses_for_run(2, bad_slice)
        template = stocks_rows(date(2026, 9, 4), run=1)[0]
        r2[("stocks", "2026-09-13/2026-09-13", 0)] = csv(
            STOCKS_HEADER, [(template[0], "2026-09-13", *template[2:])]
        )
        acquire(store, run_id=RUN_2, run=2, at=RUN_2_AT, responses=r2, slice_doc=bad_slice)
        runs_after: Runs = (*runs_before, (RUN_2, 2, RUN_2_AT))
        after = build(
            store,
            runs_after,
            as_of=AS_OF,
            build_id="synthetic-build-after",
            slices={RUN_2: bad_slice},
        )
        m_before = {
            (r["session_date"], r["security_id"]): r
            for r in artifact(before, "gold-universe-membership")
        }
        m_after = {
            (r["session_date"], r["security_id"]): r
            for r in artifact(after, "gold-universe-membership")
        }
        # 2026-09-14 was decided at 13:00Z on the 14th, before the defective bar existed
        # (first seen 09-15T02:00Z): its rows are identical before and after.
        for key, row in m_before.items():
            if key[0] == "2026-09-14":
                assert m_after[key] == row, key
        assert m_after[("2026-09-14", ZZAA.security_id)]["is_member"] is True
        # The restriction sits beside the decisions with explicit scope and applicability.
        restrictions = artifact(after, "gold-eligibility-restrictions")
        (restriction,) = [r for r in restrictions if r["security_id"] == ZZAA.security_id]
        assert restriction["check"] == "TEMPORAL_SESSION_ON_CALENDAR"
        assert restriction["restricted_from"] > RUN_2_AT.isoformat()
        assert (
            restriction["sessions_affected"] == ["2026-09-15"]
            and restriction["withheld"] == "adjusted-bars"
        )
        # Downstream use is still prevented: ZZAA's adjusted bars are withheld.
        assert not any(
            r["security_id"] == ZZAA.security_id for r in artifact(after, "gold-adjusted-bars")
        )
        assert any(
            r["security_id"] == ZZAA.security_id for r in artifact(before, "gold-adjusted-bars")
        )
        # Census, restricted counts and empty-result reporting agree.
        manifest = manifest_of(store, "synthetic-build-after")
        assert manifest["quality"]["restricted_securities"] == [ZZAA.security_id]
        assert [r["security_id"] for r in manifest["restrictions"]] == [ZZAA.security_id]
        assert manifest["census"] == manifest_of(store, "synthetic-build-before")["census"]
        assert manifest["empty_reason"] is None and after.status is bp.BuildStatus.COMPLETED
        assert artifact(before, "gold-eligibility-restrictions") == []

    def test_a_build_refusal_is_distinct_from_a_restriction(self) -> None:
        """A build-scoped BLOCKING finding refuses publication outright; nothing is rewritten
        because nothing is published."""
        store = FakeS3Store()
        acquire(store, run_id=RUN_1, run=1, at=RUN_1_AT)
        resolved = resolved_layer(store, ((RUN_1, 1, RUN_1_AT),))
        snapshot = uv.build_universe(
            resolved,
            rule=configuration().rule,
            calendar=calendar(),
            sessions=(date(2026, 9, 14),),
            as_of=AS_OF,
        )
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
