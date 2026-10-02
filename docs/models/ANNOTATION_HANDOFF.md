# 标注词表与模型侧交接

日期：2026-10-02。本文件先交付词表部分；训练快照消费、可训练性审计和触球窗口接口由 models 主任务随后扩展。范围依据 [本轮实施](../IMPLEMENTATION_ROUND_2026-10-02.md)、[完整能力方案](../END_TO_END_CAPABILITY_PLAN.md) 第 2 节及 CTX 断言。未新增模型推理、训练、数据下载或专家真值。

## 1. 本次可消费产物

[configs/models/taxonomy.v1.json](../../configs/models/taxonomy.v1.json) 是 UTF-8 JSON，当前包含 **193 个节点：37 个目录组、156 个标签**。覆盖击球与手法、完整步法、球路、本人/对手/搭档态势、单打模式、双打配合、结果评价及意图建议。顶层 `coverage_groups` 显式对应能力方案第 2.1 节全部 19 个家族。

这是 **definition_draft**，所有定义审核均为 `needs_expert_review`、审核人和锚点为空，没有虚构确认。184 个节点为 `annotation_draft`，9 个为 `unavailable`；没有 `experimental` 节点。目录项存在不能让模型卡宣称支持；现有姿态、球点或向量成功不能转换成某个目录标签的识别成绩。

| domain | 节点数（含组） | 主要范围 |
|---|---:|---|
| stroke | 57 | 正反手/持拍手/触球高度；握拍与拍面；发接发；后场、中场、网前；动作变式 |
| footwork | 41 | 准备、启动、接近、调整、击球支撑/腾空、落地、回位、再启动；基本步型与衔接 |
| shuttle | 18 | 方向、深浅、弧线、过网、相对快慢；来球和出球关联 |
| player_state | 30 | 位置、方向、回位、朝向、支撑、失衡表象、接球空间和响应关系 |
| singles_pattern | 11 | 前后/四角调动、重复区域后变线、杀/吊上网、网前争夺、反击、节奏变化 |
| doubles_pattern | 22 | 发接发第三拍、阵形、转换、轮转、补位、追身/夹缝/连续同人、防守反击 |
| outcome | 7 | 死球、回球、得分、回位表现；非受迫失误和决策评价当前不可用 |
| interpretation | 7 | 回位时间、诱导、弱点、体能、下一拍预测及替代建议；全部不可用 |

目录没有穷尽所有流派术语或残障羽毛球变体。目录中的身体/脚部判据若不适用，应显式说明并使用 `not_applicable`，不能套用普通脚步定义。任何新增适用范围需要真实专家锚点和新版本。

## 2. 格式和消费约定

顶层标识固定为：

```json
{
  "format": "badminton_taxonomy",
  "schema_version": "1.0",
  "taxonomy_id": "badminton-technique-tactics",
  "version": "1.0.0",
  "status": "definition_draft",
  "labels": []
}
```

上例仅显示结构，空 labels 不是当前完整词表，也不是训练样本。实际完整文件另含来源、缺失状态、角色、时间/坐标政策、兼容映射与家族覆盖表。

| 字段 | 消费语义 |
|---|---|
| `id` | 稳定机器键，使用小写点分层，如 `stroke.net.zhan_cuo`；不可按中文名拼接生成 |
| `parent_id` | 根为 null，其余指向已有组；用于浏览组织，不表示自动继承观察事实 |
| `domain` / `node_type` | domain 为业务维度；node_type 为 group 或 label。组只用于导航，不能当监督类别 |
| `name_zh` / `aliases` | 中文名与显示/检索别名；别名不证明外部数据集语义完全对应 |
| `definition_draft` | 产品拟定观察判据，未冻结部分明确保留，不把建议阈值当行业标准 |
| `evidence_requirements` | 必需证据列表；缺任一决定性证据时该细项仍未知，可独立保留已判粗项 |
| `counterexamples` | 易混情形/不能据此推断的情况；不是已经采集或已经审核的负例 |
| `applicability` | disciplines、subject_roles、概念性 record_kinds 与限制说明；不是已测机位白名单 |
| `support_status` | annotation_draft / unavailable / experimental；当前只出现前两者 |
| `definition_basis` / `source_ref_ids` | 当前操作定义均为 product_operational_draft；来源支持程度由顶层 source_refs 说明 |
| `definition_review` | 审核状态、审核人、日期、真实锚点引用和未决问题；当前无人类专家审核 |

