# badmintonTV

本地优先的羽毛球技战术视频检索与集锦工作台。V1：中文描述 → 可复核候选 → 人工确认 → 竖屏 MP4；V2：示例视频与动作相似检索。

四个模块已集成到 main，可运行的第一版研究工作台已交付。真实素材、Web 标注检索、竖屏成片与 WSL GPU 特征提取已有实测；细手法识别尚无合格真值，不能宣称准确率或完整产品验收。

- [本机启动与第一条工作流](docs/QUICKSTART.md)
- [原始简版计划](PROJECT_PLAN_SIMPLE.md)
- [产品需求与讨论核对](docs/PRODUCT_CONTEXT.md)
- [架构与完整工作流](docs/ARCHITECTURE.md)
- [跨模块数据合同](docs/CONTRACTS.md)
- [四任务分工、环境和容量预算](docs/EXECUTION_PLAN.md)
- [首批案例与验收](docs/ACCEPTANCE.md)
- [各阶段目标与达标状态](docs/STAGE_ACCEPTANCE.md)
- [短视频工具、交互加速与模型复用调研](docs/REUSE_RESEARCH_2026-09-29.md)
- [进度与问题记录](docs/STATUS.md)

代码进入 Git；视频、模型、数据库、缓存、训练产物和导出文件放 `D:\video`，WSL 路径为 `/mnt/d/video`。所有任务合计硬上限 **700,000,000,000 bytes（700 GB，约 652 GiB）**。

主分支统一回归 478 项通过、5 项条件跳过；浏览器提交查询和渲染任务、播放完整 14.83 秒竖屏研究样片通过。证据见 [集成验证](docs/INTEGRATION_VALIDATION.json)。模块启动、验证与限制见 `docs/library/`、`docs/models/`、`docs/render/`，平台集成状态见 `docs/STATUS.md`。主分支验收与各模块工作树实测分开记录。
