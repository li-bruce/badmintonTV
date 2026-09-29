# InpaintNet 适用性静态检查 001：冻结 BST 窗口不适用

日期：2026-09-29。结论状态：**BLOCKED — 官方 mask 排除目标窗口的全部 25 个缺球帧**。blocking code：`official_mask_excludes_all_target_missing_frames`。

这是固定源码/已下载权重元数据/既有真实模型产物的 CPU 只读调查，没有加载 InpaintNet、没有执行 pickle、没有 GPU 推理，没有新增视频下载或模型方向。模型执行状态是 **NOT_RUN**，不能将此结论写成模型准确率失败、补点成功或 BST 可靠性通过。

## 目标与冻结边界

- Asset：`asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913`；source SHA-256：`b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913`。
- 用途：`training_only`；源数据许可仍限非商业学术研究，模型软件许可不改变视频用途。
- 已有 TrackNet job：`job-d9c832fd94384ee3950918badc767b15`，`attempt-1`，`offline_weight`；原输出保留 75 帧，源帧 `[3000,3075)`，25 FPS，`[120000,123000)` ms，1280×720，time_base `1/12800`。
- 独立 BST 候选窗由三拍 previous/current/next = **3016 / 3052 / 3062** 按作者窗口规则得到 **[3016,3068)**，52 帧，**[120640,122720)** ms；主线程确认该窗口在查看模型 missing 分布前已经冻结。接触点仍是 agent 视觉候选，不是人工真值。参见[独立视觉检查](models-bst-new-source-review-001.md)。
- 本次不移动冻结窗口，不移除/放宽作者 mask，不把窗口外两帧拿来替代目标试验，不自动解除 BST 的输入可靠性阻塞。

只读输入为 `models/jobs/job-d9c832fd94384ee3950918badc767b15/attempt-1/tracknet-points.json`（相对 `D:/video`），**34,127 B**，SHA-256 **`1984f48c7ef961b83f4d8296b5fc5eaca610d83993febe9aec93868833343db6`**。原观察点 `observed` 与缺失 `missing`/null 保持不变；本次 `imputed_count=0`。

## 作者规则及具体边界

