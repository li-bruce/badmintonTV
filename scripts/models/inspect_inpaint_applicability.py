"""Read-only, stdlib-only diagnostic for the frozen b210dc39 BST window.

No model import, pickle execution, network, GPU, or output-file write occurs.
The mask rule follows the MIT-licensed TrackNetV3 commit pinned below; it is
not a replacement policy and does not promote missing observations to points.
"""
import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import pickletools
import zipfile


COMMIT = "6eda442ada1740573f200f836d93edc9a541ee86"
SOURCE_SHA = "b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913"
POINTS = "models/jobs/job-d9c832fd94384ee3950918badc767b15/attempt-1/tracknet-points.json"
POINTS_SHA = "1984f48c7ef961b83f4d8296b5fc5eaca610d83993febe9aec93868833343db6"
CHECKPOINT_SHA = "5749b66b8002f3ad9e0af841604004706fc796df30599e6bf01952696009688c"
CODE_HASHES = {
    "model.py": "04fd51ff88e58189474677dbf11f81e52b78df00226fb97ea0678b31ef7284e3",
    "test.py": "420511325901bf25d5a28b101b1db994c5d6e4ab00a74d30e600a2e4f8b1d204",
    "predict.py": "ea338db0adc8d5ff89b0313b248d82c93b43ecb96cfefcc4ef44c542f462cf88",
    "dataset.py": "c8cf51f8fd59e466f3a1916ba99b24ac8b487ff85f69362ee72758b6b1643f92",
}
BST_START, BST_END = 3016, 3068  # Frozen before model missingness review.


def read_bounded(path, limit, expected_sha=None):
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if len(raw) > limit or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("Input exceeds bound or changed during reading")
    if expected_sha and hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError("Fixed case input hash mismatch: " + str(path))
    return raw


def checkpoint_literals(path):
    """Inspect only literal pickle opcodes; never call pickle.load/torch.load."""
    with zipfile.ZipFile(path) as archive:
        members = [x for x in archive.infolist() if x.filename.endswith("/data.pkl")]
        if len(members) != 1 or members[0].file_size > 100_000:
            raise ValueError("Unexpected checkpoint metadata member")
        ops = list(pickletools.genops(archive.read(members[0])))
    starts = [i for i, (_, arg, _) in enumerate(ops) if arg == "param_dict"]
    if len(starts) != 1:
        raise ValueError("Expected one literal checkpoint param_dict")
    tail = ops[starts[0] + 1:]
    result = {}
    for key in ("model_name", "seq_len", "mask_ratio"):
        locations = [i for i, (_, arg, _) in enumerate(tail) if arg == key]
        if len(locations) != 1:
            raise ValueError("Missing/ambiguous literal checkpoint parameter: " + key)
        i = locations[0] + 1
        while tail[i][0].name in {"BINPUT", "LONG_BINPUT", "MEMOIZE"}:
            i += 1
        opcode, value, offset = tail[i]
        if opcode.name not in {"BINUNICODE", "SHORT_BINUNICODE", "BININT", "BININT1", "BININT2", "BINFLOAT"}:
            raise ValueError("Parameter is not an inspectable literal: " + key)
        result[key] = {"value": value, "pickle_offset": offset, "opcode": opcode.name}
    if {key: value["value"] for key, value in result.items()} != {
            "model_name": "InpaintNet", "seq_len": 16, "mask_ratio": 0.3}:
        raise ValueError("Checkpoint is not the reviewed InpaintNet configuration")
    return result


def author_mask(rows, height):
    """Port test.py:223-258, preserving its strict i>1 boundary condition."""
    y = [r["y"] if r["status"] == "observed" else 0 for r in rows]
    visible = [int(r["status"] == "observed") for r in rows]
    mask = [0] * len(rows)
    i = j = 0
    while j < len(rows):
        while i < len(rows) - 1 and visible[i] == 1:
            i += 1
        j = i
        while j < len(rows) - 1 and visible[j] == 0:
            j += 1
        if j == i:
            break
        if i == 0 and y[j] > height * 0.05:
            mask[:j] = [1] * j
        elif (i > 1 and y[i - 1] > height * 0.05) and (j < len(rows) and y[j] > height * 0.05):
            mask[i:j] = [1] * (j - i)
        i = j
    return mask


