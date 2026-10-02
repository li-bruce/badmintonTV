# 训练工作台合同（2026-10-02）

实现位于 `packages/contracts/training.py`，独立于制作 `Event`、`EventManifest`、`Timeline`，不改变其字段。所有新合同 `schema_version` 为 `1.0`；训练 bundle、taxonomy、snapshot 有各自明确 `format`。JSON 数组在 Python 内为 tuple，嵌套 JSON 元数据也禁止原地修改；`model_dump(mode="json")` 返回可序列化副本。

## 接入 API

```python
from packages.contracts.training import (
    TrainingProject, TrainingAssetRef, TrainingAnnotationBundle,
    TrainingBundleUpdate, TrainingTaxonomy, TrainingSnapshot,
    get_default_training_taxonomy, validate_training_bundle,
    next_bundle_revision, build_training_snapshot,
)

validated = validate_training_bundle(bundle, taxonomy)
saved = next_bundle_revision(current_or_none, validated, expected_revision,
                             actor_type="agent", reviewer="server actor")
snapshot = build_training_snapshot(
    snapshot_id="snapshot-id", project=project, taxonomy=taxonomy,
    assets=asset_refs, bundles=bundles,
    splits=[{"group_id": "trusted-group", "split": "train"}],
    created_at=creation_time,
)
```

`expected_revision=0` 创建首版，持久 bundle 从 revision 1 开始。服务端须在同一个事务里验证 CAS、保存前版并保存返回值。接口空白编辑草稿可有 revision 0，但进入此持久合同前须规范化。Helper 自动计算记录 revision/previous_revision，不能信任客户端申报的递增值。删除保留 tombstone，仍被引用的已删除对象会被关系校验拒绝。

只有服务端认证配置可以决定 `actor_type`；HTTP 提交的 reviewer 字段不是身份依据。默认 actor 为 agent。非 human 不得新增或修改 confirmed 人物身份，不得新写 human 审核或 human 来源点位；原样保留既有人工值允许。修改记录内容或它引用的人物信息（包含四种 state 角色和 judgement 主体）一律清旧审核为 pending，清 reviewer/type/time，包括 human 自己修改。后续仅审核字段的单独保存才可重新 confirmed，审核人和时间由 helper 写入。revision_audit 保留本次服务端 actor，与审核状态分开。

## 字段和验证边界

- Project 保存 catalog_version、taxonomy_id/version、asset_ids 与用途。AssetRef 保存原片 sha256/path/size/duration、PTS 引用、match/group 与 group_status；增加 root_asset_ids、source_sha256s、recording_session_id、source_group_ids 保留可追溯同源关系。用途固定 training_only，source_usage_scope 保留来源用途。注册目录、实际字节 SHA、PTS 文件内容及可信分组的核验由服务端完成，Pydantic 只验证合同和关系。
- Bundle 为每 project+asset 一个原子对象，people、records 整体提交。人物 identity_status 为 unknown/unconfirmed/confirmed，队伍可空。人物/记录 ID 必须唯一，记录的 project/asset 必须一致。
- contact/dead_ball/state 使用原片 at_ms；rally/segment 使用半开 start_ms/end_ms。数值为严格整数毫秒；区间有序、不得越过媒体或所引用回合。contact/state 不可在媒体结束处；独立 dead_ball 可在媒体结束处，关联 rally.dead_ball_id 必须指向其自身回合结束时间的死球。缺死球可保存审核草稿，但快照质量报告明确阻塞。
- 一个 record 可包含多个 judgement，值分别为 present/absent/unknown/not_applicable/unlabeled/unobservable。unknown/unobservable 必须有原因，不能被转成 absent。subject_role 默认为 self，可为 opponent/partner/opponent_partner；subject_person_id 可选。唯一键为 label+role+person，引用人物和对应 state role 须一致。raw_labels、source_label、mapping_status 保留粗标签来源，不通过粗类映射确认细手法。
- state 的 self/opponent/partner/opponent_partner 独立；引用人物须存在，同队/异队及 self 身份须一致。位置明确 image_normalized 或 court_m，前者在 [0,1]，后者必须声明 calibration_id；服务端另核验实际校准依据，合同不能凭 ID 证明校准存在。本轮平台尚无可信校准注册，平台 API 可以更严格地拒绝 court_m。
- Taxonomy 保留层级、dimension、kinds、定义及 provisional/defined 状态。`selectable=False` 的 group 只作目录，不允许选成 judgement。校验拒绝未知标签、错误 kind、缺失父节点和环。项目须冻结整个 taxonomy，不能同版本静默换词表。

