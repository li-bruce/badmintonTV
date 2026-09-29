"""R-04b contract assertions; synthetic metadata is not end-to-end acceptance."""

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts import (
    Asset, TRAINING_REGISTRY_PATH, TrainingRegistry, UsageScopeError, UsageScopeGuard,
    assert_production_allowed, inherit_usage_scope,
)


@pytest.fixture
def root(tmp_path):
    result = tmp_path / "video"
    result.mkdir()
    return result


def source(**changes):
    return {"asset_id": "ordinary", "relative_path": "data/raw/ordinary.mp4", "sha256": "a" * 64, **changes}


def entry(**changes):
    return {"asset_id": "training-source", "relative_path": "data/training/example/source.mp4", "sha256": "b" * 64, "usage_scope": "training_only", **changes}


def publish(root, assets):
    path = root / TRAINING_REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "1.0", "assets": assets}, sort_keys=True), encoding="utf-8")
    return path


def deny(root, asset, code="TRAINING_ONLY", **kwargs):
    with pytest.raises(UsageScopeError) as error:
        assert_production_allowed(asset, root, **kwargs)
    assert error.value.code == code
    return error.value


def junction_or_symlink(target, link):
    link.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


def test_old_asset_default_is_general_independent_of_license_and_split(root):
    asset = Asset.model_validate({**source(), "size_bytes": 10, "duration_ms": 1000, "width": 10, "height": 10,
                                  "match_id": "contract-fixture", "source_type": "synthetic", "split": "train",
                                  "rights": {"status": "research_only"}})
    assert asset.usage_scope == "general"
    assert_production_allowed(asset, root)
    for invalid in (None, "commercial", "TRAINING_ONLY"):
        with pytest.raises(ValidationError):
            Asset.model_validate({**asset.model_dump(), "usage_scope": invalid})


def test_partial_import_preflight_accepts_platform_extra_fields(root):
    asset = {"relative_path": "data/raw/new.mp4", "library_id": "library-local"}
    assert_production_allowed(asset, root)
    decision = UsageScopeGuard(root).check(asset)
    assert decision.allowed and decision.usage_scope == "general" and decision.registry_sha256 is None


@pytest.mark.parametrize("changes", [
    {"usage_scope": "training_only"},
    {"usage_scope": "training_only", "provenance": {"usage_scope": "general"}},
    {"usage_scope": "general", "provenance": {"usage_scope": "training_only"}},
    {"relative_path": "data/training/example/source.mp4"},
    {"relative_path": "DATA/TRAINING/source.mp4"},
])
@pytest.mark.parametrize("preview", [False, True])
def test_all_training_markers_reject_even_research_preview(root, changes, preview):
    publish(root, [])
    deny(root, source(**changes), research_preview=preview)


def test_training_path_requires_component_boundary(root):
    for path in ("data/training-copy/video.mp4", "models/training/video.mp4", "data/raw/training.mp4"):
        assert_production_allowed({"relative_path": path}, root)


def test_existing_training_directory_requires_registry_even_for_empty_asset_list(root):
    (root / "data" / "training").mkdir(parents=True)
    deny(root, source(), "TRAINING_REGISTRY_PENDING")
    deny(root, [], "TRAINING_REGISTRY_PENDING")
    publish(root, [])
    assert_production_allowed(source(), root)


def test_minimal_registry_needs_no_asset_probe_and_matches_id_hash_or_path(root):
    minimal = entry(relative_path="data/raw/registered-training.mp4")
    publish(root, [minimal])
    assert TrainingRegistry.model_validate({"schema_version": "1.0", "assets": [minimal]}).assets[0].asset_id == minimal["asset_id"]
    for incoming in (source(asset_id=minimal["asset_id"]), source(sha256=minimal["sha256"].upper()),
                     {"relative_path": minimal["relative_path"]}):
        deny(root, incoming)


