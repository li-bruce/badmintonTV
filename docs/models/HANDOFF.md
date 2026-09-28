# 模型模块交接

任务01a0e88b-416f-7ca2-bfec-c09ec1462866，分支work/models。已完成隔离WSL环境、严格CLI协议、GPU算子与真实单双打预训练前向；中文小模型实测不可靠，细手法分类尚不可验收。协议代码611eb39/00de444已由主任务集成，后续实测checkpoint见status与提交记录。

## 平台入口

在已集成仓库根目录：

```powershell
python -m packages.models catalog
python -m packages.models run --request REQUEST.json --result NEW_RESULT.json
```

WSL模型环境：

```bash
source environments/models.env.sh
# 003须为尚未使用的新run-suffix；002是已完成且不可覆盖的记录。
"$BTV_MODELS_ENV/bin/python" scripts/models/prepare_experiments.py --run-suffix 003
"$BTV_MODELS_ENV/bin/python" -m packages.models run --request /mnt/d/video/models/handoff/requests/real-pose-003.json --result /mnt/d/video/models/handoff/real-pose-003/attempt-01/result.json
```

管理员launcher用参数数组调用，Windows路径由launcher转换，绝不把请求拼进shell。模型不读写平台SQLite。请求须含schema_version/job_id/attempt_id/operation/assets/parameters/output_dir。assets是完整Asset数组；parameters.model_id必填；output_dir以models/开头。新attempt应使用新目录/result路径，既有结果不覆盖。

操作：query_parse、pose、video_embedding、movement_classification；analyze仅作为共享fixture兼容别名，依model_id解析非查询能力。平台queue可叫model，但CLI不能传operation=model。退出码0成功/1失败/2blocked/130cancelled。强杀未产result时由worker记录WORKER_INTERRUPTED并确认旧进程终止才释放GPU；解析数据、SHA256、stderr都不是成功凭据，检查result+exit+attempt。

## 模型清单与结果

`configs/models/catalog.json` 与 `D:/video/models/handoff/models.runtime-001.v1.json` 是2026-09-28实际WSL环境快照，三个ML模型为experimental。catalog实时检查本进程依赖、受控权重清单/文件大小：在没有torch的Windows平台Python执行会真实返回not_installed，平台必须选WSL环境启动。模型实际加载前复核完整文件SHA256；experimental不代表解析或动作准确率通过。

| model_id | 能力/结果 | 首版限制 |
|---|---|---|
| query-rule-v1 | QuerySpec artifact，stdlib | 有限中文词表，不支持的修饰/否定/任选/未确认姓名明确失败；不推断player_id |
| query-endpoint-v1 | 兼容端点解析 | 管理员BTV_LLM_CONFIG路径；只发固定prompt+查询；默认loopback，远程需显式HTTPS；未配blocked |
| qwen3-0.6b | 本地小模型解析，实测仍不可靠 | 首轮0/24，fewshot开发诊断2/24；默认CLI未换prompt，失配blocked，无静默fallback |
| torchvision-keypointrcnn | COCO17原片坐标+PTS特征 | 每帧detection ID，track_id/player_id=null；没有跨帧跟踪或手法分类 |
| clip-frame-mean | 512维短窗抽帧均值向量 | 无时序顺序、中文检索未验证，不能据此识别细搓球 |
| skeleton-temporal-v1 | unavailable | TRAINING_DATA_REQUIRED；只有骨骼特征函数，未训练分类器 |

姿态与CLIP结果events为空，这是没有动作证据的真实状态。所有特征含源asset/time/hash、模型版本/job/attempt与未验证事项。推理max30秒、max120采样帧、80M保留像素、10k解码帧/解码循环60秒截止；单次原生解码阻塞还需worker超时兜底。只在platform GPU租约下运行；本轮模型GPU实验已结束，已给platform真实pose联调窗口。

兼容端点管理员JSON只有base_url/model/api_key_env/timeout/allow_remote；不接受HTTP响应重定向，不继承系统代理，key只放Authorization，不返回原始服务端错误。未部署实际LLM端点，loopback测试是传输测试。

## 已验证与数据边界

