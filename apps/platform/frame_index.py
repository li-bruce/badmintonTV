"""Bounded-memory pages over legacy library probe PTS JSONL.

The legacy format has no random-access index: page reads remain O(file size) to
verify its hash and count, but retain only a page plus one lookahead frame.
New media proxies use their indexed SQLite reader instead.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from packages.runtime import resolve_relative_path

MAX_PAGE_FRAMES = 1000
MAX_LEGACY_INDEX_BYTES = 64_000_000  # Same bound as library's legacy probe writer.
MAX_ROW_BYTES = 65_536


@dataclass(frozen=True)
class _Frame:
    number: int
    pts: int
    start: Fraction
    end: Fraction

    def as_source(self) -> dict[str, Any]:
        return {"source_frame_index": self.number, "source_pts": self.pts,
                "source_pts_ms": float(self.start), "source_end_ms": float(self.end)}

    def as_label_studio(self) -> dict[str, Any]:
        # Preserve the existing LS integer boundary convention exactly; never
        # round via a float or infer timing from the source/nominal frame rate.
        return {"ls_frame": self.number + 1, "source_start_ms": int(self.start),
                "source_end_ms": int(self.end), "source_pts": self.pts}


def _integer(value: Any, name: str, low: int, high: int | None = None) -> int:
    if type(value) is not int or value < low or (high is not None and value > high):
        raise ValueError(f"{name} must be an integer in {low}..{high if high is not None else 'unbounded'}")
    return value


def _scan(asset: dict[str, Any], storage_root: str | Path, *, offset_frame: int,
          limit: int, at_ms: float | None = None, full_export: bool = False):
    offset_frame = _integer(offset_frame, 'offset_frame', 0)
    limit = _integer(limit, 'limit', 1, MAX_PAGE_FRAMES)
    index = asset.get('probe', {}).get('pts_index') or {}
    if not isinstance(index, dict):
        raise ValueError('PTS index metadata must be an object')
    if index.get('complete') is not True or not index.get('relative_path'):
        raise ValueError('没有完整原片PTS索引，不能推算标注帧时间')
    if index.get('format', 'jsonl') != 'jsonl':
        raise ValueError('legacy PTS index must use JSONL')
    declared_count = index.get('frame_count')
    if declared_count is not None:
        _integer(declared_count, 'PTS frame_count', 1)
        if full_export and declared_count > MAX_PAGE_FRAMES:
            raise ValueError('Label Studio完整映射最多1000帧，请先生成小段代理映射；UI请使用源帧分页')
    duration = _integer(asset.get('duration_ms'), 'duration_ms', 1)
    try:
        time_base = Fraction(asset['time_base'])
        target = Fraction(str(at_ms)) if at_ms is not None else None
        if time_base <= 0 or (target is not None and target < 0):
            raise ValueError
        if index.get('time_base') is not None and Fraction(index['time_base']) != time_base:
            raise ValueError
    except (ValueError, TypeError, ZeroDivisionError, KeyError):
        raise ValueError('PTS time_base or at_ms is invalid/inconsistent') from None
    path = resolve_relative_path(storage_root, index['relative_path'], must_exist=True)
    if not path.is_file():
        raise ValueError('PTS index path must name a JSONL file')
    if path.stat().st_size > MAX_LEGACY_INDEX_BYTES:
        raise ValueError('旧PTS JSONL超过64MB上限，请生成带分页索引的小段代理')
    checksum = hashlib.sha256()
    frames: list[_Frame] = []
    count = 0
    consumed = 0
    origin = None
    previous = None
    selected_offset = None if target is not None else offset_frame

    def take(number, pts, start, end):
        nonlocal selected_offset
        if not 0 <= start < end <= duration:
            raise ValueError('源PTS边界必须递增并位于原片时长内')
        if target is not None and selected_offset is None and (start <= target < end or number == count - 1 and end == duration):
            selected_offset = number
        if selected_offset is not None and selected_offset <= number < selected_offset + limit:
            frames.append(_Frame(number, pts, start, end))

    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        while True:
            raw = stream.readline(MAX_ROW_BYTES + 1)
            if not raw:
                break
            consumed += len(raw)
            if len(raw) > MAX_ROW_BYTES or consumed > MAX_LEGACY_INDEX_BYTES:
                raise ValueError('PTS JSONL行或文件超过读取上限')
            checksum.update(raw)
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
                pts = row['pts']
                if type(pts) is not int:
                    raise ValueError
                if 'frame_index' in row and (type(row['frame_index']) is not int or row['frame_index'] != count):
                    raise ValueError
            except (ValueError, TypeError, KeyError, UnicodeDecodeError):
                raise ValueError(f'PTS JSONL frame {count} has invalid integer PTS/ordinal') from None
            if origin is None:
                origin = pts
            start = (pts - origin) * time_base * 1000
            if previous is not None:
                take(*previous, start)
            previous = (count, pts, start)
            count += 1
            if full_export and count > MAX_PAGE_FRAMES:
                raise ValueError('Label Studio完整映射最多1000帧，请先生成小段代理映射；UI请使用源帧分页')
        if previous is None:
            raise ValueError('PTS索引为空')
        take(*previous, Fraction(duration))
        after = os.fstat(stream.fileno())
    current = path.stat()
    identity = lambda stat: (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    if identity(before) != identity(after) or identity(before) != identity(current):
        raise ValueError('PTS索引在读取期间发生变化')
    digest = checksum.hexdigest()
    if index.get('sha256') and digest != str(index['sha256']).lower():
        raise ValueError('PTS索引hash不符')
    if declared_count is not None and declared_count != count:
        raise ValueError('PTS索引实际帧数与声明不符')
    return frames, count, selected_offset, digest, time_base, duration


def read_source_frame_page(asset: dict[str, Any], storage_root: str | Path, *,
                           offset_frame: int = 0, limit: int = 128,
                           at_ms: float | None = None) -> dict[str, Any]:
    """Return <=1000 global zero-based source frames with one-frame lookahead.

    at_ms takes precedence over offset_frame and selects the containing frame;
    a target at/after the end selects the last frame, matching proxy pagination.
    Hash/count verification scans the entire bounded file without accumulating it.
    """
    frames, total, offset, digest, time_base, duration = _scan(
        asset, storage_root, offset_frame=offset_frame, limit=limit, at_ms=at_ms)
    return {'source_frames': [frame.as_source() for frame in frames], 'total': total,
            'offset_frame': offset, 'limit': limit, 'mapping_id': 'pts-' + digest[:20],
            'source_time_base': str(time_base), 'source_duration_ms': duration}


def read_label_studio_frame_map(asset: dict[str, Any], storage_root: str | Path) -> dict[str, Any]:
    """Legacy-compatible complete LS map, only after proving <=1000 real frames."""
    frames, _, _, digest, _, duration = _scan(
        asset, storage_root, offset_frame=0, limit=MAX_PAGE_FRAMES, full_export=True)
    from .labelstudio import FrameMap
    return FrameMap.from_dict({'mapping_id': 'pts-' + digest[:20],
                              'source_duration_ms': duration,
                              'frames': [frame.as_label_studio() for frame in frames]}).as_dict()
