# 三环境统一 ModelManifest 清单

2026-09-29：新增 `scripts/models/compose_catalog.py`，只读采集与合并；**尚未更新 `configs/models/catalog.json`**。VL 环境未安装完成，未采集 VL 快照、未构造其成功状态。最终发布须等待根任务确认安装与真实前向结果。

## 11 张卡的固定归属

| 实际执行环境 | registry model_id |
|---|---|
| `/mnt/d/video/runtime/models/env` | `query-rule-v1`、`query-endpoint-v1`、`qwen3-0.6b`、`torchvision-keypointrcnn`、`clip-frame-mean`、`skeleton-temporal-v1`、`tracknetv3-reuse`、`torchvision-continuous-pose`、`bst-cg-ap-reuse` |
| `/mnt/d/video/runtime/models/yolo-env` | `yolo11n-pose-bytetrack` |
| `/mnt/d/video/runtime/models/vl-env` | `qwen3-vl-embedding-2b` |

脚本固定 9+1+1，并核对实际 registry 的完整 ID 集合。新增/删除 ID 必须显式更新归属；重复、遗漏、环境间错配均报错。不能在 Windows 或旧模型环境运行一次 catalog 后修改 prefix，冒充其它环境的实测结果。

`probe` 必须在对应 WSL 解释器运行，核对 `sys.prefix`、`-s`、`PYTHONNOUSERSITE=1`、共享存储根，拒绝非空 `PYTHONPATH`。只通过 `importlib.metadata` 和顶层 `find_spec` 读取包版本、distribution 实际目录、模块 origin；来源必须在本环境或其 base prefix。YOLO 的 system-site-packages 来自旧 models/env，因此两者分别记录。采集不 import torch、Ultralytics、Transformers、NumPy、PyAV，不触发默认配置写入，不运行 CUDA、下载或安装。

每张卡的 `environment` 保存真实 prefix/base_prefix/executable/Python、检查时间/方法、包版本与路径、registry/reuse_catalog/采集脚本文件哈希。模型源码与合同来源有独立路径断言。权重清单检查仍是存在/大小检查；manifest 中的权重 SHA **不是此次重新计算的权重 SHA**，执行适配器继续负责完整校验。

## 已完成的只读实机检查

| 证据 | 实际结果 |
|---|---|
| `catalog-probe-base-20260929.json` | 真 models/env，Python 3.11.16；torch 2.7.1+cu128 / torchvision 0.22.1+cu128 / transformers 4.51.3；只取归属本环境的 9 张卡 |
| `catalog-probe-yolo-20260929.json` | 真 yolo-env，Python 3.11.16；torch 来自 models/env，Ultralytics 8.3.203 来自 yolo-env；只取 YOLO 卡 |
| `catalog-job-evidence-20260929.json` | 只读重新校验四个真实平台作业的 request/result/bridge.done、8 个产物的 SHA/大小/producer；没有重新推理 |
| 主合同验证 | 上述 10 张原始快照卡均通过实际主 checkout `ModelManifest`；主 `packages/contracts/models.py` SHA `7de5d370741d2d26b02cfd2c7caaa8bf2cbec8da1044ea13f8c6328d3d80aeed` |
| CPU 自动测试 | `test_compose_catalog.py` 16 项通过；合成证据只测试元数据/守卫，不能称真实模型成绩 |

四条真实执行证据：

- YOLO：`job-57c6354813b94ad1ba12d42b24e5968e / attempt-1`。
- TrackNet：`job-d9c832fd94384ee3950918badc767b15 / attempt-1`。
- 连续姿态：`job-b8a4ac96da6543f8b4f6afc5ae3c4220 / attempt-1`。
- 基础姿态：`job-3dc9ece15e914eecb9616ac306ece6b8 / attempt-1`。

原始快照保留 registry 原返回值；例如 BST 在文件和依赖齐全时原始 registry 返回 experimental。**这些 probe 文件不是 UI catalog**：合并会应用下列真实输入门禁，BST 不以该原状态发布。

## 合并与状态门禁

合并必须同时提供三份真实环境快照。各快照的源文件哈希必须一致；采集后脚本或 registry 改动时重新采三份，保留旧观察记录。合并进程不重新探测 ML 依赖，因而不会把 Windows 缺 torch、旧环境 transformers 4.51.3 写成 VL 的实机状态。

状态上限和证据分开：

