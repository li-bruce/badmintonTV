# 模型模块：换设备后如何继续开发

只做播放、剪辑和人工标注的电脑，不需要安装这个模块。模型模块通过文件接收已导出的标注和视频引用，处理后再把结果交给工作台；不接管工作台数据库。

## 1. 选择设备和环境

以下内存与显存数字是起步建议，不是性能保证。原视频分辨率、片长、模型、精度与批量都会改变需求。

| 环境 | 能做什么 | 必要条件 | 起步建议 | 状态 |
|---|---|---|---|---|
| `cpu-prep` | 检查快照、检查比赛划分、按真实 PTS 解码小窗口 | CPU；WSL Ubuntu x86_64；Python 3.11 环境 | 4 核、8GB 内存，SSD | 新入口已测试计划；旧 CPU 环境已实测真实帧；新机器安装未测 |
| `gpu-base` | 已有 COCO17 姿态、CLIP 抽帧向量、中文查询模型实验 | NVIDIA CUDA；单独 PyTorch 2.7.1/cu128 环境；相应权重 | 16GB 系统内存；12GB 以上显存可作为小窗口试验起点 | 推理已有历史实测，新环境重建未测 |
| `gpu-pose-tracknet` | YOLO 姿态/匿名跟踪、TrackNet 球点、BST 粗球种实验 | 独立 2.7.1/cu128 环境；权重、来源锁及符合要求的输入 | 16–32GB 内存；16GB 以上显存先小批量验证 | 仍是候选特征，不是细技战术真值 |
| `gpu-vl` | Qwen3-VL 视频语言向量实验 | 独立 PyTorch 2.8.0/cu128 + transformers 4.57.3；对应权重 | 32GB 内存；24–32GB 显存先测试短片 | 不与 2.7.1 混装；新环境重建未测 |
| 将来的定点训练 | 击球检测、脚步时序、球路/姿态修正、视频向量微调 | 足量人工真值、整场留出、对应训练代码 | 本机 5090/32GB 可先测小模型；批量与长序列需实测 | **当前没有可交付的统一训练循环** |

GPU 不能弥补画面看不清、没有人工真值或标签定义不清。Windows 原生模型训练不在支持范围。原生 Linux 机器可先输出环境计划和检查信息，但项目当前训练约定仍是 WSL Ubuntu，正式迁移须单列验证与调整部署约定。

## 2. 部署入口

从完整源码仓库或模型源码包的根目录运行。需要系统已有 Python 3 和用户自行选择的 Conda/Miniforge 安装；此入口不安装 Conda、不改 base、不改驱动。

路径都是参数。下面用一个新盘作为**示例**；在当前机器继续使用既有 `/mnt/d/video`。不要把原机器的 Python 环境目录复制到新设备，应重新建立环境。

```bash
# 只输出计划：不联网、不创建目录、不执行安装。
bash scripts/models/setup_device.sh --profile cpu-prep \
  --storage-root /mnt/e/badminton-data \
  --conda-executable /opt/miniforge3/bin/conda

# 实际只读检查：目标存储根须已存在，扫描容量并检查依赖。
bash scripts/models/setup_device.sh --profile cpu-prep \
  --storage-root /mnt/e/badminton-data \
  --conda-executable /opt/miniforge3/bin/conda --dry-run

# 明确安装：只允许新 prefix；已有目录一律拒绝覆盖或修复。
bash scripts/models/setup_device.sh --profile cpu-prep \
  --storage-root /mnt/e/badminton-data \
  --env-prefix /mnt/e/badminton-data/runtime/models/envs/cpu-prep \
  --conda-executable /opt/miniforge3/bin/conda --apply

# 换 profile 可生成其他环境的计划；不要默认把四个都装上。
bash scripts/models/setup_device.sh --profile gpu-vl \
  --storage-root /mnt/e/badminton-data \
  --conda-executable /opt/miniforge3/bin/conda --dry-run
```

`--doctor` 只检查主机和已安装包的元信息，不导入模型、不使用 GPU 运算；GPU 可见不等于 CUDA 算子通过。`--dry-run` 的通过仅表示容量检查通过，仍需阅读 `doctor` 中 Conda、环境和 GPU 状态。

安装后先设置当前终端的路径，再用一份已同步的快照和素材清单验证小窗口。修改下面的根目录、环境和文件名，使其对应实际文件：

