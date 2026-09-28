# Label Studio 后续编辑回写409

状态：已修复并回归。2026-09-29。

触发：首次导入新LS区域后，在LS修改该区域再次导出；旧实现仍使用初次seed的expected_revision（新区域为0），与已经入库的revision1冲突。seed事件也一直使用导出时旧revision。简单改成取平台最新revision会静默覆盖随后做过的平台人工修改，不能采用。

修复：`Store.import_label_studio`持久保存snapshot/asset/task/annotation同步记录，只用上次由LS成功导入写出的event revision做CAS；事件、轨迹和同步记录同事务提交。保留全部已接收annotation哈希，旧快照重放完全不写；未见过但updated_at不递增的快照拒绝。平台人工修订或confirmed事件不允许LS隐式覆盖。同一snapshot的旧数据库按每个event/哈希最早历史revision恢复导入基线，避免将后续同hash的人工审计误当同步。没有snapshot的早期导出明确409重新导出，参见[不可变快照修复](platform-labelstudio-snapshot.md)。

回归：新区域与seed的首次→修改后第二次成功；已接收旧快照重放不回退Event或框；未接收旧时间戳409；平台后续unreviewed/confirmed修改409；首次导入也不覆盖confirmed seed；多region中一个冲突使先前事件更新、轨迹与游标全部回滚；旧DB人工审计后仍冲突。

剩余操作约束：内容变化必须携带真实、带时区、递增的LS updated_at。没有该字段的初始简化JSON只能首导和原样重放，不能作为可排序的新快照。冲突需要用户在平台/LS明确协调后重新建立工作任务，不自动重置同步游标。
