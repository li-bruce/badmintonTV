# A-14 区域证据合同（2026-10-03）

新增 `TrainingImageRegion` 与 `TrainingImagePoint`，从 `packages.contracts.training` 导入。区域仍保存在 `record.evidence` 的原始 JSON 字典里，仅 `type == "image_region"` 触发新校验；旧其它 evidence 不改写，也不套用新字段限制。未给旧 Project、AssetRef、Record、Bundle 或 Snapshot 增加默认字段，旧六份 schema 不变。

## 字段协议

```json
{
  "type": "image_region",
  "schema_version": "1.0",
  "evidence_id": "region-example",
  "record_id": "contact-example",
  "asset_id": "asset-example",
  "at_ms": 62000,
  "coordinate_system": "image_normalized",
  "shape": "rectangle",
  "points": [{"x": 0.2, "y": 0.3}, {"x": 0.6, "y": 0.8}],
  "subject_role": "self",
  "subject_person_id": null,
  "observation_source": "agent",
  "precision": "browser_time"
}
```

除 `subject_person_id` 可省略或为 null 外，其余字段必须显式提供；多余字段拒绝。主体角色为 self/opponent/partner/opponent_partner，来源为 agent/human/model。`precision` 本轮固定 browser_time，不能加 exact_frame、source_frame_index 或米制标定字段来声称精确帧/真实场地坐标。

- 坐标为有限数值且在 [0,1]，拒绝布尔值、字符串、NaN、无穷。它们相对实际视频内容矩形，排除黑边；CSS 缩放/黑边的换算由前端实现和真实浏览器验收，合同无法验证像素来自何处。
- rectangle 恰有两个对角点，可按任意方向画，宽高都非零。polygon 为 3–64 顶点，不重复首点闭合；拒绝重复顶点、零面积、非相邻边相交/接触、相邻边折返重叠。顺/逆时针和不自交凹多边形允许。几何谓词使用输入浮点值的精确有理数表达，避免以容差放过近共线交叉。
- evidence_id 在同一记录的区域证据中唯一。record_id/asset_id 必须与包含它的记录一致。点记录 at_ms 必须完全相同，不得移动 contact 来迁就截图时间；区间要求 start_ms ≤ at_ms < end_ms；截图时间须严格小于媒体 duration，结束处 dead_ball 也没有不存在的末帧。
- 人物必须属于该 bundle。统一合并 record.person/team 的 self fallback、四个 state role、judgement 与区域显式主体；每角色最多一个已知人物/队伍，同人物不得占多个角色。非 self 角色须有对应 state role，显式人物须与已有主体一致；人物未知时也不能绕过已知队伍关系。己方搭档同队、对手及其搭档同队、已知两侧队伍不同。省略或 null 主体继承解析后的角色，保存时不填入默认值。

## 来源、修订和冻结

`next_bundle_revision` 仍使用服务端可信 actor。非 human 不得新增或修改 `observation_source="human"` 的区域；同一 record/evidence_id 的旧 human 字典及解析后的角色/人物/队伍均不变，才允许保留。省略主体继承 record/state 时，改父记录人物、角色或所属队伍同样属于改写，不能借 pending 审核状态免检。前端所传来源不是授权，独立模型导入也不能借 JSON 冒充人工。Human 来源本身不等于已确认技法。

删除旧 human ROI 允许，仍清除记录审核；Agent 调整旧 ROI 时显式降为 agent 来源也允许。同样的解析后主体保护用于旧 state.position.source=human，不能仅保留点坐标字典而给它换人或换队伍；改为 agent 来源可正常保存待审核。

新增、调整或删除 ROI 属于记录内容修改，递增修订并把旧审核清为 pending；区域引用人物的变化也触发审核失效。区域不是跟踪轨迹，不向其它时间自动传播。默认训练视图的词表、人工审核、可见性、主体、证据及分组门禁原样保留，不因画了区域自动升级。

`TrainingImageRegion.model_validate(evidence)` 提供独立几何验证；完整记录绑定须验证 TrainingAnnotationBundle。原 evidence 字典会被校验但不会用新模型的 dump 替换，避免省略字段被补齐而改变旧快照。独立 schema 为 `packages/contracts/schemas/TrainingImageRegion.schema.json`；旧 `training_schemas()` 的六种顶层合同及默认 CLI 导出集合保持不变。

## 验证范围和结果

```powershell
& 'D:/video/runtime/platform/env/Scripts/python.exe' -m pytest tests/contracts -q
```

新增 `tests/contracts/test_training_regions.py` 验证几何、时间/人物/队伍/ID、来源权限、删除清审核、新快照保真、旧 schema 与旧 snapshot 不变。所有区域都是合成合同数据，没有 GPU、原片复制、媒体解码或专家真值。

真实旧快照只读输入：`D:/video/platform/integration-20261002/snapshot-before-restart.json`。实测 `TrainingSnapshot.model_dump(mode="json")` 与原 JSON 对象逐字段相等，重算内容 SHA256 仍为 `d2deb51291cbb8ad5ac100e7a95d60afb6670e8c3762f05304daee77410a67dd`。没有改写输入文件；该条件测试在缺少本机证据文件的环境会明确 skip，本次实际文件存在并通过。

截至本次最终全合同运行：331 passed in 1.80s，无 skip；其中新增区域及角色回归 70 项。这只关闭 A-14 的平台合同子范围；A-11/12 时间线拖拽、A-13 真实视频区域交互、A-14 的 models/render 实际消费仍由对应 owner 验收，不用此测试数替代。
