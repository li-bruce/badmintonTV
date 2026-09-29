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
- `export_preset`：`portrait_1080p30`（默认）或`portrait_1080p60`，均1080×1920 H.264/yuv420p/AAC48k。显式Timeline.output须与命名档一致，否则preset_conflict；不指定命名档时保留旧24/25/30/50/60输入。30fps封顶8M/缓冲16M，50/60fps12M/24M，实际文件码率受内容影响。
- `platform_profile="youtube_shorts"`：可选，仅此档要求按最终总帧数/帧率计算的成片≤180秒，包含慢放效果。其他平台不自动套用此限制；平台上传接受仍未测试。
- `safe_area`：可选归一化`{x:0.06,y:0.10,width:0.82,height:0.78}`，调节标题/字幕/说明的边距和大小，供UI绘制覆盖层；不烧入辅助框，也不裁比赛画面。这是产品默认布局，不是跨平台官方安全区保证。
- `preview=true`：实际360×640轻量输出，时间/构图逻辑一致；保存的Timeline仍为1080×1920正式工程，实际尺寸记在QA/source_map。
- `research_preview=true`：未人工确认的本地研究演示，画面加固定说明；默认false。
- `merge_overlaps=true`：仅合并相邻、同源且编辑设置相同的重叠窗口；审核状态取保守结果，原区间与全部审核者来源保留，任一未确认不会自动升级。
- `deduplicate_replays=true`：仅按人工提供的显式replay_group_id去重，不自动识别回放。
- `segment_options`：以segment_id为键，每项可含`subtitles`（片段输出毫秒）、`replay_group_id`、`editorial_review`（含reviewer_type）。所有扩展保存在source_map；恢复工程须连同扩展加载。

输出4个已校验Artifact：video/mp4、timeline、source_map、qa_report。Timeline可直接过统一合同；source_map记录源hash、原片毫秒、time_base/start_pts、library PTS索引引用、速度、输出帧边界、量化误差及去重回查。QA的技术通过不表示手法正确或可公开发布。

预设、安全区和平台profile扩展也保存在source_map的`editorial_metadata.preset`及原始request；重载工程须恢复这些parameters。Timeline本身仍只保存合同允许的正式输出规格，360×640预览不改变1080×1920工程。

## 后端与训练用途隔离

管理员使用`BTV_RENDER_BACKEND=cpu|nvenc|auto`或独立CLI `--backend`，默认cpu。请求JSON不能覆盖可信后端。CPU/NVENC均使用CPU解码、ASS字幕、缩放和补边；NVENC只加速H.264编码，未启用NVDEC。30fps转60fps不增加真实动作信息。

nvenc/auto必须通过同一`D:/video/platform/runtime.sqlite3`窗口+worker作业租约。worker注入`BTV_RUNTIME_DB/BTV_GPU_LEASE_ID`，render只读核对job/attempt/worker/model/resource/截止时间，并在运行中持续检查。管理员runner见`docs/platform/CONTROLLED_GPU_RUN.md`；不能只grant窗口后直接运行FFmpeg。编码器以实际输出尺寸/帧率做短可用性预检：nvenc初始化失败明确blocked/backend_unavailable；auto仅对此预检的编码失败回退CPU，原因记录在backend.json和QA。实际分段开始后的失败、取消或租约失效均停止作业，不重跑或降级。CQ21与CRF21不是质量等价承诺。

平台优雅取消使用可信环境变量`BTV_RENDER_CANCEL_FILE`，绝对路径必须精确对应当前`platform/jobs/<job_id>/<attempt_id>/cancel.request`；文件存在即取消，无内容格式要求。此可信env优先于独立CLI `--cancel-file`，后者继续限定render下相对路径。取消时等待本次FFmpeg停止，再释放本模块容量锁。

使用包含共享合同依赖的`D:/video/runtime/platform/env/Scripts/python.exe`运行。原片检查在合并/去重前覆盖每一个原始引用：共享用途helper检查typed/provenance、逻辑/物理保留路径、受信注册表以及实际文件hash。training_only即使confirmed、preview或research_preview仍拒绝；registry损坏/待发布时fail closed。独立CLI也执行同一门禁。没有安装训练框架或修改共享Conda。

QA新增实际avg/r帧率、progressive field_order、moov早于mdat的faststart、requested/effective backend和阶段命令/耗时。技术QA、平台上传、人工业务审核和公开权利仍分别记录。

## 已交付真实样片

最终hand-off：`D:/video/render/handoff/real-research-e071063a44/`，含request/result/progress/handoff。

MP4：`D:/video/render/jobs/real-research-e071063a44/attempt-01/export.mp4`，17.066667秒、512帧、1080×1920、1,010,245 bytes；SHA256 `1285574d32d6300fc6051d45c064329e89011ac64b04c7a1165e927080ebf5e8`。

3段均保留现有小片段完整窗口：video_001951原速6秒，video_000002 0.75x约7.166667秒，video_000003原速3.9秒。来源为library FineBadmintonBenchmark Asset，完整场次原时间未知；映射只承诺回到已下载片段。原片无音轨，成片补静音。细手法unknown、身份未确认、原画面rights unknown、人工观看待做。不能称为“2–3段已人工确认技法”的完整业务验收。

原片联系表与输出联系表分别位于`D:/video/render/review/first-samples/`、`D:/video/render/review/real-output/contact.png`；已由agent查看，确认全场、两端球员、中文字幕可见。最终MP4 hash与被查看版本相同。

测试与限制见 `VALIDATION.md`；来源/许可证见 `RESEARCH.md`、`ENVIRONMENT.md`；没有安装OTIO/自动剪辑/目标跟随模型。当前JSON工程与FFmpeg承担实际交付，OTIO仅评估为后续互操作增强。
