# Windows heartbeat Win5：共享锁在探针前释放的有界恢复

2026-09-29，关联 `G-02b-wsl-heartbeat-io` / `G-02`。本次限定目标：已成功发布同一次任务心跳后，原子 replace 遇到 Win5，但共享竞争在 DELETE 探针前消失时，允许证明充分的短时恢复；永久权限错误仍 fail closed。不是修改模型参数、GPU 租约或 token/path 验证。

## 真实输入和已有证据

只读生产队列 `D:/video/platform/runtime.sqlite3` 的 `job-d1ef49677c32448b959b0707de189f3f`：seq10 为 `heartbeat.replace.failed / PermissionError / errno=13 / winerror=5 / attempts=1`；seq11 为模型 result=cancelled 但 Windows bridge exit=1，期望130。该 attempt 的 done 记录 `compute_stopped=true / reason=cancel_requested / exit_code=130`。未写数据库、未启动 WSL、模型或 GPU。

这证明新任务实际遇到了 replace Win5，不能证明是哪一个进程短暂持有文件。旧 `job-3757b3d57b2142cd80841a585d9523e0` 缺 errno/winerror，仍保持根因未知；见[原始心跳诊断记录](platform-wsl-heartbeat-sharing.md)。本次失败时旧探针只返回 bool，没有记录探针成功、权限拒绝或路径错误，无法追溯它当时为何返回 false。

## 固定断言与实现范围

`_HeartbeatPublisher` 只存在于已验证 request/attempt 的 `run_windows` 中，保留本实例上一回成功原子发布的路径、文件身份和目录身份。证明不会从请求 JSON 读取；publisher 保留同一份 job/attempt/token。首个心跳和普通 `_atomic_json` 不因此获得 Win5 的宽松重试。

后续 Win5 必须满足以下全部条件：目标为 `bridge-heartbeat.json`；同一直属目录没有 reparse 路径；目标与先前成功写入的普通单链接文件身份一致；源临时文件刚完成 write/flush/fsync，且身份仍相同；源、目标均非只读、非 reparse。然后对源与目标分别用 `CreateFileW(DELETE, FILE_SHARE_READ|WRITE|DELETE, OPEN_EXISTING)` 做非修改探针；两者必须为权限可获或明确32/33共享冲突，任何5/未知错误立即失败。

两次探针均成功只表示此刻 DELETE 可获，**不宣称**这次 Win5 的根因已被确定。仍使用原先从创建临时文件之前开始的 **0.7秒总预算**、10→100ms退避和同一个完整临时文件；持续 Win5 到期失败、保留旧 tick、走既有取消及 compute-stopped 协议。其他 IO 阶段不重试。OS 系统调用自身长期阻塞不受该 Python 截止时间抢占。

安全诊断继续只含 `stage,type,errno,winerror,attempts`；新增 proof mismatch/rejected、DELETE probe allowed/denied。探针成功的 winerror=0，明确区分“当前权限可获”和“确定共享冲突”；日志不输出路径、token或异常全文。

## CPU / Windows 实际结果

命令（只用新 pytest 临时文件）：

```powershell
& D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/platform/test_wsl_heartbeat.py tests/platform/test_wsl_bridge.py -q -p no:cacheprovider --basetemp .test-tmp-heartbeat-win5-final-r3
```

| 断言 / 方法 | 实际结果 | 状态 |
|---|---|---|
| 真实 Windows 读句柄不授 DELETE sharing，使真实 `os.replace` 失败；在捕获异常后、探针前释放读句柄 | OS 实际返回 Win5；两次 DELETE 探针0；下一次替换恢复，旧完整tick→新完整tick，低于0.7秒 | PASS |
| 既有 publisher + 持续注入 Win5，真实 DELETE 权限可获 | 0.7秒预算结束后失败，旧tick不变，无残余tmp；不假报成功 | PASS |
| 同实例的目标被换成同内容新文件、目标只读、临时文件只读、父目录身份改变 | 首次失败，不进入重试 | PASS |
| 真正 Windows ACL 拒绝 DELETE，触发 Win5时探测当前权限 | 对单个新文件及其新pytest目录设置并最终恢复 DACL；真实 DELETE probe=5，单次失败 | PASS |
| 初始 Win5、一般 EACCES、其他IO错误、fsync错误 | 保持原先立即失败行为；只有已确认32/33共享冲突保留原有恢复路径 | PASS |
| 持续故障取消 launcher、done归属、路径及环境隔离 | 既有 CPU 回归通过；不伪造已启动Linux的停机证明 | PASS（夹具范围） |
| 该真实模型 / DrvFS / GPU重跑 | 本子任务未运行，由 models 排期重测；CPU文件竞争不代替真实推理结果 | NOT_RUN |

最终 **60 passed / 1 skipped / 4.44秒**。唯一既有 skip 为显式 opt-in 的 Windows→WSL CPU watchdog 集成，本轮未开启。

测试迭代保留：初版真实 ACL 用例只在文件上 deny DELETE，探针仍成功，首次结果59 passed / 1 failed / 1 skipped。Windows 可通过父目录 DELETE_CHILD 取得删除权限；补为只对专用pytest目录也 deny DELETE_CHILD、且 finally 恢复两份原DACL后，60 passed / 1 skipped。这是测试前提纠正，不是放宽权限断言。

## 依据和下一步

Microsoft 文档说明删除权限可来自文件 DELETE 或父目录 DELETE_CHILD，且只读与未授删除共享的打开句柄会阻止删除/替换：[DeleteFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-deletefilew)、[CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)、[文件访问权限](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)。本机测试确认本次可重现的 Win5 路径，不从文档推断生产失败根因。

安装/环境：未安装任何包；Windows平台既有 Python3.12 venv，测试仅CPU/Win32标准库。媒体、生产队列、原失败证据均未修改，无新增服务/端口。下一次 models 实跑使用本提交；若仍失败，根据新 proof/probe 分类定位，保留失败与取消证据，不无限重试。
