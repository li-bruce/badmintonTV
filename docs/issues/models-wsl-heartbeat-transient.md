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

## 新职业输入的复发记录

2026-09-29 18:00左右，固定新训练Asset b210dc39、120000–123000ms：

- TrackNet `job-d1ef49677c32448b959b0707de189f3f` 在 load_model 后被取消；
  main 新桥接日志 seq10 首次给出底层诊断：`heartbeat.replace.failed`、
  `PermissionError`、`errno=13`、`winerror=5`、`attempts=1`。
  Windows error5 是 access denied；仅此不能独立确定文件共享、杀毒或ACL根因。
- 独立新YOLO `job-440e2f730165435f9edafed4a172f407` 也被桥接取消，
  worker报告同样的 cancelled/exit1 协议不匹配；其seq10也明确给出
  `heartbeat.replace.failed/PermissionError/errno13/winerror5/attempts1`。
- 两次未取得新视频模型产物，不记作模型前向成功。runner均确认GPU lease/window=null；
  两份done均明确 compute_stopped=true/cancel_requested/exit130。
- 已通知platform/main，在其模块处理严格目标约束下的有界重试；models未改runtime，
  未放宽watchdog或用直接GPU启动绕过失败。旧YOLO job98cb成功也不能覆盖这两次失败。
