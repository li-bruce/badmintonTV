# Library 一手来源核验

核验日期：2026-09-28（Asia/Shanghai）。本报告为来源调查；没有把网页可达当成视频已下载/可解码，下载和实测结果由 library 的 handoff 与状态报告记录。本子任务仅读取公开网页、API、许可文本和少量标注内容，没有下载媒体、安装工具或访问登录后的服务。

## 数据集证据表

| 来源与版本 | 可获取内容、标签与规模 | 许可分层 | 本轮取舍与障碍 |
|---|---|---|---|
| [ShuttleSet 官方目录](https://github.com/wywyWang/CoachAI-Projects/tree/main/ShuttleSet)，GitHub API 当前提交 `45517f7d4cb936b03f3eabf939cc7959d39226fe` | 逐局 CSV，可单文件读取；44 场、104 局、3,685 回合、36,492 拍，2018–2021 年单打。击球时间/帧号、18 类球种、正反手/绕头、落点及双方位置。 | [仓库 LICENSE](https://github.com/wywyWang/CoachAI-Projects/blob/main/LICENSE) 为 MIT、2022 Wei-Yao Wang；目录未见独立标注许可，记录为“仓库 MIT 声明，标注独立许可未见”。不涵盖 BWF 原画面授权。 | 优先单个 CSV；不是视频下载库。不可把 net shot / cross-court net shot 映射为展搓/收搓，不把位置记录当小跳真值。 |
| [TrackNetV3 官方仓库](https://github.com/qaz812345/TrackNetV3) 与其链接的 [Shuttlecock Trajectory Dataset](https://hackmd.io/@TUIK/rJkRW54cU) | 轨迹 CSV `Frame,Visibility,X,Y`、真实回合视频；发布说明含职业和作者自打样本，1280×720、30 fps。主说明列 78,200 帧，另列 3 个测试比赛。 | TrackNetV3 README 明确代码与预训练权重 MIT；轨迹数据说明未见独立许可，原转播权利未知。不得将 MIT 外推给数据/画面。 | [NYCU SharePoint 官方下载入口](https://nycu1-my.sharepoint.com/:u:/g/personal/tik_m365_nycu_edu_tw/EWisYhAiai9Ju7L-tQp0ykEBZJd9VQkKqsFrjcqqYIDP-g?e=S0AB1Z) HEAD 200，跳到 `TrackNetV2.zip` 网页；未取得单回合直链与压缩包实际大小。先不全量下载。作者自打样本也需确认授权条款。 |
| [BFMD 官方仓库](https://github.com/Ning-D/BFMD)、[数据说明](https://ning-d.github.io/BFMD-Dataset/) | Drive 标注包约 1.8 GB；实际释放说明为 12 男单+7 男双、1,058 回合、11,301 拍。手工 shot_type 与回放/回合区间；shuttle 是 TrackNet 预测；hit_inferred 是推导结果；双打目前主要为 hit/bounce/net_hit 和结构区间。 | 数据页明确仅非商业学术研究、不得再分发；视频属于 BWF TV。根目录 API 未见 LICENSE，代码许可不能假定开源。 | [Drive 文件夹](https://drive.google.com/drive/folders/1wQr4DpMbx-e8jFnvOH9WUJXxfXgTC1IJ?usp=drive_link) 可定位，但网页抓取无可用文件内容；未下载。原视频不在标注包中，作者脚本指向 BWF YouTube。总体介绍的 1,687 回合/16,751 拍与实际释放数字不同，必须按实际包版本统计。 |
| [FineBadminton 官方代码页](https://github.com/iLearn-Lab/MM25-FineBadminton)、[FBBench 数据卡](https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark)，提交 `ff86093a51efdf9a243a0635704952d404e99e52` | 可公开取独立 MP4 和 JSON；QA 经 `video_uid` 一对一关联。12 类任务含球种分类/定位/预测、击球计数/定位、移动、回合描述。标注目录约 3.84 MB，HF API 总 usedStorage 10,230,342,715 bytes。 | 官方 GitHub 和 HF 元数据标 Apache-2.0。独立比赛转播授权链未见，因此原画面仍单列 rights unknown，不能据数据卡允许发布赛事集锦。 | API `gated=false,private=false`；最小视频约数百 KB，适合本轮。QA 不含原整场 ID/原片偏移，不能拿 video_uid 当独立比赛划分。 |
| [Finebadminton-20K](https://huggingface.co/datasets/iLearn-Lab/Finebadminton-20K)（同一研究的公开子集） | 70 整场视频、2,066 回合、20,757 击球；文件树约 43.4 GB，JSON 目录约 26.6 MB。 | HF 卡 Apache-2.0；画面权利仍需单列核验。论文方法含 MLLM 提案与人工修订，不能把全部内容无条件当专家真值。 | 不全量下载。[benchmark_source_videos.txt](https://huggingface.co/datasets/iLearn-Lab/Finebadminton-20K/blob/main/benchmark_source_videos.txt) 标出与 FBBench 有交叠的 20 个整场来源；需要整场关联后再训练/测试。 |
| [Fine-Badminton / Zenodo 20292976](https://zenodo.org/records/20292976)（不同团队，勿与上项混淆） | 2026-05-19 v1.0；10 场单打、9,817 帧级动作区间、29 类，单个 ZIP 约 6.5 GB，页面 MD5 `cb3fcaca0ae9b08c564ac2a19ae4e7a0`。 | 页面只允许非商业学术研究，原视频权利保留给内容拥有者；无可推断的公开商用授权。 | 单包超过初次小样需求，不下载。待需要29类具体词表时先查包内清单，不能因名称含 Fine 就推断存在本项目三个细标签。 |

## 已核验可交给受控下载器的小样入口

以下大小来自发布者 GitHub/HF 文件元数据，非本地探测值。下载器仍需硬字节上限、SHA-256、媒体探测，并用固定提交代替 `main`。

| 候选 | 固定版本 URL | 发布大小 | 使用与映射约束 |
|---|---|---:|---|
| FBBench video_000001 | [MP4](https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark/resolve/ff86093a51efdf9a243a0635704952d404e99e52/hf_video_clips_qa/video_000001.mp4) | 642,017 B | QA 指上方球员最后一拍 clear。仅粗标签导入候选，身份需复核。 |
| FBBench video_000002 | [MP4](https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark/resolve/ff86093a51efdf9a243a0635704952d404e99e52/hf_video_clips_qa/video_000002.mp4) | 591,764 B | QA 指上方球员最后一拍 block。不是展搓/收搓。 |
| FBBench video_000003 | [MP4](https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark/resolve/ff86093a51efdf9a243a0635704952d404e99e52/hf_video_clips_qa/video_000003.mp4) | 499,766 B | QA 指下方球员最后一拍 smash。 |
| FBBench 原始 QA | [JSON](https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark/resolve/ff86093a51efdf9a243a0635704952d404e99e52/finebadmintonbenchmark/benchmark_action_classification.json) | 页面约334 kB | 以 `video_uid` 联接；原文保留，转换 provenance.source=import，review_status=unreviewed。 |
| ShuttleSet 桃田贤斗—周天成，2018 丹麦赛决赛第1局 | [CSV](https://raw.githubusercontent.com/wywyWang/CoachAI-Projects/45517f7d4cb936b03f3eabf939cc7959d39226fe/ShuttleSet/set/Kento_MOMOTA_CHOU_Tien_Chen_Denmark_Open_2018_Finals/set1.csv) | 61,860 B | 与前3个 FBBench 视频没有已证关联；严禁配成同源训练样本。 |
| BFMD demo_petronas.mp4 | [固定版本 MP4](https://raw.githubusercontent.com/Ning-D/BFMD/c7c7e8e4c815085dda42746f16e07f1172503312/demo_petronas.mp4)、[官网同页嵌入 MP4](https://ning-d.github.io/BFMD-Dataset/videos/demo_petronas.mp4) | 481,202 B | 官网紧邻标题为2025 Malaysia Open、Kodai Naraoka vs Anders Antonsen、SF；官网媒体HEAD 200、video/mp4。仍需看片确认；非原始整场替代品。 |
| BFMD demo_all_petronasm.mp4 | [固定版本 MP4](https://raw.githubusercontent.com/Ning-D/BFMD/c7c7e8e4c815085dda42746f16e07f1172503312/demo_all_petronasm.mp4) | 878,665 B | 展示样例可能已有标注覆叠；不凭文件名确认球员/比赛。 |

容量建议：FBBench 前3视频+1份QA只需数 MB；先预留 20 MB（原件、失败 .part 与小型探测报告），不需要下载整个数据集。BFMD demo 仅作研究备选，保留发布者非商业/不再分发限制。**BFMD 官网对数据集整体写研究限制，也亲自嵌入上述 demo；这证明发布路径，不能证明 BWF 向项目授予许可。没有发现单独覆盖 repo demo 的再许可语句或 BWF 授权链。** 记录发布者用途声明和原画面权利缺口，不声称法律授权已经完整核实。未确认原整场身份的 FBBench 片段先共用保守的待核验分组、`split=unassigned`，不得建立互相独立的训练和测试样本。

## 官方比赛候选与历史顶尖背景

下面是来源目录，不是已下载资产。保留 `download_status=not_attempted` 或由实际下载日志改为具体失败。世界排名必须带日期；赛事标题的 `[1]` 等是种子，不能直接当 BWF 周排名。

| 比赛候选 | 一手观看入口 | 日期/球员背景依据 | 获取状态与权利 |
|---|---|---|---|
| 林丹—李宗伟，2011 世锦赛男单决赛 | [BWF TV 全场](https://www.youtube.com/watch?v=WI8Od4jBpUc) | 官方视频发布于2011-08-14，双方为当届世锦赛决赛球员；[BWF 2023-05-26 名人堂典礼](https://www.youtube.com/watch?v=s3UUavKaeog)支持历史名将背景。 | 官方来源已核验；未下载/未探测，时长大小未知；原画面权利未授权给项目。 |
| 李宗伟—林丹，2011 全英赛男单决赛 | [BWF TV 全场](https://www.youtube.com/watch?v=5F1Pn8-Lp0c) | 赛事为2011-03-08至13日，官方视频2011-10-12发布；顶尖背景同上，不能写成当前世界前十。 | 同上。 |
| 林丹—李宗伟，2012 伦敦奥运男单决赛 | [Olympic Games 官方视频](https://www.youtube.com/watch?v=ytjD4f_I0sc) | 官方说明确认林丹赢得金牌，发布于2012-08-07。奥运决赛背景足以列为历史顶尖案例，不编造周排名。 | 官方页面可被搜索核验；未下载/探测。 |
| 桃田贤斗—安赛龙，2020 马来西亚大师赛男单决赛 | [BWF TV 官方集锦](https://www.youtube.com/watch?v=J9UjiLffAbk) | 2020-01-12发布；[BWF 2019-07-06报道](https://bwfworldtourfinals.bwfbadminton.com/news-single/2019/07/06/momota-highest-earner-this-season/)当时明确桃田世界第1。集锦与原整场应归同match_id。 | 集锦候选；不能据它直接校准 ShuttleSet 整场时间码。 |
| 戴资颖—陈雨菲，2018 印尼公开赛女单 | [BWF TV 官方比赛视频](https://www.youtube.com/watch?v=Vs3ZUem_nT0) | 2018-07-07发布，赛事为Super1000；标题分别标种子1/5，仅记录赛事种子。[BWF 2020-03-11报道](https://bwfworldtour.bwfbadminton.com/news-single/2020/03/11/all-england-after-challenging-first-round-a-message-for-rivals/)明确该日陈雨菲世界第1；日期不同，不能倒推2018周排名。 | TrackNet数据说明的对应比赛轮次须重新对齐；官方视频标题未明确轮次，不擅自写决赛。 |
| 蔡赟/傅海峰—鲍伊/摩根森，2012 伦敦奥运男双金牌赛 | [Olympics 官方全场](https://www.youtube.com/watch?v=uBwLPvW7lYs) | 2026-09-28直接读取 YouTube oEmbed 返回标题为男双金牌赛、author_name=`Olympic Games`、author_url=`https://www.youtube.com/@Olympics`。据奥运金牌赛背景列为历史顶尖双打，不声称当前排名。 | 只核验元数据，未下载或实播；双打身份/动作需独立验证，不继承单打模型结果。 |

BWF 官方[马来西亚大师赛说明](https://www.youtube.com/watch?v=gdBb6980KeA)说明部分地区因转播权出售而限制观看。具体某次下载是否受地域限制、登录或反机器人限制，必须由实际日志确认；本调查没有绕过限制，也不把发布者附带下载脚本视为转播权授权。

## 核验方法与遗留事项

- 使用本会话 `web.run` 搜索/打开一手发布者页面；PowerShell 公开只读 REST 查询用于 HF/GitHub 文件大小、提交号、少量 QA 结构和 YouTube oEmbed 作者核验。没有安装额外技能/MCP/依赖。
- 普通沙箱的网络 REST 首次出现 socket access denied；通过工具自动审批的 `require_escalated` 只读查询成功。这是环境网络限制，不是数据源拒绝访问；不要误报数据集不可得。
- HF 部分目录/文件由网页抓取器返回 Internal Error，但公开 REST/API读取成功；本报告逐项区分网页抓取限制与真实下载状态。
- 模型字段必须区分手工标签、预测与推导标签；未知手法/脚步保留 unknown。训练时另查原比赛映射与 FineBadminton/FBBench 重叠表，视觉近似/重上传去重只是辅助，不能取代整场分组。
- 尚未完成：广播原片再分发授权链、SharePoint压缩包大小/单回合获取、BFMD Drive包内清单、Fine-Badminton 29类词表。上述缺口不阻止以FBBench数百KB研究小样验证下载—探测—manifest技术链。
