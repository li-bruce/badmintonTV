# badmintonTV

本地优先的羽毛球技战术视频检索与集锦工作台。V1：中文描述 → 可复核候选 → 人工确认 → 竖屏 MP4；V2：示例视频与动作相似检索。

工作台用于整理比赛、标注动作、检索片段和制作集锦。普通电脑可播放、标注与CPU剪辑，模型数据准备和GPU模型开发分别使用独立环境。

先看[标注使用指南](docs/FRAMEWORK_GUIDE.md)。需要换设备或单独开发一个模块，查看[模块输入输出与设备分工](docs/MODULES_AND_DEVICES.md)、[迁移指南](docs/MIGRATION_GUIDE.md)和[部署命令](docs/deployment/README.md)。完整源码、模块源码与Git历史分别打包；不包含视频、权重、数据库或虚拟环境。

2026-10-19本轮改版、打包和部署的实际结果见[验收记录](docs/ROUND_VALIDATION_2026-10-19.md)。细技法训练仍需合格标注、独立比赛划分和专门训练器，不能把GPU环境就绪当成识别能力达标。

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

历史版本的回归、研究样片和GPU特征实验分别保留在验收文档中；它们不代替当前版本或新设备实测。模块启动、验证与限制见 `docs/library/`、`docs/models/`、`docs/render/`，集成状态见 `docs/STATUS.md`。