- BST 固定为 unavailable，reason 明确缺真实连续双人 COCO17、球观测、场地 H/击球边界审阅；引用固定 52 帧窗口中 25 帧缺球与远端漏检的报告。权重存在不解除输入前置条件。
- VL 版本门禁要求本环境 torch 2.8.0、torchvision 0.23.0、transformers 4.57.3、qwen-vl-utils 0.0.14；不接受 `ready` 输入。即使文件/依赖齐全，无合格真实视频执行证据也保持 unavailable。缺文件/包时保留 not_installed/unavailable 的原始原因。
- VL 的合格证据必须包括独立 request、succeeded result、`compute_stopped=true / exit_code=0 / reason=completed` 回执，以及产物哈希/大小/内外 producer。另检查报告成功状态、2048 维有限向量、窗口对应请求 Asset/hash、原 PTS/时基/原点换算/采样点数/严格时间顺序/时间范围，以及运行报告版本与当前环境一致。不能用 CPU fixture、只有文本向量或其它 model_id 的成功记录晋升。
- YOLO 安装版本不为固定 8.3.203 时 unavailable。成功执行证据也不将模型升级为 ready，不推导准确率、细标签或稳定实名跟踪。
- 其它卡保留归属环境 registry 的真实状态及 reason；没有运行证据时 `execution_evidence=null`。基础模型已有诊断局限仍见原文档，尤其 Qwen3-0.6B 并非可靠中文解析器、骨骼细分类仍未训练、管理员端点未配置。

执行证据位于合同允许的 `evaluation_report` 字典，环境检查证据位于 `environment`；不增加 ModelManifest 顶层字段。merge 用指定主 checkout 的实际合同验证每张卡，并记录合同哈希。清单 entrypoint 是模型协议描述，不会自动创建平台 launcher 注册或 GPU 授权。

## 最终发布流程（尚未执行）

在 VL 安装与真实作业完成后，从同一源码版本重新采集三个环境。下面为 WSL 命令；文件写到仓库 docs，脚本本身只输出 stdout。`FINAL` 替换为新的观察编号，不覆盖前面的真实快照。

```bash
repo=/mnt/c/Users/Li/.codex/worktrees/c5b1/badmintonTV
cd "$repo"
env -u PYTHONPATH PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 BTV_STORAGE_ROOT=/mnt/d/video \
  /mnt/d/video/runtime/models/env/bin/python -s -B scripts/models/compose_catalog.py probe --environment base \
  > docs/models/catalog-probe-base-FINAL.json
env -u PYTHONPATH PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 BTV_STORAGE_ROOT=/mnt/d/video YOLO_AUTOINSTALL=false \
  /mnt/d/video/runtime/models/yolo-env/bin/python -s -B scripts/models/compose_catalog.py probe --environment yolo \
  > docs/models/catalog-probe-yolo-FINAL.json
env -u PYTHONPATH PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 BTV_STORAGE_ROOT=/mnt/d/video \
  /mnt/d/video/runtime/models/vl-env/bin/python -s -B scripts/models/compose_catalog.py probe --environment vl \
  > docs/models/catalog-probe-vl-FINAL.json
```

Windows 平台 Python 拥有 Pydantic；用全新进程先导入主合同，脚本已做实际 module-origin 断言。`ACTUAL_VL_JOB` 必须替换成已完成真实作业，不使用预期 ID：

```powershell
& 'D:/video/runtime/platform/env/Scripts/python.exe' -B scripts/models/compose_catalog.py merge `
  --base docs/models/catalog-probe-base-FINAL.json `
  --yolo docs/models/catalog-probe-yolo-FINAL.json `
  --vl docs/models/catalog-probe-vl-FINAL.json `
  --storage-root D:/video --contracts-repo C:/Users/USER/Desktop/Program/badmintonTV `
  --evidence torchvision-keypointrcnn=platform/jobs/job-3dc9ece15e914eecb9616ac306ece6b8/attempt-1 `
  --evidence torchvision-continuous-pose=platform/jobs/job-b8a4ac96da6543f8b4f6afc5ae3c4220/attempt-1 `
  --evidence tracknetv3-reuse=platform/jobs/job-d9c832fd94384ee3950918badc767b15/attempt-1 `
  --evidence yolo11n-pose-bytetrack=platform/jobs/job-57c6354813b94ad1ba12d42b24e5968e/attempt-1 `
  --evidence qwen3-vl-embedding-2b=platform/jobs/ACTUAL_VL_JOB/attempt-1 `
  > docs/models/catalog-review-FINAL.json
```

检查 exit code=0、恰好 11 卡、每卡实际环境/状态/reason/证据，再由根任务一次发布 `configs/models/catalog.json` 并让 UI 导入。若 VL 真实 forward 失败，不提供假成功证据；合并会保留 unavailable，可以如实发布全部 11 卡。不要用旧 `export_environment_snapshot.py` 在单一环境覆盖最终组合清单。

复核命令：`D:/video/runtime/platform/env/Scripts/python.exe -B -m unittest tests.models.test_compose_catalog -v`。本阶段没有 D 盘写入、依赖安装、GPU 使用或服务端口；仅产生小型脚本、测试、文档及只读元数据快照。
