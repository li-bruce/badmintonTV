"""Pure export-preset validation for R-01a; no media processing or I/O.

Safe areas are editable application layout margins, not source crop rectangles
or a claim that every platform UI will leave those pixels unobstructed. The
returned metadata never requests guide lines to be burned into the video.
"""
from __future__ import annotations

import math


_PRESET_FPS = {"portrait_1080p30": 30, "portrait_1080p60": 60}
_OUTPUT_DEFAULTS = {
    "width": 1080, "height": 1920, "fps": 30,
    "video_codec": "h264", "audio_codec": "aac",
}
_SAFE_AREA_DEFAULT = {"x": 0.06, "y": 0.10, "width": 0.82, "height": 0.78}
_SHORTS_MAX_DURATION_MS = 180_000


def _require(condition, message, code="invalid_request"):
    if not condition:
        # Keep import-time dependency one-way if timeline starts consuming this
        # module. Errors still use the existing, public RenderError identity.
        from .timeline import RenderError
        raise RenderError(code, message)


def _profile(value):
    _require(value is None or (isinstance(value, str) and value == "youtube_shorts"),
             "platform_profile must be null or youtube_shorts")
    return value


def _safe_area(value):
    _require(isinstance(value, dict) and set(value) == set(_SAFE_AREA_DEFAULT),
             "safe_area must contain exactly x, y, width and height")
    result = {}
    for key in _SAFE_AREA_DEFAULT:
        number = value[key]
        _require(type(number) in (int, float) and 0 <= number <= 1 and math.isfinite(number),
                 f"safe_area.{key} must be a finite normalized number in 0..1")
        result[key] = float(number)
    _require(result["width"] > 0 and result["height"] > 0,
             "safe_area width and height must be positive")
    _require(result["x"] + result["width"] <= 1 and result["y"] + result["height"] <= 1,
             "safe_area must stay within the output frame")
    return result


def resolve_preset(parameters, timeline_output=None):
    """Return a new canonical output and encoding/layout metadata dictionary.

    ``parameters.export_preset`` optionally names ``portrait_1080p30`` or
    ``portrait_1080p60``. An explicitly supplied Timeline.output field must
    agree with an explicit preset; conflicts raise ``preset_conflict`` instead
    of silently overriding either input. Without a named preset, the previous
    explicit 24/25/30/50/60 fps choices remain supported. No fps means 30.

    Result keys:
      export_preset: matching named preset, or None for legacy 24/25/50 fps
      preset_explicit: whether the request actually named export_preset
      output: width, height, integer fps, video_codec, audio_codec
      maxrate, bufsize: FFmpeg rate-budget arguments (8M/16M or 12M/24M)
      video_bitrate_bps: numeric video budget for capacity estimates
      safe_area: normalized x/y/width/height; never a source crop
      burn_in_guides: always False
      platform_profile: None or youtube_shorts
      max_duration_ms: None or 180000

    50/60 fps receives the higher rate budget. Neither argument is mutated.
    Other request parameters, such as timeline or preview, are left to callers.
    """
    _require(isinstance(parameters, dict), "parameters must be an object")
    explicit = "export_preset" in parameters
    preset = parameters.get("export_preset")
    if explicit:
        _require(isinstance(preset, str) and preset in _PRESET_FPS,
                 "export_preset must be portrait_1080p30 or portrait_1080p60")
    provided = {} if timeline_output is None else timeline_output
    _require(isinstance(provided, dict), "Timeline.output must be an object")
    _require(set(provided) <= set(_OUTPUT_DEFAULTS),
             "Timeline.output contains unsupported export fields")
    expected = {**_OUTPUT_DEFAULTS, "fps": _PRESET_FPS[preset]} if explicit else _OUTPUT_DEFAULTS
    if explicit:
        for key, value in provided.items():
            _require(value == expected[key],
                     f"Timeline.output.{key} conflicts with export_preset {preset}",
                     "preset_conflict")
    output = {**expected, **provided}
    _require(output["width"] == 1080 and output["height"] == 1920,
             "export requires 1080x1920")
    _require(type(output["fps"]) in (int, float) and output["fps"] in (24, 25, 30, 50, 60),
             "unsupported output fps")
    output["fps"] = int(output["fps"])
    output["width"], output["height"] = 1080, 1920
    _require(output["video_codec"] == "h264" and output["audio_codec"] == "aac",
             "export requires h264/aac")
    if not explicit:
        preset = next((name for name, fps in _PRESET_FPS.items() if fps == output["fps"]), None)
    profile = _profile(parameters.get("platform_profile"))
    safe_area = _safe_area(parameters.get("safe_area", _SAFE_AREA_DEFAULT))
    high_rate = output["fps"] >= 50
    return {
        "export_preset": preset, "preset_explicit": explicit, "output": output,
        "maxrate": "12M" if high_rate else "8M",
        "bufsize": "24M" if high_rate else "16M",
        "video_bitrate_bps": 12_000_000 if high_rate else 8_000_000,
        "safe_area": safe_area, "burn_in_guides": False,
        "platform_profile": profile,
        "max_duration_ms": _SHORTS_MAX_DURATION_MS if profile == "youtube_shorts" else None,
    }


def validate_duration(duration_ms, platform_profile=None):
    """Validate final output duration after trimming, speed and frame quantization.

    Pass the duration derived from the final total frame count and fps. A finite
    nonnegative int/float is required. The optional youtube_shorts profile caps
    it at exactly 180000 ms; general exports have no profile duration limit.
    Returns None, or raises RenderError (``platform_duration_exceeded`` when the
    cap is exceeded, otherwise ``invalid_request`` for malformed arguments).
    """
    profile = _profile(platform_profile)
    finite_number = type(duration_ms) is int or (type(duration_ms) is float and math.isfinite(duration_ms))
    _require(finite_number and duration_ms >= 0,
             "output duration_ms must be a finite nonnegative number")
    if profile == "youtube_shorts":
        _require(duration_ms <= _SHORTS_MAX_DURATION_MS,
                 "youtube_shorts output duration must not exceed 180000 ms",
                 "platform_duration_exceeded")