固定官方 commit：[`6eda442ada1740573f200f836d93edc9a541ee86`](https://github.com/qaz812345/TrackNetV3/tree/6eda442ada1740573f200f836d93edc9a541ee86)。

1. [predict.py 第 240–241 行](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/predict.py#L240) 从 checkpoint 读取序列长度，并以原图高的 5% 调用 mask。720 高对应 **36 px**；不要误用 `generate_inpaint_mask` 函数签名里的默认 30。
2. [test.py 第 223–258 行](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/test.py#L223) 扫描 Visibility=0 的连续缺口。内部缺口必须满足 **左邻可见点 y > 36 且右邻可见点 y > 36**，才将该缺口标为待修补。比较是严格大于；源码还保留 `i > 1` 的边界条件，因此局部索引 1 开始的缺口也不会进入内部缺口分支。
3. 同一函数对开头缺口允许只根据右侧重新出现点的 y 门槛设 mask；末尾缺口没有可见右端点且 missing 的作者坐标为零，因此不会获得有效 mask。循环也不把最后一个 missing 单点设为有效。这个边界行为原样保留，没有静默修正。
4. 作者对不满足 y 门槛的分支给出了“画面之外”的启发式解释。这**不是**本次真实球确实出画的人工证明；当前判断仅是官方规则不选择该缺口。
5. [dataset.py 第 357–398 行](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/dataset.py#L357) 根据坐标和 mask 建立窗口；[第 463–473 行](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/dataset.py#L463) 按原图宽、高归一化。InpaintNet 输入是 `(N,L,2)` 坐标与 `(N,L,1)` mask，不读图像；[model.py 第 100–129 行](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/model.py#L100) 是保长 Conv1d 网络及 sigmoid 输出。
6. 默认 weight 模式用 **16 帧、步长 1**，不是把长缺口递归填满后再送入下一轮。有效完整窗口数是 `N-16+1`；中间用位置三角权重，首尾用实际已有窗口等权平均。[predict.py 第 264–318 行](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/predict.py#L264)。只有 nonoverlap 模式在最后不完整窗口重复末项 padding；本轮未选用它。
7. 输出替换公式仅采用 mask=1 位置的网络结果，mask=0 保留原坐标。[predict.py 第 281–286 行](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/predict.py#L281)。归一化 x、y 都小于 `50/sqrt(288²+512²) = 0.08511479854731926` 时作者置零；此后处理阈值与前述 36 px mask 门槛不同。[utils/general.py 第 15–19 行](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/utils/general.py#L15)。

源码 **没有 max_gap 或“25 帧必拒绝”的长度条件**。本案例的直接排除原因是两端 y 门槛。25 帧长度大于 checkpoint 的 16 帧上下文，还产生了起点 3020–3029 共 **10 个全缺失 16 帧窗口**；不存在一个 16 帧窗口能同时包含 3019 与 3045 两端真实观察点。它说明长缺口缺少窗口内锚点，不能被说成作者提供了长 gap 专用恢复机制或验证保证。

## 实际静态结果

诊断将真实记录的 missing/null **仅在内部 mask 计算中**按作者缺失输入约定视为 y=0、Visibility=0；不把零写回原始观察或当成补点输出。

| 源缺口（含端点） | 帧数 | 左/右相邻 observed y | 作者 mask=1 帧数 | 与冻结 BST 窗口关系 |
| --- | ---: | --- | ---: | --- |
| 3020–3044 | 25 | 3019: y=5；3045: y=5 | **0** | 全部位于 [3016,3068) 内 |
| 3068–3069 | 2 | 3067: y=267；3070: y=242 | 2 | **全部在冻结窗口外** |
| 3071–3074 | 4 | 3070: y=242；右端缺失 | 0 | 窗口外、尾部缺口 |

全部 75 帧：44 observed / 31 missing。冻结 BST 52 帧：**27 observed / 25 missing / 0 mask eligible**。因此原样运行官方 InpaintNet 也不会替换冻结窗口中这 25 帧的缺失坐标。为了看到非空结果而去跑窗口外 3068、3069 两帧，对本次 BST 输入目标没有帮助，按本轮约束不做该旁路试验。

## 已下载权重及来源校验

已校验 `models/weights/tracknetv3/reuse-manifest.json` 的 source_commit、review_sources 和 inpaint_checkpoint。下列本地文件 full SHA 与 manifest 相符；这些是本地来源留存摘要，官方公开 zip 未提供发布者签名/独立权重哈希。

| 对象 | 字节 | SHA-256 |
| --- | ---: | --- |
| InpaintNet_best.pt | 6,264,451 | `5749b66b8002f3ad9e0af841604004706fc796df30599e6bf01952696009688c` |
| model.py | 5,890 | `04fd51ff88e58189474677dbf11f81e52b78df00226fb97ea0678b31ef7284e3` |
| test.py | 49,439 | `420511325901bf25d5a28b101b1db994c5d6e4ab00a74d30e600a2e4f8b1d204` |
| predict.py | 17,554 | `ea338db0adc8d5ff89b0313b248d82c93b43ecb96cfefcc4ef44c542f462cf88` |
| dataset.py | 41,285 | `c8cf51f8fd59e466f3a1916ba99b24ac8b487ff85f69362ee72758b6b1643f92` |
| README.md | 9,325 | `cda4991691ca354c4cdda8b63f535b21e1fad7d0344fbf16ff409745fecd6691` |
| LICENSE | 1,097 | `1eeb31683deba741bce99f5f33bb813293a23b4e6c8302d6f056a587a30cd497` |

`utils/general.py` 不在当前本地 review_sources 中；本次只读获取固定官方 raw 小源码用于确认常数，19,855 B，SHA-256 `7c7bdbac3d341302652292c0d62d848235ef774d4579f421797938eae230c3b4`，没有写入 D:。

Checkpoint 是 ZIP；只读其中 **archive/data.pkl（7,090 B）**，用标准库 `pickletools.genops` 静态看字面量，未调用 `pickle.load` 或 `torch.load`，未导入 torch：

| param_dict 字段 | 字面量 | pickle 字节偏移 / opcode |
| --- | --- | --- |
| model_name | InpaintNet | 6729 / BINUNICODE |
| seq_len | 16 | 7066 / BININT1 |
| mask_ratio | 0.3 | 6992 / BINFLOAT |

[README 第 162 行](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/README.md#L162) 也给出 seq_len=16、mask_ratio=0.3 的训练调用。仅有此参数不能证明连续 25 帧遮挡的恢复能力；本轮没有训练或验证该能力。

## 可复现方法与实施决定

新增 [inspect_inpaint_applicability.py](../../scripts/models/inspect_inpaint_applicability.py)，纯标准库、固定案例检查；固定来源 hash 不符、PTS/帧序号或尺寸不符即拒绝。脚本只输出 JSON 到 stdout，不写 D:，不联网，不执行模型和 pickle，不产生推断坐标。

从仓库根运行：

```powershell
python scripts/models/inspect_inpaint_applicability.py --storage-root D:/video
```

WSL 对应：

```bash
python scripts/models/inspect_inpaint_applicability.py --storage-root /mnt/d/video
```

2026-09-29 已实际以 Windows Python 3.12.11 执行，exit 0；输出包括 `status=not_applicable_for_frozen_bst_window`、`bst_frames=52`、`bst_observed=27`、`bst_missing=25`、`bst_mask_eligible=0`、`eligible_source_frames=[3068,3069]`、`model_loaded=false`、`gpu_inference_run=false`、`imputed_count=0`。

对本目标的最小实施为这份静态诊断与阻塞记录，**不新增推理适配器或 GPU job**。即使技术上可从已有 6.26 MB 权重和已审 model.py 封装坐标后处理，官方 mask 在目标上全为零，接入无法检验所需的 25 帧补点。原本 TrackNet 的离线未来依赖仍保留；没有生成候选坐标，也没有把 missing 升级为 observed、修复 BST 球/人输入缺口或修改真实验收状态。
