# 2026-09-29 训练数据实际交付

本轮 library 已完整获取 Fine-Badminton 2026 原包及 BFMD 标注包，均保留在 `D:/video/data/training/`。新增媒体仅用于训练与研究诊断；不进入生产素材库、时间线、研究预览或渲染。原生产5样本及其两个manifest不变。训练素材不代表已确认的动作真值或公开发布许可。

## Fine-Badminton 2026

来源为 Zenodo record `20292976` / `v1.0`，DOI `10.5281/zenodo.20292976`。完整原包 `fine-badminton-2026-zenodo-20292976-v1.0/source/Fine-Badminton.zip` 为 **6,455,837,331 B**，作者MD5 `cb3fcaca0ae9b08c564ac2a19ae4e7a0` 匹配，本地SHA256 `a3518f52d66dd6c5d2b01ce1347de8e589516ccc24a72aae818fea64e0b04439`。一次连续200响应完成，3354.230秒，无续传。

安全提取22/22成员（10 MP4、10 CSV、README、LICENSE），展开6,467,329,596 B；原名与短路径保存在 `archive-inventory.v1.json` / `extracted-sources.v1.json`。视频是作者处理过的片段，不能称10份无剪辑整场。真实全片CPU解码和完整原序PTS **10/10 PASS**，合计 **980,703帧、38,592,556 ms**，标注实读 **9,817行**。帧数和标注数精确符合作者声明；实测10.720154444小时按作者公布的两位小数、Decimal ROUND_HALF_UP舍入为10.72，公布精度的一致性 **PASS**。本项目只比较这一显示精度，不推断作者容差或精确秒数一致，原差0.556秒继续保留。

2017视频是真实VFR：`time_base=1/90000`，316个1800-tick间隔和119698个3600-tick间隔，不能用frame/25替代PTS。首轮null输出时基误报已通过真实A/B、全源PTS和修正后的完整解码定位并修复；所有原失败/孤立PTS保留，详见 [时基问题](../issues/library-probe-output-timebase.md)。修正后的两份全片stdout/stderr日志位于数据集 `diagnostics/reprobe-20260929T101835Z-970261c6/`，分别64,069 / 65,122 B，均exit0、stderr0。

CSV双语原值、重复/时序、四种帧端点假设及逐视频技术字段详见 [完整数据报告](FINE_BADMINTON_2026_DATA_REPORT.md) 与同名JSON。60种原始字符串并非已确认的60类；29语义类别与中文31种原值的映射、0/1帧基、端点开闭、location含义、原转播偏移仍 **BLOCKED**。本轮0个Event，细手法/步法保持unknown。

10张固定中点训练QA均实际生成并逐张检查，共图片+收据397,365 B，记录见 [画面QA](TRAINING_VISUAL_QA.md)。4张可见球场主体（1张清洁场地），6张人物/场边镜头；未挑选更理想帧，未验证身份、动作或CSV边界。

包内README/LICENSE为CC BY-NC4.0，Zenodo API为CC BY4.0；LICENSE允许Share与README另行限制再分发也存在差异。全部证据保留，不据此推断新的画面授权，保持研究用途限制。

## BFMD

固定来源快照为作者仓库 `Ning-D/BFMD` commit `c7c7e8e4c815085dda42746f16e07f1172503312` 及其公开Drive文件。**121/121** 文件、**1,825,439,459 B** 实际下载完成，115活动JSON、1备份、5根文件；121份成功收据、121次尝试、0续传字节、0失败。首份开始09:43:33.125672 UTC，最后完成10:29:32.631620 UTC，跨度2759.506秒。

全过程为一个顺序下载器。速度一度约0.19MB/s，后恢复高速自然完成；没有杀进程、切换双流或实际验证服务器Range。新增两连接实现的夹具结果与真实本批获取分开记录，不能声称本批跑过双流。作者Python脚本只归档，未执行；未下载BFMD视频，不创建Asset/PTS/Event，`video_alignment=unmatched`。

统计和结构以 [BFMD实际报告](BFMD_DATA_REPORT.md) 及同名JSON为准：12单打手工拍/推断hit/caption分别11301，7双打手工hit5450，合计16751；不同模态不能相加当更多拍。回合数差异、caption来源和自动姿态/轨迹限制见报告与[语义问题单](../issues/library-training-annotation-semantics.md)。许可仅非商用学术研究、禁止再分发；视频不在本次交付，原视频版权与作者代码LICENSE未知项分别保留。

## 交接、隔离与容量

以下路径均相对 `D:/video/`，下游只读：

| 路径 | 内容 | 最终SHA256 |
|---|---|---|
| `data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json` | 10个typed训练Asset | `2725970f4485732e67ba249b72262c51dbba24ee17e5e97d901b18ec8a29e286` |
| `data/training/handoff/training-registry.v1.json` | 先于Asset发布的10源SHA可信用途登记 | `63eb86de88e6c760be8ff3464318d8fd55a923e7bfa1d1c177dc2bdd643e52aa` |
| `data/training/handoff/bfmd.annotations.v1.json` | 121项完整稳定清单 | `8643173ce76db81f93d28a382e9492544522c07e24ba1905761a6687a6dff1bf` |
| `data/training/bfmd/source-catalog.v1.json` | 固定来源目录 | `84af589448d63ccf5e5ab25d5795e81943d92aee6419be51663d9fd38139b142` |

library在主线合同 `4dc912533145ad277d5b713b3cd380faa0a5595e` 上实际验证15个typed Asset：新10个全部禁止生产，旧5个全部允许；新旧原SHA交集0，但无法据此证明跨片段比赛/内容不重叠。20项改名、改路径、去provenance的**纯元数据别名**仍TRAINING_ONLY，包含research_preview开关；没有物理复制。详细证据见 `VALIDATION_TRAINING_ISOLATION.json`。

render用首个实际Asset测试独立CLI、preview、research_preview和仅测试的confirmed请求，4项均exit2/TRAINING_ONLY，0子进程、0媒体产物。library已只读查看其 `D:/video/render/handoff/training-denial-5f1e29d2eab9/validation.json`，该测试使用当时4Asset的manifest快照，不冒称复跑最终10项。主任务另独立读最终10原片/PTS并复核哈希通过。平台入口与模型识别结果由各模块单独验收，不将本模块采集通过当识别精度通过。

18:32:18本地实际容量快照：写容量收据后data为 **14,802,357,491 B**（上限300GB）、活动预留 **0**、剩余物理空间 **931,035,758,592 B**。全项目保守账目92,251,701,558 B（含不可遍历runtime的70GB分配上界，不能称70GB实占），低于700GB。Fine目录12,965,074,147 B、BFMD目录1,825,691,214 B。无新环境/依赖/GPU/端口，runtime/library新增0。完整证据见 `TRAINING_CAPACITY.json`；已有Python3.12.11、平台Pydantic和FFmpeg9.0.2的使用方法见 [RUNBOOK](RUNBOOK.md)。
