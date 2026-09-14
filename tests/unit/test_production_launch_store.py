"""The launch tool's durable state (proposed ADR-0045 §6), on a temporary directory.

Exclusive reservations that survive everything, a ledger lock that is never taken twice
and never removed by another process, an atomic ledger replacement that refuses a changed
ledger and leaves the old bytes on failure, record names that cannot collide, and the
reconciliation of interrupted work -- each observed on the real filesystem primitives
this workstation uses, never asserted from a docstring.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from fixtures.production_launch import ACQ, ledger_document, ledger_row, specification_for
from fixtures.production_runtime import NOW, OTHER_RUN_ID, RUN_ID, encode, slice_document
from kalpamani.data.production.sharadar import launch_records as lr
from kalpamani.data.production.sharadar import launch_store as ls

pytestmark = pytest.mark.unit


def _store(tmp_path: Path, rows: list[dict[str, Any]] | None = None) -> ls.LaunchStore:
    ledger = tmp_path / "ledger.json"
    ledger.write_bytes(encode(ledger_document(rows or [])))
    return ls.LaunchStore(ledger_path=ledger, records_dir=tmp_path / "records")


def _reservation(
    identity: str = RUN_ID, *, window: str = "2025-01-01/2025-12-31", **overrides: Any
) -> ls.Reservation:
    specification = specification_for(
        actor=ACQ,
        kind="production",
        identity=identity,
        slice_doc=slice_document(windows={"actions": window, "tickers": "SNAPSHOT"}),
    )
    fields_: dict[str, Any] = {
        "identity": identity,
        "actor": ACQ,
        "kind": lr.LaunchKind.PRODUCTION,
        "specification": specification,
        "reserved_at": NOW,
    }
    fields_.update(overrides)
    return ls.Reservation(**fields_)


DIGEST = _reservation().specification_digest
OTHER_DIGEST = _reservation(window="2024-01-01/2024-12-31").specification_digest


class TestReservations:
    def test_a_reservation_is_exclusive_durable_and_never_expires(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.reserve(_reservation())
        path = store.reservation_path(RUN_ID)
        assert path.is_file()
        with pytest.raises(ls.StoreError, match="RESERVATION_EXISTS"):
            store.reserve(_reservation(window="2024-01-01/2024-12-31"))
        # Untouched by the refused second attempt.
        assert json.loads(path.read_bytes())["specification_digest"] == DIGEST != OTHER_DIGEST
        found = store.reservation(RUN_ID)
        assert found is not None and found.specification_digest == DIGEST
        assert found.specification.workload["slice"]["windows"]["actions"] == (
            "2025-01-01/2025-12-31"
        )
        assert store.reservation(OTHER_RUN_ID) is None
        # Far later, with a ledger that never recorded it, it is still there and still
        # the one thing that names the identity as consumed.
        ledger, _ = store.read_ledger()
        assert store.unreconciled(ledger) == [RUN_ID]
        assert ls.parse_reservation(path.read_bytes()) == found

    def test_competing_threads_reserve_exactly_once(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        outcomes: list[str] = []
        barrier = threading.Barrier(8)

        def attempt() -> None:
            barrier.wait()
            try:
                store.reserve(_reservation())
                outcomes.append("reserved")
            except ls.StoreError as error:
                outcomes.append(error.defect.value)

        threads = [threading.Thread(target=attempt) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert outcomes.count("reserved") == 1
        assert outcomes.count("RESERVATION_EXISTS") == 7

    def test_a_malformed_reservation_refuses_and_is_not_ignored(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        store.reserve(_reservation())
        store.reservation_path(RUN_ID).write_bytes(b"{}")
        with pytest.raises(ls.StoreError, match="RESERVATION_MALFORMED"):
            store.reservation(RUN_ID)
        ledger, _ = store.read_ledger()
        with pytest.raises(ls.StoreError, match="RESERVATION_MALFORMED"):
            store.unreconciled(ledger)
        # A reservation filed under another identity's name is malformed too.
        store.reservation_path(RUN_ID).write_bytes(encode(_reservation(OTHER_RUN_ID).document()))
        with pytest.raises(ls.StoreError, match="RESERVATION_MALFORMED"):
            store.unreconciled(ledger)

    @pytest.mark.parametrize(
        "mutate",
        [
            lambda d: d.__setitem__("identity", "bad identity!"),
            lambda d: d.__setitem__("kind", "test"),
            lambda d: d.__setitem__("specification_digest", "xyz"),
            lambda d: d.__setitem__("contract_id", "kalpamani-launch-reservation/v2"),
            lambda d: d.__setitem__("extra", 1),
            lambda d: d.pop("reserved_at"),
            # The first revision's shape: no specification carried.
            lambda d: d.pop("specification"),
            # A specification whose digest is not the one named.
            lambda d: d.__setitem__("specification_digest", OTHER_DIGEST),
            # A specification for another identity, or another kind, than the reservation.
            lambda d: d["specification"].__setitem__("identity", OTHER_RUN_ID),
            lambda d: d["specification"].__setitem__("kind", "verification"),
            # A specification that does not parse.
            lambda d: d["specification"]["placement"].__setitem__("subnet_id", "subnet-x"),
            lambda d: d["specification"]["placement"].__setitem__("security_group_ids", []),
            lambda d: d["specification"]["workload"].__setitem__("plan_digest", "00" * 32),
            lambda d: d["specification"].__setitem__("workload", {"runs": []}),
        ],
    )
    def test_reservation_documents_are_closed(self, mutate: Any) -> None:
        document = _reservation().document()
        mutate(document)
        with pytest.raises(ls.StoreError, match="RESERVATION_MALFORMED"):
            ls.parse_reservation(encode(document))

    def test_a_reservation_names_its_own_specification(self) -> None:
        other = specification_for(actor=ACQ, kind="production", identity=OTHER_RUN_ID)
        with pytest.raises(ValueError, match="identity, actor and kind"):
            ls.Reservation(
                identity=RUN_ID,
                actor=ACQ,
                kind=lr.LaunchKind.PRODUCTION,
                specification=other,
                reserved_at=NOW,
            )


class TestReservationLocation:
    """PR #104 review, second cycle, finding 1: the location never depends on the records dir."""

    def test_reservations_live_beside_the_ledger_and_not_under_the_records(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        store.reserve(_reservation())
        assert store.reservations_path == tmp_path / "ledger.json.reservations"
        assert store.reservation_path(RUN_ID).parent == store.reservations_path
        assert not (tmp_path / "records").exists()
        # Another records directory over the same ledger: the same reservation, the same
        # lock, the same pending recovery.
        other = ls.LaunchStore(ledger_path=tmp_path / "ledger.json", records_dir=tmp_path / "b")
        assert other.reservations_path == store.reservations_path
        assert other.lock_path == store.lock_path == tmp_path / "ledger.json.lock"
        found = other.reservation(RUN_ID)
        assert found is not None and found.specification_digest == DIGEST
        ledger, _ = other.read_ledger()
        assert other.unreconciled(ledger) == [RUN_ID]
        with pytest.raises(ls.StoreError, match="RESERVATION_EXISTS"):
            other.reserve(_reservation())
        # And the records directory received nothing but what was written to it.
        other.write_record("launch-evidence", {"n": 1}, at=NOW)
        assert [p.name for p in (tmp_path / "b").iterdir()] != []
        assert not (tmp_path / "b" / ls.LEGACY_RESERVATIONS_DIRECTORY).exists()

    @pytest.mark.parametrize(
        "spelling",
        [
            lambda root: root / "ledger.json",
            lambda root: root / "records" / ".." / "ledger.json",
            lambda root: Path(str(root / "ledger.json").upper()),
            lambda root: Path(str(root / "ledger.json").replace("\\", "/")),
            lambda root: Path(os.path.relpath(root / "ledger.json")),
        ],
    )
    def test_equivalent_spellings_of_one_ledger_share_one_reservation_store(
        self, tmp_path: Path, spelling: Any
    ) -> None:
        canonical = _store(tmp_path)
        canonical.reserve(_reservation())
        spelled = ls.LaunchStore(ledger_path=spelling(tmp_path), records_dir=tmp_path / "x")
        assert spelled.ledger_path == canonical.ledger_path
        assert spelled.reservations_path == canonical.reservations_path
        assert spelled.lock_path == canonical.lock_path
        assert spelled.reservation(RUN_ID) is not None
        with pytest.raises(ls.StoreError, match="RESERVATION_EXISTS"):
            spelled.reserve(_reservation())
        with canonical.locked(now=lambda: NOW), pytest.raises(ls.StoreError, match="LOCKED"):
            with spelled.locked(now=lambda: NOW):
                pass

    def test_first_revision_reservations_under_the_records_directory_refuse(
        self, tmp_path: Path
    ) -> None:
        """Legacy state is refused, never read, moved or deleted (synthetic directories)."""
        store = _store(tmp_path)
        store.refuse_legacy_state()  # nothing there: fine
        legacy = tmp_path / "records" / ls.LEGACY_RESERVATIONS_DIRECTORY
        legacy.mkdir(parents=True)
        store.refuse_legacy_state()  # an empty directory hides nothing
        stale = legacy / f"{RUN_ID}.json"
        stale.write_bytes(b'{"first": "revision"}')
        with pytest.raises(ls.StoreError, match="LEGACY_RESERVATIONS_PRESENT"):
            store.refuse_legacy_state()
        assert stale.read_bytes() == b'{"first": "revision"}' and legacy.is_dir()
        assert store.reservation(RUN_ID) is None  # never read as a reservation
        # A records directory the owner did not name is not looked at.
        other = ls.LaunchStore(ledger_path=tmp_path / "ledger.json", records_dir=tmp_path / "b")
        other.refuse_legacy_state()


class TestLedgerLock:
    def test_the_lock_is_exclusive_released_on_exit_and_never_taken_over(
        self, tmp_path: Path
    ) -> None:
        store = _store(tmp_path)
        with store.locked(now=lambda: NOW):
            assert store.lock_path.is_file()
            marker = json.loads(store.lock_path.read_bytes())
            assert marker["pid"] == os.getpid()
            with pytest.raises(ls.StoreError, match="LEDGER_LOCKED"):
                with store.locked(now=lambda: NOW):
                    pass
        assert not store.lock_path.exists()
        # A lock another process left behind is never removed by this one.
        store.lock_path.write_bytes(b"{}")
        with pytest.raises(ls.StoreError, match="LEDGER_LOCKED"):
            with store.locked(now=lambda: NOW):
                pass
        assert store.lock_path.exists()

    def test_the_lock_is_released_when_the_body_raises(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        with pytest.raises(RuntimeError), store.locked(now=lambda: NOW):
            raise RuntimeError("body failed")
        assert not store.lock_path.exists()


class TestAtomicLedger:
    def test_replacement_is_atomic_and_refuses_a_changed_ledger(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        ledger, digest = store.read_ledger()
        grown = lr.append_row(
            ledger,
            lr.OwnerLedgerRow(
                identity=RUN_ID,
                actor=ACQ,
                kind=lr.LaunchKind.PRODUCTION,
                outcome="REFUSED",
                evidence=lr.LedgerEvidence.EXIT_CODE_ONLY,
                launched_at=NOW,
                completed_at=NOW + timedelta(seconds=1),
                slice=None,
                plan_digest=None,
            ),
        )
        # Another writer changed the ledger since it was read: the write refuses.
        store._ledger_path.write_bytes(encode(ledger_document([ledger_row(OTHER_RUN_ID)])))
        with pytest.raises(ls.StoreError, match="LEDGER_CHANGED"):
            store.replace_ledger(grown, expected_digest=digest)
        assert [r["identity"] for r in json.loads(store._ledger_path.read_bytes())["rows"]] == [
            OTHER_RUN_ID
        ]
        # Re-read, then replace: the new bytes land whole, and no temporary file remains.
        ledger, digest = store.read_ledger()
        store.replace_ledger(lr.append_row(ledger, grown.rows[0]), expected_digest=digest)
        identities = [r["identity"] for r in json.loads(store._ledger_path.read_bytes())["rows"]]
        assert identities == [OTHER_RUN_ID, RUN_ID]
        assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".ledger")] == []

    def test_a_failed_replacement_leaves_the_old_ledger_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _store(tmp_path, [ledger_row(RUN_ID)])
        before = store._ledger_path.read_bytes()
        ledger, digest = store.read_ledger()

        def failing_replace(source: Any, destination: Any) -> None:
            raise OSError("sharing violation")

        monkeypatch.setattr(os, "replace", failing_replace)
        with pytest.raises(ls.StoreError, match="WRITE_FAILED"):
            store.replace_ledger(ledger, expected_digest=digest)
        assert store._ledger_path.read_bytes() == before
        assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []

    def test_an_unreadable_or_malformed_ledger_refuses(self, tmp_path: Path) -> None:
        store = ls.LaunchStore(ledger_path=tmp_path / "missing.json", records_dir=tmp_path / "r")
        with pytest.raises(ls.StoreError, match="LEDGER_UNREADABLE"):
            store.read_ledger()
        (tmp_path / "missing.json").write_bytes(b"not json")
        with pytest.raises(ls.StoreError, match="LEDGER_UNREADABLE"):
            store.read_ledger()


class TestRecords:
    def test_record_names_cannot_collide_within_one_second(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = _store(tmp_path)
        first = store.write_record("launch-evidence", {"n": 1}, at=NOW)
        second = store.write_record("launch-evidence", {"n": 2}, at=NOW)
        assert first != second and first.parent == second.parent
        assert json.loads(first.read_bytes()) == {"n": 1}
        assert json.loads(second.read_bytes()) == {"n": 2}
        # Even a random name that already exists is retried rather than overwritten.
        taken = first.name.split("-")[-1].removesuffix(".json")
        sequence = iter([taken, taken, "feedface"])
        monkeypatch.setattr(secrets, "token_hex", lambda n: next(sequence))
        third = store.write_record("launch-evidence", {"n": 3}, at=NOW)
        assert third.name.endswith("feedface.json") and json.loads(first.read_bytes()) == {"n": 1}
        # And a name space that never frees up is refused, never overwritten.
        monkeypatch.setattr(secrets, "token_hex", lambda n: taken)
        with pytest.raises(ls.StoreError, match="NAME_EXHAUSTED"):
            store.write_record("launch-evidence", {"n": 4}, at=NOW)
        assert json.loads(first.read_bytes()) == {"n": 1}

    def test_launch_records_are_listed_by_name(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        assert store.launch_records() == []
        store.write_record("launch-record", {"a": 1}, at=NOW)
        store.write_record("launch-evidence", {"a": 1}, at=NOW)
        assert len(store.launch_records()) == 1