```bash
export BTV_STORAGE_ROOT=/mnt/e/badminton-data
export BTV_MODELS_ENV="$BTV_STORAGE_ROOT/runtime/models/envs/cpu-prep"
export HF_HOME="$BTV_STORAGE_ROOT/models/cache/huggingface"
export TORCH_HOME="$BTV_STORAGE_ROOT/models/cache/torch"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONNOUSERSITE=1
export TMPDIR="$BTV_STORAGE_ROOT/runtime/models/device-cache/cpu-prep/tmp"

"$BTV_MODELS_ENV/bin/python" -s -B scripts/models/device_cpu_smoke.py \
  --storage-root "$BTV_STORAGE_ROOT" \
  --snapshot "$BTV_STORAGE_ROOT/platform/handoff/training-snapshot.json" \
  --manifest "$BTV_STORAGE_ROOT/data/training/handoff/annotation-catalog.v1.json" \
  --samples 2
```

该命令只读原片，输出真实帧 PTS/RGB 哈希，不写数据集、不使用 GPU。

安装时按官方 conda-forge/PyPI/PyTorch cu128 源取依赖，不下载视频或模型权重。所有新环境独立，不使用 `--system-site-packages`。CPU 依赖文件不含 torch/CUDA；GPU 的框架版本和完整 pip 版本锁分别保存。版本锁不包含全部下载文件哈希，也未锁 Conda Python 的补丁版本，因此不宣称逐字节复现；安装收据记录实际命令、版本探测与失败信息。

## 3. 空间、缓存和失败恢复

| 位置（相对 storage-root） | 内容 | 上限 |
|---|---|---|
| `runtime/models/envs/<profile>` | 独立环境，允许参数指定其他 models 子目录 | 与下面两项合计 35GB |
| `runtime/models/device-cache/<profile>` | Conda 包、pip/tmp/XDG 缓存 | 同上 |
| `runtime/models/device-reports/<id>` | 安装日志、计划、环境配置和结果 | 同上 |
| `models/cache` | 显式 HF/Torch 缓存；默认离线 | models 总额 180GB |
| `models/weights`、`models/handoff` | 模型与数据处理结果 | 同上 |

整体仍以 700 十进制 GB 为硬上限，并保留各模块固定分区。存储根外的既有 Conda base/包缓存扣除非本项目 `envs` 后计入公共 15GB；新 Conda 包缓存计入模型 35GB，不靠放到别处避开预算。

CPU 安装计划预留 2GB 峰值，GPU 三种计划分别预留 18/20/24GB，包括缓存、解包和新环境。容量不足会停止，不会清理旧环境。安装持有公共 `.models-bootstrap-lock`，执行时检查新增文件量、日志大小、时间和剩余磁盘；保留 10% 峰值与 5GB 物理磁盘缓冲。这个进程级监控不是文件系统强制配额，测量与写入之间仍有间隙；运行期间应停止其他模型环境安装，不把安全余量挪作其他下载。

失败时保留新 prefix、缓存和报告。不要删除未知文件或其他任务的锁。确认该安装进程已结束、查看报告后，另选新 prefix 或由负责人记录清理方案。正常完成只报告“环境已安装”；模型仍需迁移来源清单、检查权重哈希、做一次真实推理和评测。

## 4. 输入、输出与已实现的入口

| 子模块 | 输入要求 | 输出要求 | 目前入口与可用性 |
|---|---|---|---|
| 快照审计（CPU） | `TrainingSnapshot@1.0`；可附原始 `AssetManifest@1.0` | `readiness.json`：训练可用性、排除原因、标签/人物/证据原样引用；`capacity.json` | `python -m packages.models.training_prepare audit`，已实现 |
| 样本准备（CPU） | 上述快照 + manifest + 原片 + 完整 PTS 索引；哈希必须吻合 | 源时间窗口、真实帧 PTS/RGB 哈希、只读审核报告；当前不落盘大量训练帧 | 同模块 `prepare`，已实现 |
| 模型推理（GPU） | `JobRequest@1.0`，固定 model_id/version，Asset 数组，受限参数，新 output_dir；本地权重/源码来源锁 | `JobResult@1.0` + JSONL 真实进度 + 有哈希的 features/report/候选 events | `python -m packages.models run --request ... --result ...`，按适配器提供，缺依赖明确 blocked |
| 评测 | 按整场划分的人审真值、查询/检索排序和可见性 | 样本数量、指标及其分母、未知/排除项、误差与限制 | `packages.models.evaluation.evaluate_rankings` 等 Python API 已实现；尚无统一外部评测 CLI |
| 模型卡/目录 | 模型来源/权重清单、当前环境、实测评测链接 | `ModelManifest@1.0`，能力/状态/支持范围/许可 | `python -m packages.models catalog`；当前环境目录跟随 `BTV_STORAGE_ROOT` 和 `BTV_MODELS_ENV` |
| 正式训练 | 人审标签定义、可训练快照、整比赛 train/validation/test、训练配置、算力计划 | checkpoint + 固定配置 + 验证报告 + 模型卡 | **未实现统一 trainer**；不把环境准备或特征提取写成训练成功 |

