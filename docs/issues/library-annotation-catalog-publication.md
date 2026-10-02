# 标注目录发布边界审查

2026-10-02，library，已修复；真实数据未发生篡改或审计磁盘故障。

独立审查发现并处理：旧目录读取缺少大小上限；registry按SHA唯一索引会误拒合法别名且漏查未使用的坏记录；PTS时距只差1tick时应沿用原probe的unknown判断；去掉archive中间目录可能错误配对同名CSV。现在使用有界读取、完整TrainingRegistry验证及ID/SHA/path关联、原probe状态规则、已审查的flat member结构。

原子发布的提交点为兼容manifest的 `os.replace`。sidecar/源核验/切换前审计或replace失败时旧入口保留；所有不可变sidecar先落盘，所以读者只能看旧完整代或新完整代。

审查另发现：审计completed记录在replace之后生成，如果此时磁盘写入失败，目录已经提交，不能普通报错后声称旧发布没变。实现返回 `published_with_audit_warning` 和原因，保留新完整代、旧不可变代及started记录。调用方运行verify并查明审计写入失败；不能自动删除或回滚已注册的有效代。此情形以临时合成文件做故障注入验证，不冒充真实存储事故。

真实发布、幂等重建和独立核验均无warning，见[交接](../library/ANNOTATION_HANDOFF.md)。进程/电源中断后仍需核对遗留owner锁与容量预留，不自动回收；这是已有存储协议的恢复要求。
