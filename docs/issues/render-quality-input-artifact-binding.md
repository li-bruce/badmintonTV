# 质量比较成片未绑定可信 Artifact（P2，已修复）

发现：2026-09-29 主任务独立复核。原 `quality_compare.preflight` 验证原请求的素材和来源链，但只要求输入成片存在。若保留原 request / QA / source_map 而替换 `export.mp4`，原检查可能通过；替换为 registry 已登记的 training-only 字节也未被实际成片门禁覆盖。

修复：质量脚本只接受固定 `platform/runtime.sqlite3` 中成功 render 作业当前 attempt 的 canonical 输出。以只读 SQLite 连接查询，不初始化 Queue；规范化后整体绑定 request 与账本 payload，并核对 result 身份、成功状态及 worker exit code。MP4 / timeline / source_map / QA 的种类、路径、唯一身份、实际大小和 SHA 均须匹配账本 Artifact。邻接 `result.json` 不能授权输入。账本及产物禁止物理重定向。

每个产物的实际 SHA 进入共享用途门禁；保留 producer 声明的来源关系并核验可达祖先实际字节，再逐一继承原始选片来源的用途。已登记训练字节在普通哈希不符报错之前返回 `TRAINING_ONLY`。这些检查均在运行 FFmpeg `-version`、容量预留和媒体进程之前。

参考重建另有两个未登记旁文件：`stage_timings.json` 必须完整匹配已绑定 QA 内的 timings；ASS 则从可信请求、时间线归一化和默认字体在内存中重新生成后比对。两臂同时篡改字幕不能通过。当前脚本仍仅支持既定三段、1080p30/60 contain 质量实验；自定义字体需要另行提供可信字体快照。

验证：新增 15 项无媒体回归（31 subtests）覆盖静态替换、作业和请求身份、Artifact 元数据、producer 来源以及旁文件边界，全部通过；真实 Windows junction 测试未跳过。完整 render 回归 165 passed / 1 旧 timeline symlink 权限 skipped / 409 subtests passed。四个已有真实输入（CPU/NVENC × 30/60fps）于 10:12 UTC 只读通过产物、来源、ASS 和命令核对，记录见 `docs/render/QUALITY_INPUT_AUDIT_2026-09-29.json`。未重跑 16 个基准或质量媒体，未改原始报告、共享账本、registry、环境或 GPU 排期。此修复以平台账本为信任边界，不声称可防御并发修改账本/文件的恶意本机进程。