def test_registry_same_hash_aliases_with_same_or_different_ids_are_all_restricted(root):
    original = entry(relative_path="data/raw/training-original.mp4")
    alias_same_id = {**original, "relative_path": "data/raw/training-copy.mp4"}
    alias_other_id = {**original, "asset_id": "other-id", "relative_path": "data/raw/third-copy.mp4"}
    publish(root, [original, alias_same_id, alias_other_id])
    for row in (original, alias_same_id, alias_other_id):
        deny(root, {"relative_path": row["relative_path"]})


def test_registry_rejects_conflicting_duplicate_id_or_path(root):
    original = entry()
    for changed in ({**original, "sha256": "c" * 64}, {**original, "asset_id": "other-id", "sha256": "c" * 64}):
        publish(root, [original, changed])
        deny(root, source(), "TRAINING_REGISTRY_INVALID")


@pytest.mark.parametrize("payload", [
    "not-json", "{\"schema_version\":\"1.0\",\"assets\":[", "{}", '{"assets":[]}',
    '{"schema_version":"2.0","assets":[]}', '{"schema_version":"1.0","assets":[{}]}',
    '{"schema_version":"1.0","assets":[],"assets":[]}',
])
def test_damaged_registry_is_a_global_failure_not_an_empty_match(root, payload):
    path = publish(root, [])
    path.write_text(payload, encoding="utf-8")
    deny(root, source(), "TRAINING_REGISTRY_INVALID")


def test_registry_validates_entire_array_including_unrelated_bad_record(root):
    publish(root, [entry(), {"asset_id": "bad", "relative_path": "data/training/bad.mp4", "sha256": "bad", "usage_scope": "training_only"}])
    deny(root, source(), "TRAINING_REGISTRY_INVALID")


def test_registry_wrong_scope_and_invalid_source_metadata_fail_closed(root):
    for invalid in (entry(usage_scope="general"), entry(provenance={"source_sha256": "not-a-hash"})):
        publish(root, [invalid])
        deny(root, source(), "TRAINING_REGISTRY_INVALID")


def test_registry_permission_failure_does_not_allow_production(root, monkeypatch):
    path = publish(root, [])
    original = Path.open

    def inaccessible(self, *args, **kwargs):
        if self == path:
            raise PermissionError("synthetic inaccessible registry")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", inaccessible)
    deny(root, source(), "TRAINING_REGISTRY_UNAVAILABLE")


def test_guard_reloads_same_size_and_same_mtime_registry_updates(root):
    path = publish(root, [entry(sha256="c" * 64)])
    original_stat = path.stat()
    guard = UsageScopeGuard(root)
    incoming = source(sha256="b" * 64)
    before = guard.check(incoming)
    assert before.allowed
    path.write_text(path.read_text(encoding="utf-8").replace("c" * 64, "b" * 64), encoding="utf-8")
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert path.stat().st_size == original_stat.st_size
    assert path.stat().st_mtime_ns == original_stat.st_mtime_ns
    after = guard.check(incoming)
    assert not after.allowed and before.registry_sha256 != after.registry_sha256


def test_training_physical_path_alias_is_restricted(root):
    publish(root, [])
    target = root / "data" / "training" / "set"
    target.mkdir()
    junction_or_symlink(target, root / "data" / "raw" / "alias")
    error = deny(root, {"relative_path": "data/raw/alias/source.mp4"})
    assert any("physical path" in reason for reason in error.reasons)


def test_registry_path_cannot_be_redirected_by_a_junction(root):
    target = root / "data" / "untrusted"
    target.mkdir(parents=True)
    (target / "training-registry.v1.json").write_text('{"schema_version":"1.0","assets":[]}', encoding="utf-8")
    junction_or_symlink(target, root / "data" / "training" / "handoff")
    deny(root, source(), "TRAINING_REGISTRY_INVALID")


def test_unregistered_derived_asset_is_restricted_by_recursive_source_chain(root):
    training = entry()
    publish(root, [training])
    proxy = source(asset_id="proxy", sha256="c" * 64, relative_path="platform/proxy/source.mp4",
                   provenance={"source_asset_id": training["asset_id"], "source_sha256": training["sha256"]})
    derived = source(asset_id="export", sha256="d" * 64, relative_path="render/exports/clip.mp4",
                     provenance={"source_asset_id": proxy["asset_id"], "source_sha256": proxy["sha256"]})
    deny(root, derived, source_assets=[proxy])


