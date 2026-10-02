# 实验 002：真实单打/双打短片基线与预览 QA

日期：2026-09-28。状态：**三次真实视频推理执行成功；模型能力仍为 experimental；正式 A/B/C 对照和细动作识别未通过验收**。本报告只读取既有结果、校验文件和复看预览，没有重新运行 GPU、训练或生成媒体。

## 1. 实际做了什么

| job_id / attempt_id | 原片窗口 | 请求采样 | 实际产物 | 执行结果 |
|---|---|---|---|---|
| `real-pose-002 / attempt-01` | 单打 `[0,6000)` ms | 4 fps，max_frames=30 | 24 帧 COCO17 人体预标注 | succeeded；events=[] |
| `real-video_embedding-002 / attempt-01` | 同一单打 `[0,6000)` ms | 4 fps，max_frames=30 | 24 帧汇成一个 512 维 CLIP 向量及 4 个文本相似分数 | succeeded；events=[] |
| `real-pose-doubles-001 / attempt-01` | 双打 `[0,4404)` ms | 2 fps，max_frames=10 | 9 帧 COCO17 人体预标注 | succeeded；events=[] |

三份 `result.json` 均为 `error=null`。成功指模型加载、真实视频解码、推理及产物写出完成；不表示动作标签、身份或检索结果正确。三份 `report.json` 均明确 `accuracy=null`、`recall=null`、`manual_review_required=true`，不支持 `fine_hand_technique / player_identity / contact_time / temporal_action_classification`。

本轮 A 仅是 **CLIP 图像编码器的短窗帧均值**，没有视频时序建模或查询检索评测；B 仅有人体姿态，没有稳定跟踪、场地方向或已训练时序分类器；C 未运行，缺少已确认同一 track 的轨迹、细标签真值与相同查询评测集。这里不是正式 A/B/C 比较，也没有用两段短片训练模型。

## 2. 原片、来源与数据隔离

所有相对路径均相对 `D:\video`（WSL `/mnt/d/video`）。原片只读，媒体、PNG 和特征保留在 D 盘，不提交 Git。

### 单打 S

- asset_id：`asset-5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90`。
- 原片：`data/raw/finebadmintonbenchmark/video_001951.mp4`。
- SHA256：`5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90`；669,106 bytes。
- 1280×720，duration_ms=6000，fps=30/1，time_base=1/15360；library 完整 PTS 索引 180 帧，观测为 CFR，delta=512 ticks。
- 来源清单指向 FineBadmintonBenchmark，revision=`ff86093a51efdf9a243a0635704952d404e99e52`；来源页：[发布者数据集页](https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark)。这里引用已交接的来源记录，本次不新增线上许可核验。
- `source_type=dataset`、`camera_type=rear`、`discipline=singles`；画面为转播形式，但保留合同元数据 dataset，不悄悄改成 personal 或 broadcast。
- `match_id=unknown`、`split=unassigned`、`players=[]`、`identity_status=unconfirmed`、`source_match_offset_ms=null`。比分牌文字只是观察，不能填成已确认姓名或比赛 ID。
- 该窗口从**已导入短片**的零时刻起算；不能称为完整比赛的 0–6 秒。所属 quarantine_group=`finebadmintonbenchmark-source-matches-unresolved`。
- PTS 索引：`data/probes/video_001951.pts.jsonl`；SHA256=`15efa499303607c73169b62d96dc7dd0277b21220af6f2be66cf0b36cd8bc99c`，5,626 bytes。

### 双打 D

