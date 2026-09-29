# Null output time-base diagnostic

The CPU decode check produced a false failure in this bounded window: six null
muxer DTS errors disappeared when only the output encoder time base was changed
to `-enc_time_base:v demux`. Both runs decoded 3006 frames and completed with exit
code 0. All error rejection remains enabled, including `-xerror`, `-v error`, and
rejection of any nonempty decode stderr. This is a 120-second diagnostic, not
whole-file acceptance or a claim that the entire source has valid timestamps.

The source is asset SHA-256
`80d9c5be022baef9ce57773cbadfb28647d8e11c651fc4528eec5d8e7b32c4b7`,
as recorded by its existing verified extraction receipt. This diagnostic did not
rehash the full 1,055,036,097-byte video; source size and mtime were unchanged.
Exact commands, log hashes and summaries are in [summary.json](summary.json).
All three commands used the installed FFmpeg 9.0.2 tools, CPU and one thread.
No media was written and there were no writes to `D:/video`.

| Check | Result |
| --- | --- |
| A, original command, `-ss 3400 -t 120` | 3006 decoded frames; six DTS errors; stderr 746 bytes |
| B, same command plus `-enc_time_base:v demux` | 3006 decoded frames; stderr empty |
| C, independent source frame timestamps | 3006 frames; zero non-increasing PTS pairs; deltas 1800–3600 ticks at 1/90000 |

FFprobe interval seeking starts at an earlier keyframe. C's actual sampled source
range is 3395.840000–3515.820000 seconds; it overlaps but does not have identical
bounds to A/B. Its full raw frame inventory is preserved under
`D:/video/data/training/fine-badminton-2026-zenodo-20292976-v1.0/diagnostics/window-timebase-20260929/`,
with bytes/hash and the recorded workspace-to-training move in `summary.json`;
raw source frame data is kept out of Git. Complete A/B stdout/stderr logs remain
alongside this report. The original whole-file failure log was not
fully retained by the caller; these logs reproduce the failure mechanism locally.

The source nominal frame rate is 25/1, but the observed window includes 1800-tick
(20 ms) gaps. FFmpeg documents the default video encoder time base as reciprocal
frame rate and `demux` as the demuxer time base. A 1/25 output clock cannot
represent all those distinct timestamps. `fps_mode passthrough` alone does not
select that finer clock. See the official [encoder time-base and frame timing
options](https://ffmpeg.org/ffmpeg.html#Advanced-options).
The official implementation selects a default reciprocal-frame-rate time base
and rescales frame timestamps before the passthrough decision in
[`choose_out_timebase`, `adjust_frame_pts_to_encoder_tb`, and `video_sync_process`](https://ffmpeg.org/doxygen/trunk/ffmpeg__filter_8c_source.html).
The [null muxer](https://ffmpeg.org/doxygen/trunk/nullenc_8c_source.html) uses the
wrapped-frame encoder. The A/B evidence supports output time-base quantization
as the cause in this window; an independent complete source PTS scan and full
decode with the corrected command are still required for publication.

The regression tests keep output timestamp precision, selected-stream mapping,
CPU settings and strict rejection explicit. Unsupported encoder time-base options
fail closed; there is no retry using a coarser clock or ignored stderr.

Validation: `C:/Users/USER/miniforge3/python.exe -m unittest
tests.library.test_probe tests.library.test_manifest -v` passed all 29 tests on
2026-09-29, including the three new command/failure regressions. Those unit tests
mock subprocess output; the A/B logs above supply the separate real-media check.