节点 ID 的词根与 domain 不要求相同，例如 `doubles.rotation.front_back_to_side_by_side` 的 domain 是 `doubles_pattern`；消费者必须读取 domain 字段。数组顺序只作显示顺序，不能当稳定类别编号；训练配置必须冻结独立的 `label_id → class_index` 映射及词表文件 hash。

`applicability.record_kinds` 是本目录的概念性表示（contact / interval / state），不能绕过公共训练合同验证。死球、得分等节点可关联独立 mark 或回合结果；接入时按公共合同表达点/区间，不能为点伪造一个正长度动作区间。本词表没有自行新增公共字段或修改制作 Event 白名单。

### 三个可直接读取的节点

以下是实际 JSON 中的目录定义摘要，**不是实际视频标注**：

| ID | 草案判据和必要证据 | 关键反例/未决问题 |
|---|---|---|
| `stroke.net.zhan_cuo` | 保留“展搓”旧名称；需触球局部拍头、拍面、手腕及专家按正反手/持拍手冻结的锚点 | 手臂远离身体不等于展搓；未确认与教材 in-to-out 的一一对应 |
| `footwork.start.backward_small_hop` | 严格候选为同人准备→明确离地→落地/推离→后场方向移动；完整脚部、源时间及场端可回查 | 普通后退、原地垫步、起跳击球不同；跳的尺度、阶段间隔和变体范围待专家冻结 |
| `doubles.rotation.front_back_to_side_by_side` | 同队从持续前后关系转为持续左右关系；需四人连续轨迹、两队、球路及前后时间 | 单帧站位或切镜前后差异不足；阵形转换不自动证明攻防转换或成功 |

这三个节点全部为 annotation_draft / needs_expert_review，不能作为已有真实识别样例。

## 3. 状态、负例和审核是不同维度

顶层 `annotation_states` 专门列出四种非正负判定状态；它不是完整训练记录的审核状态枚举，也不在 labels 中生成“未知动作”类：

| 状态 | 中文 | 使用条件 |
|---|---|---|
| unknown | 未知／无法确定 | 尝试判读但定义、身份、上下文或证据冲突仍未决 |
| unannotated | 未标 | 尚未判读该属性；缺字段默认不能当否定 |
| not_visible | 看不清 | 实际检查过，但手拍、脚、球或关键时段不可见；附具体原因 |
| not_applicable | 不适用 | 该属性前置条件不成立，例如单打的搭档状态；需说明依据 |

正常可判定样本的明确正/负判断由公共训练合同独立表达。未选标签、低模型分数、其它粗类别、rejected 审核、没有检测到动作，均不能自动生成 negative。细标签未知时，可以保留独立证据充分的粗标签。例如确认网前放网并不能确认展搓或收搓；脚不可见时可以记录可见的后退位移，但不能确认后退小跳。

还要分别保存：每字段可见性/缺失原因；human / agent / model / rule / import 来源；人工审核状态与当前 revision；定义版本。**human confirmed 的 unknown 仍不是正例或负例**。agent 能核验工具操作和保存格式，不能冒充教练的技术真值。

当前所有定义未冻结。annotation_draft 允许采集观察、候选和分歧；正式细标签监督还需：

