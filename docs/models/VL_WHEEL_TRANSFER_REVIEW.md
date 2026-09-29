# VL 固定 Linux wheel 迁移只读调查

调查时间：2026-09-29 17:54–18:08，Asia/Shanghai。目标是把既有 Torch 2.8.0 / torchvision 0.23.0 / cu128、CPython 3.11、Linux x86_64 环境的下载阶段交给 Windows；不改版本、不创建第三环境。本调查没有安装、下载 wheel body、停止进程或修改正在运行的 bootstrap。主线程随后独立完成了一次 8 MiB 有界测速。

## 结论与清单边界

建议主线程在保护现有完整文件及暂停后的 partial 后，切换同一 VL 环境的下载来源。主线程提供的真实原官方地址测速为 8,388,608 B / 5.062 s，约 1.657 MB/s；它支持这种尝试，但单片速度不是剩余全程吞吐保证。

机器可读固定清单为 [vl-linux-cp311-wheels.json](vl-linux-cp311-wheels.json)，17 个核心 wheel 合计 **3,916,256,631 B**。每项记录固定 Linux wheel filename、官方 URL、精确 size_bytes 与 SHA-256。它只覆盖 Torch、torchvision、14 个 NVIDIA 包和 Triton，**不是完整离线依赖锁**：还需补齐 Torch 的 Python 小依赖以及 Transformers/Qwen-VL-utils 阶段依赖，方可使用完全 `--no-index` 安装并通过 `pip check`。不能用 Windows 平台默认 wheel 或自动替换为 PyPI 不带 `+cu128` 的 Torch wheel。

本地已下载 Torch METADATA 明确为 `2.8.0+cu128`，torchvision 为 `0.23.0+cu128`。NVIDIA 与 Triton 固定版本逐项来自 Torch 的 Linux/x86_64 Requires-Dist；与下表 PyPI 元数据一致。

## 正在运行的安装

检查对象：[bootstrap_reuse_vl.sh](../../scripts/models/bootstrap_reuse_vl.sh) 与 [models-vl.env.sh](../../environments/models-vl.env.sh)。

- 环境为 `/mnt/d/video/runtime/models/vl-env`，临时目录 `/mnt/d/video/runtime/models/vl-tmp`，配置的持久缓存 `/mnt/d/video/runtime/models/vl-pip-cache`。
- 两次 pip install 都启用 `--no-cache-dir --no-compile --only-binary=:all:`。因此 `vl-pip-cache` 实测为空；完整 wheel 在 `vl-tmp/pip-unpack-*/`，不是 pip 持久缓存。
- 第一阶段是官方 cu128 索引的 `torch==2.8.0 torchvision==0.23.0`。第二阶段保持 `transformers==4.57.3 qwen-vl-utils==0.0.14 accelerate==1.6.0 safetensors==0.5.3 av==15.0.0 pillow==11.2.1`。
- 调查时尚无最终 `models-vl-pip-freeze.txt` / `models-vl-conda-explicit.txt`；不能把已下载视为已安装成功。
- bootstrap 有 `test ! -e "$BTV_MODELS_ENV"`，因此现存环境不能直接从头重跑该脚本。恢复应由主线程在同一环境续装并完成原检查/版本记录。
- 18:07 左右的只读进程快照：pip PID **159553**，PPID **159498**，状态 `Sl+`，命令为：
  `/mnt/d/video/runtime/models/vl-env/bin/python -m pip install --no-cache-dir --no-compile --only-binary=:all: --index-url https://download.pytorch.org/whl/cu128 torch==2.8.0 torchvision==0.23.0`。
- 父进程 PID **159498** / PPID **159493** 为 `bash /mnt/c/Users/Li/.codex/worktrees/c5b1/badmintonTV/scripts/models/bootstrap_reuse_vl.sh`；159493 → 159492 → 2 是 WSL init 链。PID 仅为此时证据，主线程发送信号前需重验命令/父关系，不按旧 PID 猜测。

## 本地文件快照与完整性

18:00 对已完成的六项做了流式 full SHA-256，读取前后 size/mtime 一致；18:06 对随后完成的 curand 同样核验。七项均与官方 PyPI SHA-256 相符，合计 **1,657,087,474 B**。ZIP 中央目录检查仅用于识别 partial；本调查没有把“ZIP 可打开”等同于完整校验。

| 完整文件 | 临时子目录 | 字节 |
| --- | --- | ---: |
| cudnn 9.10.2.21 | pip-unpack-3kukkrkh | 706,758,467 |
| cublas 12.8.4.1 | pip-unpack-9oc_x8y8 | 594,346,921 |
| nvrtc 12.8.93 | pip-unpack-88p9wyxv | 88,040,029 |
| cuda runtime 12.8.90 | pip-unpack-6sah5pgx | 954,765 |
| cupti 12.8.90 | pip-unpack-m2jpgigm | 10,248,621 |
| cufft 11.3.3.83 | pip-unpack-ii126589 | 193,118,695 |
| curand 10.3.9.90 | pip-unpack-ido8uu5b | 63,619,976 |

