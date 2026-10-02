# 旧Label Studio任务借用新导出seed覆盖本地修改

状态：已修复，2026-09-29。

复现：平台seed为revision1时生成LS任务；平台随后本地修改到revision2（仍unreviewed）；再次为同一asset生成LS任务；旧实现用`ls_task[asset_id]`保存最新任务，导入旧导出时却拿到新seed revision2，因此CAS通过并覆盖本地修改。若只加独立snapshot却不隔离同步游标，新snapshot的成功导入也可能提升旧snapshot同task/annotation的基线。

修复：每次生成任务都分配`data.btv.snapshot_id`，使用`ls_task_snapshot`只INSERT保存seed/PTS。导入仅使用指定ID的可信快照并校验asset，绝不取最新by-asset seed。同步游标同时包含snapshot_id，Event/track provenance保留ID。快照缺失、ID未知或素材不匹配返回409重新导出；早期无snapshot任务不自动绑定到当前任务。旧DB同步恢复只接受同一snapshot历史。

回归已通过：原复现导入返回409且本地revision2不变；即使新snapshot已导入revision3，再导入更晚updated_at的旧snapshot仍409；第二次导出不同PTS映射后旧任务仍使用自己的映射；重复snapshot INSERT拒绝并保持原内容；缺失/空/未知ID和不同asset快照均拒绝。测试命令及49项通过结果见[集成说明](../platform/LABEL_STUDIO.md)。
