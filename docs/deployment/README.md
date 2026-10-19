# 部署与迁移工具

## 选设备，再选环境

| 设备用途 | profile | 安装内容 | GPU |
|---|---|---|---|
| 播放、人工标注、规则检索 | workbench-cpu | FastAPI、播放器和合同；不含模型框架 | 不需要 |
| 资料清单与校验 | library-cpu | 合同、下载/校验 CLI；视频探测需 FFmpeg | 不需要 |
| 视频剪辑与导出 | render-cpu | 合同、剪辑 CLI；需 FFmpeg/ffprobe | 不需要；默认 CPU 编码 |
| 同一台电脑做以上全部 | desktop-cpu | 工作台、资料和剪辑；需 FFmpeg | 不需要 |
| 只开发接口与调度 | core-cpu | Pydantic 和标准库运行时 | 不需要 |
| 训练样本检查 | models-cpu-prep | 委托模型独立 CPU 环境 | 不需要 |
| 模型训练、推理 | models-gpu | 委托 WSL/Linux Conda 环境 | NVIDIA GPU，具体条件见模型说明 |

独立源码包与 profile 是两件事：包决定有哪些源码，profile 决定给当前设备安装哪些依赖。工作台包可独立播放标注；编码需加 render 包（或使用完整包），模型计算需模型环境。现有检索仍在工作台内部。训练入口、模型可用性与人工真值不能由环境安装成功代替。

## 新设备第一次部署

需要 Python 3.11+。源码解压到任意目录，以下命令中的路径改成当前设备实际路径。数据目录由你先创建。原设备继续使用 D:/video；Linux 可用本机原生数据目录。SQLite 与 API/worker 必须在同一个系统运行，不能 Windows 与 WSL 同时读写一个 WAL 库。

先看计划（不写文件）：

```powershell
python scripts/deploy/manage.py plan --profile workbench-cpu --storage-root D:/video
python scripts/deploy/manage.py setup --profile workbench-cpu --storage-root D:/video --dry-run
```

安装和诊断：

```powershell
./scripts/deploy/setup.ps1 -Profile workbench-cpu -StorageRoot D:/video
python scripts/deploy/manage.py doctor --profile workbench-cpu --storage-root D:/video
./start-platform.ps1 -StorageRoot D:/video -TrainingReviewer human
```

Linux/macOS CPU 入口（模型 GPU 仅 Linux/WSL）：

```sh
bash scripts/deploy/setup.sh --profile workbench-cpu --storage-root /srv/btv-data
python3 scripts/deploy/manage.py doctor --profile workbench-cpu --storage-root /srv/btv-data
bash start-platform.sh --profile workbench-cpu --storage-root /srv/btv-data --reviewer human
```

浏览器打开 http://127.0.0.1:18080/training 。无资料时需要先同步媒体和清单，再在页面建标注项目。只启动页面不会执行模型任务。任务 worker 需另开终端，完整 CPU 设备使用 `start-worker.ps1 -StorageRoot ... -Profile desktop-cpu` 或 `bash start-worker.sh --storage-root ...`。`--reviewer agent` 专供自动测试，不能冒充人的确认。

所有启动器均从脚本位置定位源码，可在其他工作目录调用。Windows 的旧 `runtime/platform/env` 环境仍可用；新环境优先选择 `<storage>/runtime/<owner>/envs/<profile>`。用 `--env-root` / `-EnvRoot` 改变父目录，但必须仍在对应 runtime owner 内，避免漏算容量。环境已存在时 setup 会拒绝覆盖；需升级则指定新的环境目录。普通部署不改全局 Python，不安装 torch。

`setup` 用共享容量账本预留默认 2 GB 安装峰值，覆盖环境、缓存和临时目录，检查全局 700 GB 及固定 owner 配额；安装时监控该 owner 增量。失败保留部分环境以便检查，不自动删除。`--max-install-bytes` 可缩小预留，不能超过固定配额。外部已存在的环境占用仍需按项目容量规则另记。

CPU 依赖版本复用本项目已运行锁定版本，只安装二进制 wheel；首次安装需要能访问 Python 包索引。当前没有随包附带完整 wheelhouse，不能称为离线安装包。源码 ZIP 不包含任何现成 venv。`--dev` 可给 workbench/desktop 加入 pytest 等开发依赖。FFmpeg/ffprobe 由操作系统安装，不由本工具悄悄下载安装；`doctor --ffmpeg /path/ffmpeg --ffprobe /path/ffprobe` 可指定。运行时同样可指定这两项，或设置 BTV_FFMPEG/BTV_FFPROBE。

模型安装单独执行：

```sh
bash scripts/models/setup_device.sh --profile cpu-prep --storage-root /srv/btv-data --conda-executable /path/to/conda --dry-run
bash scripts/models/setup_device.sh --profile gpu-base --storage-root /srv/btv-data --conda-executable /path/to/conda --apply
```

