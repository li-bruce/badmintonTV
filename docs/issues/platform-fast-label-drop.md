# 快速拖入已有时间线记录时标签未投放

2026-10-03；关联训练工作台 A11。状态：**已修复，定向真实复测 PASS**。修复提交：`8ba5cc2`。

首次真实浏览器验收中，标签拖入空轨道成功创建区间，点击回退操作也能追加标签；同一标签原生拖入已有记录块连续无变化且无错误。1366×768 视口下，主任务确认源标签与目标块坐标，临时记录原生事件：`dragstart → dragenter(lane) → dragenter(record) → dragenter(lane)`，约 11–16 ms 内完成几步移动，最后才进入记录块；没有目标块 `dragover`，也没有 `drop`。这次快速进入并释放的事件序列未经过原来仅在 `dragover` 上设置的接受逻辑。

修复使空轨道和已有记录的 `dragenter`、`dragover` 共用接受函数：仅对 `application/x-btv-label` 调用 `preventDefault()`、`stopPropagation()` 并设置 `dropEffect='copy'`。实际 `drop` 仍检查当前 taxonomy 中的可选标签和目标记录，不放宽标签或主体约束。临时 `BTV_DIAG` 控制台诊断已从时间线及标签拖动入口移除。

验证结果：

| 方法 / 输入 | 实际结果 | 状态 |
|---|---|---|
| 新增已有记录、空轨道两组 `dragenter → drop`（中间无 `dragover`）事件回归；同时验证 `text/plain` 不被接受 | 旧实现 18 PASS / 2 FAIL；修复后时间线测试 **20/20 PASS** | PASS（事件夹具） |
| 主任务真实 CUA 原生拖动标签中心 `(132,480)` 到已有记录；标签、角色、人物已存在 | 显示“同一标签、角色和人物已存在，保留原判断”，正确进入去重路径 | PASS（真实浏览器） |
| 主任务切换为对手及远端人物后再次原生拖入已有记录 | 新增第 3 项 judgement | PASS（真实浏览器） |

单位测试命令：`node --preserve-symlinks --preserve-symlinks-main --test tests/platform/training_timeline.test.cjs`。真实浏览器操作、事件诊断及复测由主任务执行并记录，本文件依据其回执，不将事件夹具当成浏览器实测；目前未提供独立截图文件名。未进行跨浏览器兼容性验收。
