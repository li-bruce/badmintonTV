# Platform runtime 设计与执行记录

2026-09-28。标准库实现，无 torch；Windows 原生 SQLite，独立 worker。

## 数据流

API 将固定 operation 与 JSON payload 入队 → 独立 worker 事务领取 → 心跳保活 → 安全解析共享根内路径 → 固定处理器或管理员登记 CLI → 持久 JSONL 日志 → 同时检查退出码和结果 → API 验证结果并同步业务 DB。runtime 不写业务数据库。

`jobs` 保存请求、幂等键、尝试次数、取消请求、租约、结果/错误与最后进度；`job_logs` 使用每 job 递增 seq；`reservations` 保存 owner 的容量峰值预留。SQLite 使用 WAL 和 BEGIN IMMEDIATE，多个 Queue 实例领取同一 job 时只有一个成功。不得跨 WSL/Windows 共享同一 WAL。

状态：queued → running → succeeded/failed/blocked/cancelled。排队取消可直接完成；运行取消先置 cancel_requested，worker 确认停止子进程树后才写 cancelled。租约失效留下 WORKER_INTERRUPTED 错误并进入 failed，不自动重新执行。显式 retry 保留日志与最大尝试次数；旧 worker 无法心跳或完成失效租约。worker 自身传 expected_attempt，防止同名 worker 的旧尝试更新新尝试。

容量按固定 owner 分区统计文件实际 bytes；同 owner 所有写入使用同一预留账本。慢目录计量由独立capacity-lock SQLite串行，不占用job DB写事务；主runtime DB只在短事务内重读活动预留并登记峰值，以免阻断heartbeat。目录扫描不跟随符号链接，写路径经resolve_owner_path拒绝任何symlink/junction/reparse祖先，且词法与物理路径均属于指定owner。检查owner限额、总700GB和可用磁盘；reservation必须覆盖临时与最终产物同时存在的峰值。固定owner配额不得借用50GB余量。

目录遍历显式传播权限错误，不能静默漏算。reserve时本owner无法读取即失败；其他固定owner无法测量时在全局700GB逻辑核验中按其完整配额计一次（不再加同owner实际bytes或活动预留），usage返回measured=false。已分区目录之外的占用另外测量，不可读则失败，避免漏算未登记文件。物理free检查只包含实际活动预留与本次峰值，不把其他owner完整配额当成本次磁盘写入需求。

## Python 接口

从 `packages.runtime` 导入 `Queue, CapacityLedger, resolve_relative_path`。

`Queue(db_path)`：

- `enqueue(operation, payload, idempotency_key=None, max_attempts=3) -> dict`
- `get(job_id) -> dict | None`，`list(status=None, limit=100) -> list[dict]`
- `logs(job_id, after_seq=0, limit=1000) -> list[dict]`
- `claim(worker_id, lease_seconds=30) -> dict | None`
- `heartbeat(job_id, worker_id, lease_seconds=30, expected_attempt=None) -> bool`
- `append_log(job_id, event, stage=None, current=None, total=None, unit=None, message='', **data) -> dict`
- `finish(job_id, worker_id, status, result=None, error=None, expected_attempt=None) -> dict`
- `request_cancel(job_id) -> dict`，`retry(job_id) -> dict`，`recover_expired() -> list[str]`

job 字段：job_id、operation、payload、status、attempt、max_attempts、cancel_requested、worker_id、lease_expires_at、created_at、updated_at、result、error、progress。

`resolve_relative_path(storage_root, relative_path, must_exist=False) -> Path`。

`CapacityLedger(db_path, storage_root, quotas=None)`：`reserve(owner, peak_bytes, job_id=None) -> reservation_id`；`release(reservation_id)`；`usage() -> dict`。生产使用默认配额，测试可注入小配额。

## worker 命令与管理员配置

`python -m packages.runtime.worker --db D:/video/platform/runtime.sqlite3 --storage-root D:/video --poll-seconds 1 --lease-seconds 30`。

`--once` 领取至多一个任务并退出，适合诊断。固定 operation 为 probe、verify_manifest、render、model。probe payload 为 `{relative_path, asset_metadata?: {...}}`；成功结果含 asset 与 artifacts，由 API 审核导入。哈希进度来自已读取字节；ffprobe 和缩略图使用独立本任务子进程。

`verify_manifest` payload 为 `{assets: Asset[], library_id}`，1–1000 条Asset且序列化元数据≤16MB。先按统一 AssetManifest 校验，再逐文件从安全路径读取实际字节，严格比较声明size_bytes与SHA-256；每次读4MiB，记录累计真实字节进度，读取前后检查文件身份、大小及mtime。任意文件失败使整job失败，不返回部分资产。成功返回 `{schema_version,job_id,attempt_id,status,assets:[verified],artifacts:[],events:[],error:null}`，不解码、不复制媒体、不写业务DB。控制面可将大于8MB媒体总量的清单交给本handler，成功apply时直接一次性导入已核验数组，避免重复排队；较小清单仍需有限同步hash后入库。该handler使用当前128MB platform峰值预留，不需要ffmpeg。

