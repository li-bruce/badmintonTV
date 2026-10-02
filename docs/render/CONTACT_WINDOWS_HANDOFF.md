# 触球窗口交接（04 → 01 / 03）

2026-10-02，基线 main `3dab169`。此文件先冻结 A-07 / A-08 断言后实现；公共训练合同由 01 持有。以下 API 已实现，正式合同兼容和真实 PTS 验证见 [验收记录](CONTACT_WINDOWS_VALIDATION.md)，不把工程范围验证当人工动作真值。

## 调用与边界

```python
from packages.render.contact_windows import derive_contact_windows, SourceClock
result = derive_contact_windows(asset, records, project_id="project-01",
    vocabulary_version="v1", rules=None, clock=None, available_until_ms=None)
```

函数只做逻辑派生，不读视频、不切片、不编码、不生成 Timeline。输出 format=`badmintonTV.training-contact-windows`、schema_version=`1.0`、usage_scope=`training_only`、production_eligible=false；即使 general 原片明确供训练使用，训练窗口也不能反向成为制作工程。原 render API/CLI 和 general 素材制作路径保持兼容。

CLI：`python -B -m packages.render.contact_windows --request <json> --storage-root D:/video`。输入为 `{asset,records,project_id,vocabulary_version,rules?}`；读取 canonical Asset 与其 `probe.pts_index`，核对实际源 SHA / 大小、PTS 索引 SHA / 帧数 / 递增顺序，并保留 registry 用途判定；成功结果 JSON 写 stdout，错误 JSON 写 stderr，退出 2。无媒体进程、文件写入或容量预留；调用方若持久化 stdout，须遵守自己 owner 的配额和不可覆盖规则。

可直接运行的技术示例（不是专家标注）：

```powershell
& 'D:/video/runtime/platform/env/Scripts/python.exe' -B -m packages.render.contact_windows --request configs/render/contact-windows.example.json --storage-root D:/video
```

源是现有 b210dc39…训练 Asset；示例只包含元数据和明确 agent 技术 marks，没有媒体。API 的 `derive_contact_windows` 为纯逻辑入口，不执行文件真实性验证；生产服务应复用自己的可信源注册/PTS证明，或调用 `derive_verified_request(request, storage_root)` 的只读适配器。两者都只生成训练窗口。

## 模块内 records 形状

01 可在自己的服务中把公共合同映射成以下记录，避免在两个 worktree 改公共接口。记录需是当前修订的视图；同一个 record_id 出现两次直接拒绝，不自动选版本。

所有记录：`record_id`、正整数 `revision`、`asset_id`、`rally_id`、`kind`，可附 `player_id`、`team_id`、任意 JSON `labels`、`visibility`、`unknown_reason`、`review_status`、`provenance` 等原始审阅信息，按输入保留，不提升审核状态。

`evidence` 如存在必须为对象数组；每条同源证据给 `start_ms/end_ms` 或 `time_ms`。非时间证据须另给明确 `latest_evidence_ms`，不能假定标签只看了触球时刻。点可显式给 `phase_not_applicable: ["landing"]` 等阶段不适用；不与同阶段区间并存，不根据“没标落地”自动推断不适用。

规则 `contact-windows/1.0.1` 起，证据同时给`at_ms/time_ms`时必须相等；区间须成对提供`start_ms/end_ms`且为非空半开范围，混合点/区间必须包含该点（末端不包含）。所有声明的证据时间均计入水印，冲突不会用字段优先级掩盖。含`at_ms`的image_region等附加JSON原样保留，本工具不执行ROI裁剪。

| kind | 时间/关联字段 | 规则 |
|---|---|---|
| rally | `start_ms`, `end_ms`（可 null） | record_id = rally_id；半开范围，互不重叠。end 未知不会自动取最后触球 |
| contact / serve / dead_ball | `time_ms`；可选 `uncertainty: {start_ms,end_ms}`、`source_pts` | uncertainty 是闭合的不确定包络，必须包含 nominal time；serve 同时作为第一拍触球；dead_ball 可以等于 rally.end_ms / 媒体结束 |
| movement | `start_ms`, `end_ms`, `anchor_id`, `phase`, `player_id` | 半开阶段区间；anchor_id 引用同回合同球员 contact/serve。phase 使用 preparation/initiation/arrival/stroke_support/landing/recovery 或 unknown |

