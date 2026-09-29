# 平台模型适配器配置

核对日期：2026-09-29。本文依据[管理员配置脚本](../../configure-platform-adapters.ps1)、[平台API](../../apps/platform/main.py)、[worker](../../packages/runtime/worker.py)、[WSL桥接器](../../packages/runtime/wsl_bridge.py)和[当前模型清单](../../configs/models/catalog.json)描述配置行为；不把命令登记或模型卡状态当作实际推理验收。

## 固定命令映射与默认环境

在API和worker各自的PowerShell终端中点引入脚本，使两个进程继承相同环境。脚本不启动服务、不安装依赖、不下载权重，也不自动授予GPU排期。

```powershell
. ./configure-platform-adapters.ps1
```

默认`StorageRoot=D:/video`，平台解释器为`D:/video/runtime/platform/env/Scripts/python.exe`，缺失即报错。`ModelsRepo`默认脚本所在的集成仓库，不默认依赖另一个开发worktree。`WslEnvPrefix=/mnt/d/video/runtime/models/env`，独立视觉语言环境`VlEnvPrefix=/mnt/d/video/runtime/models/vl-env`，独立YOLO环境`YoloEnvPrefix=/mnt/d/video/runtime/models/yolo-env`。脚本为`BTV_MODEL_COMMANDS_JSON`写入按完整model_id匹配的参数数组：

| model_id | 默认注册 | 执行路径 |
|---|---|---|
| `query-rule-v1` | 是 | 平台Python `-m packages.models`，规则解析不依赖模型GPU环境 |
| `torchvision-keypointrcnn` | 是 | 平台Python启动WSL桥，Ubuntu中使用`WslEnvPrefix` |
| `tracknetv3-reuse` | 是 | 同上 |
| `torchvision-continuous-pose` | 是 | 同上 |
| `bst-cg-ap-reuse` | 否；须`-EnableExperimentalBst` | WSL桥，使用`WslEnvPrefix` |
| `qwen3-vl-embedding-2b` | 否；须`-EnableVlEmbedding` | WSL桥，使用独立`VlEnvPrefix` |
| `yolo11n-pose-bytetrack` | 否；须`-EnableExperimentalYolo` | WSL桥，使用独立`YoloEnvPrefix`；当前交接版本0.1.0 |

三个开关只增添固定命令映射，不改变模型卡、权重状态或质量结论。可同时启用；API和worker必须使用相同开关。`query-endpoint-v1`、`qwen3-0.6b`、`clip-frame-mean`及其他ID不因出现在catalog中就自动获得命令权限。

YOLO必须显式启用，例如`. ./configure-platform-adapters.ps1 -EnableExperimentalYolo`。管理员可通过`-YoloEnvPrefix`指定其他独立环境；脚本拒绝旧`/mnt/d/video/runtime/models/env`、当前`WslEnvPrefix`或`VlEnvPrefix`，避免误复用主环境或VL环境。修改`WslEnvPrefix`不会改变YOLO默认环境；未传YOLO开关时不登记该ID，也不回退到旧环境。版本来自模型卡和任务快照，不由命令映射硬编码。这些配置不表示YOLO依赖或权重已安装，更不表示推理通过。

WSL命令前缀固定为平台Python `-m packages.runtime.wsl_bridge --distribution Ubuntu --env-prefix <prefix> --repo <ModelsRepo>`，worker追加结构化的`run --request <path> --result <path>`。浏览器请求和模型卡`entrypoint`均不能替换可执行命令；没有完整ID映射时worker明确blocked/not_installed，不使用通配fallback。

`-ModelsRepo`仅供管理员显式指定临时开发仓库。`-ModelCatalogPath`可指定已导出的本地catalog快照；未提供时使用`<ModelsRepo>/configs/models/catalog.json`。脚本还设置平台`PYTHONPATH`、`BTV_STORAGE_ROOT`、当前仓库`BTV_CODE_REVISION`、固定`BTV_RENDER_COMMAND_JSON`；传入`-FfmpegPath/-FfprobePath`时解析为本地路径。重新点引入会重建整张命令表，不能假定上次开关仍然有效。

## 清单快照与API展示

当前仓库`configs/models/catalog.json`是模型模块交接记录中的2026-09-28 WSL快照，六项版本均为0.1.0。下表说明以该文件和默认脚本组合得到的展示规则，不是本次启动服务后的实测结果。

| model_id | 文件内状态 | 默认映射 | GET models的展示规则 |
|---|---|---|---|
| `query-rule-v1` | ready | 有 | 保留ready |
| `query-endpoint-v1` | unavailable | 无 | 保留unavailable；快照理由为未配置`BTV_LLM_CONFIG` |
| `qwen3-0.6b` | experimental | 无 | 降为unavailable：独立运行命令未登记 |
| `torchvision-keypointrcnn` | experimental | 有 | 保留experimental |
| `clip-frame-mean` | experimental | 无 | 降为unavailable：独立运行命令未登记 |
| `skeleton-temporal-v1` | unavailable | 无 | 保留unavailable：缺专家细标签、跨比赛真值及训练checkpoint |