管理员可通过 `BTV_FFPROBE`、`BTV_FFMPEG` 指定可执行文件。`BTV_RENDER_COMMAND_JSON` 为JSON argv数组，例如 `["python", "-m", "packages.render"]`；worker追加 `run --request ... --result ...`。模型只接受 `BTV_MODEL_COMMANDS_JSON` 的 model_id → 命令数组精确映射，已移除通用BTV_MODEL_COMMAND_JSON fallback，不能借其他模型卡启动未登记模型。render未设置环境变量时使用当前Python的packages.render（缺少模块则blocked/not_installed）。浏览器payload的command/entrypoint不参与命令构造。

模型任务在队列内 operation 固定为 model；CLI request.operation 使用 payload.adapter_operation（main 依据模型卡 capabilities 验证后持久化，例如 query_parse/pose/video_embedding/movement_classification）。模型 payload 必须保存非空 model_id/model_version 快照，worker 注入 request.parameters，并覆盖用户 parameters 内冲突的同名字段。缺少已验证 capability 或版本快照时明确失败，不猜测默认模型。指定模型不在管理员命令表内时 blocked/not_installed。

后续GPU租约已实现，接口与管理见[GPU.md](GPU.md)。payload.gpu_required为true，或管理员登记argv含packages.runtime.wsl_bridge时，worker必须在启动前取得同runtime DB中的管理员授权窗口与独占租约；没有窗口则blocked/GPU_LEASE_REQUIRED。bridge无论浏览器模型卡声称何种device都需要租约，客户端token无授权效力。worker持续心跳，失效停止计算；Windows本机CLI确认进程树已停才release，WSL桥接须确认匹配attempt的bridge.done.json并compute_stopped=true，否则orphaned保留锁，不自动因过期变为可用。桥接设计与真实边界验证见[WSL_BRIDGE.md](WSL_BRIDGE.md)。

跨环境 CLI 输出目录固定为 render/jobs/<job_id>/attempt-N 或 models/jobs/<job_id>/attempt-N；请求/结果交换文件写 platform/jobs/<job_id>/attempt-N，request/result 含 attempt_id 并拒绝迟到旧结果。assets 为完整 Asset 数组，output_dir 为 POSIX 相对路径。worker 传 `BTV_STORAGE_ROOT`，Windows/WSL 转换仍由管理员注册 launcher 负责，未完成的跨系统配置不得声称可用。

源视频只能通过 Asset relative_path 解析。CLI 自身负责其 owner 输出配额；当前worker为platform单attempt预留128MB，覆盖request/result（各≤16MB）原子写入临时双份、SQLite/WAL、持久日志与缩略图，不复制原片。子进程输出逐行有限读取，进度由统一 ProgressEvent 校验；未知总量保持 null；stderr 限长且屏蔽环境中密钥值。结果由 JobResult 校验，匹配退出码0/1/2/130=成功/失败/阻塞/取消；还须核对已存在 artifacts 的受控路径、哈希和大小。Artifact 校验时仍响应取消。

WorkerContext 对单attempt的progress/warning/error等执行日志累计限制8,000,000 UTF-8 JSON bytes（含持久化envelope），先保留一条省略warning的空间。达到预算后只记录一次省略说明，后续日志不再写库；仍继续解析CLI进度、检查取消/租约和核验真实结果，最终状态仍由退出码/result决定。队列入队/领取/终结状态记录独立保留。日志上限解决原先合法progress可绕过行数上限的问题；峰值预留从32MB上调，既往真实运行的32MB历史记录不改写。

