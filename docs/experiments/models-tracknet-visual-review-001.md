# TrackNetV3 首次离线结果：Agent 视觉 QA 001

日期：2026-09-29。执行者：models 子 agent；**这是 agent 对真实帧的视觉自检，不是 human review、专家标注或准确率评估。** 没有修改原模型输出、确认球员身份或生成动作真值。

这组抽查中，若干观测环贴近可见白色球迹 / 拖影，没有看到明确落到人物或大幅广告文字上的误点。仍有两个值得后续核查的情况：3.667 秒的 missing 帧在上边界可见被截断的小白色亮斑；5.967 秒的观测环围住网带附近近静止白色物，单帧不能确认是停留的球还是背景误点。其余人物 / 网线附近的 missing 也不能据此判为“无球”。本结论不能推广到其余帧或其他比赛。

## 输入与结果证据

- job：`job-16153fad2f21429e8f88aa48fb978ccc`，attempt：`attempt-1`；mode：`offline_weight`。
- 源 Asset：`asset-5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90`。
- 原片只读路径：`D:/video/data/raw/finebadmintonbenchmark/video_001951.mp4`，669106 bytes，1280×720，180 帧，6 秒；SHA256：`5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90`。
- [球点 JSON](D:/video/models/jobs/job-16153fad2f21429e8f88aa48fb978ccc/attempt-1/tracknet-points.json)，SHA256：`cc6ba9c80405b04e7c66045241a4775d3cbe4419032c015df8a0c83d91f7b7aa`。
- [运行报告 JSON](D:/video/models/jobs/job-16153fad2f21429e8f88aa48fb978ccc/attempt-1/tracknet-report.json)，SHA256：`8b7b0d2eb9ff92089b7b8d26b70e16e283f117370c50f1322335cb3f92f5264a`。
- 原始 PTS 索引：`data/probes/video_001951.pts.jsonl`，time_base=`1/15360`，每帧递增 512 ticks；索引 SHA256=`15efa499303607c73169b62d96dc7dd0277b21220af6f2be66cf0b36cd8bc99c`。

报告中的 165 observed、15 missing、0 inpainted 是模型输出数量，不是正确 / 错误数量。`response_peak` 是未校准热图峰值，不是本次 QA 的信心分数。源资产 usage_scope=`general`；原视频 rights.status=`unknown`，这里只保留本地研究证据，未发布媒体。

## 方法和环境

选取 10 个时点，覆盖首帧、3 段中间 missing、最大相邻坐标跳变、高空球、网边及末帧。选择在看叠图前按输出状态和时序完成：frame 0、21、27、65、70、100、110、120、150、179；不是随机抽样，也不是盲评。

原生 Windows CPU：`C:/Users/USER/miniforge3/envs/t104_conda_env/python.exe`；Python 3.12.11、OpenCV 4.9.0、NumPy 1.26.4；OpenCV FFMPEG backend，显式 `VIDEO_ACCELERATION_NONE`，读取回报 hw_acceleration=0。没有导入 torch，没有运行 GPU、安装依赖、下载、重跑模型或写 D 盘。未使用当前 models writer 锁。

先校验源文件、PTS 索引摘要，再从 frame 0 顺序 CPU 解码完整 180 帧，只保存选中帧。所有模型行的 frame_index / pts 与索引一致；10 张选中图的 OpenCV POS_MSEC 与模型 source_ms 差值小于 0.01ms。没有根据名义 fps 随意 seek 猜帧。

每张图的上方为原分辨率画面叠加半径 12px 的黄色空心环，中心为模型原始 x/y；下方左侧为未标记的 160×90 ROI，右侧为同一 ROI 的标点版本，两者均 4× nearest 放大。空心环不覆盖中心白色球迹。missing 帧不画任何“补球”点；其 ROI 仅为查阅位置，不能当作插值预测或标注。逐个用图片查看工具打开了下表全部 10 张图。

10 张 PNG 总计 11,292,180 bytes，仅保存于可写 visualizations 目录，不进入 Git / 模型数据目录。复核输入、ROI、各图 hash 和环境详见 [review-inputs.json](C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/tracknet-visual-review-001/review-inputs.json)。

## 逐帧观察

坐标均为原图左上角起算的像素。time_base 对所有行均为 `1/15360`。下表“看起来”是 agent 视觉判断，未测数值定位误差。

