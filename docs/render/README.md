# Render 初版交接

这是工作流末端的无Python第三方依赖模块；源码在 `packages/render`，不写业务数据库，不使用GPU，不复制library原片。Windows/Python3.12/FFmpeg9.0.2已运行；其他系统需配置本机FFmpeg与中文字体后另验。

## 直接调用

以下PowerShell从仓库根运行。共享platform虚拟环境只读复用；不向base安装依赖。FFmpeg安装位置以环境清单为准。

```powershell
$renderRuntime = Get-Content environments/render-runtime.json -Raw | ConvertFrom-Json
$env:BTV_FFMPEG = $renderRuntime.checks.ffmpeg
$env:BTV_FFPROBE = $renderRuntime.checks.ffprobe
$env:BTV_STORAGE_ROOT = 'D:/video'
& D:/video/runtime/platform/env/Scripts/python.exe -B -m packages.render run `
  --request configs/render/real-research.request.json `
  --result D:/video/render/handoff/example-real-research.result.json `
  --cancel-file render/handoff/example-real-research.cancel
```

例子引用真实只读Asset，需library原片已存在。每次重跑先在请求中换job_id/attempt_id/output_dir，并选择新result路径；已有目录与文件会拒绝覆盖。`scripts/render/real_demo.py` 自动生成唯一ID，可直接重现本次三段研究样片。

不同cwd可把本仓库根加入管理员 `PYTHONPATH` 后使用同一argv；`packages`是namespace package。受控worker传参数数组，不拼接shell。`BTV_FFMPEG/BTV_FFPROBE`只接受管理员配置的二进制；request不能传过滤器/程序。

Python接口：

```python
from pathlib import Path
from packages.render import RenderConfig, render
cfg = RenderConfig(Path('D:/video'), ffmpeg_path, ffprobe_path,
                   cancel_file=Path('D:/video/render/handoff/job.cancel'))
result = render(request_dict, cfg, emit=save_progress, cancelled=is_cancel_requested)
```

request/result必填attempt_id；stdout严格ProgressEvent JSONL，seq递增；退出码0成功、1失败、2阻塞、130取消。进度按实际FFmpeg输出时间，完成依据result+退出码。取消文件在编码时约0.2秒轮询，终止并等待本任务FFmpeg；强制kill未写result须由平台记录中断，残留锁需先查PID，再由管理员处理。

## 编辑设置

基础Timeline数组控制排序；毫秒边界直接裁切原片；speed范围0.125–8；默认contain，crop使用0..1的显式窗口（旋转视频或非方像素crop暂拒绝）。最终尺寸1080×1920；fps支持24/25/30/50/60；H264/AAC固定。

参数均放`parameters`：

- `timeline`：canonical Timeline。
- `preview=true`：360×640轻量输出，时间/构图逻辑一致。
- `research_preview=true`：未人工确认的本地研究演示，画面加固定说明；默认false。
- `merge_overlaps=true`：仅合并相邻、同源且编辑设置相同的重叠窗口。
- `deduplicate_replays=true`：仅按人工提供的显式replay_group_id去重，不自动识别回放。
- `segment_options`：以segment_id为键，每项可含`subtitles`（片段输出毫秒）、`replay_group_id`、`editorial_review`（含reviewer_type）。所有扩展保存在source_map；恢复工程须连同扩展加载。

输出4个已校验Artifact：video/mp4、timeline、source_map、qa_report。Timeline可直接过统一合同；source_map记录源hash、原片毫秒、time_base/start_pts、library PTS索引引用、速度、输出帧边界、量化误差及去重回查。QA的技术通过不表示手法正确或可公开发布。

## 已交付真实样片

最终hand-off：`D:/video/render/handoff/real-research-e071063a44/`，含request/result/progress/handoff。

MP4：`D:/video/render/jobs/real-research-e071063a44/attempt-01/export.mp4`，17.066667秒、512帧、1080×1920、1,010,245 bytes；SHA256 `1285574d32d6300fc6051d45c064329e89011ac64b04c7a1165e927080ebf5e8`。

3段均保留现有小片段完整窗口：video_001951原速6秒，video_000002 0.75x约7.166667秒，video_000003原速3.9秒。来源为library FineBadmintonBenchmark Asset，完整场次原时间未知；映射只承诺回到已下载片段。原片无音轨，成片补静音。细手法unknown、身份未确认、原画面rights unknown、人工观看待做。不能称为“2–3段已人工确认技法”的完整业务验收。

原片联系表与输出联系表分别位于`D:/video/render/review/first-samples/`、`D:/video/render/review/real-output/contact.png`；已由agent查看，确认全场、两端球员、中文字幕可见。最终MP4 hash与被查看版本相同。

测试与限制见 `VALIDATION.md`；来源/许可证见 `RESEARCH.md`、`ENVIRONMENT.md`；没有安装OTIO/自动剪辑/目标跟随模型。当前JSON工程与FFmpeg承担实际交付，OTIO仅评估为后续互操作增强。
