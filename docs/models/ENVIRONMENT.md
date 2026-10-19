# Models 环境复现记录

新设备请使用 [DEVICE_SETUP.md](DEVICE_SETUP.md) 的参数化部署入口。本页保留 2026-09-28 原机器环境与历史重建证据，下面的固定路径脚本不是可迁移入口。

整理日期：2026-09-28。本文依据已有冻结文件和[环境实验记录](../experiments/models-001-environment.md)整理；本次整理没有运行安装、下载或 GPU 任务，也没有重新验证一次干净环境重建。

## 环境与证据

| 项目 | 已记录的实际值 |
|---|---|
| 操作系统 | WSL2 Ubuntu，kernel `6.18.33.2-microsoft-standard-WSL2`，Linux x86_64 |
| 既有 Miniforge | `/home/ubuntu/miniforge3`；conda `25.9.1`，base Python `3.12.12`；history 显示 conda-forge 构建 |
| 项目隔离环境 | `/mnt/d/video/runtime/models/env`，Python `3.11.16` |
| GPU / Windows 驱动 | NVIDIA GeForce RTX 5090，32607 MiB，驱动 `591.86` |
| PyTorch / Torchvision | `2.7.1+cu128` / `0.22.1+cu128` |
| 实际编译运行信息 | CUDA build `12.8`，cuDNN 返回值 `90701`，设备 capability `12.0`，compiled arches 包含 `sm_120` |
| 其他关键版本 | transformers `4.51.3`、accelerate `1.6.0`、safetensors `0.5.3`、PyAV `15.0.0` |

复用了已存在的 Miniforge，没有重新下载安装器，因此没有本轮安装器 SHA256。既有 `deepseek-ocr`、`embedding`、`vllm` 环境未修改；没有更新 base、全局 Python、Windows 驱动或在 WSL 安装 Linux NVIDIA 驱动。平台进程通过 JSON CLI 调用此环境，不需要导入 torch。

| 文件 | 用途 |
|---|---|
| [models-conda-explicit.txt](../../environments/models-conda-explicit.txt) | `linux-64` / `noarch` Conda 包的显式下载地址与构建记录，包含 Python、pip、packaging 等 |
| [models-pip-freeze.txt](../../environments/models-pip-freeze.txt) | 原始 `pip freeze` 证据，完整保留本机 `packaging @ file:///home/conda/...` 来源表示 |
| [models-requirements-lock.txt](../../environments/models-requirements-lock.txt) | 可跨同类 Linux 环境使用的 pip 版本锁；仅把上述 packaging URI 规范为 `packaging==26.3`，版本由 Conda 显式清单佐证 |
| [models.env.sh](../../environments/models.env.sh) | 显式环境、缓存、临时目录和离线开关 |
| [models-gpu-smoke.json](../../environments/models-gpu-smoke.json) | 已执行 GPU 算子的原样报告 |

pip 锁固定版本，但不含每个 wheel 的哈希；它不是完整的离线 wheel 仓库，也不承诺 Windows 原生或其他 Python 主次版本可安装。GPU 权重的来源、revision 和文件哈希由各自 `weights-manifest.json` 另行管理。

## 安装顺序与重建

实际安装顺序为：用既有 Conda 创建独立 Python 3.11 prefix；从 PyTorch 官方 `https://download.pytorch.org/whl/cu128` 安装 torch `2.7.1` 和 torchvision `0.22.1`（最终安装版本含 `+cu128`）；再安装 transformers、accelerate、safetensors、Pillow 和 PyAV。不得把项目依赖散装进 base 或系统 Python。

PyAV `14.4.0` 在此次安装中走到源码构建，因缺少 pkg-config / FFmpeg 开发依赖失败。随后改为 `av==15.0.0` 的 cp311 manylinux_2_28 wheel，并使用 `--only-binary=:all:`。本轮没有为旧版本补装全局编译链。初始脚本还出现过运行中被编辑后退出的情况，原因记为推断；后续由独立 `complete_environment.sh` 补齐依赖。正在运行的 shell 脚本必须保持不变，详见实验记录。

