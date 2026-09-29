# 30/60fps CPU 预设基准入口

对应固定用例 **R-01a**。本文的直接CPU入口 `benchmark_presets.py` 已做语法与轻量逻辑检查，尚未运行真实媒体基准。另一个受控worker入口 `benchmark_nvenc.py` 已完成相同FFmpeg 8.0.1下CPU/NVENC各30/60fps首次及重复3次，共16个真实作业；详见[本轮结果记录](ROUND_2026-09-29_RESULTS.md)。技术成功不构成完整R-01a/R-03a验收PASS。

这16份结果位于 `D:/video/render/benchmarks/presets-controlled-cpu-7b61b195daf3/` 与 `D:/video/render/benchmarks/presets-controlled-nvenc-6e21d23d0d7f/`，已只读核对全部外层worker状态为succeeded、attempt=1，内层result为succeeded、attempt-1。受控入口现同时要求外层成功和attempt匹配，取消竞争不能仅凭内层CLI成功被计为性能成功样本。

固定输入是仓库 `configs/render/real-research.request.json` 中三个原有 general 研究小样，路径为 `data/raw/finebadmintonbenchmark/video_001951.mp4`、`video_000002.mp4`、`video_000003.mp4`。沿用原片段、0.75倍慢放、字幕、contain、未审核状态和研究预览标记；不从新 `data/training` 包取片，不提升为人工确认。

每次调用先对全部资产复用共享 `check_usage` 和 `verify_source_bytes`（含实际字节 SHA 的 registry 复核），通过后才创建批次或预留容量。固定旧路径不代表永久 general 资格；registry 后续标记训练用途时会拒绝。

## 预先固定的断言

- 30/60fps 均输出1080×1920、H.264 yuv420p、AAC 48kHz，CPU libx264，完整解码和 renderer QA 通过。
- 原片 asset/hash、起止时间与速度保持一致。输出帧连续，片段量化误差不超过半个输出帧；源映射和实际帧数一致。
- 保持 contain，安全区仅作为文字布局元数据，不烧入辅助线、不自动裁比赛画面。
- 以上为技术断言。完整视觉审阅、真实内容人工确认与平台上传验收分别保留 pending/not_tested，不由基准自动宣称通过。

## 调用

PowerShell，cwd 为 render 仓库工作树：

```powershell
& D:/video/runtime/platform/env/Scripts/python.exe scripts/render/benchmark_presets.py --backend cpu --repeats 3 --threads 4
```

可选 `--environment environments/render-runtime.json`、`--storage-root D:/video`。`--repeats` 为每种帧率首次观测之后的重复次数，默认3，范围1–10。默认执行顺序是30fps首次及3次重复，再执行60fps首次及3次重复，共8次。**不启用 GPU，不接受 nvenc/auto 后端。**

默认创建 `D:/video/render/benchmarks/presets-<uid>`。如中断，续跑：

```powershell
& D:/video/runtime/platform/env/Scripts/python.exe scripts/render/benchmark_presets.py --backend cpu --repeats 3 --threads 4 --batch-dir D:/video/render/benchmarks/presets-<uid>
```

相同批次必须保持参数、原请求、renderer/预设/时间线/backend/脚本代码哈希相同。两入口都会先计算FFmpeg和ffprobe实际二进制SHA256，并核对环境清单声明，再只运行 `-version` 保存完整版本输出；声明hash或版本不符即拒绝。直接CPU入口将解析后的程序路径、实际SHA与版本一并纳入续跑配置，同路径替换二进制也必须另开批次。缺少此指纹的旧批次不能续跑；不回填或改写历史实测记录。

续跑跳过已有 summary 的测试位，包括已记录失败的测试位；失败不会被覆盖成成功。尚未完成的测试位使用新 jobID，保留中断时的旧 request/result/媒体。修复失败原因后要重新得到完整可比基准，应启动新批次。批次锁 `.benchmark.lock` 与渲染 owner 锁分开；既有未清理锁要求人工核查，不自动删除。

## 结果与容量

批次目录内保存 `batch.json`、每次会话 `session-*.json`、每次独立的 `*.request.json` / `*.result.json` / `*.summary.json` 和只增不覆盖的 `batch-report-*.json`。每次媒体输出都在独立 `render/jobs/<job_id>/attempt-01`，沿用 renderer 的 MP4、QA、timeline、source_map 和编码阶段日志。

批次元数据总量硬上限2,000,000 bytes，每次写入先单独短时 reservation，再释放锁后调用 render；render 自己执行媒体容量预留。进度仅保留每阶段首末观测和事件计数，不累积全部 JSONL。不会复制源视频、删除已有数据或全局修改环境。

两入口和每次元数据写入都验证物理路径：storage root先resolve，render和benchmarks父目录不得经junction/symlink重定向，批次必须直接位于该benchmarks目录。指向根外、其他owner或其他父目录的别名会在写入与容量预留前拒绝。

summary 保存端到端时间、分阶段 subprocess 时间、输出大小/帧率/帧数/时长、预期与实际 checks、紧凑源映射及完整 QA/source_map 路径。重复运行汇总 min/median/mean/max。片段阶段同时包含解码、滤镜和编码，不能作为独立 NVDEC 或纯编码时延；其余引擎时间包含预检、哈希、探测及产物登记。

每次启动脚本会先读取三个源文件做 SHA-256 核验，操作系统缓存未清空，因此 `first_observed` 仅代表本批次该预设首次观测，**不是冷缓存**。30fps原片导出60fps可能复制帧，不增加真实动作细节。`full_case_status` 在人工视觉检查前保持 `NOT_RUN`，即使 `technical_status=PASS`。