TrackNetV3、continuous-pose、BST、Qwen3-VL及YOLO这五个新ID尚未包含在这一仓库快照中。固定映射已存在不等于模型卡已展示；清单缺项也不能据此断定对应WSL环境未安装。须使用包含这些ID的已集成模型代码，在目标原生环境导出对应快照，再通过`-ModelCatalogPath`选择该文件，或导入经验证的模型卡。旧registry只认识旧六项时，重跑旧代码不会自动发现新适配器。

| API | 行为与边界 |
|---|---|
| GET `/api/v1/models` | 合并数据库模型卡与管理员catalog，同ID以catalog为准。catalog须存在、≤16MB、schema_version为1.0并通过ModelManifest校验。ready/experimental无固定命令时降为unavailable；完全无卡则返回not_installed占位项 |
| POST `/api/v1/models/import` | 导入单张合法模型卡；卡片不能授予命令执行权。管理员catalog同ID仍优先 |
| GET `/api/v1/models/{id}/health` | 返回`model_id,status,reason,command_registered`；只反映卡片和注册信息，不主动加载WSL依赖、权重或GPU |
| POST `/api/v1/models/{id}/run` | 操作须属于卡片capabilities；将模型ID/版本/卡片状态/操作/源Asset固化到job。202只表示已入队，实际结果须检查job及attempt |

不要把`health.command_registered=true`称为推理成功。worker会验证非空参数数组、请求及结果大小、JobResult身份和退出码；结果成功须有对应attempt的真实产物。GPU模型仍受排期窗口、租约、取消和超时约束；WSL桥命令在worker侧按GPU任务保守处理。资源入口为GET `/api/v1/resources/gpu`。

## 使用原生WSL状态判断依赖

模型catalog在执行它的Python进程中检查依赖，以及受控权重清单和文件大小。在没有torch的Windows平台venv中执行`python -m packages.models catalog`，得到的not_installed仅描述该Windows解释器；不得据此否定WSL模型环境。反过来，旧WSL快照experimental也不证明当前权重或环境仍健康。

应在所配置Ubuntu仓库和目标环境内检查，例如模型模块主环境的只读catalog入口：

```bash
source environments/models.env.sh
"$BTV_MODELS_ENV/bin/python" -m packages.models catalog
```

独立VL与YOLO适配器须分别在`VlEnvPrefix`、`YoloEnvPrefix`对应解释器中检查。桥接器实际使用目标环境`bin/python -m packages.models run`，Windows平台Python只负责启动、请求/结果路径转换和生命周期监督；不会在平台venv安装训练框架来伪装WSL状态。桥接器只允许Ubuntu及`/mnt/d/video/runtime/models/`下的规范环境路径，设置独立缓存和离线加载环境，强制`PYTHONNOUSERSITE=1`，按job/attempt/token监督子进程。

[模型快照脚本](../../scripts/models/export_environment_snapshot.py)在原生模型环境中将catalog写入指定`models/`产物路径，并更新仓库`configs/models/catalog.json`和`weights-lock.json`。当前版本还读取旧三组权重manifest，因此它属于模型模块受控维护操作，不是平台启动时的只读健康检查；本文没有执行它或覆盖既有快照。实际加载前的权重SHA256复核、真实素材运行、输出语义和准确率必须分别记录，experimental不能提升为三细标签或战术识别通过。

## 本次核对范围

已完成脚本、API、worker、WSL桥和当前catalog的源码/快照核对。本轮额外新增YOLO显式映射，并通过`tests/platform/test_adapter_configuration.py`实际调用PowerShell验证默认不登记、三个开关共存、独立默认/自定义前缀、共用环境拒绝及重新点引入时清除YOLO登记。测试使用临时空解释器占位文件，只运行配置脚本，没有启动API/worker、WSL、模型、GPU或安装依赖；未修改models包、数据库或模型环境。配置验证不能作为YOLO推理验收。

2026-09-29使用既有平台环境运行`python -m pytest tests/platform/test_adapter_configuration.py tests/platform/test_wsl_bridge.py -q`，结果为`43 passed, 1 skipped in 6.38s`；其中8项是新增PowerShell配置回归，跳过项为既有真实WSL watchdog显式opt-in测试。

前端修复另见[预览UI文档](PREVIEW_UI.md)。模型既有真实实验与许可边界见[模型交接](../models/HANDOFF.md)、[模型状态](../status/models.md)；平台阶段验收以[平台状态](../status/platform.md)记录为准。
