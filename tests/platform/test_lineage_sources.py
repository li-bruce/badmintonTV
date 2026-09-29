"""Production lineage verification with real synthetic bytes; no GPU/media tools."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.platform.store import Store
from packages.contracts import Asset, TRAINING_REGISTRY_PATH, UsageScopeError, assert_production_allowed
from packages.runtime import Queue
from packages.runtime import production


@pytest.fixture
def lineage(tmp_path, monkeypatch):
    root = tmp_path / "video"
    root.mkdir()
    store = Store(root / "platform/catalog.sqlite3", root)
    queue = Queue(root / "platform/runtime.sqlite3")
    queue.bind_business_database(store.path)
    monkeypatch.setenv("BTV_DB_PATH", str(store.path))
    return SimpleNamespace(root=root, store=store, queue=queue)


def asset(p, name, content, *, provenance=None, store=True):
    path = p.root / f"data/{name}.bin"
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(content)
    body = Asset.model_validate({"asset_id": name, "relative_path": path.relative_to(p.root).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content), "duration_ms": 1000,
        "width": 16, "height": 16, "match_id": "synthetic-lineage", "source_type": "synthetic",
        "provenance": provenance or {}}).model_dump(mode="json")
    if store:
        p.store.import_assets([body], "synthetic-library")
    return body


def derived(p, name, parent, *, store=True):
    return asset(p, name, (name + " synthetic derived bytes").encode(), store=store,
        provenance={"source_asset_id": parent["asset_id"], "source_sha256": parent["sha256"]})


def context(p, source, operation="render"):
    payload = {"assets": [source]} if operation in ("render", "model") else {"asset": source}
    return SimpleNamespace(storage_root=p.root, queue=p.queue,
        job={"job_id": "lineage-fixture", "attempt": 1, "operation": operation, "payload": payload},
        check=lambda: None, log=lambda *args, **kwargs: None)


def publish_training(p, content):
    path = p.root / TRAINING_REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "1.0", "assets": [{"asset_id": "registered-training",
        "relative_path": "data/training/synthetic/original.bin", "sha256": hashlib.sha256(content).hexdigest(),
        "usage_scope": "training_only"}]}), encoding="utf-8")


def track_media_reads(p, monkeypatch):
    reads = []
    original = Path.open
    def tracked(path, mode="r", *args, **kwargs):
        if str(mode) == "rb" and path.suffix == ".bin":
            reads.append(path.relative_to(p.root).as_posix())
        return original(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", tracked)
    return reads


@pytest.mark.parametrize("operation", ["render", "media_proxy", "exact_frame"])
def test_actual_training_parent_blocks_derived_with_matching_but_stale_claims(lineage, operation):
    p = lineage
    parent = asset(p, "parent", b"safe-source-a")
    child = derived(p, "derived", parent)
    training = b"train-bytes-x"
    assert len(training) == parent["size_bytes"]
    publish_training(p, training)
    (p.root / parent["relative_path"]).write_bytes(training)
    # Metadata remains mutually consistent: only opening the parent reveals it.
    assert_production_allowed(child, p.root, source_assets=p.store._raw_assets())
    with pytest.raises(UsageScopeError, match="TRAINING_ONLY"):
        production.check_job_sources(context(p, child, operation))


def test_model_diagnostics_skip_production_lineage_hashing(lineage, monkeypatch):
    p = lineage
    parent = asset(p, "parent", b"before-change")
    child = derived(p, "derived", parent)
    (p.root / parent["relative_path"]).unlink()
    monkeypatch.setattr(production, "_actual_source", lambda *args: pytest.fail("model diagnostics must remain separate"))
    production.check_job_sources(context(p, child, "model"))


def test_reachable_grandparents_verified_once_and_unrelated_missing_files_not_opened(lineage, monkeypatch):
    p = lineage
    grandparent = asset(p, "grandparent", b"synthetic original")
    parent = derived(p, "parent", grandparent)
    child = derived(p, "derived", parent)
    unrelated = asset(p, "unrelated", b"not on the lineage")
    (p.root / unrelated["relative_path"]).unlink()
    reads = track_media_reads(p, monkeypatch)
    production.check_job_sources(context(p, child))
    assert sorted(reads) == sorted([item["relative_path"] for item in (grandparent, parent, child)])


@pytest.mark.parametrize("bad", ["missing_file", "missing_size", "missing_sha", "changed_hash", "changed_size"])
def test_reachable_parent_missing_or_false_evidence_fails_closed(lineage, monkeypatch, bad):
    p = lineage
    parent = asset(p, "parent", b"initial parent")
    child = derived(p, "derived", parent)
    path = p.root / parent["relative_path"]
    if bad == "missing_file":
        path.unlink()
    elif bad in ("missing_size", "missing_sha"):
        records = p.store._raw_assets()
        records[0].pop("size_bytes" if bad == "missing_size" else "sha256")
        monkeypatch.setattr(production, "current_source_records", lambda _: records)
    elif bad == "changed_hash":
        path.write_bytes(b"x" * parent["size_bytes"])
    else:
        path.write_bytes(b"longer replacement source")
    with pytest.raises(ValueError, match="SOURCE_(UNAVAILABLE|METADATA_INVALID|CHANGED|CONFLICT)"):
        production.check_job_sources(context(p, child, "media_proxy"))


def test_id_only_parent_reference_verifies_all_same_hash_physical_aliases(lineage, monkeypatch):
    p = lineage
    parent = asset(p, "parent", b"safe-source-a", store=False)
    alias = asset(p, "alias", b"safe-source-a", store=False)
    child = asset(p, "derived", b"derived actual source", store=False,
                  provenance={"source_asset_id": parent["asset_id"]})
    # Exercise a legal metadata alias graph; Store currently deduplicates SHA.
    monkeypatch.setattr(production, "current_source_records", lambda _: [parent, alias, child])
    training = b"train-bytes-x"
    publish_training(p, training)
    (p.root / alias["relative_path"]).write_bytes(training)
    with pytest.raises(UsageScopeError, match="TRAINING_ONLY"):
        production.check_job_sources(context(p, child, "exact_frame"))


def test_shared_parent_dag_is_linear_in_nodes_and_hashes_each_file_once(lineage, monkeypatch):
    p, records = lineage, []
    for level in range(18):
        digest = records[-1]["sha256"] if records else None
        for variant in ("a", "b"):
            records.append(asset(p, f"node-{level}-{variant}", f"level-{level} actual bytes".encode(), store=False,
                provenance={"source_sha256": digest} if digest else {}))
    child = derived(p, "derived", records[-1], store=False)
    records.append(child)
    monkeypatch.setattr(production, "current_source_records", lambda _: records)
    reads = track_media_reads(p, monkeypatch)
    guard_calls, original_guard = [], production.assert_production_allowed
    def batch_guard(assets, *args, **kwargs):
        guard_calls.append(len(assets))
        return original_guard(assets, *args, **kwargs)
    monkeypatch.setattr(production, "assert_production_allowed", batch_guard)
    production.check_job_sources(context(p, child))
    assert len(reads) == len(records) == 37
    assert len(set(reads)) == 37
    assert len(guard_calls) == 2  # Metadata batch, then actual-byte batch; never per row.


def test_parent_alias_metadata_restriction_is_checked_before_reading_bytes(lineage, monkeypatch):
    p = lineage
    parent = asset(p, "parent", b"safe-source-a", store=False)
    alias = asset(p, "alias", b"safe-source-a", store=False)
    alias["usage_scope"] = "training_only"
    child = asset(p, "derived", b"derived bytes", store=False,
                  provenance={"source_asset_id": parent["asset_id"]})
    monkeypatch.setattr(production, "current_source_records", lambda _: [parent, alias, child])
    monkeypatch.setattr(production, "_actual_source", lambda *args: pytest.fail("metadata must block before file reads"))
    with pytest.raises(UsageScopeError, match="TRAINING_ONLY"):
        production.check_job_sources(context(p, child))


@pytest.mark.parametrize("budget", ["MAX_LINEAGE_NODES", "MAX_LINEAGE_EDGES"])
def test_lineage_work_budget_is_fail_closed_before_hashing(lineage, monkeypatch, budget):
    p = lineage
    parent = asset(p, "parent", b"synthetic parent")
    child = derived(p, "derived", parent)
    monkeypatch.setattr(production, budget, 1)
    monkeypatch.setattr(production, "_actual_source", lambda *args: pytest.fail("budget must be enforced before hashing"))
    with pytest.raises(UsageScopeError, match="USAGE_SOURCE_CONFLICT"):
        production.check_job_sources(context(p, child))


def test_unknown_external_reference_does_not_invent_parent_bytes(lineage, monkeypatch):
    p = lineage
    child = asset(p, "derived", b"available derived bytes",
                  provenance={"source_asset_id": "unknown-external-parent", "source_sha256": "f" * 64})
    reads = track_media_reads(p, monkeypatch)
    production.check_job_sources(context(p, child))
    assert reads == [child["relative_path"]]
