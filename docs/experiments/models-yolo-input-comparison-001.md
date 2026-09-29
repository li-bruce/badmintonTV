# models-yolo-input-comparison-001：YOLO与旧姿态的同PTS真实输入对照

日期：2026-09-29。主协调执行模型；本子任务只读原JSON做CPU分析，没有运行GPU、写D盘、修改原结果、生成BST pack或把校准改为human。结论：**31/32帧仍失败，54帧几何异常减轻，但YOLO整体诊断通过数更少**。这是一段真实短窗的输入诊断，非识别准确率或正式模型优劣实验。

## 输入与可追溯产物

Asset `asset-5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90`；源SHA256 `5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90`。源文件 `data/raw/finebadmintonbenchmark/video_001951.mp4`，669,106 B，1280×720、30/1 fps、6,000ms。PTS time_base=1/15360，stream_start_pts=0。`match_id=unknown`、`split=unassigned`；不能当独立比赛正式test样本。

两份输出均覆盖 `[700,3700)` ms、原源帧21–110，**90/90 PTS完全匹配**。完整PTS清单由 `10752+512*i, i=0..89` 精确表示，首10752、末56320；源时刻700–3666.666…ms。旧输出 source_ms 保留小数、新输出四舍五入整数；比对使用原整数PTS，未用毫秒四舍五入join。

所有路径均相对 `D:/video/`；媒体、权重和实际JSON保留D盘，不提交。

| 产物 | 相对路径 | 字节数 | SHA256 |
|---|---|---:|---|
| 旧pose features | `models/jobs/job-b8a4ac96da6543f8b4f6afc5ae3c4220/attempt-1/features.json` | 2,396,704 | `1980da632d679dcec7fb1193b81ebce73bda7d2f7d877e29140bd25f58a5771a` |
| 旧pose report | `models/jobs/job-b8a4ac96da6543f8b4f6afc5ae3c4220/attempt-1/report.json` | 2,226 | `dd205edd84307c0a53999803fb8f90c35e03e95be79fa599e94e2dcd8f05c72b` |
| YOLO features | `models/jobs/job-98cb65954fab42408f3b6fd1082d6330/attempt-1/features.json` | 2,381,643 | `29fc0727683acf59ce67e9ebb9c54cc1a1cb1534fb55060693dc18d4ece149a2` |
| YOLO report | `models/jobs/job-98cb65954fab42408f3b6fd1082d6330/attempt-1/report.json` | 8,003 | `eed0616e7da0995a7540f0fddab88b9b7dd487596eafab53c1883f70ef1932bb` |

旧模型 `torchvision-continuous-pose@0.1.0`：COCO Keypoint R-CNN、score_threshold=.7，未实现tracking，权重清单SHA `af6573d08a5db3f244cde6039435a5853a3f3408903a60d4955907718f5e6d12`。YOLO `yolo11n-pose-bytetrack@0.1.0`：ultralytics8.3.203、imgsz640、detector conf=.1、NMS IoU=.7；权重6,255,593 B，SHA `869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0`。两个detector阈值/原生分数语义不同，不能把它们当校准后同等阈值。

YOLO代码/权重为AGPL-3.0路径，详见 [复用记录](../models/YOLO_POSE_REUSE.md)。本Asset源视频rights.status仍unknown，allowed_uses为空；两份产物usage_scope均general，**general不是公开发布权利确认**。数据卡Apache-2.0声明与原广播视频权利继续分开。

## 对照方法与实际结果

只读脚本 `scripts/models/compare_pose_inputs.py` 复用 `prepare_bst_window.py` 的固定Agent提议校准：远左(380,327)、远右(896,327)、近右(1050,668)、近左(221,668)→unit court四角。ID `video001951-root-agent-proposed-20260929`，`proposal=true/human_confirmed=false`。投影两脚踝再求均值、soft边界(-.01,1.01)、两候选分居y=.5两侧且间距≥.05。邻帧诊断门槛仍为court速度≤6单位/秒、图像中心≤2.5图像对角线/秒；这些是未校准的工程守卫，不是人体运动真值。

每帧保留全部检测，按同一几何规则统计；无手动删掉重复框、无用ByteTrack非空ID筛掉无ID人体。遇几何失败后中断连续性检查，下一有效帧重新起段，遵循当前准备脚本。本文“通过”仅指这个**pose几何/连续性守卫**，不含羽球、击球边界、身份或关键点真值，不等于BST完整输入可用。

| 同90帧诊断 | 旧pose | YOLO+ByteTrack |
|---|---:|---:|
| 原始检测数 min/median/max | 9 / 9 / 9（无cap遗漏） | 5 / 7 / 8 |
| 场内候选恰好2帧数 | 88 | 81 |
| 场内候选仅1帧数 | 2：31、32 | 7：29–35 |
| 场内候选3帧数 | 0 | 2：41、66 |
| pose几何/连续性守卫通过 | 87/90 | 81/90 |
| 额外速度异常 | 54 | 无（仅在几何成立的相邻段检查） |

没有真值，不能把“场内候选仅1”直接解释为真实人体漏检，也不能把候选3直接定为真正3人入场。此处只是固定投影/门槛下的输出表现。