下列命令供**未占用的目标 prefix**按冻结记录重建，需在仓库根目录的 WSL Bash 中执行。现有工作环境不要重复创建或覆盖；若改用新 prefix，旧、新目录、下载与临时空间都计入同一额度。先按下节完成容量核算，再执行安装。此处命令仅做了静态核对，本次整理没有执行它们。

```bash
set -euo pipefail
source environments/models.env.sh

# 在未占用的目标前缀上重建；当前已有环境时立即停止。
test ! -e "$BTV_MODELS_ENV"
test -x /home/ubuntu/miniforge3/bin/conda
mkdir -p "$CONDA_PKGS_DIRS" "$TMPDIR" "$PIP_CACHE_DIR" "$HF_HOME" "$TORCH_HOME"

# 与公共 Conda 安装流程使用同一排他锁；已有锁时停止，不删除他人的锁。
mkdir /mnt/d/video/runtime/shared/.models-bootstrap-lock
trap 'rmdir /mnt/d/video/runtime/shared/.models-bootstrap-lock' EXIT
python3 scripts/models/budget_check.py --reserve-runtime 18000000000 --reserve-models 3000000000

/home/ubuntu/miniforge3/bin/conda create --yes --prefix "$BTV_MODELS_ENV" \
  --file environments/models-conda-explicit.txt

# CUDA wheel 必须先从官方 cu128 索引安装。
"$BTV_MODELS_ENV/bin/python" -m pip install --no-cache-dir --no-compile \
  --only-binary=:all: --index-url https://download.pytorch.org/whl/cu128 \
  'torch==2.7.1+cu128' 'torchvision==0.22.1+cu128'

# 已安装的 CUDA wheel 满足精确版本；其余包按完整版本锁安装。
"$BTV_MODELS_ENV/bin/python" -m pip install --no-cache-dir --no-compile \
  --only-binary=:all: --no-deps -r environments/models-requirements-lock.txt
"$BTV_MODELS_ENV/bin/python" -m pip check
```

`bootstrap.sh` 保存首轮安装流程，`complete_environment.sh` 保存补齐依赖流程；上面的显式Conda清单加完整pip锁用于重建冻结版本。补装脚本持有共享安装锁后，先用CPU包metadata确认torch/vision精确版本并运行pip check，阻止缺框架时意外下载大型CUDA依赖；随后用`--reserve-runtime 3000000000`检查剩余依赖下载/解包额外峰值，再以完整版本锁作为约束执行pip；安装后再次复核容量。`set -euo pipefail`使预检失败时在pip install前停止；3GB预算只用于既有完整torch/vision环境的本轮依赖补装，不是任意未来依赖保证。此修正通过bash语法/顺序静态检查及3种metadata模拟，未重复安装/下载。包源不可达、指定wheel不可用或pip check失败时记录错误，不能把部分安装称为环境就绪。

## 路径、离线权重与容量

运行前执行 `source environments/models.env.sh`，得到以下路径。所有 GB 均按十进制字节计算。

| 内容 | WSL 路径 | 计入额度 |
|---|---|---|
| 独立环境 | `/mnt/d/video/runtime/models/env` | models runtime 35 GB |
| 模型环境临时目录 / pip 缓存 | `/mnt/d/video/runtime/models/tmp`、`/mnt/d/video/runtime/models/pip-cache` | 同上，合并计算 |
| 公共 Conda 包缓存 | `/mnt/d/video/runtime/shared/pkgs` | 公共 15 GB |
| 既有 Miniforge base 与旧公共包缓存 | `/home/ubuntu/miniforge3`，扣除其 `envs` 子目录；包含原 `pkgs` | 原生路径另行统计，仍占公共 15 GB |
| HF / Torch 缓存 | `/mnt/d/video/models/cache/huggingface`、`/mnt/d/video/models/cache/torch` | models 数据/权重 180 GB |
| 权重与实验结果 | `/mnt/d/video/models/weights`、`/mnt/d/video/models/handoff` | 同上，含 `.partial` 与保留的失败文件 |