18:03:38 快照的当前 partial 是 `pip-unpack-bpr2790i/nvidia_cusolver_cu12-11.7.3.90-py3-none-manylinux_2_27_x86_64.whl`，**52,953,088 B**，ZIP 目录尚不完整；目标大小 **267,506,905 B**。文件仍由 pip 增长，当前大小不代表可直接复用的稳定 prefix。pip partial 也使用 `.whl` 后缀，不可只按后缀当成完整。

保留已校验完整件时，同一 D: 卷上的独占硬链接可避免复制内容；仍需确认链接指向的原对象、目标不存在、size/full SHA 一致。硬链接并非内容快照，所以当前 partial 必须先由主线程确认暂停确切 pip 并稳定后再处理。终止 pip 的清理可能移除临时名字；先建立保留对象才不会把完整下载成果丢失。当前 partial 若接续，必须保持同一来源 identity、精确 offset 与 Content-Range，最后做全文件 SHA；prefix 不是已验证完整 wheel。

## 官方元数据与精确大小

CUDA/Triton 的 filename、size、SHA、URL 来自每个固定版本的 PyPI JSON（下表链接），Torch/vision 的 filename/SHA 来自官方 cu128 索引。对该索引当前指向的 `download-r2.pytorch.org` wheel 做 Windows HEAD 得到 403；未据此断言 GET 不可用。

公开原域名 `download.pytorch.org` 的同固定发布路径 HEAD 均为 200、`Accept-Ranges: bytes`，Torch **889,185,760 B**，vision **8,628,439 B**。清单采用这个公开原域名；其完整下载仍必须匹配索引 SHA，不以 HEAD 或 ETag 代替 SHA。未使用认证、代理绕过或第三方镜像。