- 主任务共享合同8900958（platform原6a3e3d）：canonical model-request、所有结果fixtures、六清单（含新WSL快照）、五真实Asset、五实际CLI结果、QuerySpec交叉验证通过。
- 协议/查询/安全边界100项：Windows98过、2个symlink权限跳过；WSL100项全过，包含symlink与真实loopback HTTP。主任务独立复核同样通过。后续小型容量修复的定向测试另见status。
- 真实四片来源D:/video/data/handoff/assets.v1.json，另有assets.doubles.v1.json一条高校双打；FBBench match_id unknown，DroneBD仅保守来源组，全部split unassigned，没有细标签真值，只能预训练推理与人工诊断。
- 协议/算子/真实推理/准确率四者分开报告。缺细标签、专家命名锚点与跨场真值，详见docs/issues/models-fine-label-ground-truth.md。

| 实际运行 | 样本/采样 | 耗时秒 | 峰值allocated / reserved bytes |
|---|---|---:|---:|
| real-pose-002 | 单打6秒，4fps，24帧 | 26.398954 | 489201152 / 792723456 |
| real-video_embedding-002 | 同一单打窗口，24帧，512维CLIP | 44.853380 | 616739840 / 664797184 |
| real-pose-doubles-001 | 双打4.404秒，2fps，9帧 | 28.254249 | 574289408 / 731906048 |

上述耗时从源文件hash校验之后开始，含解码、torch导入、权重hash/模型加载、推理和features写入；不含进程启动、容量扫描、源hash、report/result写入。是单片冷启动，不能据外推字段声称完整一小时视频的实测吞吐。实际PTS与源hash、每帧QA见docs/experiments/models-002-real-baselines.md。

产物均在 `D:/video/models/handoff/<运行名>/attempt-01/`：features.json/report.json/result.json；原始请求在requests/。单双打各检查三个分散时点：场上人物可见检测，但场边裁判/重复框与编号互换已观察到，远端/遮挡关节不确定，没有track/player身份。CLIP英语prompt余弦只是诊断相似度，不是动作概率；A/B/C正式优劣、细手法和检索准确率均未评测。

Qwen原始记录在query-diagnostic-001与002（每轮run-metadata、24条raw及report）。固定bf16/greedy/non-thinking、768 token上限，首轮0/24，加入3示例后2/24；第二轮看过第一轮结果后调试，属于开发集诊断而非独立用户测试。默认CLI复杂查询qwen3-0.6b-002为blocked2/LLM_SCHEMA_OR_SEMANTIC_FAILURE。受限规则解析可用，但不冒充LLM成功。详见docs/experiments/models-003-query-diagnostics.md。

复核命令：

```powershell
$env:BTV_CONTRACT_FIXTURES_DIR='C:/Users/USER/Desktop/Program/badmintonTV/packages/contracts/fixtures'
python -m unittest discover -s tests/models -v
D:/video/runtime/platform/env/Scripts/python.exe scripts/models/check_contracts.py --contracts-repo C:/Users/USER/Desktop/Program/badmintonTV
```

## 环境和存储

WSL共享base=/home/ubuntu/miniforge3（conda25.9.1已有）；新models prefix=/mnt/d/video/runtime/models/env。公共包缓存=/mnt/d/video/runtime/shared/pkgs。无需其他任务安装公共Conda。Python3.11.16/torch2.7.1+cu128/vision0.22.1+cu128/transformers4.51.3/PyAV15.0.0，pip check通过，5090 CUDA12.8五项实际算子通过。脚本environments/models.env.sh固定HF/Torch/tmp/pip路径，禁自动线上拉权重；docs/models/ENVIRONMENT.md和原样/便携锁提供复现依据，未重新做一次干净环境安装。没有模型网络服务端口。

model权重/特征等<=180GB；models runtime<=35GB；公共base+cache<=15GB（原生base+旧pkgs保守约5.925GB计入，其他用户env单独记录不修改）；其他runtime20GB保留。没有删除用户数据。下载中断partial保留有记录，下载流实际字节受限；models写者原子排他预留，其他owner按固定全额配额保守计数。

权重原始manifest位于D:/video/models/weights各目录，Git仅保存configs/models/weights-lock.json（来源、固定revision、每文件hash、license）。代码许可、预训练权重、标注、原视频分别记录；unknown视频权利不因开源模型改变。平台实际受控WSL/GPU租约端到端结果由platform任务保存，不把本模块直接CLI运行冒充平台联调。