不接受跨资产、回合、球员的动作关联，不按列表相邻行推断同人；点和区间不能互换，非法/越界输入整批拒绝。没有可知回合终点时，上下文策略给明确 unavailable；球路可使用同回合下一次触球。下一回合的触球永远不能补当前回合终点。

## 输出 windows 与策略

每个 contact/serve 生成 `ball_flight`、`hand_technique`、`footwork`；每个 rally 另生成一个 `rally`。每项含 `window_id`、`strategy`、`anchor_id`、`rally_id`、`player_id`、`status`（ready / candidate / unavailable / pending）、`range`（`{start_ms,end_ms}` 或 null）、`reasons`、`annotation_refs`（ID+revision）、`source`、`labels`、规则版本、源 PTS 映射和未来信息说明。manifest 保留全量输入记录、源 Asset 身份/用途/许可和规则参数及内容 hash，未提供 PTS 时明确 not_provided。

| 策略 | 预期行为 |
|---|---|
| ball_flight | 当前触球到时间最早的下一触球/死球，不过滤对手/搭档；缺两者 unavailable。同刻多触球/不确定包络重叠 candidate，不宣称唯一精确下一拍 |
| hand_technique | 默认触球前 500ms、后 500ms；按不确定包络扩展，裁到当前回合/媒体。裁短或不确定均 candidate |
| footwork | 同人同锚点已标阶段的完整包络；缺 preparation/initiation/arrival/stroke_support/landing/recovery 任一适用阶段为 candidate。倒序、重复冲突、不可见也 candidate。没有阶段时给显式 ±2000ms 保守候选，不伪造阶段 |
| rally | 必须同时有唯一 serve 和 dead_ball，且serve的不确定包络严格早于每个其他触球包络；从发球到死球，默认审阅余量 0。缺项 unavailable；发球前已有触球、同刻或包络相交时candidate且range=null，完整保留冲突refs。不能把第一/最后一次普通 contact 当作发球/死球 |

rules 可设置 `hand_before_ms/hand_after_ms`、`footwork_before_ms/footwork_after_ms`、`rally_before_ms/rally_after_ms`（0–10000ms），规则版本固定由代码维护。窗口不改变原 mark 时间；半开范围内的源帧用真实整数 PTS + time_base + origin_pts 二分查找，不用 frame/fps。SourceClock 接受 `pts`、`time_base`、`origin_pts`（默认首 PTS）、`reference`，PTS 严格递增；非零起始 PTS 和 VFR 保留。

已声明死球还会限制手法/步法上下文，即使外层 rally.end_ms 更晚也不越过死球包络；裁短保留 candidate 原因。多个死球或时间包络竞争的下一拍都不能声称唯一精确终点，参与判断的修订全部进入 refs。CLI 必须有 complete=true、绑定源 hash/大小的 PTS 元数据，并使用 probe.start_pts 原点；不能以不完整索引第一帧重新归零。

毫秒区间不偷偷吸附到帧：输出 `anchor_source_pts` 和 `anchor_time_rounding_delta_ms`，小于 1ms 的整数化若导致锚点帧落在范围外，明确降为 candidate / `anchor_pts_outside_millisecond_range`。`pts` 只声称对给定毫秒半开范围的真实源帧映射，不把整数毫秒变成无误差的触球帧真值。

`available_until_ms` 指离线证据可见截止点，用于模拟在线消费。记录和其引用证据尚不可见时不派生；需要未来终点或上下文时返回 pending、range=null、明确等待/缺终点原因，不向消费方泄漏未来范围。`wait_ms=null` 表示无法知道未来终点还需等多久，不能写成零等待。离线输出同时给出 `future_context_used`、`latest_source_time_ms` 和相对锚点的 `lookahead_ms`。本工具不是实时识别器。

## 01 公共训练合同接入

