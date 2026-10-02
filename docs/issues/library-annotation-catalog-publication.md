# 标注目录发布边界审查

2026-10-02，library，已修复；真实数据未发生篡改或审计磁盘故障。

独立审查发现并处理：旧目录读取缺少大小上限；registry按SHA唯一索引会误拒合法别名且漏查未使用的坏记录；PTS时距只差1tick时应沿用原probe的unknown判断；去掉archive中间目录可能错误配对同名CSV。现在使用有界读取、完整TrainingRegistry验证及ID/SHA/path关联、原probe状态规则、已审查的flat member结构。

原子发布的提交点为兼容manifest的 `os.replace`。sidecar/源核验/切换前审计或replace失败时旧入口保留；所有不可变sidecar先落盘，所以读者只能看旧完整代或新完整代。

审查另发现：审计completed记录在replace之后生成，如果此时磁盘写入失败，目录已经提交，不能普通报错后声称旧发布没变。实现返回 `published_with_audit_warning` 和原因，保留新完整代、旧不可变代及started记录。调用方运行verify并查明审计写入失败；不能自动删除或回滚已注册的有效代。此情形以临时合成文件做故障注入验证，不冒充真实存储事故。

真实发布、幂等重建和独立核验均无warning，见[交接](../library/ANNOTATION_HANDOFF.md)。进程/电源中断后仍需核对遗留owner锁与容量预留，不自动回收；这是已有存储协议的恢复要求。

## 提交后收尾补充断言（开发前冻结）

主任务在集成版本精确注入复现P2：入口已经replace成功后，锁unlink的PermissionError、quota release的OSError、最终snapshot的PermissionError仍可外溢，CLI误报failed/exit2。原修复只包住publication_audit退出，范围不够。此补修不修改已发布目录内容、不重扫原媒体，不重跑已完成全套。

隶属A-02.library-publication：分别注入上述三类故障，预期新完整代及旧不可变代均保留；返回明确已发布的warning而非failed，`entry_committed=true`。锁/预留清理失败保留其真实状态和可定位的lock_path/reservation_id；容量未知返回null，不伪造0。同次多项故障需分别记录，不能互相遮蔽；已经相同的目录重跑发生收尾故障应报告unchanged加warning。提交点之前失败仍按失败处理且不替换入口。开发前为NOT_RUN，实测结果如下。

实际旧版复现：3项测试均ERROR，0.672秒；分别为lock unlink PermissionError、quota release OSError及最终snapshot PermissionError外溢。修复将提交状态与收尾分离，分别保护audit/lock/quota的context退出，并独立记录最终容量读取错误；多个故障逐一进入cleanup_issues，保留首个body异常。入口write helper在replace后、temp清理前立即标记提交；若文件系统包装器replace完成后才报错，则通过有界目标字节比较确认提交，不假定失败意味着未提交。

实际修复验证：相关目录测试 **33/33 PASS、0skip、6.619秒**，包含10个新增用例。三类故障分别覆盖新发布与unchanged，另验证锁与预留同时失败、CLI exit0/stdout明确warning、replace完成后包装器报错、入口temp清理报错。临时文件的旧代字节/mtime不变、新代verify通过；锁/预留失败保留真实残留状态，capacity无法读取时为null。证据见[定向回归收据](../library/ANNOTATION_CATALOG_CLEANUP_TESTS.json)。未重扫真实视频、未运行全库、未写D:/video；原209项全库结果仅作为修复前历史基线。