| 固定包 / 元数据源 | size_bytes | 状态 |
| --- | ---: | --- |
| [nvidia-cuda-nvrtc-cu12 12.8.93](https://pypi.org/pypi/nvidia-cuda-nvrtc-cu12/12.8.93/json) | 88,040,029 | 本地完整、SHA 一致 |
| [nvidia-cuda-runtime-cu12 12.8.90](https://pypi.org/pypi/nvidia-cuda-runtime-cu12/12.8.90/json) | 954,765 | 本地完整、SHA 一致 |
| [nvidia-cuda-cupti-cu12 12.8.90](https://pypi.org/pypi/nvidia-cuda-cupti-cu12/12.8.90/json) | 10,248,621 | 本地完整、SHA 一致 |
| [nvidia-cudnn-cu12 9.10.2.21](https://pypi.org/pypi/nvidia-cudnn-cu12/9.10.2.21/json) | 706,758,467 | 本地完整、SHA 一致 |
| [nvidia-cublas-cu12 12.8.4.1](https://pypi.org/pypi/nvidia-cublas-cu12/12.8.4.1/json) | 594,346,921 | 本地完整、SHA 一致 |
| [nvidia-cufft-cu12 11.3.3.83](https://pypi.org/pypi/nvidia-cufft-cu12/11.3.3.83/json) | 193,118,695 | 本地完整、SHA 一致 |
| [nvidia-curand-cu12 10.3.9.90](https://pypi.org/pypi/nvidia-curand-cu12/10.3.9.90/json) | 63,619,976 | 本地完整、SHA 一致 |
| [nvidia-cusolver-cu12 11.7.3.90](https://pypi.org/pypi/nvidia-cusolver-cu12/11.7.3.90/json) | 267,506,905 | 18:03 快照尚未完整 |
| [nvidia-cusparse-cu12 12.5.8.93](https://pypi.org/pypi/nvidia-cusparse-cu12/12.5.8.93/json) | 288,216,466 | 18:03 快照尚未完整 |
| [nvidia-cusparselt-cu12 0.7.1](https://pypi.org/pypi/nvidia-cusparselt-cu12/0.7.1/json) | 287,193,691 | 18:03 快照尚未完整 |
| [nvidia-nccl-cu12 2.27.3](https://pypi.org/pypi/nvidia-nccl-cu12/2.27.3/json) | 322,364,134 | 18:03 快照尚未完整 |
| [nvidia-nvtx-cu12 12.8.90](https://pypi.org/pypi/nvidia-nvtx-cu12/12.8.90/json) | 89,954 | 18:03 快照尚未完整 |
| [nvidia-nvjitlink-cu12 12.8.93](https://pypi.org/pypi/nvidia-nvjitlink-cu12/12.8.93/json) | 39,254,836 | 18:03 快照尚未完整 |
| [nvidia-cufile-cu12 1.13.1.3](https://pypi.org/pypi/nvidia-cufile-cu12/1.13.1.3/json) | 1,197,834 | 18:03 快照尚未完整 |
| [triton 3.4.0](https://pypi.org/pypi/triton/3.4.0/json) | 155,531,138 | 18:03 快照尚未完整 |
| [torch 2.8.0+cu128](https://download.pytorch.org/whl/cu128/torch/) | 889,185,760 | 18:03 快照尚未完整 |
| [torchvision 0.23.0+cu128](https://download.pytorch.org/whl/cu128/torchvision/) | 8,628,439 | 18:03 快照尚未完整 |

Torch 的固定 SHA 为 `039b9dcdd6bdbaa10a8a5cd6be22c4cb3e3589a341e5f904cbb571ca28f55bed`；vision 为 `93f1b5f56b20cd6869bca40943de4fd3ca9ccc56e1b57f47c671de1cdab39cdb`。全部固定 wheel URL 与完整 SHA 在 JSON 清单中。

## 剩余量、时间与资源

以 18:03:38 快照计，扣除七个完整件仍需 **2,259,169,157 B** 核心下载；若暂停后能够继续当时 52,953,088 B 的 cusolver prefix，则是 **2,206,216,069 B**。这是时点快照，pip 后续增长应重新扣除，不能作为暂停时的实时值。

- 按原观察 0.4–0.7 MB/s，剩余核心纯下载约 **54–94 分钟**。
- 按主线程此次 Windows 1.657 MB/s 单片速度推算约 **23 分钟**。
- 两者都不含网络波动、校验、依赖小包、解包、安装和真实模型启动；也不是完成承诺。应以逐包字节进度和有限超时控制继续判断，不无限等待。

只读运行已有 `runtime_preflight_reuse.py` 得到：

| 项目 | 字节 |
| --- | ---: |
| models runtime 当前逻辑用量 | 9,720,205,371 |
| shared disk | 1,244,822,546 |
| native base + packages（排除 envs） | 5,924,496,893 |
| shared 合计 | 7,169,319,439 |
| D: 剩余 | 935,349,485,568 |

既有方案额外 models reserve 24,000,000,000 B、shared reserve 2,000,000,000 B；保守地再次从这个当前用量叠加，models 峰值计划 **33,720,205,371 B < 35 GB**，shared **9,169,319,439 B < 15 GB**。另计其他 runtime 20 GB，runtime 峰值计划 **62,889,524,810 B < 70 GB**，且磁盘余量满足 5 GB margin。

24 GB 是保守容量预留，不是已测安装大小。它覆盖约 3.916 GB 全套核心 wheel、主线程预留约 10 GB 的库拆包、Python 依赖和临时开销；保留现有完整件使用硬链接不会再复制其 1.657 GB 内容。必须继续沿原配额计入 wheelhouse、partial、环境与临时解包，安装完成后记录真实大小；不得因“硬链接不复制”跳过实际目录/磁盘核查。

## 已完成与未完成

已完成：官方版本/URL/SHA/大小核查；七个本地完整 wheel 的全 SHA 核验；明确 current partial；进程父关系只读定位；容量快照；固定核心清单。

主线程另行完成：8 MiB Windows 206 测速。尚未由本调查执行：停止/恢复 pip、硬链接保留、并发实际 wheel 获取、安装、pip check、GPU 或 Qwen 推理。所以上述清单和调查不能算作 VL 模型加载通过的证据。


## 主线程执行追加（2026-09-29约18:08–18:13）

- 重测preflight：models runtime9,866,743,867B，+24GB保守增量后33,866,743,867B<35GB；shared7,169,319,439B，+2GB后<15GB；70GB整体和D空余935,030,521,856B通过。原始JSON在environments/models-vl-transfer-preflight.json。
- 核对本任务pip159553精确argv、父bootstrap159498后SIGSTOP。7完整包1,657,087,474B和cusolver未完182,190,080B经独占NTFS hardlink保护到runtime/models/vl-wheelhouse，完整者全SHA匹配官方。原文件不删除；preserved-pip-20260929.json保留来源和字节。然后仅对此已核实pip发送TERM+CONT，旧bootstrap退出并释放锁。
- 为保留中断证据不随append变化，182,190,080B归档partial另复制一份到正常续传前缀并建立固定URL/总bytes/SHA的来源标记；额外182MB包含上述24GB预留。最终全SHA才证明完整权重，prefix并不独立声称官方内容完整。
- 原生Windows acquire_vl_wheelhouse.py 默认dry-run确认7个完整skip、cusolver前缀182,190,080B，全清单剩余2,076,979,077B；15项CPU守卫测试通过后用4并发严格206 Range执行。没有使用Windows pip解算Linux包。
- 第一个cusolver实际剩余85,316,825B在41.187s下载完，随后整个267,506,905B SHA与官方匹配并排他发布。原partial归档仍在。这是下载与完整性进展，不代表env安装或VL GPU已完成。
