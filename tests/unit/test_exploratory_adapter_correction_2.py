"""PR #113 review correction 2 -- targeted regressions, written before the correction.

One finding from source inspection of ``47b70d53``: correction 1 reconciled every fact the producer
writes twice **except one**. ``bind_configuration`` validated the compiled configuration's
``evidence`` block and discarded its ``version``; ``parse_manifest`` read the manifest's
``transformation.evidence_version`` (the producer writes ``resolved.evidence_version`` there, which
is ``configuration.evidence.version``) as dynamic text. So a manifest whose evidence version
disagreed with the digest-bound configuration was bound, and a dataset was constructed under it.
Synthetic artifacts from the accepted producer only.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Final

import pytest

from fixtures import m0_build_artifacts as ba
from kalpamani.data.contracts.canonical import canonical_bytes
from kalpamani.data.exploratory import adapter
from kalpamani.data.exploratory.adapter import (
    AdapterDefect,
    AdapterError,
    assemble_layer,
    build_dataset,
    parse_manifest,
)

pytestmark = pytest.mark.unit

INCONSISTENT: Final = AdapterDefect.CONFIGURATION_INCONSISTENT

#: Evidence versions that are not the configuration's ``synthetic-evidence-v0``: another label,
#: the same label at another version, the same label with a suffix, and a case variant.
DISAGREEING_VERSIONS: Final = (
    "other-evidence-v0",
    "synthetic-evidence-v1",
    "synthetic-evidence-v0-amended",
    "Synthetic-Evidence-V0",
)


@pytest.fixture(scope="module")
def build() -> ba.BuildArtifacts:
    return ba.m0_build()


@pytest.fixture(scope="module")
def bound(build: ba.BuildArtifacts) -> Any:
    manifest = parse_manifest(build.manifest)
    return adapter.bind_configuration(build.configuration, manifest=manifest)


def with_evidence_version(manifest: bytes, version: str) -> bytes:
    document = json.loads(manifest)
    document["transformation"]["evidence_version"] = version
    return canonical_bytes(document)


def refusal(callable_: Any, *args: Any, **kwargs: Any) -> AdapterDefect:
    with pytest.raises(AdapterError) as caught:
        callable_(*args, **kwargs)
    return caught.value.defect


def test_c2_the_producer_writes_the_evidence_version_twice_and_the_fixture_agrees(
    build: ba.BuildArtifacts,
) -> None:
    """Positive control on the unchanged head: the compiled configuration's ``evidence.version``
    and the manifest's ``transformation.evidence_version`` are one fact written twice, the
    fixture's two documents agree on it, and the agreeing pair binds."""
    manifest = parse_manifest(build.manifest)
    configuration = json.loads(build.configuration)
    assert configuration["evidence"]["version"] == "synthetic-evidence-v0"
    assert manifest.transformation_versions["evidence_version"] == "synthetic-evidence-v0"
    assert adapter.bind_configuration(build.configuration, manifest=manifest) is not None


@pytest.mark.parametrize("version", DISAGREEING_VERSIONS)
def test_c2_a_disagreeing_manifest_evidence_version_is_refused_at_binding(
    build: ba.BuildArtifacts, version: str
) -> None:
    """The evidence version is a dynamic value (parse accepts any non-empty text), so the only
    place it can be held is reconciliation: the digest-bound configuration is the authority and
    a manifest that repeats it differently is CONFIGURATION_INCONSISTENT."""
    manifest = parse_manifest(with_evidence_version(build.manifest, version))
    assert manifest.transformation_versions["evidence_version"] == version
    assert manifest.configuration_digest == parse_manifest(build.manifest).configuration_digest
    assert (
        refusal(adapter.bind_configuration, build.configuration, manifest=manifest) is INCONSISTENT
    )


@pytest.mark.parametrize("version", DISAGREEING_VERSIONS)
def test_c2_a_disagreeing_manifest_evidence_version_is_refused_at_dataset_construction(
    build: ba.BuildArtifacts, bound: Any, version: str
) -> None:
    """A configuration faithfully bound to the consistent manifest, offered against an assembly
    whose manifest carries the same configuration digest and a different evidence version:
    construction re-binds against the assembly's manifest and refuses -- the dataset is never
    built."""
    disagreeing = parse_manifest(with_evidence_version(build.manifest, version))
    assembly = assemble_layer(disagreeing, build.artifacts)
    assert bound.configuration_digest == assembly.manifest.configuration_digest
    assert refusal(build_dataset, assembly, configuration=bound) is INCONSISTENT


def test_c2_the_bound_configuration_carries_the_evidence_version_and_a_forged_one_is_refused(
    build: ba.BuildArtifacts, bound: Any
) -> None:
    """The reconciled value is carried on the bound object like every other reconciled fact, and
    the re-derivation at construction compares it: a carried value the bytes do not derive is
    CONFIGURATION_INCONSISTENT."""
    manifest = parse_manifest(build.manifest)
    assembly = assemble_layer(manifest, build.artifacts)
    assert bound.evidence_version == manifest.transformation_versions["evidence_version"]
    forged = replace(bound, evidence_version="forged-evidence-v9")
    assert refusal(build_dataset, assembly, configuration=forged) is INCONSISTENT
    # The faithful object still constructs.
    assert build_dataset(assembly, configuration=bound).as_of == manifest.as_of


def test_c2_a_configuration_side_evidence_version_change_is_unbound_not_inconsistent(
    build: ba.BuildArtifacts,
) -> None:
    """Control: the configuration side cannot disagree quietly -- editing ``evidence.version`` in
    the compiled document changes its canonical digest, and the digest is checked before any
    field is read, so that document is CONFIGURATION_UNBOUND. Only the manifest side can reach
    reconciliation, which is why the manifest-side comparison is the one that matters."""
    manifest = parse_manifest(build.manifest)
    document = json.loads(build.configuration)
    document["evidence"]["version"] = "other-evidence-v0"
    assert (
        refusal(adapter.bind_configuration, canonical_bytes(document), manifest=manifest)
        is AdapterDefect.CONFIGURATION_UNBOUND
    )


def test_c2_the_valid_producer_round_trip_is_retained(build: ba.BuildArtifacts, bound: Any) -> None:
    manifest = parse_manifest(build.manifest)
    assembly = assemble_layer(manifest, build.artifacts)
    dataset = build_dataset(assembly, configuration=bound)
    assert dataset.calendar == build.calendar
    assert dataset.source_manifest_digest == manifest.manifest_digest
