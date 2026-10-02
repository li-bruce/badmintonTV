# 短视频、交互处理与技战术检索：复用调研

核查日期：2026-09-29。代码基线 `05329a5`，证据来自本项目已有实验和官方文档、作者论文/仓库。本轮没有安装工具、下载新媒体/权重、占用GPU、训练或上传平台。所有新方案均尚未实测。

## 1. 建议采用的路线

保留FFmpeg渲染核心，补平台导出预设；用PySceneDetect生成镜头候选、OTIO交换剪辑工程。标注体验先补兼容代理、PTS映射、逐帧/循环/放大和缩略图时间线，继续复用Label Studio。模型先试有公开权重的文本视频召回，再按误差训练冻结特征上的小型时序头；不从零训练基础模型。

## 2. 开源短视频工具

| 工具与一手来源 | 用途 | 本项目取舍 |
|---|---|---|
| [FFmpeg](https://ffmpeg.org/legal.html) | 裁切、补边、字幕、慢放、拼接、编码 | 继续作为正式引擎；本机含libx264的构建记录为GPLv3，不能把默认LGPL当成所有构建的许可 |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | 镜头切换候选、关键帧 | BSD-3-Clause；镜头边界不等于回合或动作边界，须修订 |
| [OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) | 时间线和源片引用、编辑器交换 | Apache-2.0；适配现有Timeline，不负责最终编码 |
| [MoviePy](https://github.com/Zulko/moviepy) | Python模板、标题、分屏原型 | MIT、v2维护；逐帧Python/NumPy处理可能比直接FFmpeg慢，不作为加速替代 |
| [Kdenlive](https://apps.kde.org/kdenlive/) / [LosslessCut](https://github.com/mifi/lossless-cut) | 桌面精修 / 快速粗切 | GPL-3.0-only / GPL-2.0；外部工具，不是可直接嵌入的Web组件。补边、字幕、慢放仍需编码 |
| [Auto-Editor](https://github.com/WyattBlue/auto-editor) | 音量等信号驱动的粗剪 | 源码Unlicense，二进制依赖另计。适合教学口播空白段；比赛停顿有意义，不用于判断技法高光 |

[AutoFlip](https://github.com/google-ai-edge/mediapipe/blob/master/docs/solutions/autoflip.md?plain=1)旧方案官方已停止支持，只参考构图思路。[Remotion许可](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md)有组织规模等条件，不能归为无条件免费开源工具。真实比赛集锦无需生成式模型重造动作。

## 3. 竖屏平台规格

没有适用于所有平台、全部入口的统一硬标准。建议工程预设：**1080×1920、9:16、MP4、H.264、yuv420p、逐行、AAC 48kHz、默认30fps**；源片为50/60fps时另保留高帧率档，不把插帧当真实细节。首批15–60秒，另设≤180秒Shorts档。1080p 30fps约8Mbps、60fps约12Mbps可作质量起点，来自[YouTube编码建议](https://support.google.com/youtube/answer/1722171?hl=en)，不是跨平台硬限制。

| 平台 / 上传入口 | 官方查证结果 | 证据范围 / 限制 |
|---|---|---|
| YouTube Shorts | [普通上传规则](https://support.google.com/youtube/answer/12779649?hl=en-IN)：正方或竖屏、≤3分钟；[创建工具帮助](https://support.google.com/youtube/answer/10059070?hl=en)写最大1080p | 1080p按创建工具说明记录，不当作所有上传路径上限；并非只能9:16，本轮未实际上传 |
| TikTok Web Studio | [官方帮助](https://support.tiktok.com/en/using-tiktok/creating-videos/creator-tools-on-tiktok?lang=nl)索引显示MP4/WebM、≥720×1280、≤30分钟、<10GB | 正文直开为空，仅索引证据；不能外推手机/API/全部账户 |
| TikTok Content Posting API | [媒体指南](https://developers.tiktok.com/docs/en/content-posting-api-media-transfer-guide)：MP4/WebM/MOV、推荐H.264、23–60fps、宽高各360–4096、≤4GB | [Direct Post](https://developers.tiktok.com/docs/en/content-posting-api-get-started)须查询creator info；入口和账户时长不同，不统一硬编码 |
| 快手PC创作者 | [官方帮助](https://www.kuaishou.com/help/feedback/4000)：支持60fps、最长15分钟、最大4G，仍会转码 | 本页没有竖屏像素硬限制或明确发布日期 |
| 抖音Upload API | [官方文档](https://open.douyin.com/platform/resource/docs/openapi/video-management/douyin/create/upload)：推荐MP4/WebM、15分钟、单次128M，超出用分片、总量4GB内 | 把“16:9/1280×720”写作竖版，文字矛盾；不据此设竖屏比例，也不当客户端上限 |
| Instagram Reels | [官方帮助](https://help.instagram.com/1038071743007909)返回429，[官方镜像](https://www.facebook.com/help/instagram/1038071743007909)需登录 | 当前普通上传完整规格未核实，不拿广告规格或第三方转述填空 |
| 微信视频号 | [官方创作者入口](https://channels.weixin.qq.com/)不可读取，未找到可读的当前普通上传完整规格 | 未核实；不以腾讯云点播、广告、小程序规则替代 |
| B站普通竖屏投稿 | 可查的[2018年说明](https://www.bilibili.com/read/cv527957/)已过时，课堂/素材库规则属于其他业务 | 当前完整硬限制未核实，不声称60秒或某码率为统一上限 |

安全区应按平台做可调覆盖层，未查到跨平台统一像素边距。羽球默认保留全场，上下放标题/说明；局部放大可用画中画，避免裁掉远端球员、羽球和脚步。编码正确、平台接受、画面具备公开发布权须分别验收。

## 4. 当前视频实现与升级选择

| 环节 | 代码事实 | 未具备/未验证 |
|---|---|---|
| 探测、缩略图 | `packages/runtime/worker.py`调用FFprobe/FFmpeg，真实小样通过 | 目前CPU路径 |
| 渲染 | `packages/render/engine.py`分段CPU libx264，拼接video copy，最终faststart | 未启用/实测NVENC；构建含硬件支持不等于硬件运行通过 |
| Web播放 | `apps/platform/main.py`原文件直出，Range已测 | MIME固定video/mp4，无自动兼容代理；MKV/FFV1可探测不等于浏览器可播 |
| 标注取点 | `apps/platform/static/app.js`使用currentTime | 缺逐帧、缩略图条、循环、拖动边界；Range不保证精确快速寻帧 |
| 模型读取 | `packages/models/inference.py`用PyAV CPU decode→PIL→CUDA推理，保留源PTS | 没有NVDEC；缺完整分阶段计时，不能断言解码是当前主瓶颈 |
| Label Studio | 1.23.1真实区间/框编辑、PTS回写和CAS通过 | 大frame-map只提示小段代理，尚无自动生产；真实VFR代理回写未测 |

静态发现单列为[媒体代理缺口](issues/platform-media-proxy-gap.md)。已有小样PASS不扩大到任意容器或整场视频。

最小改造顺序：

1. **代理与交互先行**：按需720p/1080p H.264、短GOP、faststart和缩略图条；原生播放器配[vis-timeline](https://github.com/visjs/vis-timeline)做区间编辑，加快捷键、逐帧、循环和原分辨率局部放大。[requestVideoFrameCallback](https://web.dev/articles/requestvideoframecallback-rvfc)可同步显示帧mediaTime，但不是精确seek API。
2. **继续LS，按需CVAT**：[TimelineLabels](https://labelstud.io/tags/timelinelabels)适合当前区间；密集轨迹和骨骼修订可评估[CVAT Track](https://docs.cvat.ai/docs/annotation/manual-annotation/shapes/track-mode-basics/)与[骨骼](https://docs.cvat.ai/docs/annotation/manual-annotation/shapes/skeletons/)。轻量离线备选[VIA](https://www.robots.ox.ac.uk/~vgg/software/via/)仍需接修订和源映射。
3. **NVENC单独对照**：先比较CPU字幕/布局+NVENC与现有路径，再考虑NVDEC和GPU缩放；不能只加硬件解码开关就说全部滤镜在GPU。保留CPU回退与GPU排期。[NVIDIA官方指南](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/index.html)
4. **有瓶颈再换解码器**：保留[PyAV](https://pyav.org/docs/stable/)精确基线；[TorchCodec](https://github.com/meta-pytorch/torchcodec)可直接输出CPU/CUDA张量、批量采样。当前最新兼容表与torch2.7.1不同，必须另建实验环境或锁兼容旧版，不把新版能力倒推到旧版。[Decord](https://github.com/dmlc/decord)GPU需源码构建，次优先。

每个代理显示帧需映射回源PTS/毫秒；CFR转码可能重帧/丢帧，不能直接“帧号÷FPS”。精细拍面/手腕审核须可切回原分辨率，720p代理不能充当不可见细节的真值。[LS的VFR说明](https://labelstud.io/templates/video_object_detector)也提示此问题。整场处理继续原生后台worker；[ffmpeg.wasm FAQ](https://ffmpegwasm.netlify.app/docs/faq/)的性能/输入限制使它不适合替换此路径。

## 5. 论文与现成模型：什么能直接复用

本轮未找到能直接保证“中文名称→展搓/收搓/后退小跳片段”的现成羽球checkpoint。中文解析、视频事实识别和时序查询是不同任务，多拍顺序不能只靠一个平均向量判断。

| 官方项目 / 论文 | 可复用内容 | 不能直接替代什么 |
|---|---|---|
| [Qwen3-VL-Embedding/Reranker](https://github.com/QwenLM/Qwen3-VL-Embedding)，[2026论文](https://arxiv.org/abs/2601.04720) | 公开2B/8B权重，文字与视频召回/重排；优先2B小窗零样本基线 | 通用检索成绩不是细手法成绩；当前尚未在本机运行。与已有失败的Qwen3-0.6B查询解析是不同模型任务 |
| [ShuttleSet](https://github.com/wywyWang/CoachAI-Projects/tree/main/ShuttleSet) | 44场单打、36,492拍、18类球种及时间/球员/位置，可补粗事件 | 数据不是识别模型；击球点不是动作边界；网前球不等于两种搓球。标注/原片许可分别核实 |
| [ShuttleNet](https://github.com/wywyWang/CoachAI-Projects/tree/main/Stroke%20Forecasting) | MIT代码，根据历史逐拍记录预测未来球种/落点 | 不是原视频文本检索或动作定位；本轮未找到现成权重入口 |
| [TemPose，CVPRW2023](https://github.com/MagnusPetersenIbh/TemPose-BadmintonActionRecognition) | MIT代码，骨骼+场地位置+球轨迹做已分段逐拍分类 | 本轮未找到预训练权重入口；依赖稳定双人轨迹，双打须扩展；COCO17不描述拍面/手指 |
| [FineBadminton/FBBench，2025](https://github.com/iLearn-Lab/MM25-FineBadminton) | 动作/战术/评价层级与视频问答；可参考术语及描述，现有四小样来源 | 未找到专用分析流水线权重；QA得分不是检索P@K；数据卡许可不自动覆盖比赛画面 |
| [TrackNetV3](https://github.com/qaz812345/TrackNetV3) | 官方代码及预训练入口；README声明代码/权重MIT，可提供球位置和修补轨迹 | 不是技术分类/文本检索模型；修补必须保留推断来源，不能作已观察真值 |
| [ActionFormer](https://github.com/happyharrycn/actionformer_release) / [OpenTAD](https://github.com/sming256/OpenTAD) | MIT / Apache-2.0代码，时间定位实现；有通用数据模型/配置 | 不是本项目羽球细标签权重；仍需新标签头、训练和整场评测 |
| [UniVTG](https://github.com/showlab/UniVTG) / [InternVideo2-CLIP](https://github.com/OpenGVLab/InternVideo/tree/main/InternVideo2/multi_modality) | 前者有文本时间定位代码/checkpoint，后者中英文视频相似检索 | 羽球细动作效果未证实；后者[权重页](https://huggingface.co/OpenGVLab/InternVideo2-CLIP-1B-224p-f8)有访问条件，不当作无门槛即用 |
| [DSTA / Fine-Badminton，2026-05](https://arxiv.org/abs/2605.23355) | 羽球时间动作定位、冻结主干的适配器；新公开数据值得试 | 未找到作者正式代码/checkpoint，属复现候选。29类未显式含展搓/收搓/后退启动，不能直接映射 |

[BadmintONTO](https://github.com/huanyu-li/BadmintONTO)的Apache-2.0领域本体与查询可参考术语和逐拍关系，但不输出视觉预测。建议先受控中文标签/QuerySpec + 视频向量召回，再用同球员/同回合/顺序约束及原片局部证据复核，最后由人确认。

### 新找到的完整职业素材

[作者Zenodo发布页](https://zenodo.org/records/20292976)于2026-05-19发布6.5GB ZIP，说明有10场职业单打、约10.72小时、9,817个时间标注；[目录预览](https://zenodo.org/records/20292976/preview/Fine-Badminton.zip?include_deleted=0)有林丹/李宗伟的亚运、世锦赛等录像及CSV。本轮未下载校验。作者声明仅非商业学术研究，原视频版权仍归权利人；不能据此认为可以公开发布成片。

这是2026年的Fine-Badminton，与2025 iLearn-Lab项目不同；论文全部31场/27,597动作不等于公开子集量。[DSTA正文](https://arxiv.org/html/2605.23355v1)报告在RTX4090机器上做适配器实验，但旧torch/MMCV栈不适合直接覆盖5090环境；其ShuttleSet时间区间由击球点±9帧构造，不能当自然动作边界真值。29类网前变体没有明确两种搓球或启动步标签，仍需专家映射/补标。

### 现成模型试验优先级

先比较当前CLIP帧均值与Qwen3-VL-Embedding-2B，不先微调。低频抽帧可用于粗召回，瞬时触球和脚步阶段要回到高帧率原片；放大无法恢复缺失细节。[2B模型卡](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B)为Apache-2.0，示例要求transformers≥4.57.0、qwen-vl-utils≥0.0.14、torch2.8.0；本机是transformers4.51.3/torch2.7.1，应新建隔离实验环境，不覆盖已验收环境。

若粗召回有效，优先冻结特征、训练小型线性/时序头。后退小跳以连续骨骼+场地位置为主；展搓/收搓需要可见的手腕/拍面/球路证据。看不清则unknown，不因名称相近转成阳性。

## 6. RTX5090与训练难度

本机约32GB显存、sm_120算子已有[实测环境报告](experiments/models-001-environment.md)。下表是工程判断，非本轮训练实测。

| 方案 | 本机适合程度 | 难度/主要限制 |
|---|---|---|
| 现成2B视频嵌入推理 | 优先，限制窗口/帧数/像素、batch从1开始 | 中低；激活和工作区随视频输入变化，不一次塞整场 |
| 冻结特征+线性头/TCN/小骨骼模型 | 很适合单卡原型 | 中；数据定义、稳定轨迹和独立真值是主要成本 |
| 2B–4B LoRA/QLoRA、小视频适配器 | 有合理可行性，先小batch与梯度检查点 | 中高；Blackwell量化/自定义算子兼容和激活占用待测 |
| 8B视频微调、长序列高分辨率端到端 | 显存风险明显，只做有界小实验 | 高；冻结/量化/低分辨率仍不能保证任意配置可训 |
| 从零训练大型视频/语言基础模型 | 不作为本项目方案 | 计算、数据和验证投入远超三个动作原型必要范围 |

参数级粗算：2B BF16权重约4GB、8B约16GB，均不含激活/缓存。典型混合精度AdamW全参训练按约18 bytes/参数加激活估计，8B约144GB参数相关状态，实际随优化器变化；推理能装下不意味着全参训练能装下。[官方内存说明](https://huggingface.co/docs/transformers/v4.33.0/model_memory_anatomy)、[PEFT/QLoRA文档](https://huggingface.co/docs/peft/developer_guides/quantization)

先测100–200训练步并分解加载/解码/推理/反向、显存峰值，再按样本量、batch、epoch估算时间。现有短片26–45秒含冷启动，不能外推整场吞吐或训练总时长；所有GPU实验继续遵守同一排期。

## 7. 标注量与人时：带假设的起步预算

以下为项目估算，不是论文证明的最低量或准确率保证。相邻帧、同回合裁切与增强不算独立样本；先按比赛/录制组划分，后切片。个人/转播、单/双打、机位分开评测。

| 阶段 | 建议数量 | 目的 |
|---|---|---|
| 可见性/定义 | 先每类10个正例及易混对照；能一致判定后扩到每类30–50正例，加近似等量难负例、30–60个unknown；三目标约210–360段 | 专家与另一审阅者复核。看不清或定义不一致则先换素材/定义，停止盲目扩标 |
| 零样本模型对照 | 20–30条真实查询，各路线审前K候选，K=min(20,返回数) | 20查询×20候选=400次相关性判断/路线；可跨路线去重，但不能拿不完整候选审查算完整召回 |
| 小模型首轮训练 | 每类200–500个可判正例，三类600–1,500；加约等量已确认难负例，即1,200–3,000训练段 | 先预标后审核、补难例；unknown不做负例，按学习曲线决定是否扩量 |
| 独立验证/测试 | 验证每类50–100正例、测试每类约100正例，另配难负例 | 三类连同等量负例约300–600验证段+600测试段；总计训练/验证/测试约2,100–4,200段，来自不重合比赛组 |
| 完整召回 | 另对选定连续回合/完整比赛区间穷尽标注全部目标和不可判区间 | 分类片段集不能替代此项。每类30正例只是现有最低探索条件，不代表泛化充分 |

标“区间、球员轨迹/身份、目标标签、可见性、关键时刻与修订”，不从逐帧手画全部关键点开始。姿态/球框先预标，只纠正影响动作判断的部分。

人时例子只适用**已找到并切好的片段**：每段45–90秒，1,000段初标+20%同耗时复审约15–30人时；若细手法需3分钟则约60人时。寻找稀有动作、专家定义、全量双人复核、身份纠正和仲裁另计。先实际计时20段再更新预算。

## 8. 后续候选用例与状态

以下候选关联既有阶段，尚未纳入25项正式计数；启动开发时冻结为子用例。资料查到不等于实现PASS，本轮不改变旧验收状态。

| 候选 / 阶段 | 目标断言 | 当前状态 | 首次验证 |
|---|---|---|---|
| R-01 / S4 | 平台导出预设技术参数正确，规则和实际上传接受分开记录 | NOT_RUN | 相同真实时间线输出30/60fps档，ffprobe、全场/安全区审阅；上传未测不能计通过 |
| R-02 / S1 | CFR/VFR/不支持格式都可用代理标注，往返误差≤一个源帧，修订不丢 | NOT_RUN | 30个固定寻帧点测冷/热中位数/P95，逐帧映射核对、长片/容量拒绝 |
| R-03 / S2、S4 | GPU编解码速度收益可解释，质量/源时间/排期不退化 | NOT_RUN | CPU/NVENC同素材分项计时、文件大小/运动细节对照，不预设倍速 |
| R-04 / S0 | 新职业数据来源、哈希、CSV语义、时间映射和整场划分可用 | NOT_RUN | 先做下载+解压+代理峰值与配额预检，再小样核查；6.5GB不是总落盘量 |
| R-05 / S3 | Qwen3-VL-Embedding-2B本机可复现，在同真值/审片预算下比较CLIP与规则 | BLOCKED | 环境/无评分推理可先行；效果验收仍依赖真实相关性真值，记录显存、速度和逐查询错误 |
| R-06 / S0、S5 | 三细标签具备可见性定义和独立样本后再决定训练 | BLOCKED | 先每类10段试标，专家冻结判据再扩量；原S0-03/04和S5门槛不降低 |

本轮完成资料核查，未执行新数据下载、平台上传、硬件视频加速、新模型推理/训练。所有新增环境、代理、权重和特征仍计入700GB及各owner配额。
