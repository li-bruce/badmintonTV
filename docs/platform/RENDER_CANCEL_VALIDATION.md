# 真实 CPU 渲染取消集成验证

2026-09-29，G-02 运行时稳定性补充子用例 `G-02a-render-cpu-cancel`：**PASS**。目标预先固定为：Windows worker启动真实render/FFmpeg后请求取消；本attempt收到取消标记；终态cancelled；render自有锁释放；已观察到的自有计算进程退出；随后短任务成功。此用例不代表GPU取消或强杀故障路径通过。

仅使用独立队列 `D:/video/platform/research-20260929/render-cancel-cpu-r1/runtime-test.sqlite3`，未连接生产队列或业务DB。render owner提前协调CPU空窗，验证结束后已即时归还。GPU未使用；未终止其他任务进程；原片只读。

## 输入、版本、执行

- 平台当前Windows worker的graceful cancel实现，平台Python `D:/video/runtime/platform/env/Scripts/python.exe`。
- 只读调用render worktree `C:/Users/USER/.codex/worktrees/3e52/badmintonTV`，实测commit `4ecaf6dfcf0536fe95e720a612c7bfd3a9a54206`；没有cherry-pick或修改该模块。
- 既有general原片 `data/raw/finebadmintonbenchmark/video_000001.mp4`，SHA256 `057d2d6dd52eb892719b36aa1f017ac6272e19502dd93efbc0ca9f97f35b6fe0`，642,017字节；不读取training素材。
- 首job为两段各4秒真实源区间、1080×1920 / 30fps、静音、`research_preview=true`；后续job为同源1秒单段。没有人类技法确认声明。
- `BTV_RENDER_BACKEND=cpu`；`BTV_FFMPEG`、`BTV_FFPROBE`沿用render提供的9.0.2 essentials二进制。管理员固定argv为platform Python `-c`，将3e52加入sys.path后 `raise SystemExit(packages.render.__main__.main())`；不是浏览器提供命令。

复现脚本：[validate_render_cancel.py](validate_render_cancel.py)。使用全新证据子目录运行：

```powershell
& D:/video/runtime/platform/env/Scripts/python.exe docs/platform/validate_render_cancel.py --evidence platform/research-20260929/render-cancel-cpu-NEW --render-repo C:/Users/USER/.codex/worktrees/3e52/badmintonTV
```

## 实际断言与证据

总耗时 **18.391秒**。脚本从render自身锁读取CLI PID **54632**，通过Win32_Process观察其直接子进程 **FFmpeg PID 62932**，命令确实编码 `.partial.mov`，随后才向独立queue请求取消。

取消job：`job-4ae18387c6704355ada50a98f20b2abf` / `attempt-1`。worker终态与render `result.json`均为 **cancelled**。`platform/jobs/<job>/attempt-1/cancel.request` 内容包含相同job、attempt及 `cancel_requested=true`。队列seq11的 `render_cancel_cleanup.graceful=true`，报告CLI已退出且输出管道关闭。render锁在取消完成时不存在；对已观察CLI/子进程PID的Win32进程存活检查为空列表。平台没有代删render锁。

随后的 `job-7602f85d0dd84d95abe2f910eb3b492c` / `attempt-1` **succeeded**，证明下一CPU任务可重新获得render锁。其 `export.mp4` 为141,188字节，SHA256 `bfa4b58b224ae98de747ddc6ed5b646fd229d4bd82788b668c535a47e86aba44`；worker核验了结果身份、退出状态及四个Artifact的尺寸/hash。此补充测试没有重复浏览器播放验收。

主证据：`D:/video/platform/research-20260929/render-cancel-cpu-r1/render-cancel-validation.json`，包含两个job结果、原JSONL日志、取消前真实进程/锁、取消标记、存活检查和时间。原始生成时case_id误标为 `S2-06/R-02-runtime-cancel`，保留原始文件不改证据；本文将其正式归入已有G-02及本子用例，脚本已修正后续报告标识，不宣称不存在的S2-06通过。

其他证据：

- `D:/video/platform/jobs/job-4ae18387c6704355ada50a98f20b2abf/attempt-1/result.json` 与 `cancel.request`。
- `D:/video/render/jobs/job-4ae18387c6704355ada50a98f20b2abf/attempt-1/reservation.json`。
- `D:/video/render/jobs/job-7602f85d0dd84d95abe2f910eb3b492c/attempt-1/` 下export、QA、source_map与reservation。

## 容量与边界

写入前独立CapacityLedger预留setup **16MB**，worker每次再预留platform协议 **128MB**。renderer自身预留首job **95,680,000**字节、后续job **67,960,000**字节，并核验render 40GB、全局700GB与物理free。物理free从950,167,556,096到950,122,713,088字节；其他模块可同时写小文件，因此差值不当作本测试净产物大小。最终独立queue未释放预留数为 **0**。保留取消后的残余产物及证据，没有删除原片或旧文件。

此次只证明正常协作取消路径：真实编码中取消、CLI主动退出、锁清理以及下一任务恢复。10秒宽限期超时强杀、进程崩溃、永久IO故障与真实CUDA中途取消仍须单列，不能从此次PASS外推。