| 关键原源帧 / PTS / 时间 | 旧结果 | YOLO结果 | 可支持的判断 |
|---|---|---|---|
| 31 / 15872 / 1033.333ms | 场内候选1 | 场内候选1，只有近侧ID1 | 未改善；远端候选缺失/投影问题需源帧QA |
| 32 / 16384 / 1066.667ms | 场内候选1 | 场内候选1，只有近侧ID1 | 未改善 |
| 54 / 27648 / 1800ms | 远侧court速度7.038>6；脚踝原生heatmap分数-0.752/-2.310 | 远侧速度0.585；ID2；detector .212；左右踝conf .781/.666 | 此局部几何跳变减轻，关键点正确性仍unknown |
| 41 / 20992 / 1366.667ms | 两候选且守卫通过 | 3候选；近侧两框IoU=.632，一框ID1、另一框null | 新增重叠候选；不能静默删null框来凑双人 |
| 66 / 33792 / 2200ms | 两候选且守卫通过 | 3候选；近侧两框IoU=.693，一框ID1、另一框null | 新增重叠候选；不自动NMS二次修正 |

第65帧两模型pose守卫均通过，但既有羽球65/66帧缺失属于另一模态，YOLO人体运行不会修复它。没有把旧60帧综合输入的55有效改写为本表90帧pose计数，也没有生成“补齐后BST成功”记录。

## 匿名ID与远端脚踝

原始YOLO输出ID1出现90帧；ID2出现79帧，缺口为28–35及99–101共11帧；ID13出现76帧，按同提议H全部位于场外。所有ID仍只是ByteTrack在单镜头内的模型关联，不等于人名或已验证身份。

在81帧恰好两侧候选的子集中，近侧ID1为81/81；远侧ID2为77/81，另4帧为null。可比较的连续帧中未出现两个不同非空ID切换；这不证明跨缺口是同一个真实人，也不是IDSW=0的真值评测。旧模型track_id全null，无法据此比较身份指标。ByteTrack的分组索引恢复只保持检测对应，不是ReID。

YOLO远侧子集162个脚踝conf：min .613792、median .951270、max .988088；81/81帧双踝都≥.5。这个分布**条件于场内候选恰好2且脚踝可用于投影**，漏掉的7帧和额外候选帧没有被变成高置信观测。高分不证明投影脚点真实正确；54帧远端分数仅.781/.666，仍需图像检查。

旧模型相同筛选的88帧/176个远踝原生分数为min -2.864819、median3.782601、max6.109855；这些是torchvision原始关键点heatmap分数，不能和YOLO的[0,1] confidence作数值涨跌/概率对照。COCO第三维1也不能当作“人工确认可见”。

## 计时与资源：保留原记录边界

YOLO report：CUDA、torch2.7.1+cu128，融合前2,874,462参数，固定wheel校验260个源码/配置文件。peak allocated **151,847,424 B**，reserved **176,160,768 B**；旧pose分别489,193,472 B / 792,723,456 B。均为各自这次进程报告，非整套系统最大显存。

| 原报告阶段 | YOLO秒 | 旧pose秒 |
|---|---:|---:|
| 源hash | .014522 | .004669 |
| 模型cold加载 | 32.209544（含本适配器依赖/包核验路径） | 1.258847（另列weight核验1.111214） |
| 源解码/转换 | .170175 | decode .123919 + preprocess .673092 |
| pose阶段 | 1.737745 | model2.854153 + postprocess .262752 |
| ByteTrack | .060824 | 未实现 |

YOLO首真实帧pose wall为1.024859秒，后89帧合计.712886秒、中位.007742秒。它们是此次predict调用统计，首帧含冷启动；没有paced ingest或持续稳定吞吐试验。旧报告另有elapsed_seconds41.524129，但两套cold/preprocess/全程计时边界不同，不能直接计算加速倍数。

**原YOLO report没有D2H/list转换、检测序列化、execute整体elapsed，不能将现有分项相加称完整端到端。** 原JSON保持不变。后续adapter修复已添加transfer/serialize、features写入、execute elapsed/unattributed，并注明仍排除最终report写入/Artifact hash/worker IPC；只有下一次实际运行能产生这些实测新字段。没有把短片冷启动外推为“整小时实测”、实时达标或精度。

## 复现与验收状态

只读分析命令（只向stdout输出JSON）：

```powershell
python scripts/models/compare_pose_inputs.py --root D:/video --old models/jobs/job-b8a4ac96da6543f8b4f6afc5ae3c4220/attempt-1/features.json --yolo models/jobs/job-98cb65954fab42408f3b6fd1082d6330/attempt-1/features.json
```

CPU命令 `python -m unittest tests.models.test_yolo_pose_reuse tests.models.test_pose_input_comparison -v`：16+3 PASS，覆盖精确CFR首尾、同PTS不丢未匹配帧、输入不修改、原生分数分开、校准不升级human、null metrics；不是视频识别成功测试。

| 用例 | 目标及验证 | 实际/状态 | 原因和下一步 |
|---|---|---|---|
| R-07b | 真pose/可审查匿名关联/提议H同源PTS可回查 | 真实90帧运行和数值对照完成，完整下游窗口 **BLOCKED** | 缺失、重叠候选、脚踝/身份/校准未有真值；检查对应源帧，不自动转换BST输入 |
| R-07c | 完整实时链路时延证据 | **NOT_RUN** | 原短窗计时不完整，无paced/full-match实测 |
| S2-03 | 模型能力对真实视频验证 | 真实模型输出存在，完整能力验收 **BLOCKED** | 不以JSON成功/帧数通过替代正式验收 |
| S2-04 | 目标细动作真值评估 | **NOT_RUN** | 没有细动作真值及分类器；标签unknown、accuracy/recall保持null |

当前结论保留失败：更小显存与54帧局部变化不足以支持替换旧输入路线；先做新的独立真实片段验证，继续显式保留缺球/人体关联不确定性。
