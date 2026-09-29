# 战术分析与检索复用边界（2026-09-29）

本文件对应 [R-07d](../IMPLEMENTATION_ROUND_2026-09-29.md)：分别记录可复用的实现、文献方向及本项目可运行状态。**当前没有已验收的真实逐拍事实日志或战术识别模型，自动战术识别/意图判断保持 `unavailable`。** 研究材料查到、模型源码存在、通用向量成功均不能替代真实战术效果验收。

## 当前可运行范围与未满足条件

| 能力 | 已有证据 / 可复用部分 | 本项目状态及输出边界 |
|---|---|---|
| 姿态检测 | 已有真实单打/双打稀疏 pose 基线及人工抽帧 QA，见 [实验记录](../experiments/models-002-real-baselines.md) | 特征链存在；裁判误检、重复框、遮挡与不稳定检测编号已知。不能将编号视为稳定球员身份 |
| 球轨迹 | 本轮 TrackNetV3 复用工作单独推进，见 [轨迹调研](TRACKNET_REUSE.md) | 以该组件的真实运行报告为准。轨迹/补轨不是已确认击球、落地或战术标签 |
| 球员场地位置 | 可按 pose 脚点、可审查关联和镜头校准实现，见 [BST 输入路线](BST_REUSE.md) | 本文件只提出路线；未人工确认的四点/H 不填 human_confirmed，未跟踪则显式 untracked |
| 图像/视频向量检索 | 已有 CLIP 短窗图像均值真运行；本轮更强视频向量单独推进 | 可形成候选相似度；没有真值时不报战术 precision/recall。语义相近不证明发生了某战术 |
| BST 粗球种 | 官方代码、25类映射及公开权重入口已核对 | 本文编写时本地适配/真实推理 NOT_RUN；球种预测仍非逐拍真值，不含细手法或战术意图 |
| 基于事实的统计/规则查询 | 技术上可从已审核回合日志计算区域、序列、计数和持续时间；无需另一个大模型 | **建议、未实现/未验收**。没有该日志时返回缺字段原因，不能以虚构日志生成看似真实报告 |
| 战术解释/因果归因 | 有 MADR、CoachAI 等一手研究路线 | `unavailable`；无本地合格模型+真实输入+专家验证，不显示已识别战术 |

`可复用` 表示有实现或可明确实现的组成部分，不等于本项目已运行。未来实验可分开报告“规则执行成功”“文本向量产生成功”“专家战术正确率”；任一前者不自动提升后者。

## MADR：研究方向，当前不能当成可下载模块

