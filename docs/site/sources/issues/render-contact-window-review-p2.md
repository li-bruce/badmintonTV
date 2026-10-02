# 触球窗口复核 P2

2026-10-03，A-07。主任务在首次交付后发现四处边界缺口；本页保留失败事实，不沿用旧PASS覆盖新增断言。

1. 同回合contact@1500、唯一serve@3500、dead@8500曾返回ready `[3500,8500)`，既漏前一拍又漏冲突修订引用。目标是candidate/null并保留全部冲突；同刻及闭合不确定区间相交也不能证明发球首拍。
2. 同一证据`at_ms=8500,time_ms=1500`无PTS时只取time_ms，cutoff2500仍能生成窗口。目标是拒绝矛盾别名/点区间，兼容一致时间及完整证据时间上界。
3. 公共快照的冻结PTS引用未绑定SourceClock引用，替换索引仍能mapped。目标是校验冻结索引身份与实际clock元数据，矛盾或缺证明拒绝。
4. 未归属contact@3000带8500ms证据被晚加入candidate与refs，但latest仍5000。目标是引用与证据的完整时间闭包；无法定位证据仍明确unknown，不写零等待。

修复/验证状态：四项均已修复，规则与adapter升1.0.1。独立回归先复现发球首拍9个subtest失败；新增16项后触球测试76项/174子例PASS，完整render+contracts为502 passed、1旧权限skipped、583 subtests passed。既有真实源、网页快照和18项隔离负例在北京时间00:35只读复验PASS。无GPU、媒体进程或D盘写入。最终结果与提交见`docs/status/render.md`和`docs/render/CONTACT_WINDOWS_VALIDATION.md`。