`get_default_training_taxonomy()` 返回明确 provisional 的 UI 占位词表，不是专家定义。models 可提供同格式替换词表，原始文件及适配信息由 provenance 保留；未审定语义仍为 provisional。

Judgement 唯一性在解析继承主体后再次检查：同一记录中，`subject_person_id: null` 若继承 record.person_id 或 state 对应角色，与显式填写同一人物是同一个主体，不能对相同 label 同时提交 present/absent 或重复值。不同角色/人物的同名标签保留独立判断；此为跨字段校验，schema 字段不变。

## 快照与训练视图

快照保存项目、完整 taxonomy、AssetRef、完整 bundle 和记录 revision 的实际值，而不只是引用 ID。创建后不可原地修改；重新读取验证 `content_sha256`。Hash 为全部规范化 JSON 字段（排除 content_sha256 自身）的 UTF-8 SHA256，键排序、紧凑分隔符、禁止 NaN。created_at 也是内容的一部分，重复读取必须使用保存的值。

训练视图由冻结内容重新推导，拒绝客户端伪造的 view/quality_summary，即使它重算了 hash。默认只纳入 human confirmed、词表已 reviewed 且 label 已 defined、语义映射为 manual/exact、值为 present/absent 的 judgement；需要人物的标签还要求其主体人物 identity confirmed。正负值都要求 visibility clear/partial 及可识别的 evidence；后者至少含非空 reference/ref/relative_path/source/evidence_id 或非负整数 at_ms/source_frame_index。absent 另需非空且不是 unknown/不明等的解释。这里只验证证据引用结构，证据真实性和专家判断仍由可信服务及审核负责。其它 judgement 连同原因留在 exclusions，导出例和排除项都保留主体。Agent confirmed 仍不是人工真值。

Split 按 group_id 指定 train/validation/test/unassigned；未知或未确认 group 不可分配，asset_id 本身不能冒充独立比赛组。相同原 SHA、source_sha256s、match、root_asset_ids、录制 session、source_group_ids 的连接边均不可跨 split，因此其连通分量不可分到多个 split。缺失 match_id、未确认 group 或缺可信分组证据，均保留草稿但阻塞 trainable；本版不只凭 session 推定独立比赛。分组证据采用可信 AssetRef.provenance.group_evidence：`{"verified": true, "source": "目录来源", "reference": "可回查分组依据"}`，字段须非空，服务端不得允许客户端自行提升此证据。未分组和缺回合终点也以质量阻塞呈现。合同不验证不存在的专家知识或外部被抹去的来源信息。

## Schema、fixture 和验证

```powershell
& 'D:/video/runtime/platform/env/Scripts/python.exe' -m packages.contracts --training --output packages/contracts/schemas
& 'D:/video/runtime/platform/env/Scripts/python.exe' -m pytest tests/contracts -q
```

`--training` 只导出 6 个新顶层 schema；默认命令仍导出旧合同。跨对象关系、时间边界、审核权限和推导 hash 须运行 Python 验证，不能只靠 JSON Schema。

四个 `training.*.v1.json` fixture 明示 synthetic：含回合、两次触球、独立死球、动作区间、双方状态、多标签及 unknown。人物 confirmed 仅为合成合同角色，记录为 agent 待审核，快照训练视图为空；没有真实原片、人工运动真值或模型推理结果。

本文件的自动测试覆盖 A-01 及 A-04/A-05 的合同部分：边界/关系、旧合同兼容、审核重置与 CAS、unknown、taxonomy group 禁选、split/lineage 泄漏、主体及双打角色、证据排除、快照冻结和 hash。2026-10-02 初版实际运行上面全合同命令：**258 passed in 1.63s**，其中训练测试 72 项。随后修复隐式/显式同主体重复，单独运行 `tests/contracts/test_training.py`：**75 passed in 0.36s**，schema 字段未改变。无 GPU、原片复制或真实专家标注。A-02/A-03/A-06/A-07/A-08/A-09/A-10 的真实目录、浏览器、WSL和产品集成不由这些合成测试替代。