| frame / source ms / PTS | 模型输出；peak | Agent 视觉观察与疑点 | 图证 |
|---|---|---|---|
| 0 / 0.000 / 0 | missing；0.4801 | 远端人物与网附近细节重叠，单帧无法独立确定小球中心。missing 如实无点；不能判断为正确缺失或漏检。 | [frame 000](C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/tracknet-visual-review-001/frame-000-pts-0.png) |
| 21 / 700.000 / 10752 | observed (730,335)；0.7271 | 原始 ROI 中白色球状物清晰，环中心贴近该亮斑，位于近端人物头部右上方。未见明显落到人物或地面文字。 | [frame 021](C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/tracknet-visual-review-001/frame-021-pts-10752.png) |
| 27 / 900.000 / 13824 | missing；0.3152 | 远端人物上身 / 网线附近有复杂白色纹理，原始 ROI 不能可靠分离球。连续 25–28 帧 missing 中选取此帧；是否因遮挡或漏检，未判定。 | [frame 027](C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/tracknet-visual-review-001/frame-027-pts-13824.png) |
| 65 / 2166.667 / 33280 | missing；0.4088 | 近端人物正向左前方伸拍，拍 / 手 / 场线区域模糊。该静帧不足以独立标出球心，不把 missing 解释为画面没有球。 | [frame 065](C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/tracknet-visual-review-001/frame-065-pts-33280.png) |
| 70 / 2333.333 / 35840 | observed (412,222)；0.8191 | 红色背景与 VICTOR 牌交界处有竖向白色球迹。环靠拖影上端，可能相对亮斑几何中心偏上；仍围绕球迹而非下方大字。没有标定真值，未计算像素误差。 | [frame 070](C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/tracknet-visual-review-001/frame-070-pts-35840.png) |
| 100 / 3333.333 / 51200 | observed (532,110)；0.7222 | 原始 ROI 中可见斜向白色拖影；环靠其右上 / 飞行前缘。与前一观测 (497,142) 的 47.4px 跳变在本片最大，但画面确有快速球迹，不能直接把该跳变归为误点。 | [frame 100](C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/tracknet-visual-review-001/frame-100-pts-51200.png) |
| 110 / 3666.667 / 56320 | missing；0.3726 | 原图最上缘约 x≈700、y≈0 有一部分被画框截断的白色小亮斑，看起来与球迹相符。**边界漏检嫌疑**：不能声称此 missing 帧完全看不到球；完整中心和是否完全出框须看连续原片 / 标注。 | [frame 110](C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/tracknet-visual-review-001/frame-110-pts-56320.png) |
| 120 / 4000.000 / 61440 | observed (805,30)；0.6689 | 顶部深色背景上的白色球状物清楚；环中心贴近球迹，未吸附到文字。它说明此时已经恢复观测，不能倒推此前 missing 都正确。 | [frame 120](C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/tracknet-visual-review-001/frame-120-pts-61440.png) |
| 150 / 5000.000 / 76800 | observed (822,307)；0.7356 | 网边附近、场地白字上方有可分离的小白色球状亮斑；环围绕该亮斑，未明显落到场地白字或网柱。局部拖影 / 网带仍使精确球心定义不清。 | [frame 150](C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/tracknet-visual-review-001/frame-150-pts-76800.png) |
| 179 / 5966.667 / 91648 | observed (807,297)；0.7528 | 网带附近的白色球状物在原始 ROI 可见，环贴近它。后段坐标长时间近静止，不能仅凭本帧区分停留 / 挂网的球与背景误点，也不能称仍在飞行；这是明确保留的歧义。 | [frame 179](C:/Users/USER/.codex/visualizations/2026/09/28/01a0e88b-416f-7ca2-bfec-c09ec1462866/tracknet-visual-review-001/frame-179-pts-91648.png) |

## 验收边界与下一步

| 验收 ID / 本次子项 | 方法与预期 | 实际 / 状态 | 未覆盖内容 |
|---|---|---|---|
| R-07a：源 PTS / observed / missing / inpaint 证据关联 | 真实文件 hash、全帧 PTS 索引对照、10 张原片叠图 | PASS（仅此子检查）：帧位核对一致，missing 未伪装观测，未调用 InpaintNet | 不代表 R-07a 整体通过 |
| R-07a：识别质量指标 | 独立真值、定义球心与可见性、完整样本评估 | NOT_RUN；本次仅完成 agent 视觉线索记录 | 无 accuracy / recall / 定位误差统计，无 human-reviewed 状态 |
| R-07c：因果实时与端到端延迟 | 因果输入、节奏 / backlog、完整时间口径 | NOT_RUN；此次 artifact 明确 offline_weight / causal_image_dependencies=false | 全窗背景读取未来信息，离线 RTF 不能充当实时通过 |

后续应优先让独立审核者看原片 3.6–3.9 秒的顶部边界段，以及 5.1–6.0 秒的网带静止段，明确部分出框球与停球是否应标注。人物 / 网前 missing 段也需要连续帧可见性标签。不要用本次选中帧的“看起来贴近”替代完整球点真值，也不要将本文件写入人工审核通过记录。