初查 Miniforge 总量 `34,911,557,859` bytes，既有用户环境 `28,987,060,966` bytes，其中公共 `pkgs` 为 `5,756,364,977` bytes。扣除用户环境后，base 加公共包缓存为 `5,924,496,893` bytes，约 **5.925 GB**，保守计入公共 15 GB。旧用户环境独立记录，未计入本项目，也未修改。这个原生目录占用不能因不在 D 盘而遗漏，也不要把其中 pkgs 再重复相加。

`budget_check.py` 现会自动统计默认 `/home/ubuntu/miniforge3` 的 base 与 pkgs，在遍历前排除其 `envs` 子树和符号链接，不扫描旧用户环境。该实际值计入 `usage_bytes.runtime_shared`、`usage_bytes.runtime` 和 `project_total_bytes` 各一次；pkgs 已包含在 base 根目录统计中，不再重复相加。历史 `5,924,496,893` bytes 只是快照，无须再手工加到新报告。`--native-base PATH` 可指定其他既有 Miniforge 根目录；路径缺失时报告 `size_bytes=0`、`reused=false`、`status=not_found`。即使显式指定的 base 已在受控目录内，也会先从该目录扫描中排除，再单独计入，避免重复。

报告同时保留受控目录自身的 `disk_usage_bytes`、原生目录的 `native_base` 明细和各项 `checks`。`free_bytes` 仍是共享存储根所在盘的剩余空间，作为新增写入预检；`native_base.free_bytes_reference` 仅供只读参考，不替代 D 盘空间检查，也不表示已为原生盘写入预留容量。models runtime 不超过 35 GB，公共部分不超过 15 GB；runtime 的另 20 GB 为 platform/library/render 预留，总 runtime 不超过 70 GB，总项目不超过 700 GB。50 GB 总安全余量不可自行借用。

下载与安装要预留峰值，包括未完成文件、保留副本、解包和缓存；脚本中的 18 GB runtime / 3 GB models 为首轮预检参数，不代表任意重建的实际峰值保证。自动原生目录核算解决了已有容量遗漏；`checks_passed` 仍是本次目录快照与传入峰值的检查结果，并不代替模块写入锁或其他任务的并发预留。

已注册模型从以下受控本地目录加载：

| 模型 | 权重目录 |
|---|---|
| Qwen3-0.6B | `/mnt/d/video/models/weights/qwen3-0.6b` |
| Torchvision Keypoint R-CNN | `/mnt/d/video/models/weights/torchvision-pose` |
| CLIP ViT-B/32 | `/mnt/d/video/models/weights/clip-vit-base-patch32` |

每个目录须有完整的 `weights-manifest.json`；模型加载前校验所需文件、路径、大小及 SHA256。环境默认 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，加载器使用本地文件；权重不存在时返回明确阻塞，不自动下载补齐。独立下载工具仍是显式联网操作，受固定来源、来源身份、校验和容量约束；离线开关不代表所有 Python 网络请求被操作系统禁止。各目录是否已经完整，以当前 manifest 和运行结果为准，不能由本文列出路径推断已安装。

## GPU 验证边界

已保存报告的五项检查均为真：matmul、conv2d、bf16 SDPA、torchvision CUDA NMS 和 ROI Align。算子段耗时 `1.0972453759750351` 秒，峰值已分配显存 `8,974,848` bytes。这验证了所记录版本在该 5090 上的实际 GPU 算子路径，超过单独检查 `cuda.is_available()` 的范围。

报告明确标记 `synthetic_operator_smoke_not_video_accuracy`。这些数字不是完整模型显存需求、真实视频处理速度或羽毛球识别准确率；没有证明姿态身份、细手法、骨骼时序或跨机位泛化。真实视频推理与标签评测应引用各自实验产物。需要复测时使用 `scripts/models/gpu_smoke.py`，先取得项目 GPU 排期/租约，不结束现有用户进程；本次文档整理未运行它。

没有为模型环境启动网络服务，无监听端口；运行边界仍是受控 CLI。初期 DrvFS 下 pycache 引起启动/遍历缓慢，已在环境脚本设置 `PYTHONDONTWRITEBYTECODE=1`。源码、版本锁与小型报告可提交 Git；环境目录、模型权重、缓存与媒体保留在受控数据路径。