模块 `packages.render.training_window_adapter` 提供 `derive_training_bundle(asset, bundle, vocabulary_version=..., serve_mark_refs=..., phase_bindings=..., clock=...)` 和 `derive_training_snapshot(asset, snapshot, serve_mark_refs=..., phase_bindings=..., clock=...)`。公共合同按 01 新 `TrainingAnnotationBundle/TrainingSnapshot` 校验；未安装时明确 `training_contract_unavailable`。正式适配基线为合同 `6fec08f` + 主体判重修复 `2128568`（本分支等价 `177a8e9` / `055c42a`），根任务已有，不重复集成依赖。

- 点 `at_ms` → `time_ms`；uncertainty_start_ms/end_ms → envelope；person_id → player_id；judgements 全对象保留，不把 coarse/unverified 改成细标签。
- rally record_id 作为 rally_id，独立 dead_ball 点保留。没有独立 serve kind，因此必须显式提供 `serve_mark_refs=[{record_id,revision}]`，不能自动取首 contact。这个版本不猜词表 label ID。
- footwork segment 须显式提供 `phase_bindings=[{record_id,revision,anchor_id,anchor_revision,phase}]`；同回合/同人关联由核心复验。不做未标阶段的推断。映射由调用方纳入不可变项目/快照设置，产物完整保存映射和版本/hash。
- state、未绑定的 segment、未分回合、deleted/rejected 记录不当作边界，列出排除原因并保留原 bundle；已拒绝的回合也不提供边界。原 bundle/revision/hash、标签/审核来源、快照ID/hash/词表/项目修订与质量摘要均可回查。
- 未分回合的触球/死球如果落在窗口内，不自动归属，也不能忽略后把更远终点称为精确下一拍：窗口为 candidate，保留 `unresolved_boundary_refs`。bundle 修订变化会重算窗口ID，防复用旧 ready 结果。
- adapter `training-window-adapter/1.0.1` 对冻结`asset.pts_reference`与`clock.reference`的已声明索引身份逐项核对，并检查实际clock帧数/时基；已有冻结引用却无clock来源证明或存在矛盾时拒绝，不能替换索引仍声称mapped。无clock仍明确not_provided；纯内存clock的内容真实性仍须由调用方可信加载器负责。
- 晚加入refs的未归属冲突记录也按同样规则核验时间/PTS证据，更新`latest_source_time_ms`、`lookahead_ms`和`future_context_used`。无时间证据保持unknown并按源时长保守计入，不默认为零未来信息。
- 规范证据 `at_ms`、source_frame_index/frame_index、source_pts 均核验，混用且矛盾即拒绝。仅有外部引用而无时间时，离线 adapter 标记 evidence_time_unresolved、按源时长保守记证据上界；不宣称零未来信息。四种主体的 judgements 保留为完整列表，不能按 label_id 合并不同角色。
- adapter 为离线审阅窗口消费口，不生成新的 training_view 或放宽原快照 eligibility；即使 ready，也只表示该逻辑范围的边界完整。训练/标注权限仍由 01 服务和公共合同控制。

## 冻结验收断言

| ID | 输入/验证 | 预期 | 当前 |
|---|---|---|---|
| A-07 | 精确、不确定、越界、缺终点、对手插拍、四人交替、阶段缺失等逻辑夹具 | 四策略不同，半开且不跨回合；关联/版本/标签/unknown/用途不丢；错误和保守候选明确 | PASS（工程范围） |
| A-07 | 现有真实 training Asset 和完整 PTS，技术 agent marks | 实际 hash/PTS 可核、范围逐帧在界内，原片只读；不把技术 marks 称触球/技法真值 | PASS（真实时间映射，不含动作真值） |
| A-08（04部分） | 训练窗口、真实训练源及其来源引用进入 render；旧 general 回归 | 训练窗口不能充当 Timeline，训练源始终拒绝且零媒体启动；general 正常路径回归通过 | PASS（render 边界和旧逻辑；全链由 root 验收） |

01 的制作导入/候选/Timeline API 和 root 的真实浏览器链单独验收；本模块测试不替代 A-08 全链 PASS、专家标注或模型识别准确率。
