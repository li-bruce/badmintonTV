# Platform 状态

2026-09-28 23:30 更新。任务 01a0e88b-2410-7da0-970e-7f4187ed485f；cwd C:/Users/USER/.codex/worktrees/6991/badmintonTV；branch work/platform。

- 设计：已读全部基线文档，见 docs/platform/DESIGN.md。
- 已实现：v1 Pydantic合同/JSON Schema/标准fixtures；FastAPI+页面；SQLite库/素材/球员/事件修订/候选/时间线；规则查询；环境变量LLM遮盖与连接测试；持久worker、attempt/租约/取消子树/真实进度；LS任务导出/PTS转换/原始归档/修订回写。
- 已运行：合同64 passed；API12 passed；runtime24 passed/1 symlink skipped；LS10 passed。独立worker真实原片hash/ffprobe/缩略图通过；4真实视频已导入18080。Label Studio 1.23.1真实Edge完成TimelineLabels31–48→31–60、VideoRectangle31/41帧改框、导出→平台revision2 [1000,2000)回写，保留未知标签，LS重启持久通过。
- 失败：沙箱 Git 元数据不可写，使用按命令 safe.directory 和授权写入；不修改全局 Git 配置。
- 最终已验证：141 passed/1 skipped；真实Edge标注→QuerySpec→3候选确认→标题/0.75倍速时间线→worker render成功，job-3ebf04b748644087b1328283382df830/attempt-1，14.833333s、1080x1920、445帧、H264/AAC、4产物hash及完整解码均通过。研究样片明确未获human技术确认。真实服务重启后标注/LS三版历史保留；CPU模型CLI显式retry attempt2成功。
- 未测：真实LLM端点未提供；GPU共享租约/WSL launcher未实现，平台明确blocked；个人录像/专家细技术真值缺失。
- 阻塞：无阻塞人工流程的外部条件；跨WSL模型未安装能力保持不可用。
- 下一步：主协调审查集成；按专家真值、GPU租约与实际LLM端点补后续能力。不要将Agent区间审阅当技术真值。
- 提交 SHA：6a3e3deb4ff34bf4eb22f18d20e995f9e8d28e1d（统一合同，可独立集成）；业务待提交。
- 启动：./start-platform.ps1（18080）；./start-worker.ps1；Label Studio实际18081，命令见 docs/platform/LABEL_STUDIO.md。
- 环境/容量：Windows Python3.12.11；D:/video/runtime/platform/env独立venv，FastAPI0.141.1/Pydantic2.13.5；锁定清单docs/platform/requirements-lock.txt。实际platform约2,711,054bytes/60GB；runtime/platform约1,047,249,473bytes/10GB（含LS约994MB与所有pip缓存）。任务协议/日志峰值预留当前128MB，日志单attempt上限8MB。只读复用FFmpeg9.0.2；无GPU。computer-use技能使用本机Edge，未新增插件。
- handoff：D:/video/platform/handoff/platform-real-flow.json、platform-restart-check.json、events.v1.json、assets-imported.v1.json；成片由render owner持有，路径见VALIDATION.md。