def test_source_reference_can_match_registry_by_id_or_sha_alone(root):
    training = entry()
    publish(root, [training])
    for provenance in ({"source_asset_id": training["asset_id"]}, {"source_sha256": training["sha256"]}):
        deny(root, source(provenance=provenance))


def test_source_id_hash_conflict_and_cycles_are_hard_errors(root):
    parent = source(asset_id="parent", sha256="c" * 64)
    derived = source(asset_id="derived", relative_path="platform/proxy/derived.mp4",
                     provenance={"source_asset_id": "parent", "source_sha256": "d" * 64})
    deny(root, derived, "USAGE_SOURCE_CONFLICT", source_assets=[parent])
    a = source(asset_id="a", provenance={"source_asset_id": "b"})
    b = source(asset_id="b", relative_path="platform/proxy/b.mp4", provenance={"source_asset_id": "a"})
    deny(root, a, "USAGE_SOURCE_CONFLICT", source_assets=[b])


def test_missing_registry_preserves_unresolved_source_note_without_claiming_detection(root):
    decision = UsageScopeGuard(root).check(source(provenance={"source_asset_id": "external-unavailable-source"}))
    assert decision.allowed
    assert any("unresolved" in reason for reason in decision.reasons)


def test_product_derivation_preserves_source_and_cannot_downgrade_training(root):
    parent = source(usage_scope="training_only")
    derived = {"relative_path": "platform/proxy/derived.mp4", "provenance": {"proxy_pts_map": "mapping-01"}}
    inherited = inherit_usage_scope(derived, parent, root)
    assert inherited["usage_scope"] == inherited["provenance"]["usage_scope"] == "training_only"
    assert inherited["provenance"]["source_asset_id"] == parent["asset_id"]
    assert inherited["provenance"]["source_sha256"] == parent["sha256"]
    assert inherited["provenance"]["proxy_pts_map"] == "mapping-01"
    assert "usage_scope" not in derived
    deny(root, inherited)
    with pytest.raises(UsageScopeError) as error:
        inherit_usage_scope({**derived, "provenance": {"source_asset_id": "another-source"}}, parent, root)
    assert error.value.code == "USAGE_SOURCE_CONFLICT"


@pytest.mark.parametrize("bad", [{}, {"relative_path": "../outside.mp4"}, {"relative_path": "data/a.mp4", "usage_scope": None},
                                 {"relative_path": "data/a.mp4", "provenance": {"source_sha256": "bad"}}, None])
def test_partial_metadata_validation_is_fail_closed(root, bad):
    deny(root, bad, "USAGE_METADATA_INVALID")


def test_media_hash_verification_remains_callers_obligation(root):
    publish(root, [entry()])
    declared = source(sha256="a" * 64)
    assert_production_allowed(declared, root)
    # Once the worker supplies the real hash, the copy is recognized by registry.
    deny(root, {**declared, "sha256": "b" * 64})


def test_usage_scope_canonical_fixtures_are_valid_and_restricted(root):
    fixtures = Path(__file__).parents[2] / "packages" / "contracts" / "fixtures"
    training = Asset.model_validate_json((fixtures / "usage-scope-training-asset.json").read_text(encoding="utf-8"))
    derived = Asset.model_validate_json((fixtures / "usage-scope-derived-asset.json").read_text(encoding="utf-8"))
    registry = TrainingRegistry.model_validate_json((fixtures / "training-registry.json").read_text(encoding="utf-8"))
    assert registry.assets[0].asset_id == training.asset_id
    assert derived.provenance["source_asset_id"] == training.asset_id
    assert derived.provenance["source_sha256"] == training.sha256
    publish(root, registry.model_dump(mode="json")["assets"])
    deny(root, training)
    deny(root, derived, source_assets=[training], research_preview=True)


def count_physical_checks(monkeypatch):
    calls = []
    original = UsageScopeGuard._physical
    def counted(self, record):
        calls.append(record.relative_path)
        return original(self, record)
    monkeypatch.setattr(UsageScopeGuard, "_physical", counted)
    return calls


