# 项目协作约定

先读 `PROJECT_PLAN_SIMPLE.md` 和 `docs/PRODUCT_CONTEXT.md`、`docs/ARCHITECTURE.md`、`docs/CONTRACTS.md`、`docs/EXECUTION_PLAN.md`、`docs/ACCEPTANCE.md`。用户最新要求优先。

涉及设备迁移、独立模块开发或环境部署时，再读 `docs/MODULES_AND_DEVICES.md`、`docs/MIGRATION_GUIDE.md` 和 `docs/deployment/README.md`。从源码包开始时还要读包内 `CONTINUE_DEVELOPMENT.md` 与 `source-manifest.json`；源码ZIP没有Git历史，不能把重新git init说成恢复原历史。

## 工作方式

- 这是同一个产品的四个模块，不是四个独立应用。先设计接口和数据流，再开发、运行和验证。
- 任务使用各自 Git worktree/分支。只提交自己模块的改动，不覆盖他人文件，不重置用户改动，不使用 `git add .` 收入未知文件。主任务负责集成到 main。
- 如 worktree 为 detached HEAD，在本地创建 `work/<module>` 分支（如已存在则使用不冲突的后缀），不对其他 worktree 切分支。不要自行推送、创建远程仓库或发布视频。
- 每个任务须在 `docs/status/<module>.md` 持续写真实进展：设计、已实现、已运行、失败、未测、阻塞、下一步、提交 SHA、启动命令、环境/端口和容量。
- 每阶段按 `docs/STAGE_ACCEPTANCE.md` 的固定用例 ID 记录目标要求、验证方法/输入、预期结果、实际结果、PASS/FAIL/BLOCKED/NOT_RUN、证据及未达标原因/下一步。模块状态引用对应 ID，主任务维护阶段总表；全部必需项 PASS 才算该阶段达标，跳过、代码存在、agent 审阅与模型特征成功不能替代对应真实验收。新目标先写断言再开发，不悄悄降低门槛。
- 有问题单独写 `docs/issues/<module>-<slug>.md`；模型逐次实验写 `docs/experiments/`，记录失败也有价值。不能用合成数据的成功冒充真实视频识别成功。
- 需要技能/MCP时自行选择可用工具，读对应 SKILL.md；记录安装来源、版本、用途和环境。平台依赖不为训练框架背负冲突版本。

## 数据和资源

- 硬上限为所有任务总体700十进制GB；固定分区配额见 EXECUTION_PLAN。预算包含下载临时文件、解压双份、权重、缓存、环境、数据库、导出。
- 大文件只放 `D:\video` / `/mnt/d/video`；已有文件不可无记录删除或覆盖。写入前预估峰值、检查目录额度和磁盘剩余，流式下载需限制实际字节数。
- 上述D盘路径是当前设备配置。迁移设备必须显式配置storage root，并维持相同owner目录、相对路径及额度；复制的数据也记录容量，不因换设备另领700GB。不要复制旧虚拟环境；不要跨系统或同步盘共享正在运行的SQLite/WAL。
- 不把数据、凭据、权重、虚拟环境或媒体放进 Git。资料引用用 manifest 的 asset_id 和相对路径。原片只读引用，避免每个工作树复制。
- 模型任务负责共享 WSL Conda runtime 建立；其他任务不同时安装 Conda。等待时可在本任务 `.venv` 中进行轻量开发。训练只能用 WSL Ubuntu 隔离环境，不改全局 Python/驱动。
- 初始阶段 models 任务持有GPU实验排期；其他任务默认CPU渲染/测试，需要GPU先协调，不同时启动抢显存的大模型。不得结束用户现有GPU进程。
- 只绑定本机地址。模型适配器要显式上报 not_installed/unavailable，不伪造模型进度或预测。
- 网前展搓、收搓、后退小跳启动是待验证细标签；未知不是阴性，不能把粗球种映射为已确认细手法。
- 代码、模型权重、数据标注和原视频各自记录来源/许可；仅研究许可不可当成可公开商用。不得绕过登录、付费或下载限制。

## 修改边界

- platform：`apps/platform/`、`packages/contracts/`、`packages/runtime/`、`tests/platform/`、`tests/contracts/`、根 Python 配置与启动脚本。
- library：`packages/library/`、`tests/library/`、`configs/library/`、`scripts/library/`。
- models：`packages/models/`、`tests/models/`、`configs/models/`、`scripts/models/`、`environments/models*`。
- render：`packages/render/`、`tests/render/`、`configs/render/`、`scripts/render/`、`environments/render*`。
- deployment（由主任务协调）：`deployment/`、`scripts/deploy/`、`tests/deployment/`、`docs/deployment/`及根部署入口；模型环境脚本仍由models维护，公共合同变更仍须协调。
- 每人拥有对应 `docs/<module>/`、`docs/status/<module>.md`；问题和实验文件带模块前缀。
- 根 docs 及初始合同由主任务协调。发现合同缺口先提出兼容扩展；避免不同工作树各改一份接口。无法等待时在模块内用兼容适配器，记录差异。
