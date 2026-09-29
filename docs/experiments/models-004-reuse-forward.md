# 004：公开模型复用真实短窗（2026-09-29，进行中）

目标：R-03b 分项耗时、R-07a 连续球点、R-07c 因果吞吐/延迟诊断。
R-05a VL真实前向和BST粗球种另待环境/输入就绪。没有独立人工真值，不报精度、召回、P@K。

输入：library既有 `data/handoff/assets.v1.json` 的
`asset-5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90`，
原片 `data/raw/finebadmintonbenchmark/video_001951.mp4`，1280×720、30fps、
time_base=1/15360、清单窗口6000ms、general、split=unassigned、match_id=unknown。
源hash即asset后缀。源视频rights未知，公开模型许可不代表广播视频可发布。
本记录是旧真实素材；不能冒称library正在下载的新职业训练集已经跑过。

环境：WSL Ubuntu，既有env `/mnt/d/video/runtime/models/env`，torch2.7.1+cu128、
torchvision0.22.1+cu128、PyAV15.0.0、Pillow11.2.1；仅补装
opencv-python-headless4.11.0.86（CPU PyPI wheel，--no-deps，pip check通过）。
GPU RTX5090，同平台SQLite账本，由native Windows worker与WSL watchdog管理。
无NVDEC；原片只读；输出均models；没有直接SQL、driver修改或外部发布。

TrackNet固定代码commit与SHA、公开ZIP/权重SHA见 `docs/models/TRACKNET_REUSE.md`。
限制：窗口内≤32张未来帧背景中值的offline实验不同于作者全视频背景；
因果版本只用开头8张历史帧中值+当前序列末帧输出，InpaintNet未运行。
阈值heatmap>0.5为作者后处理，响应值不是校准概率。observed不等于真阳性。

| 运行 | job_id | 实际结果 |
|---|---|---|
| 6s TrackNet offline | job-16153fad2f21429e8f88aa48fb978ccc | succeeded；180帧，165 observed/15 missing/0 inpainted |
| 6s TrackNet causal paced首试 | job-3757b3d57b2142cd80841a585d9523e0 | failed；Windows bridge心跳写失败，模型取消，未取得推理结果 |
| 相同causal新job重试 | job-4081ac5e54f944b7b087c149efe43e69 | succeeded；180帧，160 observed/20 missing（含8 warmup）；0 inpainted |
| 连续姿态700–3700ms | job-b8a4ac96da6543f8b4f6afc5ae3c4220 | succeeded；90源PTS帧/82,944,000像素；无track/player身份 |

TrackNet输出：`models/jobs/<job_id>/attempt-1/tracknet-points.json`及
`tracknet-report.json`；pose是同目录`features.json`/`report.json`。
对应受控交换的原始result/bridge.done在`platform/jobs/<job_id>/attempt-1/`。
三次成功worker校验Artifact hash及JobResult；每次done后lease/window=null并revoke。
失败的心跳、cancel、done及Queue日志保留；done compute_stopped=true/exit130，
native bridge自身exit1导致worker明确failed，未被记成功。

| 指标 | offline | causal paced |
|---|---:|---:|
| cold（含TrackNet运行时加载） | 13.9549s | 见原始report |
| decode | 0.2940s | 0.1634s |
| preprocess | 2.9235s | 2.4310s |
| model windows | 0.9057s / 173窗 | 0.9325s / 172窗 |
| postprocess | 0.2222s | 0.0825s |
| pipeline wall | 4.4205s | 5.9848s（含2.2781s主动等待） |
| steady active RTF | 0.6184（离线，不算因果实时） | 0.6059（扣除明确pacing等待） |
| allocator allocated/reserved peak | 431,071,744/683,671,552B | 见原始report |

因果回放按源PTS安排到达，最多1帧解码前读，图像在计划到达后才进入历史队列。
回放到达→完成延迟mean21.18ms/p95 36.04ms/max150.46ms；40ms预算下12/180帧迟到，
其中8个prediction帧迟到；最大待处理4帧；0主动丢帧。codec内部drop未知。
这是文件回放的计划到达边界，不含真实摄像头/传输；`live_end_to_end_latency_ms=null`。
可证明此短窗因果处理速度有余量，**不能据此通过完整直播系统R-07c**，
也不能从180帧推论完整比赛可靠吞吐。

连续pose原始报告elapsed41.5241s，而已列阶段约6.289s，说明框架import/CUDA初始化等
约35s未归入旧阶段。该差异原样保留。之后适配代码新增framework_startup_seconds与
unattributed_seconds，未回写旧实验；下一真实运行验证新分项。模型前向2.8542s，
不拿这一项单独冒充端到端3秒视频处理成本。换用torchvision而非BST作者MMPose须记录分布变化。

复现：native平台Python运行 `scripts/models/run_registered_experiment.py`，
`--payload configs/models/reuse-payloads/<对应配置>.json`
`--runtime-repo C:/Users/USER/Desktop/Program/badmintonTV --coordination-note <已经协调的窗口说明>`。
只适用于当前单一协调worker；共享队列非原子指定job领取，禁止当并发任务runner。
脚本检查队列/租约/模型writer，失败状态退出码保持非零，结束验证lease后撤窗。

下一步：视觉QA独立记录；连续pose+球点+Agent场地候选与显式击球边界组成BST探索输入，
缺失不伪造。Qwen3VL独立env/权重完成后中文查询真实embedding。library新训练handoff
到齐再至少一个新职业窗口；用途training_only必须完整继承。
