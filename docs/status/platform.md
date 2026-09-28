# Platform 状态

2026-09-29 更新。任务 01a0e88b-2410-7da0-970e-7f4187ed485f；cwd C:/Users/USER/.codex/worktrees/6991/badmintonTV；branch work/platform。

- 设计：已读全部基线文档，见 docs/platform/DESIGN.md。
- 已实现：v1 Pydantic合同/JSON Schema/标准fixtures；FastAPI+页面；SQLite库/素材/球员/事件修订/候选/时间线；规则查询；环境变量LLM遮盖与连接测试；持久worker、attempt/租约/取消子树/真实进度；LS任务导出/PTS转换/原始归档/修订回写。
- 已运行：合同64 passed；API12 passed；runtime24 passed/1 symlink skipped；LS10 passed。独立worker真实原片hash/ffprobe/缩略图通过；4真实视频已导入18080。Label Studio 1.23.1真实Edge完成TimelineLabels31–48→31–60、VideoRectangle31/41帧改框、导出→平台revision2 [1000,2000)回写，保留未知标签，LS重启持久通过。
- 失败：沙箱 Git 元数据不可写，使用按命令 safe.directory 和授权写入；不修改全局 Git 配置。
- 最终已验证：141 passed/1 skipped；真实Edge标注→QuerySpec→3候选确认→标题/0.75倍速时间线→worker render成功，job-3ebf04b748644087b1328283382df830/attempt-1，14.833333s、1080x1920、445帧、H264/AAC、4产物hash及完整解码均通过。研究样片明确未获human技术确认。真实服务重启后标注/LS三版历史保留；CPU模型CLI显式retry attempt2成功。
- 未测：真实LLM端点未提供；GPU执行中途取消未做真实CUDA实验（Windows死亡守护已有真实WSL CPU进程树验证）；个人录像/专家细技术真值缺失。
- 阻塞：无阻塞人工流程的外部条件；GPU须先与models协调有限窗口，无窗口默认GPU_LEASE_REQUIRED。
- 下一步：主协调审查集成并接管服务；按专家真值与实际LLM端点补后续能力。不要将Agent区间审阅或pose特征当技术真值。
- 提交 SHA：6a3e3deb4ff34bf4eb22f18d20e995f9e8d28e1d（统一合同）；09be6ffc6c7d60a18a3c5d86e687298b1ae35aad（可信审核actor）；356b98f656033842aec6638c4029ba229e528286（平台完整业务基线）。
- 启动：./start-platform.ps1（18080）；./start-worker.ps1；Label Studio实际18081，命令见 docs/platform/LABEL_STUDIO.md。
- 环境/容量：Windows Python3.12.11；D:/video/runtime/platform/env独立venv，FastAPI0.141.1/Pydantic2.13.5；锁定清单docs/platform/requirements-lock.txt。最新platform约52,921,277bytes/60GB；runtime/platform约1,048,280,806bytes/10GB（含LS与所有pip缓存）。新增约50MB为有来源记录的真实原片无损probe回归派生。任务协议/日志峰值预留128MB，日志单attempt上限8MB。只读复用FFmpeg9.0.2；GPU仅使用models已建WSL Python3.11/torch2.7.1cu128环境。computer-use技能使用本机Edge，未新增插件。
- handoff：D:/video/platform/handoff/platform-real-flow.json、platform-restart-check.json、events.v1.json、assets-imported.v1.json；成片由render owner持有，路径见VALIDATION.md。

## 独立审查修复与 GPU 后续

- 大于8MB的probe结果直接使用worker全量hash结果入库，避免二次异步导入返回值类型错误；应用前检查文件存在和大小，Web不重复hash大文件。
- 检索改为全局有界top500，后出现的精确匹配不会被前500个未知候选挤掉。
- 时间线保存可携带明确human/agent审核人；绑定完整时间线hash及事件revision。正式导出需要当前人工事件与当前剪辑审核，向renderer传segment_options.editorial_review；变化后须重新审核。首页显示标注事件总数与人工确认数。
- LS可信同步游标与事件/track在同一事务：二次编辑基于上次导入revision做CAS，旧已收hash幂等、未收旧时间409、本地修改冲突409。具体见LABEL_STUDIO.md。
- 本轮全套227 passed/2 skipped；原生WSL CPU watchdog另行实机1 passed。GPU租约33项包含争锁后新时间、孤儿锁、显式停止证据与提前撤销。
- 真实平台GPU：Edge→job-3dc9ece15e914eecb9616ac306ece6b8/attempt-1→Windows worker→WSL pose，6秒24帧、RTX5090、28.7026秒含加载解码，两产物hash/大小核验成功；events=[]，accuracy/recall=null。done证实停止，lease released，window已revoke正式归还models。不是全比赛吞吐或分层精度验收。
- 真实>8MB probe修复：job-d1e09c26b26e449193b209871a9e7d5b处理50,049,933bytes无损派生，worker成功→apply HTTP200入库；报告platform-wsl-pose-real-flow.json。
- 存储修复：慢容量扫描由独立SQLite容量锁串行，不持queue写事务，心跳不被扫描阻断；写目录每级拒绝symlink/junction/reparse，platform/models/render物理owner不可借链接绕过。
- 集成启动：新增configure-platform-adapters.ps1默认使用其所在集成仓库构造argv/PYTHONPATH；旧工作树仅本轮临时联调。服务交接前API父26020/子52252，worker父772/子34568；LS18081保持。主任务接管前由本任务核对精确命令并停止这组进程。
- 后续已提交：923bb76（业务审查修复）；0a60a83e38f90fdadc6025cbad1fa56f4abda41c（不可变LS快照，旧任务不能借新seed/CAS权限，无snapshot旧导出409须重导）；e4c2749ed9bc3c5fbd55b73790ce63f3e0c8d2c2（GPU/WSL/容量扫描/物理owner/启动配置）。主任务负责cherry-pick审查与最终服务切换，本任务未推送。
