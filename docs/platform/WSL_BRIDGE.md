# Windows worker 到 WSL 模型桥接

设计日期：2026-09-28。新增后续源码，不修改既有提交历史。

Windows worker 只接受管理员 `BTV_MODEL_COMMANDS_JSON` 中按 model_id 精确登记的 argv。桥接 argv：

```json
["D:/video/runtime/platform/env/Scripts/python.exe", "-m", "packages.runtime.wsl_bridge", "--distribution", "Ubuntu", "--env-prefix", "/mnt/d/video/runtime/models/env", "--repo", "C:/Users/USER/.codex/worktrees/c5b1/badmintonTV"]
```

worker追加 `run --request <Windows request.json> --result <Windows result.json>`。此argv含bridge模块即强制GPU租约，不信任浏览器模型卡将device改成CPU。桥接自身只运行固定 `python -m packages.models`，不接受客户端shell或module。

交换文件限定在 `D:/video/platform/jobs/<job_id>/<attempt_id>`，严格映射为 `/mnt/d/video/platform/jobs/...`；请求内资产/output_dir仍使用合同POSIX相对路径。管理员env-prefix限制在 `/mnt/d/video/runtime/models/`，repo是管理员提供的Windows绝对路径，转换为WSL挂载路径。固定Ubuntu，wsl.exe全程argv数组调用，无shell拼接。桥接不接触SQLite；Windows仍独占数据库。

Windows外层原子更新该attempt的 `bridge-heartbeat.json`。Linux前台入口启动独立session的guardian后等待；guardian启动固定模型CLI的独立process group，检查心跳和取消文件，只终止自己持有的模型进程组。Windows worker/桥接死亡导致心跳失联时，默认8秒内发SIGTERM，最多3秒后SIGKILL。模型结束后guardian清理遗留同组子进程，发布 `bridge.done.json`（job_id、attempt_id、compute_stopped、pgid、退出码与原因）。禁用全局pkill。

worker取消时Windows Job Object停止外层bridge；GPU租约须等最多15秒并核对done身份与compute_stopped=true才释放，否则标记orphaned保留锁。GPU窗口由管理员单独授权，桥接不创设或延长GPU授权。GPU表与窗口接口见[GPU.md](GPU.md)。worker已在交换目录、模型输出及返回Artifact处接入物理owner路径校验；platform/jobs指向data的junction不允许写入。

固定离线环境通过 `/usr/bin/env` argv逐项传入：BTV_STORAGE_ROOT、BTV_MODELS_ENV、CONDA_PKGS_DIRS、CONDA_ENVS_PATH、HF_HOME、TORCH_HOME、TMPDIR、PIP_CACHE_DIR、PYTHONDONTWRITEBYTECODE、HF_HUB_DISABLE_TELEMETRY、HF_HUB_OFFLINE、TRANSFORMERS_OFFLINE和TOKENIZERS_PARALLELISM。值与models任务确认的环境一致，缓存分别在models与runtime/models owner目录；不通过shell source脚本。

已运行的验证：

- `python -m pytest tests/platform/test_wsl_bridge.py -q -p no:cacheprovider` → 27 passed、1 skipped；常规跳过项为需要显式授权的实际Windows/WSL边界测试。覆盖驱动器/穿越/ADS/设备名/同attempt边界、argv与离线环境、done身份校验、即使payload声称CPU仍必须租约、只有匹配done才释放GPU而陈旧done保留orphan。
- Windows实际CPU watchdog测试单独开启 `BTV_WSL_BRIDGE_TEST_ENV=/mnt/d/video/runtime/models/env` 后运行 `-k windows_job_death` → 1 passed（3.34s）。使用仅标准库的假模型（不载torch、不使用GPU），模型创建一个60秒子进程。Windows Job Object被强制关闭，外层bridge和wsl.exe被停止，detached guardian检测失联并终止自己的模型进程组。
- 证据：`D:/video/platform/jobs/job-bridge-watchdog-9133279272d84a75857973c762b168fb/attempt-1/bridge.done.json`。job_id同路径，attempt-1，reason=heartbeat_lost，compute_stopped=true，exit_code=130；guardian_pid=149391、model_pgid=149392，started_at=1790611062.4788423、finished_at=1790611064.91388。该测试特意使用2秒心跳期限；生产默认8秒。
- 该运行仅出现pytest缓存目录写入权限警告，测试断言与Linux停机证据均通过；后续测试使用 `-p no:cacheprovider`。

2026-09-29（本地时间）已完成一次真实GPU桥接：主协调确认models空窗，在同一 `D:/video/platform/runtime.sqlite3` 授予窗口后经Web触发 `torchvision-keypointrcnn`，Windows持久worker→受控WSL bridge→Ubuntu隔离模型环境→回写result全部成功。没有另建独立GPU账本。

- job `job-3dc9ece15e914eecb9616ac306ece6b8` / `attempt-1`；源asset `asset-5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90`（真实6秒数据集视频），sampled_frames=24。
- 结果：`D:/video/platform/jobs/job-3dc9ece15e914eecb9616ac306ece6b8/attempt-1/result.json`，status=succeeded，error=null，events=[]。worker核验产物大小与SHA-256通过。
- 特征：`models/jobs/job-3dc9ece15e914eecb9616ac306ece6b8/attempt-1/features.json`，620,202 bytes，SHA-256 `1705d8d6ae316aaa5c1f7602f070fe8bd1e2fc8d1af5448eeeaae0cf20147799`。
- 报告：`models/jobs/job-3dc9ece15e914eecb9616ac306ece6b8/attempt-1/report.json`，849 bytes。冷运行28.702605725秒（含模型加载与解码），峰值allocated=489,201,152 bytes、reserved=792,723,456 bytes；设备RTX5090、torch2.7.1+cu128、CUDA build12.8。此单短片耗时不能视为整场吞吐。
- `bridge.done.json`同Windows交换目录：job/attempt匹配，reason=completed、compute_stopped=true、exit_code=0；guardian_pid=149447、model_pgid=149448。主协调核验同库GPU租约最终released。对应时间为2026-09-28T16:01:22Z结果发布，属本地2026-09-29。

该结果证明一次真实姿态推理及跨系统调度协议工作，不证明细手法、运动员身份、击球时刻或时序动作识别：模型明确unsupported这些能力，accuracy/recall均null，需人工复核。真实GPU运行是正常完成；强制失联清理实际使用标准库CPU进程树单独验证，未将其写成GPU中途取消的实测成绩。该租约协调同账本内的受控任务；尚不构成四模块所有独立CLI和外部GPU进程的全局调度器。