官方 [MADR 项目页](https://yixiang1120.github.io/MADR-project-page/)题为 *From Alignment to Reason: Multi-Agent Debate for Tactical Badminton Video Retrieval*，本次读取时 Code 链接仍显示 **Coming Soon**。页面展示日志→多角色推理→文本报告→检索的路线，没有给出本次可获取、校验和加载的完整实现/权重。页面模板的 CC BY-SA 许可也不是尚未发布模型代码的许可。

作者官网提供的 [论文 §3.1 与 §3.3](https://people.cs.nycu.edu.tw/~yushuen/data/BadmintonRetrieval26.pdf)明确：实验直接使用 ShuttleSet 已标注逐拍日志，另以姿态描述补充，离线生成报告，再对报告做文本向量检索/重排。论文对未来自动抽取日志的可行性讨论，不构成本项目“原始视频→无人工战术真值”的实现证据。本项目不搬用论文数字作为本地成绩。

主协调提供的 [CVF 补充材料入口](https://openaccess.thecvf.com/content/CVPR2026F/supplemental/Zhang_From_Alignment_to_CVPRF_2026_supplemental.pdf)此前返回403；这里只保留索引和该访问限制，不尝试绕过。MADR 在本轮属于可借鉴的日志与解释分层设计，**不是已安装模型**。

## CoachAI 等官方实现：任务不同于视频识别

只读核对 [CoachAI-Projects](https://github.com/wywyWang/CoachAI-Projects) 提交 `45517f7d4cb936b03f3eabf939cc7959d39226fe`（Git tree 未截断）。仓库及 Stroke Forecasting 子项目有 MIT 文件；复用具体文件仍须保留其来源/许可和各数据、权重许可。未核定来源的其他 `Tactic.py` 不纳入，也不复制。

| 一手实现 | 原任务与需要的输入 | 复用判断 |
|---|---|---|
| [ShuttleNet / Stroke Forecasting](https://github.com/wywyWang/CoachAI-Projects/tree/45517f7d4cb936b03f3eabf939cc7959d39226fe/Stroke%20Forecasting) | 给定结构化历史拍序列，预测后续球种/落点；README 有 train/evaluate/generator 入口，evaluate/generator 需要 model_path | 是预测研究实现，不是从本项目视频抽取事实日志。本次未核验可直接使用的预训练产物，未安装/训练/推理；本地 unavailable |
| [DyMF / Movement Forecasting](https://github.com/wywyWang/CoachAI-Projects/tree/45517f7d4cb936b03f3eabf939cc7959d39226fe/Movement%20Forecasting) | 基于历史拍次和运动关系预测下一拍球种/移动；包含训练与评测脚本 | 可研究结构化运动预测；还需一致字段、归一化、checkpoint 和受控测试。不能将未来预测写成已观察球员位置 |
| [RallyNet](https://github.com/wywyWang/CoachAI-Projects/tree/45517f7d4cb936b03f3eabf939cc7959d39226fe/RallyNet) | 回合分为按球员的 state-action 轨迹，状态包含比分/位置等，动作为球种/落点/移动；另建经验字典 | 离线行为模仿/生成路线；没有这些真实状态输入或训练产物时不能调用视频识别接口冒充能力 |
| [Offline RL for Badminton](https://github.com/Wenminggong/Offline_RL_for_Badminton/tree/1419fcad316e977590f9eefb08e72f8b3f6f3559) | 官方战术决策论文实现；偏好奖励、CQL/BC、Decision Transformer 与离线评估，依赖结构化数据 | 固定提交 `1419fcad316e977590f9eefb08e72f8b3f6f3559`，MIT；本次仅读 README/tree。训练/策略代码可研究，不是已取得的通用战术识别器 |

本次没有下载这些项目的数据或模型，没有运行其训练命令；所查 README 和 tree 不足以承诺任意新球员、双打或新机位的现成可用效果。检查未发现常见 `.pt/.pth/.ckpt/.h5` 后缀的仓库内权重，不等于证明所有外部权重不存在；准确状态是“尚无已核验可直接使用的 checkpoint”。

## 建议的最小事实日志（兼容扩展草案）

以下是模型侧将来接口设计建议，不修改公共合同。需主任务协调后实施。每个字段都保留证据状态，不能由一次模型高分把整条事件设为 human-confirmed。

| 字段组 | 至少记录 |
|---|---|
| 来源 | `asset_id`、`asset_sha256`、`match_id`及确认状态、`usage_scope`、`camera_segment_id` |
| 时间 | `source_pts`、time_base、`source_ms`、回合/事件区间；另存 `available_at_source_ms`，表示该结论所依赖的最晚源时刻；处理/审核墙钟时间另列 |
| 参与者 | `track_id`、关联方法与版本、track 审查状态；有独立证据才填写 `player_id`。侧别/衣色/检测 index 不冒充身份 |
| 位置 | 原图点、场地点、单位、参考系、`calibration_id`、适用镜头、可见性、误差/缺失原因。脚点/羽球/落地位置的几何假设分开 |
| 事件 | 当前拍/回合边界、击球方、粗球种、触球/落地/得分等，每个结论独立 `unknown/predicted/confirmed`；细手法保持独立标签空间 |
| 证据 | `provenance`：源帧/区间、原特征引用、模型及权重 hash、版本、方法、审查者/时间；区分 observed / imputed / manual / inferred |
| 不确定性 | unknown 原因、遮挡/缺帧、候选分歧、校准/关联失效范围；不得把 unknown 变成没有发生 |

对每条事件保留“当时可见的事实”与“稍后才能判断的事实”。例如落地点和回合结果依赖后续帧，不能在因果评测中提前提供给当时的战术系统；离线报告须显示该依赖。`available_at_source_ms` 是源时间可得性，不是执行任务的机器当前时钟。

## 可独立实现的近期路线（建议，NOT_RUN）

1. 从一个真实、完整且可审阅的单打回合开始，人工/已审核模型字段组成事实日志；缺少的击球、落点、比分等保持 unknown。日志用途继承 training_only，不发布原媒体。
2. 用确定性模板输出“第 n 拍、来源时刻、哪一侧、观测位置/球种及不确定性”，每句引用 event_id/source PTS。先不生成“诱骗成功”“有意调动”“因为战术错误失分”等意图因果结论。
3. 对事实模板使用经过本地真实输入验证的文本向量或现有向量组件做小范围检索，锁定模型/版本/查询及数据划分。若现有组件只支持图像均值或未验证文字输入，不应视为已具备该文本路线。
4. 将顺序关系单独计算并返回证据，例如“已知连续三拍在前场”；若其中一拍 unknown，输出已知覆盖和缺口，不把缺口补成满足规则。空间区域、速度阈值和连续拍数是产品/专家需确认的参数，不是论文通用真值。
5. 在专家确认战术术语及标注规范后，另设假设层：每个 `hypothesis` 引用 supporting/conflicting event IDs、unknown 和替代解释，字段标明推测。假设不覆盖事实，不自动转成训练真值。

第一步也不能靠人工编造示例数据宣称完成。可用合成夹具检查接口/规则，但实验报告必须明确“夹具”，与真实回合及人工真值分表。

## R-07d 及相关验收记录

| 固定 ID | 方法/输入与预期断言 | 实际结果、状态及证据 | 下一步 |
|---|---|---|---|
| R-07d | 审查官方模型/论文；运行时区分事实、假设、缺失，缺模型保持 unavailable | 本文完成来源和设计边界，未有运行组件证明全部断言；**NOT_RUN** | 先实现真实日志和 unavailable 返回，再审查真实样例中每条推测的引用 |
| R-07b | 单打真实连续 pose/track/H → 可回查位置 | 本文未运行位置模型；**NOT_RUN** | 四点/镜头校准与轨迹审查，位置数值和画面交叉核验 |
| R-07c | 按 available_at 约束仅用过去/当前证据，稳态 RTF/延迟实测 | 本文路线包含离线日志/完整回合推理；**NOT_RUN** | 另设因果子路线和泄漏测试，离线成功不计此项 PASS |
| R-05b、S3-04 / 检索质量 | 同比赛划分、真实查询、人类逐候选审阅；unknown 给上下界，完整真值才给 recall | 无该真值集；**BLOCKED**；所有本地战术准确率/召回为 null | 冻结人工查询集、难负例与完整性范围后运行评测 |
| R-06a / 三细标签 | 专家可观察定义及独立真值 | 战术论文/粗球种标签不能解决该缺口；**BLOCKED** | 沿用 [细标签和评测规范](annotation-and-evaluation.md) |

本次只读取官方页面、论文和固定源码元数据；没有安装、下载大文件、启动 GPU、调用外部 LLM 推理或传出任何本地比赛媒体。未复制不明许可的战术程序；没有生成模拟模型成绩。