时间一律引用原视频毫秒/PTS，圈选引用图像归一坐标。回合、人物、标签、ROI、unknown 和审核状态随快照保存。训练专用素材继续保持 `training_only`，不能回流成为制作素材。模型不得直接连接 Windows 工作台的 SQLite。

## 5. 运行与未来合并

以下是实际 CLI 形式，文件名换成移交文件。导出到新目录，不覆盖旧 attempt。

```bash
export BTV_STORAGE_ROOT=/mnt/e/badminton-data
export BTV_MODELS_ENV="$BTV_STORAGE_ROOT/runtime/models/envs/cpu-prep"
export HF_HOME="$BTV_STORAGE_ROOT/models/cache/huggingface"
export TORCH_HOME="$BTV_STORAGE_ROOT/models/cache/torch"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONNOUSERSITE=1
export TMPDIR="$BTV_STORAGE_ROOT/runtime/models/device-cache/cpu-prep/tmp"

"$BTV_MODELS_ENV/bin/python" -s -B -m packages.models.training_prepare prepare \
  --root "$BTV_STORAGE_ROOT" \
  --snapshot "$BTV_STORAGE_ROOT/platform/handoff/training-snapshot.json" \
  --manifest "$BTV_STORAGE_ROOT/data/training/handoff/annotation-catalog.v1.json" \
  --output-dir models/handoff/prepare-attempt-001 --samples 6
```

默认选显式动作区间；需要触球点用 `--record asset_id/record_id` 选择（可重复）。`--index-only` 不解码；不能把它称真实帧通过。`--require-trainable` 会在真值、划分或定义不足时返回 2；不加时可以完成审核报告而 `trainable=false`。

将来工作流：标注电脑冻结快照 → 按 asset_id/hash 同步选中的原片和 PTS → 计算电脑重新校验并生成特征/评测 → 通过 models/handoff 交还工作台 → 人审 → 检索与剪辑。保持相对路径与 hash；设备绝对路径只放部署配置。迁移完成后仍需由平台注册各模型的受控启动命令和 GPU 排期，源码包本身不会自动启动远程 worker。

**当前跨盘编排限制：** 模型独立 CLI 可使用上述新存储根，但现有 Windows → WSL 桥接器仍固定 `D:/video` / `/mnt/d/video`。在新盘部署后，网页队列不能仅靠注册模型卡或修改启动命令重新接通；需要先改造桥接器的存储根、交换文件与环境路径校验，再验证作业、取消、心跳和 GPU 租约。这个平台改造未在本轮执行。期间通过独立 CLI 和 `models/handoff` 文件交接继续开发，详见 [跨盘桥接限制](../issues/models-new-device-bridge-root.md)。

## 6. 旧实验脚本的边界

`bootstrap.sh`、`complete_environment.sh`、`bootstrap_annotation_runtime.py`、`bootstrap_reuse_vl.sh`、`bootstrap_yolo_reuse.sh` 和 `environments/models*.env.sh` 保留历史机器的路径和实验恢复过程。它们不是本次新设备部署入口。尤其旧 annotation-env 继承了旧 GPU 父环境，新 `cpu-prep` 则完全独立；本轮“已有 CPU 环境真实解码通过”不等于新环境已安装通过。

历史实测来源见 [ENVIRONMENT.md](ENVIRONMENT.md)、[模型状态](../status/models.md)。本轮逐项验收见 [DEVICE_SETUP_ACCEPTANCE.md](DEVICE_SETUP_ACCEPTANCE.md)。没有安装新技能或 MCP；无需在轻量工作台环境加入模型依赖。
