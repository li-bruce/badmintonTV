# 新职业源：BST 击球窗口、场地提案与真实输入缺口

日期：2026-09-29。状态：**BST BLOCKED，未执行前向、未生成输入 pack**。本次先独立查看原帧提出击球窗口，再读实际 TrackNet/YOLO 结果；窗口未随模型缺失调整。52 帧候选中有连续 25 帧缺球，远端人体也未形成完整检测/匿名轨迹。所有准确率、召回率和细标签保持 `null` / `unknown`。

## 源、权限与时间基准

| 字段 | 实际值 |
|---|---|
| Asset | `asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913` |
| storage-root 相对路径 | `data/training/fine-badminton-2026-zenodo-20292976-v1.0/extracted/876ddac3abe9141b8ce7f2fe.mp4` |
| SHA-256 | `b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913`；本次重新读取原文件校验一致 |
| 大小 / 时长 | 231,500,744 B / 1,306,040 ms |
| 源图像 / 时间基准 | 1280×720，25/1 fps，`time_base=1/12800`，`start_pts=0` |
| 来源 | [Zenodo 20292976 v1.0](https://zenodo.org/records/20292976)，原归档 SHA `a3518f52d66dd6c5d2b01ce1347de8e589516ccc24a72aae818fea64e0b04439` |
| 用途 / 权利 | `training_only` / `research_only`；非商业学术研究，原视频版权仍属原权利人；API CC-BY 与作者说明的冲突继续保留 |
| split / 身份 | `unassigned`；文件名和记分牌不构成人工身份确认，本文只称近端/远端；不改变 Asset 的 `camera_type=unknown` |

原 PTS 索引位于 `data/training/fine-badminton-2026-zenodo-20292976-v1.0/probes/b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913.5bdc8c2639e241309b21e15bbf9e87cb.pts.jsonl`，1,175,271 B，SHA-256 `b18a822e0c66dd7aa810b0d1c5684e1e9c923e2d0982ea7f520341798a2b10b9`。本次校验索引哈希，并将审阅帧与两个模型的 75 个源 PTS 逐项比对，一致。

根任务先提供 `new-training-source-review-004.jpg` 及 JSON 六点预览。本次使用既有 `/mnt/d/video/runtime/models/env/bin/python`、PyAV/Pillow **CPU** 解码全部 `[120000,123000)` ms：源零基帧号 `3000…3074`，PTS 为 `1536000 + 512*i, i=0…74`，相邻 40 ms，无删帧。5 张逐帧拼图只为显示缩小至 640×360；击球细查使用原分辨率局部裁图，另保存 3000/3050/3074 原分辨率帧。没有读取标签 CSV 推断击球，没有安装依赖或运行 GPU。

## 独立视觉击球提案

以下是查看实际球/球拍及前后运动变化后的 **Agent proposal**，不是专家或人类确认真值。25 fps 的采样、模糊及远端尺度不足以证明接触发生于某个精确曝光瞬间。保留区间，不把代表帧写成精确标注。

| 作者所需边界 | 代表源帧 / ms / PTS | 接触邻域（含端点） | 可见依据与局限 |
|---|---|---|---|
| previous hit，近端 | 3016 / 120640 / 1544192 | 3016–3017，120640–120680 ms | 3012–3016 来球下降至近端头顶挥拍附近；3017–3019 白色球影向画面上方离开。球拍/球影有模糊，接触可在相邻曝光之间 |
| current hit，远端 | 3052 / 122080 / 1562624 | 3051–3053，122040–122120 ms | 3050–3052 来球下降，3052 在伸出的球拍附近，3053 后随挥与球向近端落下；远端挥拍可见，握拍和拍面细节不清 |
| next hit，近端 | 3062 / 122480 / 1567744 | 3061–3063，122440–122520 ms | 3059–3061 来球降向侧向伸拍，3062 在拍前附近，3063 以后球影向上离开；只能提出低位回球接触邻域，不能确认细手法 |

三拍边界是在检查本次模型输出前提出。没有观察到该 75 帧内的剪切；这只是 Agent 逐帧审阅结果，不是镜头检测器认证。没有将任何邻拍设为缺失或捏造 `rally_start/rally_end`。

依据固定上游 [gen_my_dataset.py 的 `between_2_hits_with_max_limits`](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/blob/fb9b310bf4c8a8e3d89c75e61bc06a7ac3de62df/ShuttleSet/gen_my_dataset.py)及项目 `bst_reuse.shot_window`，25 fps 时 `half=12, limit=37, eps=6`：

```text
previous=3016, current=3052, next=3062  # Agent 代表帧，尚非确认真值
start=max(3016, 3052-37)=3016
end=min(3062+6, 3052+37+6)=3068        # exclusive
候选：[3016,3068)，52 个完整源帧，[120640,122720) ms
PTS：1544192 + 512*i，i=0…51；最后一个实际 PTS=1570304
```

这是候选计算，不是可执行 pack。边界区间仍需审阅，原 `[120000,123000)` 的 75 帧/模型原始文件全部保留；既没有挑选 observed 子段代替这次击球，也没有把缺失帧删除后压缩时间。

## 场地四点与 H：仅提案

以源帧 **3050 / 122000 ms / PTS 1561600** 的可见外场边线交点提出下列原像素点。顺序为远左、远右、近右、近左，对应单位场地 `(0,0),(1,0),(1,1),(0,1)`，不是单打内侧边线。

```json
{
  "status": "agent_proposal",
  "human_confirmed": false,
  "source_points": [[413,303],[852,303],[1150,710],[112,712]],
  "court_points": [[0,0],[1,0],[1,1],[0,1]],
  "homography": [
    [-0.22050590142889345,-0.16227940423006582,140.23959677184297],
    [-4.0446222419792486e-17,-0.5615738743850891,170.15688393868206],
    [0.0004576260251560346,-0.3240659673290996,1.0]
  ]
}
```

H 由四点约束解出，数值回投影最大绝对误差 `4.44e-16`；这仅证明代数求解满足输入点，**不证明选点正确或定位精度**。3050 参考图、3016/3052/3067 叠图已查看。片段内边线存在数像素漂移：3000 的远/近底线约 y=296/704，3050 约 y=303/711，因此固定 H 是有偏差的局部诊断。不能扩大适用到整场、宣称相机完全静止或校准已通过。腾空脚踝也不在地面平面，投影只能作为作者式位置近似，不能视为真实落脚点/米制速度。

## 两个真实模型输出与缺口

模型重试由根任务运行。本任务只读其结果。此前根任务报告两次 forward 被平台心跳 error5 取消；不把那些尝试计为模型成功。本节对应以下成功重试的实际文件，原文件未改写。

| 原始产物（相对于 `D:/video`） | B | SHA-256 |
|---|---:|---|
| `models/jobs/job-d9c832fd94384ee3950918badc767b15/attempt-1/tracknet-points.json` | 34127 | `1984f48c7ef961b83f4d8296b5fc5eaca610d83993febe9aec93868833343db6` |
| `models/jobs/job-d9c832fd94384ee3950918badc767b15/attempt-1/tracknet-report.json` | 4170 | `c907fdf4a846fc4b13df55f3f08439ffec5e1e4acd32f1eb3555d4cd0b54c76c` |
| `models/jobs/job-57c6354813b94ad1ba12d42b24e5968e/attempt-1/features.json` | 1793762 | `26f6b936682b18a64e6fd50e4cebed7bf0a3f95e23a725175a234d44271c532e` |
| `models/jobs/job-57c6354813b94ad1ba12d42b24e5968e/attempt-1/report.json` | 8412 | `cd32782e14b72b46029411cb6303c94ea437894f829686569faa2f2308bbcd82` |

两个模型的 Asset、源 SHA、`training_only`、`stream_start_pts=0`、时间基准与 75 个源 PTS 一致。TrackNet 的 `frame_index` 是窗口内零基编号，不能当整片源帧号；本报告统一由 `pts/512` 得到源帧号。YOLO 的 `source_frame_index` 为整片编号。

**TrackNet**：全 75 帧为 44 observed / 31 missing / 0 inpaint；固定 52 帧候选为 **27 observed / 25 missing / 0 inpaint**。缺失是一整段 `3020…3044`，源时间 `120800…121760 ms`，对应时间区间 `[120800,121800)`，PTS `1546240…1558528`，原因全部 `no_heatmap_component`。三个击球邻域有 observed 球点，不能抵消中间 1 秒没有观测的事实。部分原帧中球可能超出画面或不可辨；没有人工逐帧球真值，不能把全部 missing 宣称模型假阴性，也不能用响应峰值当准确率。全部原始 missing 和原因保留，不补零、不插值、不调用 InpaintNet。

**YOLO11n-pose + ByteTrack**：固定 52 帧原始人数分布为 `{3:5,4:1,5:20,6:9,7:11,8:3,9:3}`。多数额外框来自场外人员，人数不能直接代表球员数。使用上面的提案 H、原始两踝分别投影后求均值，并沿用 `candidate_player` 的有限值/COCO17 校验及 `(-0.01,1.01)` 场地范围诊断，18 帧得到两个场内候选，34 帧仅一个。后者为 `3031` 和 `3035…3067`；这是几何诊断，不是人体召回率，边界附近和腾空情况需看原图。

| 诊断对象 | 固定候选内实际输出 |
|---|---|
| 近端原始 anonymous-1 | 52/52 帧出现，无 ID 空缺；两踝分数 104 值 min/median/max = 0.942573 / 0.979298 / 0.995547；52 帧两踝均 ≥0.5 |
| 两候选子集的远端 | 18 帧：3016–3030 为 anonymous-7（15 帧）；3032–3034 为 null ID（3 帧）；不能自动把 null 接回 7 |
| 同子集远端两踝 | 36 值 min/median/max = 0.931093 / 0.975174 / 0.990496，18 帧两踝均 ≥0.5；只统计检测到的子集，高分不能覆盖后续漏检 |
| anonymous-2 / anonymous-8 | 左侧场外人员获得的原始 ID，不能拿来充当远端球员；原输出还含重叠框 |
| anonymous-6 | 右侧场外人员的原始 ID，52 帧持续；并不代表第二名球员 |

ByteTrack 没有 ReID，不确认姓名或跨镜头身份。近端同一个输出 ID 持续只是模型内部一致性，不是 ID-switch 人工评测；本次不自动形成 `track_assignment` 审核结论。

## 五帧叠图 QA（Agent，不是人体/球真值）

叠图直接用源 PTS 取原图，加所有原始框/COCO17、匿名 ID，以及有观测时的球点；missing 帧只显示文字，不画虚构球。

| 源帧 / ms | 实际可见与原输出对照 |
|---|---|
| 3016 / 120640 | 近端 anonymous-1 与远端 anonymous-7 有对应框；左侧场外人员为 anonymous-2；右侧裁判附近有重叠框。球点 (925,257) 接近可见白色球影，不能据这一帧确认定位误差 |
| 3032 / 121280 | 远端人物仍被检测，但 track ID 为 null；左场边有多个重叠框/ID。球输出 missing，未补点 |
| 3052 / 122080 | 原图远端腾空挥拍清楚，但原输出仅近端和两侧场外框，远端无框；球 observed=(490,132) |
| 3062 / 122480 | 近端侧向伸拍有框，远端人物可见却未检测；球 observed=(402,420)，仅为模型点 |
| 3067 / 122680 | 近端恢复中仍为 anonymous-1；远端人物可见却无框；右侧场外有重叠框；球 observed=(425,267) |

这五帧证明存在具体漏检/关联缺口，不足以计算 precision、recall、关键点误差或身份切换率。近端手腕、远端肢体和运动模糊也不能由 COCO17 高分升级为准确动作真值。球种、展搓/收搓、后退小跳和战术均未标注。

## 真实计时与显存边界

| 模型 | 成功重试原报告的实际计时（秒） | 显存 allocated / reserved |
|---|---|---|
| TrackNetV3 | cold=13.093648；decode=0.263241，pre=1.484268，model=0.353737，post=0.112432；pipeline_wall=2.261882；background_wall=0.694782；points_publish=0.010767 | 431,071,744 / 683,671,552 B |
| YOLO11n-pose + ByteTrack | hash=0.662599，cold=31.915124，decode/conversion=0.220434，pose=1.620733，tracking=0.054354，D2H/list=0.017345，detection serialization=0.004378，features JSON=0.051262，unattributed=0.528946；execute_elapsed=35.075174 | 151,847,936 / 176,160,768 B |

YOLO 此次包含新的首尾完整 CFR 校验（3000–3074，75 帧）及 D2H/序列化计时；`execute_elapsed` 仅从 execute 入口至 features JSON 写完，不含最终 report 写入、产物哈希、worker result IPC，不能当用户端到端延迟。旧实验报告不追溯改写。TrackNet 的分项、background 与 pipeline 有各自边界，不能全部直接相加称总耗时；报告的 replay `steady_rtf=0.546355` 及 `rtf_including_background=0.764149` 不是直播因果证明：`offline_weight` 使用窗口中未来信息，`causal_image_dependencies=false`，球点 `available_after_source_ms` 包含后续背景帧。所有数值仅为这次 3 秒有界任务，不能外推为实测整小时速度。

## 验收与下一步

| 对应固定用例 | 本次断言 / 实际结果 | 本次范围判定 |
|---|---|---|
| R-07a | 新源真实 TrackNet 输出覆盖 75 个源 PTS，并显式保留 31 missing / 0 inpaint；原图有限 QA 完成；观测不是球真值 | PASS（仅这条来源可追溯与缺失表达的子断言，不替代完整用例质量验收） |
| R-07b | 真实人体/匿名 ID 可回查；场地有提案来源；固定候选双人轨迹不完整，34 帧几何候选人数不足，关键击球帧可见漏检 | BLOCKED（完整双人位置/姿态输入未满足） |
| R-07c | 3 秒离线吞吐已记录；无因果端到端实测，BST 需要 next hit | NOT_RUN（不将离线 RTF 计入实时验收） |
| S2-03 / S2-04、R-06a | 未生成自动动作事件或细标签真值，未进行 BST 前向 | BLOCKED（真实必要输入/标签真值缺失） |

若继续，应先针对同一固定窗口核查远端尺度、原分辨率检测/场地区域检测与匿名关联的真实改善，保留模型配置与失败对照；球离画或不可观测时继续 unknown，不能用完整张量作为目标补造数据。只有源 PTS 全量保留、双人轨迹与脚点实际可用、球观测满足严格协议、击球边界及局部 H 经明确范围审阅后才考虑 BST。即使未来跑通，也仅为 25 类粗球种实验，不是细手法支持或正式 A/B/C 评测。

## 本地证据位置

仅本 Markdown 进入 Git；原始特征与视频仍在 D 盘，未修改。所有新审阅图和小 JSON 位于既有根下：

`C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/bst-new-source-review-001/`

其中 `review-frames.json` 给全部 75 帧的源帧号/PTS，`contact-01.jpg` 至 `contact-05.jpg` 为全部逐帧拼图；`near-previous-upper-native-crops.png`、`near-previous-native-crops.png`、`far-current-native-crops.png`、`near-next-native-crops.png` 为击球邻域；`court-proposal.json` 与三张 `court-proposal-*.jpg` 保存 H/原图叠线；`multimodal-review.json` 保存上述统计、源哈希和 missing 行号；`multimodal-qa-{3016,3032,3052,3062,3067}.jpg` 为五帧叠图。文件哈希/用途/来源汇总在 `evidence-manifest.json`。这些图只限 `training_only` 研究诊断，不进入制作库或成片工作流。
