# GPU 授权窗口与任务租约

日期：2026-09-28。实现：`packages/runtime/gpu.py`。这是平台在经 models 协调的空窗内，对物理 `gpu0` 的独占调度；**尚未成为四个模块全部独立实验的统一 scheduler**。models 必须先暂停自己的独立 GPU 实验，root 才能授予有限窗口。窗口到期也不能证明旧计算已停止；models 恢复实验前仍需确认该任务已停止。

## 数据与状态

沿用平台原生 Windows `D:/video/platform/runtime.sqlite3`，不由 WSL 直接打开、共享 WAL。SQLite 的 `gpu_windows` 保存允许的 model_id、开始/结束时间、操作者与协调依据；`resource_leases` 保存 resource、window_id、model_id、job_id、attempt、worker_id、状态和核验记录。大小计入 platform 的 60 十进制 GB 配额。

租约状态为 `active → released` 或 `active → orphaned → released`。部分唯一索引只允许一个 active/orphaned 持有人，领取使用 `BEGIN IMMEDIATE`，所以并发 worker 不能双占。领取同时核对持久 job 的 running 状态、worker、attempt、作业租约和 model_id。

无授权默认 `GPU_LEASE_REQUIRED`；已有有效任务为 `GPU_BUSY`。租约或窗口到期会持久标记 `orphaned`，后续领取返回 `GPU_LEASE_ORPHANED`。过期绝不自动恢复可用，重启进程或另开窗口也不清除旧 GPU 锁。授权窗口最长 3600 秒；每次租约最长 300 秒，心跳续期不得越过窗口截止时间。

## Worker 接口

```python
from packages.runtime.gpu import GPUCoordinator, GPUUnavailable

gpu = GPUCoordinator(native_runtime_db_path)  # resource 固定 gpu0
lease = gpu.claim(model_id, job_id, attempt, worker_id, lease_seconds=30)
gpu.heartbeat(lease['lease_id'], worker_id, lease_seconds=30)  # bool
gpu.release(lease['lease_id'], worker_id, compute_stopped=True)  # bool
gpu.mark_orphaned(lease['lease_id'], worker_id, 'bridge stop not verified')
gpu.get(lease['lease_id'])
gpu.status()  # resource/code/available/active_window/lease，含当前 owner/job
```

`compute_stopped` 是可信执行器完成进程树核验后传入的内部事实，不能从 Web 请求或用户 JSON 直接透传。WSL bridge 必须等待 `platform/jobs/<job>/attempt-N/bridge.done.json`，同时核对 job_id、attempt/attempt_id 与 `compute_stopped is True`。Windows bridge 崩溃时，WSL watchdog 的约 10 秒清理窗口仍属于占用时间；缺少匹配 done 证据时调用 `mark_orphaned` 并保留锁。GPUUnavailable 有 `code` 与 `message`，由 worker 写真实 blocked/error 状态。

`release` 只接受当前 worker 的有效 active 租约；已过期租约即使随后有 done 文件，也必须进入下述管理员核验路径。`mark_orphaned` 不终止任何进程。Job 与 GPU 租约各自心跳，任何一项丢失都应由 worker 停止本任务，不能杀用户其它 GPU 进程。

## 管理员 CLI

没有公开 Web 授权端点，也没有用户 payload 自报的授权 token。以下命令应由 root 在 models 已明确让出 GPU 后执行，示例 ID/模型名须替换为实际记录：

```powershell
D:/video/runtime/platform/env/Scripts/python.exe -m packages.runtime.gpu grant-window --db D:/video/platform/runtime.sqlite3 --window-id platform-check-01 --models model-id-a model-id-b --seconds 120 --coordination-note "models 已确认暂停独立 GPU 实验，允许本次平台检查"
D:/video/runtime/platform/env/Scripts/python.exe -m packages.runtime.gpu status --db D:/video/platform/runtime.sqlite3
```

同一 window_id 不能覆盖/延长，不允许两个有效窗口重叠。允许的模型必须显式枚举，不支持 `*` 通配授权。窗口只是调用 root 的授权记录，不会代替 models 的协作暂停。

任务提前结束后，先通过可信 bridge.done 核验并释放 GPU 租约，再撤销剩余授权窗口，然后通知 models 恢复实验：

```powershell
D:/video/runtime/platform/env/Scripts/python.exe -m packages.runtime.gpu revoke-window --db D:/video/platform/runtime.sqlite3 --window-id platform-check-01 --reason "本次计算已停止且租约已释放，提前归还 GPU 给 models"
```

对应 API 为 `revoke_window(window_id, *, reason)`。短事务核对该窗口没有 active/orphaned 租约，再把 expires_at 截止到当前时间；仍有租约则返回 `GPU_WINDOW_IN_USE`，不能用撤销绕过停止核验。撤销后不能再次 claim，撤销时间和原因保存在新增 `gpu_window_revocations` 审计表，可通过 `get_window(window_id)` 回查；重复撤销保留首次记录。新增独立表兼容已运行数据库，不修改旧表列或删除历史租约。

orphaned 租约恢复命令：

```powershell
D:/video/runtime/platform/env/Scripts/python.exe -m packages.runtime.gpu prove-stopped --db D:/video/platform/runtime.sqlite3 --lease-id gpu-lease-... --done-file D:/video/platform/jobs/job-.../attempt-1/bridge.done.json --note "已核对本次 watchdog/进程树停止标记"
```

该命令验证匹配的 job/attempt 与停止标记，然后通过固定 argv 调用 `nvidia-smi --id=0 --query-compute-apps=pid --format=csv,noheader,nounits`，只有命令成功且计算进程列表为空才记录管理员核验并释放。可用 `--nvidia-smi <绝对工具路径>` 指定已安装工具。命令失败、仍有进程、N/A、不匹配或缺失 done 文件均拒绝释放；工具不杀进程。缺失可信 done 证据时保留 orphaned，不提供任意强制解锁选项。此时需修复/恢复停止证据并与 models 协调，不能依据 GPU 利用率短暂归零猜测进程已退出。

## 验证与限制

```powershell
D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/platform/test_gpu.py -q
```

结果：33 passed。覆盖默认拒绝、模型 allowlist、当前 job/attempt/worker、两个独立 coordinator 并发领取、窗口与心跳边界、过期持久 orphan、错误身份释放、缺少停止证据、停止标记匹配、管理员恢复、CLI 授权与状态、提前归还、active/orphaned 撤销保护与旧数据库兼容。所有时间敏感操作在取得 SQLite 写事务后读取当前时钟，另有 5 个回归用例模拟等待锁时窗口/租约过期，防止旧时钟续租或放行。测试使用临时原生 SQLite 和模拟 nvidia-smi，不启动 CUDA、不申请真实排期、不占用 GPU；真实 WSL 计算与 watchdog 集成验证由 root/runtime 后续报告，不能把本测试当成 GPU 推理已通过。