模型包集成后以 `docs/models/DEVICE_SETUP.md` 为准；本工具 models profile 只打印委托命令，不会把 GPU 包装入 CPU 环境。历史实验脚本保留用于复现，但旧盘符和旧环境前缀不代表新设备入口。

## 独立开发与模块运行

```powershell
python scripts/deploy/manage.py profiles
python scripts/deploy/manage.py run --profile library-cpu --storage-root D:/video --target library -- --help
python scripts/deploy/manage.py run --profile render-cpu --storage-root D:/video --target render -- --help
```

`--` 后为模块自身参数。原片路径在 manifest/合同里保存为 `asset_id` + 相对路径，不能跨设备写死盘符。每模块输入输出、依赖和入口见 `deployment/modules.json`；完整业务编排由工作台承担。默认源码可直接从根目录导入，不需要 `pip install .`；确需安装项目时基础依赖只有 Pydantic，Web 依赖为 `.[workbench]` 可选项。

## 导出源码包和历史

先提交当前改动；默认禁止导出脏工作树。正式包从固定 Git commit 的 blob 读取，不从其他 worktree 复制。

```powershell
python scripts/deploy/manage.py export --module workbench --output D:/video/platform/distributions/workbench.zip
python scripts/deploy/manage.py export --module full --output D:/video/platform/distributions/full.zip
python scripts/deploy/manage.py verify --archive D:/video/platform/distributions/full.zip
```

`core/library/workbench/models/render/full` 均可导出，`complete` 是 `full` 的别名。先创建输出父目录；同名文件存在即拒绝。每包含共享依赖、必要根文档、模块接口与小夹具、`source-manifest.json` 和 `CONTINUE_DEVELOPMENT.md`。清单逐文件记录 SHA256、字节数和源码 commit。临时试包可以显式 `--allow-dirty`，但它只能含已有 HEAD 跟踪文件，未提交标记保留，不能作为正式交付。

包内不含媒体、权重、数据库、环境、凭据或 .git。路径、链接、二进制和常见凭据格式均检查，但仍应审阅自己提交的源码，不能把正则检查当成完整秘密扫描。ZIP 是源码快照；保留分支和历史需另建 Git bundle：

```powershell
git bundle create D:/video/platform/distributions/history.bundle --all
git bundle verify D:/video/platform/distributions/history.bundle
# 目标设备
git clone D:/transfer/history.bundle badmintonTV
```

bundle 可能包含历史提交过的内容；本项目媒体/权重从未作为交付要求进入 Git，但转移前仍应核查历史凭据。不要推送远程仓库作为默认迁移步骤。不同模块分支完成后由主任务合并，再以同版合同接回流程。

## 数据、标注和数据库迁移

源码同步不会迁移标注和视频。先停止本项目 API/worker，使业务库和任务库处于一致业务状态；停止后导出两个库。没有停止时，SQLite backup API 可制作单库一致性备份，但多个库不构成共同事务，工具会要求 `--quiesced`。

```powershell
python scripts/deploy/manage.py export-state --storage-root D:/video --output D:/video/platform/backups/device-transfer-01 --database platform/platform.sqlite3 --database platform/runtime.sqlite3 --quiesced --manifest D:/video/data/training/handoff/annotation-catalog.v1.json --max-bytes 100000000
```

父目录必须存在。备份写入 platform 配额内并预留明确上限；不会复制正在运行中的 WAL 文件。`migration-manifest.json` 保存库哈希及资产相对路径；默认原片哈希是来源清单声称的值，`source_verification=not_checked`。加 `--verify-assets` 会只读原片并校验哈希，可能耗时较长，仍不复制媒体。`--quiesced` 会拒绝仍有 queued/running 待执行任务或 active/orphaned GPU 租约的队列；在备份副本中关闭旧设备活跃容量预留，并记录数量，来源数据库不受修改。导出期间还用每个来源库的 data_version 前后检查并拒绝并发变更；这不替代事先停止服务。单库在线备份只关闭导出自身预留，不能直接当成多设备完整迁移。备份失败时保留 `INCOMPLETE.txt`，不能恢复该目录。

把完整成功备份、原始资产清单/PTS sidecar、所需原片按相同相对路径分别复制到新设备；不自动复制全部大文件。目标设备停止 API/worker 后将备份库放回 `platform/`，核对迁移清单 SHA256，再启动服务。已经存在的目标数据库不得覆盖，先另行备份并明确选择版本。备份中可能包含用户设置和访问配置，按私密数据保管，不能提交 Git。运行中的数据库不要交给云盘实时同步；环境和缓存从定义重建。

## 验证范围

本目录 `DESIGN.md` 保存 P-04/P-05/P-06 的目标和实际状态。CPU 单元测试：`python -B -m unittest discover -s tests/deployment -v`。干净新设备完整安装、Linux/macOS系统差异、GPU驱动/模型与真实业务效果分开验收，未执行的不能借用源码打包测试结果。
