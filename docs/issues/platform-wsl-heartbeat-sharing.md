# Windows 心跳原子发布失败：有界共享冲突重试与安全诊断

2026-09-29，关联G-02运行时稳定性；本次子用例 `G-02b-wsl-heartbeat-io`。**CPU与本机Windows回归PASS**；失败模型的真实WSL/DrvFS或GPU重跑 **NOT_RUN**。修复不宣称已确认旧故障根因，也不把CPU夹具成功当模型推理成功。

## 真实失败证据（只读）

任务 `job-3757b3d57b2142cd80841a585d9523e0` / `attempt-1` 位于 `D:/video/platform/jobs/`。读取了heartbeat/cancel/started/done/result；诊断时省略token。heartbeat停在tick=1，`updated_at=1790673560.0205624`；Linux guardian/model分别为160072/160073，started_at=1790673560.0929508。随后Windows写入匹配job/attempt的取消记录；done报告 `compute_stopped=true,reason=cancel_requested,exit_code=130,finished_at=1790673560.7064176`，模型result为cancelled。

生产队列 `D:/video/platform/runtime.sqlite3` 以SQLite `mode=ro`查询seq18–20：只记录了旧 `run_windows` 抛出的 `RuntimeError: bridge could not maintain its heartbeat` 及堆栈位置。旧beat线程吞掉实际异常，仅保留类型，外层又输出泛化错误；没有errno、winerror或失败阶段，因而**不能从这次记录断言DrvFS sharing就是根因**。没有写生产数据库、改任务状态或申请GPU。

## 固定断言与修复

每次心跳原子写入使用一个已完整写入并fsync的临时文件。只有replace步骤发生已确认Windows共享冲突才重试，整次写入的重试截止时间从创建临时文件之前开始计算，预算 **0.7秒**，退避10/20/40/80ms后上限100ms。成功后原子替换，旧tick在替换前保持完整；不重复创建临时文件。系统调用本身若由OS长期阻塞仍不受Python超时抢占，本预算约束可重试与等待时间；Linux既有失联watchdog保持不变。

允许重试：

- WinError32/33（sharing/lock violation）。
- WinError5 **且** 对同一既有目标执行不写入/不删除的DELETE-access句柄检查，明确返回32/33。检查只打开并立即关闭句柄，不调用DeleteFile。

不重试：普通EACCES、无法确认共享冲突的WinError5、磁盘满、路径错误，以及open/write/flush/fsync等其他阶段错误。对真实只读目标实测一次即失败。不能把所有PermissionError当临时错误。

新增安全诊断只包含 `stage,type,errno,winerror,attempts`；阶段区分open_temp、write_temp、flush_temp、fsync_temp、replace、cleanup_temp，以及retry/recovered/failed。绝不复制异常文本/filename、绝对路径、心跳token或请求内容。CLI捕获特定HeartbeatWriteError后返回1并输出安全JSON，不再用带路径的异常堆栈替代已知心跳故障诊断。清理临时文件失败会单独报告，不能覆盖原始故障。

持续失败仍停止beat，发出本attempt取消标记并等待Linux按既有协议停机；不会写伪成功或放宽GPU释放条件。若初始心跳失败，WSL尚未启动，写 `launcher_not_started/compute_stopped=true` 证明；若Linux已启动，done仍必须由其guardian产生。取消/done发布再失败也只输出安全故障阶段，失联守卫与worker的停止证明规则继续fail closed。

## 实际验证

先固定失败条件再修改代码。第一版仅重试32/33时，本机真实 `CreateFileW` 读者不授 `FILE_SHARE_DELETE` 导致 `os.replace` 返回 **WinError5**，测试失败（42passed/1failed/1既有opt-in skip）。这是真实Windows文件竞争证据，促使增加明确的DELETE-access共享检查；不是凭猜测盲目重试AccessDenied。

最终命令：

```powershell
& D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/platform/test_wsl_heartbeat.py tests/platform/test_wsl_bridge.py -q -p no:cacheprovider --basetemp .test-tmp-wsl-heartbeat-final
```

**47 passed / 1 skipped / 4.41秒**。其中新增16项包括：

- 32/33短暂故障后恢复；完整临时文件复用、旧tick完整、无残余临时文件。
- 无法证实的5、普通EACCES、其他IO错误和fsync错误立即失败；cleanup错误不遮盖原故障。
- 写临时文件已消耗的时间计入同一个0.7秒预算，持续错误不无限重试。
- 明确CPU夹具验证持续失败写cancel、等待launcher退出、不代Linux伪造done；初始失败从未启动launcher。
- 诊断键集合严格受限；注入带秘密字符串及敏感路径的异常，日志与异常摘要均不含这些内容。
- **本机真实Windows读者竞争**：持有不允许删除共享的句柄120ms后释放，原子替换在1秒内恢复。
- **本机真实只读属性**：一次失败、不进入重试。
- **本机真实持续读者竞争**：0.65–1秒内失败，原tick保留，释放句柄后可清理；未动用户已有文件。

所有测试仅使用新pytest临时文件或CPU故障夹具，不启动WSL、torch、模型或GPU。唯一skip是既有显式开启的Windows→WSL CPU watchdog集成用例，本轮没有设置其opt-in环境变量。已有31项桥接路径/GPU租约协议夹具仍通过；这些夹具不等于真实GPU取消。

## 下一步与限制

将独立修复提交同步到实际启动bridge的主仓库与models使用的代码路径。下一次用户/主协调授权的真实模型窗口中，保留安全stage/errno/winerror诊断，验证实际DrvFS路径是否恢复；若出现未确认的5或其他IO错误，保持失败并依据新证据定位，不扩大到无条件重试。历史失败记录及其取消证据保持原样。