Windows 子进程先启动等待指令的轻量 launcher，加入 worker 独占的 Job Object 后才传递 argv 运行 CLI；关闭句柄会终止此 job 的整个子树。父 worker 崩溃导致句柄关闭时亦清理子树。依据[微软 Job Objects 官方文档](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。Linux 使用独立 session 和进程组。运行时未安装新工具：标准库 ctypes 调用 Windows API，无 GPU/torch。

## 验证状态

最终复核补充：worker所有终态在计算停止核验及GPU释放之后发布；取消等待期间仍为running/cancel_requested且心跳继续，无匹配done则failed/WORKER_INTERRUPTED+GPU orphan。Queue的enqueue/claim/heartbeat/finish/recover_expired统一在取得BEGIN IMMEDIATE后采时，避免写锁等待跨租约到期仍续租或提交成功；5项新增测试用真实SQLite锁与受控时钟复现边界。

2026-09-28 实际测试：`D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/platform/test_runtime.py -q` → **40 passed, 1 skipped**。覆盖同库重开、幂等冲突、8线程竞争领取、最大重试、过期失败与旧尝试隔离、排队/运行取消、危险路径、原子容量竞争、真实进程协议错误、陈旧attempt、实际Artifact哈希不符、缺失模型blocked、stderr密钥屏蔽、心跳与完整进程树取消；追加验证模型 capability 传递、模型版本参数不可覆盖、缺少快照拒绝、管理员表无模型阻塞、模型及渲染 GPU 需求在启动前阻塞。清单核验新增实际文件字节流读取成功（5.2MB+小文件）、错误hash/size拒绝、不发布部分资产、1001条拒绝。日志预算测试让CLI连续输出200条合法长中文progress，以1,400字节测试预算验证实际持久UTF-8 JSON总量不超限、仅一个省略warning、CLI仍真实成功；饱和后取消检查仍有效。容量边界测试验证遍历权限错误传播、其他owner全配额回退不重复计量、回退仅用于全局逻辑上限而不污染物理free检查、本owner不可读拒绝。此类任意字节fixture仅证明完整性检查，不是视频解码或识别成绩。唯一跳过为 Windows 当前测试账号不能创建 symlink，普通穿越、盘符、ADS、设备别名均已测；根外实际 symlink 情形需具备创建权限的环境补测。

失败记录：第一次进程树取消测试发现沙箱内 `taskkill /T` 返回 Access denied，只杀父进程不满足约定；已改为专属 Job Object，复测父子进程皆终止。第一次真实容量扫描遇 WSL 环境文件 `runtime/models/env/bin/2to3` 的 Windows reparse point 跟随失败（WinError1920）；改为 lstat 计量实际条目并禁止追随 owner 外链接，复测通过。首轮probe将4633.333ms四舍五入成4633ms，与library末帧覆盖4634ms不一致；统一向上取整后重测相符。失败产生的独立小型验证数据库保留，没有自动清除。

独立 worker 真实运行（非合成）：只读 `asset-057d2d6dd52eb892719b36aa1f017ac6272e19502dd93efbc0ca9f97f35b6fe0`，即 library 交接的 FineBadmintonBenchmark video_000001。经独立 `python -m packages.runtime.worker --db ... --storage-root D:/video --once` 成功后另一个 Queue 实例重开数据库确认状态；SHA-256与library一致、4634ms、1280×720、原PTS索引保留。缩略图已人工视觉检查，是完整羽球场地和两位球员画面。没有从这次媒体探测推断手法或识别成绩。

- 最终运行报告：`D:/video/platform/handoff/runtime-probe-verification-20260928T152244Z.json`
- DB：`D:/video/platform/runtime-verification-20260928T152244Z.sqlite3`
- job：`job-ffcfd4f128c94b36b3d76a823fbe6610`
- 缩略图：`D:/video/platform/jobs/job-ffcfd4f128c94b36b3d76a823fbe6610/attempt-1/thumbnail.jpg`
- 探测器：render任务安装的 FFmpeg/ffprobe 9.0.2，`D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin`，仅CPU。
- 最终预检platform已用2,397,693 bytes / 60,000,000,000；实际媒体衍生只有单张缩略图及小型DB/JSON，32MB峰值预留已释放。D盘之前实测剩余963,927,945,216 bytes，运行时另有动态复测。

后续真实GPU验证（本地2026-09-29）：Web触发job `job-3dc9ece15e914eecb9616ac306ece6b8` / attempt-1，通过本机runtime DB的管理员GPU窗口、Windows独立worker及Ubuntu受控bridge执行torchvision-keypointrcnn成功。真实源视频6秒、24采样帧，冷运行28.702605725秒，峰值allocated489,201,152 / reserved792,723,456 bytes；features620,202 bytes、report849 bytes均经worker核验哈希。匹配bridge.done确认compute_stopped=true、exit_code=0后，主协调核验GPU租约released。完整源asset、产物路径和误用限制见[WSL_BRIDGE.md](WSL_BRIDGE.md)。events为空且accuracy/recall为null，不从姿态产物推断细动作识别成绩。

未测/限制：原runtime媒体报告不替代真实render CLI与API/browser完整工作流验收，主任务另有集成报告。跨WSL正常GPU推理已实测；失联清理实测使用CPU进程树，未声称完成GPU推理中的强制中断测试。CLI退出仍存留后台进程将被终止，适配器不可把计算脱离任务。崩溃留下的容量预留保守保留，需确认没有在途写入后由管理员release；不自动删除中间产物。GPU独占只覆盖管理员纳入同一账本的受控任务，不是四模块所有独立CLI的全局调度器；未经协调的外部GPU进程不能被本平台终止。