1. 专家用清晰真实正例、可判负例和未知锚点冻结必要特征、适用正反手/机位、边界与阈值。
2. 两位标注者独立判读，第一轮不展示模型细标签或对方答案；细标签正例、分歧及混淆由专家裁决。
3. 当前样本修订确有 human 审核且语义有效、证据充分；保留原始两份意见和专家裁决，不以一次点击替代流程。
4. 定义更新后复核受影响的旧记录，快照固定词表版本、文件 hash、样本 revision 及审核来源。
5. 训练/验证/测试按已确认整场及同源关系分组。标签通过审核不豁免用途、许可、身份和泄漏检查。

上述是正式细标签监督门禁；不阻塞工作台保存未审核记录或做合同/只读审计。完整细标签真实训练和专家质量验收仍 BLOCKED，不能为制造“可训练”报告删除 unknown。

## 4. 参与者、时序与坐标如何配合词表

`player_state.*` 复用同一状态词，通过明确 `subject_role` 区分 actor（本人/分析目标）、opponent、partner、opponent_partner，而不是为每人复制一套类别。角色相对于本条分析目标；双打接球人可能变化，需保存两队和具体人关系。单打选择 partner 或 opponent_partner 为不适用。匿名 track 仅是镜头内候选关联，不能自动转换为 player 姓名；切镜、换边、遮挡或编号交换必须重新核查。

连续数值放状态字段，不塞进 labels：位置/轨迹/速度、时间戳、触球不确定范围、参考区域/阈值版本、校准控制点、可见性与误差。每项保留 sourcePTS/time_base、来源、最晚使用源时间（available_at）、unknown 原因。离线使用未来帧可确认本拍球路，但因果预测不能把后续回球或胜负放入输入。

步法至少容纳准备、启动、接近、到位调整、击球支撑/腾空、落地、回位、再启动。它们可以缺失或重叠；没有跳跃就不强制补“腾空/落地”。原片半开区间与触球点分开保存，窗口只是取证范围，不能当真实动作边界。

来球与出球用前/当前/后 contact 和 rally 关系连接；相关同人模式允许中间有对手击球，不能把“下一次本人击球”写成全表下一行。最后触球不是独立死球 mark。自然落点未发生时仅保存预测终点，实际截击点另存。

图像点不能声称米制场地坐标。地面映射须记录有效镜头、控制点/校准版本和审核来源；空中球与腾空脚不满足普通地面单应假设。场端、左右手和镜像未明时，相关方向保留未知。场地区域、同时落地容差、快慢阈值、连续拍数等先冻结协议再判定；这里不隐含30fps或固定等分场区。

## 5. 旧键与外部数据集映射

| 旧产品键 | 本目录稳定键 | 关系 |
|---|---|---|
| net_zhan_cuo | stroke.net.zhan_cuo | exact_identifier_alias；技术语义仍 definition_unresolved |
| net_shou_cuo | stroke.net.shou_cuo | 同上 |
| backward_small_hop_start | footwork.start.backward_small_hop | 同上，保留严格候选和未决变体 |

旧键映射只是同一产品概念改为层级 ID；不能清洗掉原标签、来源和版本，不能提升样本审核级别。旧 [标注方案](annotation-and-evaluation.md) 中三个示例及制作 Event 限制不代表新训练词表只能有三项。

外部数据集必须以来源/版本命名空间保留原标签，再记录映射依据与 `exact / source_broader / source_narrower / partial_overlap / unmapped`。例如 net shot → 展搓/收搓不是 exact；只有粗网前证据时不分配这两个细标签。2025 FineBadminton/FBBench 与 2026 Fine-Badminton/DSTA 也不能按近似名字合并。任何映射仍须检查实际原始定义与标注时间语义，本次未新建经确认的数据集映射。

## 6. 一手资料支持到什么程度

2026-10-02 通过网页工具读取 BWF 编写、国家羽协网站托管的原版教材出版页、目录及相关章节；未下载到本仓库、未安装依赖，也未复制教材插图。