def inspect(root):
    raw_manifest = read_bounded(root / "models/weights/tracknetv3/reuse-manifest.json", 100_000)
    manifest = json.loads(raw_manifest)
    if manifest["source_commit"] != COMMIT:
        raise ValueError("Unexpected upstream commit")
    for filename, digest in CODE_HASHES.items():
        read_bounded(root / f"models/upstream/tracknetv3/{COMMIT}/{filename}", 100_000, digest)
        if manifest["review_sources"][filename]["sha256"] != digest:
            raise ValueError("Manifest source hash does not match the reviewed source")
    checkpoint = root / "models/weights/tracknetv3/InpaintNet_best.pt"
    weight = read_bounded(checkpoint, 8_000_000, CHECKPOINT_SHA)
    if len(weight) != 6_264_451 or manifest["inpaint_checkpoint"]["sha256"] != CHECKPOINT_SHA:
        raise ValueError("Unexpected checkpoint identity")
    literals = checkpoint_literals(checkpoint)
    points = json.loads(read_bounded(root / POINTS, 100_000, POINTS_SHA))
    if points["source_sha256"] != SOURCE_SHA or points["usage_scope"] != "training_only":
        raise ValueError("Unexpected fixed source identity/scope")
    rows = points["frames"]
    if len(rows) != 75:
        raise ValueError("Expected the complete original 75-frame output")
    source_frames = []
    for i, row in enumerate(rows):
        frame = Fraction(row["pts"] - row["stream_start_pts"]) * Fraction(row["time_base"]) * 25
        if frame != 3000 + i or row["frame_index"] != i or (row["width"], row["height"]) != (1280, 720):
            raise ValueError("PTS/frame/dimension mismatch in fixed case")
        if row["status"] == "missing":
            if row["x"] is not None or row["y"] is not None:
                raise ValueError("Missing source observation must remain null")
        elif row["status"] != "observed" or not all(isinstance(row[k], (int, float)) and math.isfinite(row[k]) for k in ("x", "y")):
            raise ValueError("Unexpected observation status/coordinates")
        source_frames.append(int(frame))
    mask = author_mask(rows, 720)
    runs = []
    i = 0
    while i < len(rows):
        if rows[i]["status"] == "observed":
            i += 1
            continue
        end = i + 1
        while end < len(rows) and rows[end]["status"] == "missing":
            end += 1
        runs.append({"source_frames_inclusive": [source_frames[i], source_frames[end - 1]], "count": end - i,
                     "left_y": rows[i - 1]["y"] if i else None,
                     "right_y": rows[end]["y"] if end < len(rows) else None,
                     "official_mask_count": sum(mask[i:end])})
        i = end
    selected = [(i, row) for i, row in enumerate(rows) if BST_START <= source_frames[i] < BST_END]
    target_mask = sum(mask[i] for i, _ in selected)
    return {
        "schema_version": "1.0", "diagnostic": "static_inpaint_applicability_only",
        "status": "not_applicable_for_frozen_bst_window" if target_mask == 0 else "requires_review",
        "blocking_code": "official_mask_excludes_all_target_missing_frames" if target_mask == 0 else None,
        "source_commit": COMMIT, "asset_id": points["asset_id"], "usage_scope": "training_only",
        "source_sha256": SOURCE_SHA, "points_relative_path": POINTS, "points_sha256": POINTS_SHA,
        "checkpoint_size_bytes": len(weight), "checkpoint_sha256": CHECKPOINT_SHA,
        "checkpoint_static_literals": literals, "mask_threshold_source_y_px": 36.0,
        "source_frame_range": [3000, 3075], "observed": sum(r["status"] == "observed" for r in rows),
        "missing": sum(r["status"] == "missing" for r in rows), "missing_runs": runs,
        "eligible_source_frames": [frame for frame, bit in zip(source_frames, mask) if bit],
        "bst_frozen_source_frame_range": [BST_START, BST_END], "bst_frames": len(selected),
        "bst_observed": sum(r["status"] == "observed" for _, r in selected),
        "bst_missing": sum(r["status"] == "missing" for _, r in selected), "bst_mask_eligible": target_mask,
        "all_missing_16frame_window_starts": [source_frames[i] for i in range(len(rows) - 15)
                                              if all(r["status"] == "missing" for r in rows[i:i + 16])],
        "COOR_TH_normalized": 50 / math.sqrt(288 ** 2 + 512 ** 2),
        "model_loaded": False, "gpu_inference_run": False, "imputed_count": 0,
        "bst_reliability_changed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--storage-root", type=Path, default=Path("D:/video") if os.name == "nt" else Path("/mnt/d/video"))
    args = parser.parse_args()
    print(json.dumps(inspect(args.storage_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
