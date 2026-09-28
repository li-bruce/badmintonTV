# models 状态

- 任务：01a0e88b-416f-7ca2-bfec-c09ec1462866；cwd C:\Users\USER\.codex\worktrees\c5b1\badmintonTV；branch work/models。
- 设计：docs/models/DESIGN.md 与 annotation-and-evaluation.md 已写；专家冻结细标签、unknown、整场留出和A/B/C公平对照均定义。
- 已实现：纯stdlib CLI/attempt_id/JSONL/排他结果；受限中文规则、兼容端点、schema与语义校验；懒加载Qwen/COCO17姿态/CLIP抽帧适配器；受控权重下载和配额锁。
- 已运行：复用原生 Miniforge25.9.1（含用户既有环境，不修改）；新建 /mnt/d/video/runtime/models/env Python3.11.16，torch安装进行中。协议+查询32项中31通过/Windows symlink权限1跳过，后续新增测试另跑。
- 失败：普通沙箱 WSL E_ACCESSDENIED；授权提升后恢复。Git ownership 使用单命令 safe.directory，未修改全局配置。
- 未测：实际 GPU 算子、真实视频推理、中文模型、A/B/C准确率。
- 阻塞：细标签专家冻结和人工真值缺失；library真实4条小样已到，不能跨场训练/测试（match_id unknown、split unassigned）。
- 下一步：安装完成后GPU算子、Qwen解析与真实短视频姿态/向量前向，记录速度和错误。
- 提交 SHA：待首次模块提交。
- 启动：python -m packages.models run --request REQUEST --result RESULT；catalog子命令列注册模型。
- 环境/端口：WSL Ubuntu x86_64；无监听端口。
- 容量：安装预估峰值21GB已检查；模型weights约1.2GB正在按固定revision/hash下载；models180GB/runtime models35GB+公共15GB硬限制。原生既有base与pkgs约5.92GB保守记公共15GB；其他用户env约28.99GB非本项目新增，不复用/改动。其余runtime20GB保留。