- [BWF Level 1，2017 第二版](https://badminton.lv/faili/bwf_coach_education_coaches_manual_l1-2nd-edition-midres.pdf)：印刷页51–71移动，73–130击球，132–180战术。支持三大技术家族及单/双打组织的参考背景。
- [BWF Level 2，2013 第一版](https://www.badminton-israel.co.il/newsNdata/General/CoachEducationBWF/BWF_Coach_Manual_Level_2.pdf)：印刷页58–63（PDF一基页75–80）有按正反手及内向外/外向内组织的旋转网前球与对角网前球。

这两份材料不确认本产品全部中文术语、阈值、标注质量或自动识别能力。尤其“展搓/收搓”与英文分类的映射尚待专家确认。本目录操作判据、反例、区域划分和审核组织均为项目拟定草案；顶层 source_refs 区分 primary_coaching_reference、project_requirement 与 project_proposal。教材版权和视频/标注/代码许可分别核查，引用教材不授予素材用途。

## 7. 验证记录与验收边界

本次只用本地 Python 标准库读取 JSON 验证结构，无 ML import、GPU、模型推理或新数据生成。验证项：UTF-8解析、顶层标识、ID唯一/格式、父引用/无环/组父节点、字段非空及类型、domain和适用范围、支持状态、无虚构审核、来源引用、三个兼容键、四种非负缺失状态、19家族映射、完整步法阶段，以及本人/对手/搭档角色。

| 关联验收 | 本次提供的证据 | 本次状态与剩余条件 |
|---|---|---|
| A-04 / S0-03.CTX-01 目录部分 | 19家族、193节点、中文多标签、证据/反例、版本/来源/未知约束 | JSON结构检查 PASS；专家双人真实试标仍 BLOCKED，整体CTX不能报PASS |
| A-05 / S0-04.CTX-01 前置 | 词表冻结、来源分层、审核/unknown和整场组约束说明 | 这里只提供词表，不替代真实快照导出、独立分组与泄漏审计；NOT_RUN |
| A-06 | 模型侧可消费的词表 ID/版本及前置门禁 | 实际快照审计与窗口准备由主任务追加，此文件不冒称已完成 |
| S2-04.CTX-01 / S5-03.CTX-01 | 粗细分离、事实与假设分离、手拍/脚部证据不能被态势替代 | 模型和专家质量测试 NOT_RUN；无准确率或召回成绩 |

验证命令为 Windows 隔离 Python 的只读内联标准库脚本（`D:/video/runtime/platform/env/Scripts/python.exe -B -`）；最终实际统计/文件 SHA 由交付回报提供。无需新依赖、端口、运行服务或 D 盘写入。本次新增仅词表 JSON 与本 MD，小于1 MB；实际文件大小由本地验证输出。

复现最小检查可执行：

```powershell
@'
import json, pathlib
p = pathlib.Path("configs/models/taxonomy.v1.json")
t = json.loads(p.read_text(encoding="utf-8"))
nodes = {n["id"]: n for n in t["labels"]}
assert len(nodes) == len(t["labels"])
assert (t["format"], t["taxonomy_id"], t["version"]) == (
    "badminton_taxonomy", "badminton-technique-tactics", "1.0.0")
for n in nodes.values():
    assert n["support_status"] in {"annotation_draft", "unavailable", "experimental"}
    seen = {n["id"]}
    parent = n["parent_id"]
    while parent is not None:
        assert parent in nodes and parent not in seen
        assert nodes[parent]["node_type"] == "group"
        seen.add(parent)
        parent = nodes[parent]["parent_id"]
assert all(not s["negative"] for s in t["annotation_states"])
assert all(m["label_id"] in nodes for m in t["legacy_mappings"])
print({"nodes": len(nodes), "families": len(t["coverage_groups"])})
'@ | & D:/video/runtime/platform/env/Scripts/python.exe -B -
```

这是结构复现，不是产品全链验收脚本或专家签字。