def test_batch_registry_and_asset_paths_are_resolved_once_per_call(root, monkeypatch):
    publish(root, [entry(asset_id=f"training-{i}", relative_path=f"data/training/set/{i}.mp4",
                         sha256=f"{i + 10000:064x}") for i in range(500)])
    incoming = [source(asset_id=f"incoming-{i}", relative_path=f"data/raw/{i}.mp4", sha256=f"{i + 1000:064x}") for i in range(20)]
    calls = count_physical_checks(monkeypatch)
    guard = UsageScopeGuard(root)
    guard.assert_allowed(incoming)
    assert len(calls) == 520
    calls.clear()
    assert all(decision.allowed for decision in guard.check_many(incoming))
    assert len(calls) == 520  # No memo or resolved-path cache survives the call.


def layered_aliases(levels, *, restricted=False):
    records = []
    for level in range(levels):
        for alias in ("a", "b"):
            records.append(source(asset_id=f"node-{level}-{alias}", sha256=f"{level + 1:064x}",
                relative_path=f"data/raw/{level}-{alias}.mp4",
                usage_scope="training_only" if restricted and level == 0 and alias == "a" else "general",
                provenance={"source_sha256": f"{level:064x}"} if level else {}))
    return records, source(asset_id="derived", sha256="f" * 64, relative_path="render/derived.mp4",
                           provenance={"source_sha256": f"{levels:064x}"})


@pytest.mark.parametrize("restricted", [False, True])
def test_shared_alias_dag_visits_each_node_once_and_bounds_reasons(root, monkeypatch, restricted):
    records, derived = layered_aliases(24, restricted=restricted)
    calls = count_physical_checks(monkeypatch)
    decision = UsageScopeGuard(root).check(derived, source_assets=records)
    assert len(calls) == len(records) + 1  # Previous traversal had >2**24 paths.
    assert decision.allowed is not restricted
    assert len(decision.reasons) <= 1
    assert sum(map(len, decision.reasons)) < 128


def test_batch_memo_cannot_mask_restrictive_metadata_with_same_identity(root):
    allowed = source()
    restricted = {**allowed, "usage_scope": "training_only"}
    decisions = UsageScopeGuard(root).check_many([allowed, restricted])
    assert [item.allowed for item in decisions] == [True, False]


def test_batch_checks_empty_registry_and_refreshes_after_same_size_update(root):
    guard = UsageScopeGuard(root)
    assert guard.check_many([]) == ()
    path = publish(root, [entry(sha256="c" * 64)])
    asset = source(sha256="b" * 64)
    assert guard.check_many([asset])[0].allowed
    metadata = path.stat()
    path.write_text(path.read_text(encoding="utf-8").replace("c" * 64, "b" * 64), encoding="utf-8")
    os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    assert not guard.check_many([asset])[0].allowed
    path.write_text("{", encoding="utf-8")
    with pytest.raises(UsageScopeError, match="TRAINING_REGISTRY_INVALID"):
        guard.check_many([])


@pytest.mark.parametrize("budget", ["MAX_SOURCE_NODES", "MAX_SOURCE_EDGES"])
def test_source_graph_node_and_edge_budgets_fail_closed(root, monkeypatch, budget):
    import packages.contracts.usage as usage
    records, derived = layered_aliases(4)
    monkeypatch.setattr(usage, budget, 5)
    deny(root, derived, "USAGE_SOURCE_CONFLICT", source_assets=records)


def test_memoized_subtree_still_enforces_longest_source_depth(root):
    # Compute shorter chains first so every subsequent parent is already memoized.
    records = [source(asset_id=f"depth-{i}", sha256=f"{i + 1:064x}", relative_path=f"data/raw/depth-{i}.mp4",
                      provenance={"source_asset_id": f"depth-{i - 1}"} if i else {}) for i in range(130)]
    with pytest.raises(UsageScopeError, match="USAGE_SOURCE_CONFLICT"):
        UsageScopeGuard(root).check_many(records)