- asset_id：`asset-52e45b704dc32cb049b879673087e7935e4b4172b43e06f734684de250f0e118`。
- 原片：`data/raw/dronebd/study-bd12-rally1-camera1.mp4`。
- SHA256：`52e45b704dc32cb049b879673087e7935e4b4172b43e06f734684de250f0e118`；5,857,600 bytes。本地 SHA256 收据已核验；发布方未提供 SHA256。
- 3840×2160，duration_ms=4404，avg_frame_rate=41100/1367，r_frame_rate=30000/1001，time_base=1/600；完整 PTS 索引 132 帧，delta=20–21 ticks，`vfr_status=unknown`，不从名义 fps 假定精确时刻。
- 来源清单指向 Drone_BD_ControlArea，revision=`14a6a74969f54adb57e013faa4fb24298794e985`；来源页：[发布者固定版本仓库](https://github.com/Ning-D/Drone_BD_ControlArea/tree/14a6a74969f54adb57e013faa4fb24298794e985)。目录为 `Study_Videos/BD12/Rally-1/(1).mp4`。
- `source_type=dataset`、`camera_type=rear`、`discipline=doubles`；不能将高处后方视角成绩继承为顶视或其它个人录像机位成绩。
- `match_id=dronebd-study-recording-bd12` 只是基于 BD12 目录的保守录制组，真实比赛/日期未确认；`split=unassigned`、`players=[]`、`identity_status=unconfirmed`、`source_match_offset_ms=null`。非空 ID 不等于比赛身份确认。
- PTS 索引：`data/probes/dronebd-study-bd12-rally1-camera1.pts.jsonl`；SHA256=`01260e59618bd9bc996688a6f31dbc37df2aceceb65ef182d72e666bf853cdf4`，3,926 bytes。

两个素材的 `rights.status=unknown`、`allowed_uses=[]`；按交接记录仅用于当前本地研究运行，不据此宣称具备公开发布或商用资格。单打数据集卡的 Apache-2.0 标注声明与原比赛画面权利分别保存；双打 CSV 的标注许可和坐标/帧映射均未确认。

本次读取的 library 快照：

| 清单 | SHA256 | 内容 |
|---|---|---|
| `data/handoff/assets.v1.json` | `f6a646668ec688ecbbe85386f64db9d81b4c6b951a8284a1a581195cd57563aa` | 4 个单打小样；本实验只用了 S |
| `data/handoff/assets.doubles.v1.json` | `3b8b76738bc8a5ca1197fec71cd7a5d48efea22d6977bd614ff6f1ffa001815f` | 1 个双打小样 D |

请求中的 S、D Asset 字典与上述当前 library 清单一致。本次只读重新计算两原片、两 PTS 索引及六个已登记 features/report 文件的 SHA256/长度，均与登记值一致；没有删除、覆盖或复制原片。

## 3. 模型、环境和计时边界

运行环境为 WSL Ubuntu 隔离环境 `/mnt/d/video/runtime/models/env`，Python 3.11.16，torch 2.7.1+cu128，torchvision 0.22.1+cu128，CUDA build 12.8，transformers 4.51.3，PyAV 15.0.0，设备 NVIDIA GeForce RTX 5090。驱动 591.86、cuDNN 90701 和 sm_120 算子通过情况见 `models-001-environment.md` 与 `environments/models-gpu-smoke.json`；合成算子验证不计入本实验识别效果。

| 组件 | 实际配置/权重 |
|---|---|
| 姿态 | torchvision Keypoint R-CNN ResNet50 FPN，COCO 预训练，`min_size=480,max_size=854`，逐帧 batch=1，输入 float32；score_threshold 默认 0.7，每帧最多保留 10 个检测 |
| 姿态主权重 | `models/weights/torchvision-pose/keypointrcnn_resnet50_fpn_coco-fc266e95.pth`；SHA256=`fc266e953d2b302cdcbb9ae66f71f6b0d4649928bf02dc573961e361e4918926`；237,034,793 bytes |
| CLIP | `openai/clip-vit-base-patch32`，revision=`3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268`；逐帧 batch=1，未启用量化/自动混合精度；processor resize=224、center_crop=224；每帧向量归一化后求均值，再归一化 |
| CLIP 主权重 | `models/weights/clip-vit-base-patch32/pytorch_model.bin`；SHA256=`a63082132ba4f97a80bea76823f544493bffa8082296d62d71581a4feff1576f`；605,247,071 bytes |

姿态输出坐标映射回原图像素，但网络内部缩放仍会损失小关节、球拍等细节；4K 输入不能等同于 4K 细节识别。CLIP 中心裁剪也可能丢失画面边缘信息，其具体检索影响未测。

权重清单保留来源/许可与所有配置文件 hash：姿态清单 SHA256=`af6573d08a5db3f244cde6039435a5853a3f3408903a60d4955907718f5e6d12`；CLIP 清单 SHA256=`88d8c45976296802a9b04c7b03a3aefde20686854796ae701672481f394fb5b7`。推理适配器加载本地清单并验证权重后运行。环境快照 `environments/models-pip-freeze.txt` SHA256=`012f16963a9a603a5eb24086b5e70eba6acb0cfd3406a5b27e19f9de95ef6ffe`；`environments/models-conda-explicit.txt` SHA256=`dab33ef186071e9b5109bbd0f29aebcf36a1fa6a06fcee3ea9057ee63f3aa888`。

### 实测时间与显存

| run | 原片窗口 / 采样帧 | elapsed_seconds | peak_allocated_bytes（MiB） | peak_reserved_bytes（MiB） |
|---|---|---:|---:|---:|
| S pose | 6.000 s / 24 | 26.398954492993653 | 489,201,152（466.539） | 792,723,456（756.000） |
| S CLIP | 6.000 s / 24 | 44.85338041896466 | 616,739,840（588.169） | 664,797,184（634.000） |
| D pose | 4.404 s / 9 | 28.25424938101787 | 574,289,408（547.685） | 731,906,048（698.000） |

按当前 `inference.py` 的计时代码，`elapsed_seconds` 在原片 SHA256 验证之后开始，覆盖 PyAV 抽帧/解码、框架/模型加载、权重读取与校验、GPU 推理、CPU 取回结果、CUDA synchronize 以及 features.json 原子写出；在 report.json 写出前结束。不包含 CLI/WSL 启动、请求校验、容量预留、原片哈希验证、后续 report/result 写出与 artifact 哈希，也不含 PNG QA 渲染。尚无逐阶段计时分解。

运行脚本对每个 job 启动独立 Python 进程，且没有专门预热迭代，因此这里记录的是含模型加载的单次冷启动调用。文件系统缓存是否已热、其它 GPU 进程的负载、完整设备显存峰值和主存峰值未在这三份报告中采集，不能宣称为全系统冷缓存基准或完整吞吐测试。

allocated 与 reserved 均来自本进程 PyTorch CUDA allocator：`get_torch()` 在 CUDA 可用检查之后重置峰值，推理后读取峰值。reserved 是 allocator 保留量，不能和 allocated 相加当作总显存；这些数值不覆盖其它进程或全部 CUDA/驱动分配，不应与 `nvidia-smi` 设备总占用混为一谈。

原始 report 仍保留 `seconds_per_video_hour_extrapolated`：S pose=15839.37269579619、S CLIP=26912.028251378797、D pose=23096.11666023259。它们只是 `elapsed / 短片秒数 × 3600` 的机械外推，包含本轮模型加载开销，**不是实测每小时视频处理时间**。本报告不把它们用于容量、100 小时任务时长或部署性能承诺；热模型连续素材吞吐仍未测。

### 运行版本可追溯性的限制

result 的 producer 记录 adapter version=0.1.0、job_id 和 attempt_id，没有保存执行时 Git SHA。汇总时 HEAD 为 `00de44409ba0a231d33a8fe99cf0cb4c8f891ba5`，且 `inference.py` 有未提交改动；不能把该 HEAD 假称为这些运行的完整代码版本。本次审阅的 `inference.py` 文件 SHA256 为 `3c4a6e00b714746753c703fe751ed53d1dc21164db0d67b34d612d47c6d63fde`，仅标识审阅快照。下一次运行须在 producer/实验记录冻结代码提交与配置 hash。

## 4. 采样 PTS 清单

`source_ms` 按真实 PTS/时间基换算并取整，不把理想采样网格当实际帧时刻。以下 PTS 均在 library 原片索引中找到。S 的 pose 与 CLIP `sample_times_ms` 完全相同；CLIP features 未单独保存原始 PTS，表中的 CLIP PTS 对应通过相同源 hash、实际毫秒列表和已核验原片索引关联，并非 CLIP 文件原有字段。

### S：time_base=1/15360，原片区间 `[0,6000)` ms

| 序号（0 起） | source_ms | PTS ticks |
|---:|---:|---:|
| 0 | 0 | 0 |
| 1 | 267 | 4096 |
| 2 | 500 | 7680 |
| 3 | 767 | 11776 |
| 4 | 1000 | 15360 |
| 5 | 1267 | 19456 |
| 6 | 1500 | 23040 |
| 7 | 1767 | 27136 |
| 8 | 2000 | 30720 |
| 9 | 2267 | 34816 |
| 10 | 2500 | 38400 |
| 11 | 2767 | 42496 |
| 12 | 3000 | 46080 |
| 13 | 3267 | 50176 |
| 14 | 3500 | 53760 |
| 15 | 3767 | 57856 |
| 16 | 4000 | 61440 |
| 17 | 4267 | 65536 |
| 18 | 4500 | 69120 |
| 19 | 4767 | 73216 |
| 20 | 5000 | 76800 |
| 21 | 5267 | 80896 |
| 22 | 5500 | 84480 |
| 23 | 5767 | 88576 |

24 个 pose 采样帧每帧均输出 9 个检测，共 216 条检测记录；这只是返回数量，绝不是 216 个球员或 216 个正确目标。

### D：time_base=1/600，原片区间 `[0,4404)` ms

| 序号（0 起） | source_ms | PTS ticks |
|---:|---:|---:|
| 0 | 0 | 0 |
| 1 | 500 | 300 |
| 2 | 1002 | 601 |
| 3 | 1502 | 901 |
| 4 | 2002 | 1201 |
| 5 | 2503 | 1502 |
| 6 | 3003 | 1802 |
| 7 | 3503 | 2102 |
| 8 | 4005 | 2403 |

9 个采样帧每帧输出 4 个检测，共 36 条检测记录；仅由数量相同不能证明 4 个球员均正确定位或关节正确。两份姿态产物的全部检测均为 `track_id=null/player_id=null`，每条包含 17 个 `keypoints_xyv` 和 17 个原始 `keypoint_scores`，`tracking=not_implemented`。

## 5. Agent查看overlay：每段仅三个抽查帧，非人类真值确认

models主Agent通过工具查看六张PNG，撰写本报告的子Agent复看同六张；没有人类审核或真值确认，也没有增加独立抽样帧，没有双人盲标、专家动作确认或关节坐标真值。双打原图3840×2160在工具预览中缩放到2048×1152；不能据此判断更细的手指/拍面细节。以下均为Agent的可视化检查观察，不能当作用户人工验收。

| 素材 | 预览文件（位于各 run 的 attempt-01 下） | 实际 source_ms / PTS | 观察及限制 |
|---|---|---|---|
| S | `preview-1000.png` | 1000 / 15360 | 场上近/远端两人均可见相应检测；同时检测场边裁判/工作人员，左侧裁判出现重叠重复框；远端 detection 序号 6 |
| S | `preview-3000.png` | 3000 / 46080 | 场上两人可见相应检测；场边人体与重复框继续存在；远端 detection 序号变为 1，不能当作同人 track |
| S | `preview-5000.png` | 5000 / 76800 | 场上两人可见相应检测；远端身体/手腕细节较小，部分姿态受视角或遮挡影响；未确认击球接触及细手法 |
| D | `preview-500.png` | 500 / 300 | 场上四人可见相应检测；远端两人有相对遮挡和网遮挡，关节不确定性仍存在 |
| D | `preview-2000.png` | **2002 / 1201** | 场上四人可见相应检测；文件名是请求预览时间，不是精确 source_ms；无法确认握拍/接触 |
| D | `preview-3500.png` | **3503 / 2102** | 场上四人可见相应检测；近端两人相对前两图的检测序号 0/1 发生交换，不能连接成稳定身份轨迹 |

这里的“序号”是预览脚本逐帧枚举检测的显示标签，不是运动员 ID，也不是已实现跟踪器的 ID switch 指标。单打所有人体检测混合球员与场边人员；“画面上有人且有框”只支持预标注可视化的基本可用性，不能把三帧的目视命中写为 precision=1 或 recall=1。

关键点连线绘出不等于关节定位已准确；`keypoints_xyv` 中的 v 与 `keypoint_scores` 均不是经过羽毛球校准的正确率。不能直接把 xyv 的 v 当作后续骨骼特征函数所需的人工可见性/可信 score；需要额外可见性审阅和适配。远端手腕/球拍尺寸小、肢体/网遮挡、低采样率均可能丢失接触与小跳阶段，不为不可见处补造动作。

尚无人类审核；Agent查看overlay未记录独立耗时。因此人类审核分钟/小时、修改量、身份错误率与关节误差均为 `null`，而不是0。

## 6. CLIP 输出：只记录数值，不命名动作真值

S 的 512 维最终向量 L2 范数只读计算为约 1.0000000058。默认英文文本与余弦相似度如下，原始产物均为 `is_probability=false`：

| 文本 | cosine_similarity |
|---|---:|
| a badminton player hitting a net shot | 0.311004638671875 |
| a badminton player smashing | 0.32343506813049316 |
| a badminton player moving backwards | 0.3310689926147461 |
| a badminton player serving | 0.2965736389160156 |

这些是同一窗口对四个提示词的相似分数，不是四个已确认类别，不是概率，也没有匹配候选库、中文查询、P@K 或完整真值。帧均值不保留先后顺序，无法验证“先后退、再击球、随后上网”或网前展搓/收搓。原数据 `video_001951` 的回合评价选择题也不提供本轮逐帧姿态、身份或这些四个提示词的完整真值。

## 7. 失败模式、未测项和下一轮最小条件

| 已观察或明确缺失 | 对结果的影响 | 下一轮所需最小证据/实现 |
|---|---|---|
| 场边人员进入检测，左裁判有重复框 | 人体检测不等于场上球员过滤，不能直接建立球员事件索引 | 人工审核场地区域与球员实例；检验球场约束/去重是否误删边界球员 |
| 检测序号随帧改变；全部身份为 null | 不能跨帧计算同一球员步法，不能做按球员查询 | 连续原片人工确认身份轨迹；跟踪匹配和遮挡段审核；不用检测排序充当 track |
| 姿态仅 COCO17，远端小关节/网遮挡 | 不能确认拍面、握拍、接触和展/收搓；小跳阶段不完整 | 对细标签做可见性小样与专家锚点；低可见性保留 unknown |
| S 4 fps、D 2 fps，短窗 | 可能跳过短促接触/离地/落地，尚未量化漏掉多少 | 在有真值连续区间比较采样率；以原始 PTS 对齐阶段，不只选模型高分帧 |
| A 为中心裁剪图像均值；B 未训练 temporal；C 未运行 | 不构成时序/融合检索成绩 | 固定同一 QuerySpec、候选库、划分与审片预算；先跑 A/B 再预登记融合策略 |
| 单打比赛 unknown；双打仅 BD12 保守目录组；均 unassigned | 没有正式独立比赛测试集 | `match_identity_status=confirmed`，按 match 的 split_assignment 版本与证据；同源/回放不得跨 split |
| 双打 CSV 与后视片段未对齐 | 不能用 CSV 的 130 行或 status 数字计算检测/动作准确率 | 核实 CSV 对应视角、坐标、frame→PTS 映射及语义，再由人工审核转换 |
| 缺完整动作真值、身份真值和查询答案 | accuracy/recall/P@K/混淆/错人率均不可计算 | 少量清晰双人/专家审核锚点起步；正式召回必须穷尽审阅选定完整区间 |
| 只计一次含加载调用，缺阶段与系统监控 | 无稳态吞吐、主存峰值或完整设备显存结论 | 连续足够长真实素材，记录冷/热分离、阶段耗时、负载和完整资源监控 |

当前精度字段保持 `null`：`accuracy`、`recall`、`precision_at_k`、`identity_error_rate`、`keypoint_error`、`temporal_boundary_error`。不可判不是负例；现有 QA 观察也不算可用于训练/测试的已审核标签快照。尚未验证用户个人录像、侧/顶视、其它场馆、跨镜头、正式中文检索及稳定轨迹。更改 score 阈值本身不能填补这些真值缺口。

下一轮优先：先在现有真实连续片段标出场上球员与可见性，确认可连接的轨迹；补一小组可判/不可判细动作锚点与难负例；然后在整场/会话身份和划分证据齐备的留出中比较 A/B/C。每类少于 30 个可判定测试正例或仅一场时继续标 experimental，不因本轮 GPU 推理成功宣称自动识别已可交付。

## 8. 可回查产物和复现入口

统一路径模板：请求为 `models/handoff/requests/<job_id>.json`；输出为 `models/handoff/<job_id>/attempt-01/{features,report,result}.json`。全部时间与 feature 引用均指向上面的 S 或 D 原片，不使用复制媒体。原始写出时间为 UTC；本轮 features/report 的创建时间分别约为 S pose 15:42:09、S CLIP 15:42:56、D pose 15:47:27。

| job_id | features.json SHA256 / bytes | report.json SHA256 / bytes |
|---|---|---|
| real-pose-002 | `8b7bef5109c149f29d420472973d1c248a6d3a559b499409940a7f2dcfe55082` / 620169 | `e4c6844ccdeb5c8f2a41b93e2a456d41c5c8ddc2fbd223312833651141a4a5b5` / 846 |
| real-video_embedding-002 | `7c8df85a6357e3d727133c91c40bfc09be45469548ffc3e550002fa6dab8fe26` / 14811 | `b004258af9acea2d0df407d3c2498b7488bb2a9ee3d79034ffb8472cbcd81242` / 837 |
| real-pose-doubles-001 | `a71e04834a93bf6339ae47564f47a25d6d8d9a2c0a1cd709cba54d6732896a1f` / 104146 | `58c97a5910628d46fe5a25f8978e06cdae653e73beaed733a6cad3a6db3551fa` / 844 |

| job_id | request SHA256 | result SHA256 |
|---|---|---|
| real-pose-002 | `493c4ab36ad26af0d8d8a576615bca76b510ec4f58549e8a0a26d9ac017ee498` | `0578a49743c4d5311d0f911e789b2cbda5526908992b1e16b844946fa002e17c` |
| real-video_embedding-002 | `c2d521a2b45f38095727de58495afb294dc502763360e8513b4b2e5adecb9393` | `90135d64d9cef08de8834e26c949e721e2a0fce88179d4f01fede41fadaec0de` |
| real-pose-doubles-001 | `4decb8d5ce447491d1bbc712d658e9ea2d155eda28f1b6c7da5183e1b9465c7a` | `41345ca1a195e49d661d8038762122144e09946cb85b545ef02320c274bfd5b1` |

历史实际调用入口由 `scripts/models/run_baselines.sh`、`scripts/models/qa_and_doubles.sh` 保存，核心命令形态为：

```bash
source environments/models.env.sh
"$BTV_MODELS_ENV/bin/python" -m packages.models run \
  --request /mnt/d/video/models/handoff/requests/real-pose-002.json \
  --result /mnt/d/video/models/handoff/real-pose-002/attempt-01/result.json
```

这是已有运行的命令记录，不能原样覆盖重跑；现有 artifact/result 受独占发布保护。下次重现需生成新 job/attempt、同步更改 request 的 output_dir，先协调 GPU 和容量，再运行。预览使用已有 `features.json` 与只读原片，命令记录见 `qa_and_doubles.sh`；本次汇总未执行这些脚本。

容量附记：三轮预标注和PNG留在models配额目录。审阅时发现双打 `preview-2000.png` 为5,023,785bytes、`preview-3500.png` 为5,031,262bytes，超过原预览脚本5,000,000bytes的预留量。收尾已修复为：在受限4K图像内存中编码PNG，验证<=32MB后按准确字节数预留，再排他写入；同时核对asset/hash与实际解码PTS。已有六张媒体未重写或删除，仍保留原实验记录。修复后的编码/预留路径只做静态检查，未重新生成六图；这不是新识别试验。
