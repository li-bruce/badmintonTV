# 模型第二次复用实验bridge心跳异常

2026-09-29，job-3757b3d57b2142cd80841a585d9523e0。
模型请求通过验证后被guardian取消；main runtime/wsl_bridge.py run_windows中
beat任一次_atomic_json异常触发 `bridge could not maintain its heartbeat`。
现代码只保存异常类，实际底层错误信息未被输出，不能确认一定是文件共享冲突。

原始Queue日志seq18–20、platform/jobs对应request/result、bridge-heartbeat、
bridge-cancel、bridge.done全保留。done compute_stopped=true、reason=cancel_requested、
exit_code130；Windows bridge exit1，worker报告协议退出码不匹配并failed。
GPU lease/window都已释放撤销。未绕过watchdog，也未把取消记成功。

相同参数新job-4081ac5e54f944b7b087c149efe43e69一次重试成功。
已交platform在其模块补有界瞬态重试及安全错误诊断，保持失联fail-closed。
models不跨边界改runtime；等待主任务集成platform修复，再由后续实跑验证。
