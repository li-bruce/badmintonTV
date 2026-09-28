# badmintonTV

本地优先的羽毛球技战术视频检索与集锦工作台。V1：中文描述 → 可复核候选 → 人工确认 → 竖屏 MP4；V2：示例视频与动作相似检索。

目前处于架构与并行实施启动阶段，尚未宣称模型准确率或产品完成。

- [原始简版计划](PROJECT_PLAN_SIMPLE.md)
- [产品需求与讨论核对](docs/PRODUCT_CONTEXT.md)
- [架构与完整工作流](docs/ARCHITECTURE.md)
- [跨模块数据合同](docs/CONTRACTS.md)
- [四任务分工、环境和容量预算](docs/EXECUTION_PLAN.md)
- [首批案例与验收](docs/ACCEPTANCE.md)
- [进度与问题记录](docs/STATUS.md)

代码进入 Git；视频、模型、数据库、缓存、训练产物和导出文件放 `D:\video`，WSL 路径为 `/mnt/d/video`。所有任务合计硬上限 **700,000,000,000 bytes（700 GB，约 652 GiB）**。

启动与测试命令由各模块实际实现后补充，不能把架构文档当作已经运行的功能。
