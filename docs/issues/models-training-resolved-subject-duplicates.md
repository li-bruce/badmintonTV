# 公共快照：解析后的同标签同人重复判定

日期2026-10-02。关联A-04/A-05，发现于01冻结合同`6fec08f`（本分支对应`6f851bb`）。状态：已修复；01公共修复`2128568`已由主任务协调集成并同步本分支为`1d75b3c`，models没有自行修改合同。

## 输入与实际结果

一个record属于已确认人物p；同一label有两条self judgement，一条省略subject_person_id，另一条显式填写p。原始(label,role,person)元组不同，公共bundle校验可以接受；推导public training_view时，两条都解析成相同(label,self,p)，甚至可一条present、一条absent。

这不是实际视频或人工真值问题，复现使用明确合成的合同数据。对应CPU回归见`tests/models/test_training_readiness.py`中的resolved duplicate用例。

## 消费端行为与关闭条件

`training_readiness.audit_snapshot`按解析后的人物+角色+label建键，保留原记录并为冲突项附`duplicate_resolved_judgement`，不会把其中任一条当成严格监督，也不会因字典覆盖只留下后者。省略人物但正常唯一的四角色条目仍可按公共规则解析；不会把对手标签合并到本人。

公共修复现在于bundle解析角色人物后再次校验唯一性，直接拒绝同一解析键的重复判定；保留不同角色/不同人物同名标签的合法多标签场景。models回归更新为公共合同拒绝该输入，内部重复键守卫继续保留。共享schema本身不能替代该跨字段语义校验。无需重建原片或PTS。
