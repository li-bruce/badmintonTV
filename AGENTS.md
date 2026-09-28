# 项目协作约定

先读 `PROJECT_PLAN_SIMPLE.md` 和 `docs/PRODUCT_CONTEXT.md`、`docs/ARCHITECTURE.md`、`docs/CONTRACTS.md`、`docs/EXECUTION_PLAN.md`、`docs/ACCEPTANCE.md`。用户最新要求优先。

## 工作方式

- 这是同一个产品的四个模块，不是四个独立应用。先设计接口和数据流，再开发、运行和验证。
- 任务使用各自 Git worktree/分支。只提交自己模块的改动，不覆盖他人文件，不重置用户改动，不使用 `git add .` 收入未知文件。主任务负责集成到 main。
- 如 worktree 为 detached HEAD，在本地创建 `work/<module>` 分支（如已存在则使用不冲突的后缀），不对其他 worktree 切分支。不要自行推送、创建远程仓库或发布视频。
- 每个任务须在 `docs/status/<module>.md` 持续写真实进展：设计、已实现、已运行、失败、未测、阻塞、下一步、提交 SHA、启动命令、环境/端口和容量。
- 有问题单独写 `docs/issues/<module>-<slug>.md`；模型逐次实验写 `docs/experiments/`，记录失败也有价值。不能用合成数据的成功冒充真实视频识别成功。
- 需要技能/MCP时自行选择可用工具，读对应 SKILL.md；记录安装来源、版本、用途和环境。平台依赖不为训练框架背负冲突版本。

## 数据和资源

- 硬上限为所有任务总体700十进制GB；固定分区配额见 EXECUTION_PLAN。预算包含下载临时文件、解压双份、权重、缓存、环境、数据库、导出。
- 大文件只放 `D:\video` / `/mnt/d/video`；已有文件不可无记录删除或覆盖。写入前预估峰值、检查目录额度和磁盘剩余，流式下载需限制实际字节数。
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
- 每人拥有对应 `docs/<module>/`、`docs/status/<module>.md`；问题和实验文件带模块前缀。
- 根 docs 及初始合同由主任务协调。发现合同缺口先提出兼容扩展；避免不同工作树各改一份接口。无法等待时在模块内用兼容适配器，记录差异。
