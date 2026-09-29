# 平台研究实施轮交接

2026-09-29。源码、最终回归与私有API兼容验证已完成，无必须源码WIP。分支`codex/platform-research-implementation`，未推送。主任务负责集成main；整个产品阶段仍由共同验收表判断。

## 待集成提交顺序

本次只读`git cherry main HEAD`显示以下五项尚无main等价patch，依次集成；其后的本交接/证据文档提交一并取入。

| 顺序 | 完整SHA | 最终内容 |
|---|---|---|
| 1 | `f64a2a95e2f78c7c40385a881b26050844b99fd5` | 实际来源校验、训练制作隔离、有界代理/全源PTS、原图任务、持久导出设置、渲染取消与平台API |
| 2 | `a73b485a994f1013e01481d98bea6ee880d86596` | 默认关闭的YOLO固定命令与独立yolo-env映射、配置测试与说明 |
| 3 | `7e8a9bd6292dd9743590a5e2ba2a3e970fb7cce7` | 源帧预览、标注/循环/缩略图、原图串行取消及16项缓存、导出设置UI |
| 4 | `19a36cc7e654630c54bd84dded9f4e440ec15145` | **组合提交**：虽标题只写标注选择，实际同时包含artifact可信身份/Range响应/main/queue/worker主体，以及标注列表/保存/定位epoch修复 |
| 5 | `e1da6ee97a61eb377e2282bd6e2355a1cd8be0ff` | exact_frame执行时绑定成功preview job/attempt，依赖index在读取/解码/产物生成后仍复验 |

此前`7354b1f`、`a7fff391`、`4fdd200d`、`b7d7a855`、`21e16949`、`2f3fd855`、`ec8a7fc`均已被`git cherry`判为main有等价patch，避免重复合入。19a36cc形成于并行代理暂存/提交协调竞态，实际内容均为本平台授权文件；未丢失改动、未改写历史。应依赖实际diff及上述顺序，不只看提交标题。

## 最终已运行

- 冻结源码全套：`tests/platform tests/contracts` **607 passed / 7 skipped / 59.12秒**；Node语法及前端 **38/38 PASS**。条件skip和既有Starlette httpx弃用warning见[完整报告](RESEARCH_VALIDATION.md)。
- 实际四种短片代理及原PTS独立校验：32项通过；240点浏览器测量全部误差≤一个源帧，212零误差/28为-1。未复跑整批媒体基准，也不将模拟字节测试计为视频识别。
- 实际逐帧/原尺寸/事件revision重载、修复后循环、缩略图定位及原图取消/缓存闭环通过。最终服务的新#61任务`job-06a35bd0cd134c9d8c919a4ee3ec0e9a`成功，1280×720、PTS15616×1/15360；旧预览与旧成片Range下载兼容，5条可信proof当前身份核对通过，私有队列无queued/running。见[运行证据](browser-final-artifact-proof.json)。
- 导出UI实际进入1秒1080×1920/60fps H264/AAC CPU成片，12项QA通过、浏览器播放至结束；Agent来源与错误human快照的取消历史均保留。
- 完整10项真实训练manifest/10条registry时点：14 API均422/TRAINING_ONLY，普通及research render worker均blocked；无媒体读取/子进程/adapter/主DB访问，私有历史审核仅模拟fixture。此前7项时点和失败记录保留，见[真实负例报告](REAL_TRAINING_ISOLATION.md)。render独立四模式拒绝为其模块证据。
- 实际CPU编码中取消、停止自有进程、释放锁后下一job成功。Win5心跳CPU/Windows回归60/1；models后续在main fd6155b的TrackNet/YOLO两个真实3秒任务成功，但没有触发Win5诊断，不能称本次实测了重试分支。

## 环境与边界

审阅服务为`127.0.0.1:18082`，10:34:02UTC重启后parent53520/child62828；`D:/video/platform/research-20260929/services.json`保留前PID与日志记录。只有API，无永久worker；本轮未操作main18080、LS18081或启动GPU。平台Python与FFmpeg9.0.2均复用，未安装依赖。私有库启动命令见完整报告。所有媒体/截图留D盘，Git仅代码、文档和小型测量记录。

最新平台容量约198.5MB/60GB，runtime/platform约1.05GB/10GB；精确时点与旧快照见[容量记录](capacity-final-snapshot.json)，不是全模块700GB总审计。

剩余明确边界：约1秒rVFC回调等待原因未知，不是已证明的实际屏幕呈现耗时；长片原图仍需全源校验及从头解码，未证明整场流畅。专家细标签/个人录像真值、模型质量与产品阶段总验收没有由本轮替代。详见[延迟问题](../issues/platform-preview-presentation-latency.md)和[长片成本问题](../issues/platform-exact-frame-long-video-cost.md)。

跨聊天交接发送曾被自动审批拒绝，原因是当前可见用户指令未明确授权向其他聊天发消息；授权问题仍待用户回答，本任务未重试或绕过。此本地交接单提供完整可审阅结果。
