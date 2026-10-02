## 2026-10-03 拖拽与圈选增补（进行中）

- 新授权A-11～A-14；开发前设计 [TRAINING_INTERACTION_DESIGN.md](../platform/TRAINING_INTERACTION_DESIGN.md)。合同a0fc1db已提交；UI功能及API回归已接入，真实验收进行中，整项尚未PASS。
- 继续codex/platform-training-workspace，自44bd583。18080人工实例不触碰；仅18082 agent测试。基础资料手填，无新增安装/GPU/视频副本。预算2GB内，D写入前重新预留。
- 设计：独立原生Pointer/SVG模块→controller克隆校验→原bundle CAS。区域只扩展evidence字典，不给旧snapshot添加默认字段；旧实际hash必须保持。
- 已运行：350合同/API相关PASS；新增18 ROI API PASS/无skip；最终69前端PASS/无skip。旧实际snapshot dump/hash兼容。CUA已真实拖入标签到原片61996–62996ms新建区间、点击回退追加步法、保存修订2；非人工真值。现有块投放/区间拖动/圈选真实操作仍待收束；无跳过替代PASS。
- 私有预留2GB：reservation-69b9c1c91c83492991858e757bf4d0e2，证据D:/video/platform/training-interaction-20261003；DB复用training-20261002，18082 agent。16:40:10UTC重启parent49668。无新增安装/GPU。
- 下一步：先交可集成的功能提交供root独立18084并行验证，本任务继续所有真实浏览器用例，后续修复/报告单独提交。主human18080不写。

## 2026-10-02 训练工作台（平台交付完成，10-03凌晨补齐报告）

- 分支 codex/platform-training-workspace，从 main 3dab169 建立；旧分支保留。设计先行见 docs/platform/TRAINING_DESIGN.md；最终逐ID证据见 [TRAINING_VALIDATION.md](../platform/TRAINING_VALIDATION.md)。
- 已实现并提交：兼容合同6fec08f、主体语义修复2128568、完整平台370ddfe、中文质量提示146f598、独立编辑来源37cd7f2、长标签说明折叠4258f16。训练项目/人物/回合/触球/区间/态势、可信原片/PTS、CAS历史、冻结快照、/guide/入口。交接见 [TRAINING_HANDOFF.md](../platform/TRAINING_HANDOFF.md)。
- 已运行：748后端PASS/8条件skip/81.84秒；最终18前端PASS；16/16真实原始训练来源制作隔离负例PASS。浏览器播放真实1280×720原片、32651帧PTS、保存2人物/5记录/手法步法unknown/双方图像点，CAS409保留草稿后重载修订到bundle4/project6，审计JSON下载516452B且与冻结对象一致；最终服务重启及browser重载保留全部内容。
- A-01/02/03/04/05工程PASS；A-08原始来源隔离、A-09平台手册入口、A-10私有持久化子项PASS，整项仍由root汇总。A-06/07未在本模块运行；真实派生物负例与主线旧制作链不得用当前合成alias或私有库替代。
- 服务：私有127.0.0.1:18082、独立D:/video/platform/training-20261002；末次15:54:21UTC重启parent50456/server59504，无永久worker。启动 `.\start-platform.ps1 -Port 18082 -DatabasePath D:/video/platform/training-20261002/platform.sqlite3 -TrainingReviewer agent`；真正人工操作可显式human。复用Python环境，CPU；无安装/GPU/18080或生产库操作。
- 容量：预留2GB及最终截图16MB均已释放；16:07:48UTC私有目录约3.82MB，platform204739901B/60GB、runtime/platform1048360620B/10GB、D余量922181832704B，reserved均0。原片未复制；非全模块700GB总审计。
- 失败与恢复：冲突确认框后原浏览器tab自动化超时，确认框关闭后仍不可读，换新tab恢复，数据未损坏；未将原tab原地恢复记PASS。修改清审核造成来源误显“未记录”已修复37cd7f2并回归。
- 未达标/下一步：没有专家定义/真人标签/已确认独立比赛组，真实快照0eligible/2excluded/trainable=false，正式训练下载409。主任务依次集成146f598、37cd7f2、4258f16三份UX补丁并独立完成A-08/09/10总验收；03/04消费合同完成各自用例。本轮不升级模型质量或专家真值阶段。
# Platform 状态

2026-09-29 更新。任务 01a0e88b-2410-7da0-970e-7f4187ed485f；cwd C:/Users/USER/.codex/worktrees/6991/badmintonTV；branch codex/platform-research-implementation（从 main ff2c700 新建，旧 work/platform 保留）。只提交平台及共享合同的授权范围，主任务集成，无推送。

## 本轮实现、验证与交接

- 设计：R-02a 有界代理、原始PTS与原尺寸核查；R-02b 源时间标注/循环/缩略图/浏览器计时；R-04b 训练用途制作链隔离；R-03a 可信render后端与资源租约。汇总见 [RESEARCH_VALIDATION.md](../platform/RESEARCH_VALIDATION.md)，不将 Agent 操作或模型特征升级为人类技法真值。
- 已提交：7354b1f（render后端）；a7fff391（用途合同）；4fdd200d（用途图批量性能）；b7d7a855（registry公开校验）；21e16949（心跳共享重试）；2f3fd855（WSL强制PYTHONNOUSERSITE=1）；f64a2a95（代理/用途/源身份/持久导出设置等后端）；ec8a7fc（Win5竞争消退有界恢复）；a73b485a（YOLO独立环境opt-in）；7e8a9bd6（源帧预览、取消缓存与导出UI）。19a36cc7e654630c54bd84dded9f4e440ec15145是提交协调竞态形成的组合提交，包含产物身份后端8文件及标注epoch前端3文件；代码均保留，不重写历史。前端38项通过；e1da6ee97a61eb377e2282bd6e2355a1cd8be0ff已追加exact_frame执行依赖index验证，最终607/7回归及独立API实测通过。无必须源码WIP，提交顺序见[交接单](../platform/IMPLEMENTATION_HANDOFF.md)。
- 已实现：CPU H264代理，SQLite全源PTS流式索引/分页，逐帧JPEG，显示图像与coverage分离；事件修订及独立CAS导出设置；来源图、实际SHA与动态registry在API/Store/worker中检查。旧源小于等于8MB可有界重验，大源须可信worker证明；固定模型命令与GPU后端仅由管理员配置。
- R-02a实际PASS（有界后端）：真实general短片及明确派生VFR/FFV1/60→30四例，原尺寸1280×720、独立原PTS JPEG SHA交叉核验；60→30保留278全源帧。实际32 passed，分页连接回归28 passed/5 deselected，不相加。旧派生Asset继承fps/probe侧车的限制保留；未来准备脚本重新ffprobe并拒绝覆写，31 passed/5 deselected。见[MEDIA_PROXY.md](../platform/MEDIA_PROXY.md)。
- R-02b实际测量：8组×30点=240，212零误差、28为-1源帧（60→30各14），全部绝对误差≤1。total中位数990.55–996.80ms/P95 997.30–1001.60ms；cold为独特URL/no-store媒体重载，未清OS缓存。236点完全可见、4点离屏，全部document visible；可见样本仍约1秒。此处rVFC callback等待非真实屏幕呈现耗时，原因未知，[延迟问题](../issues/platform-preview-presentation-latency.md)仍OPEN，流畅目标未达标。
- R-02b操作PASS：#61原图1280×720/2x宽2560，marks1016/1034/contact1016；#62 end1050，事件35b85b38-0321-4157-ac03-c73bee056b48 revision2重载保留。循环首轮超时count0，pause→seek+rVFC→play修复后DOM23次/截图22次，非原子采集如实保留。缩略图实点1.267s→proxy38/source76、PTS19456、coverage[1266.6667,1300)。
- 原图任务控制真实PASS：普通三次step无新exact任务；显式#61任务job-3232068ebb15432aacf59d96585d50c4在切帧后attempt0取消；#62任务job-76ab9527c53146868463ebc1bc0052b3由一次CPU worker成功。切离再返回核查命中会话缓存，总exact仍4、无queued/running，worker已退出。[队列](../platform/browser-exact-request-proof.json)/[DOM](../platform/browser-exact-request-dom.json)已保存。显式请求串行取消、成功缓存最多16项，32项JS回归通过；长片全源校验/从头解码成本未优化，[问题](../issues/platform-exact-frame-long-video-cost.md)仍OPEN。
- 导出UI→CPU成片PASS：保存60fps、safe_area .08/.12/.8/.76、youtube_shorts后重载保留。正确Agent任务job-7f8fb7431dac4a92b571d485fd1f9152 revision3，UI retry后attempt1 succeeded，实际1秒/1080×1920/60帧/H264/AAC/109708B，12项QA全true，浏览器播放到0:01/0:01。CPU单次worker结束、render锁释放。错误human快照job-cef905c866494c6a8e8515c3c3a21e6a attempt0取消并保留误标历史；成功仍human_confirmed_segments=false，不能充人类真值。
- R-04b真实负例16/16 PASS：10:05UTC的7 Asset时点和10:29UTC完整10 Asset时点各16项通过（不相加），registry均10条，14 API均422/TRAINING_ONLY，两种render worker均blocked，adapter/媒体读取/子进程均0，主DB未打开。历史业务/审核行明确为私有模拟fixture，不是成功导入或真人审核。关联render任务独立四模式CLI拒绝，见[REAL_TRAINING_ISOLATION.md](../platform/REAL_TRAINING_ISOLATION.md)；最终10项仅合同/stat/registry对应验证，逐入口fixture仍为同一b210 Asset；不称全部10来源重新hash/decode或匿名未知转码可识别。
- G-01已运行：冻结源码最终后端607 passed/7 skipped/59.12秒；最新前端38 passed（标注切源新增6组，旧源码绑定新集合32通过/6失败）。该全套已含最终产物身份与index执行依赖补强。7条件skip不计通过；历史小集不累加。实际媒体、浏览器和拒绝证据各自分开记录。
- G-02 CPU编码中取消PASS：实际CLI/FFmpeg取消后锁/PID退出，下一任务成功，实验18.391秒、CPU窗口归还，见[RENDER_CANCEL_VALIDATION.md](../platform/RENDER_CANCEL_VALIDATION.md)。心跳ec8a7fc最新60 passed/1 opt-in skipped，真实Win32共享竞争消退与ACL拒绝已测，0.7秒总预算/持续故障fail closed；[Win5记录](../issues/platform-wsl-heartbeat-win5-race.md)。models随后在main fd6155b运行TrackNet job-d9c832fd94384ee3950918badc767b15及YOLO job-57c6354813b94ad1ba12d42b24e5968e成功，本任务仅mode=ro核对均attempt1/succeeded/exit0；models报告停止和租约释放，无Win5诊断，不能称实际触发恢复分支。
- 模型环境：a73b485新增EnableExperimentalYolo，默认不登记，完整yolo11n-pose-bytetrack映射至独立yolo-env，拒绝复用主/VL环境；配置及bridge43 passed/1 skipped。BST/VL仍显式开关，未新增模型能力；[配置说明](../platform/MODEL_ADAPTERS.md)。
- 环境/启动：Windows平台Python D:/video/runtime/platform/env，CPU FFmpeg9.0.2复用，无安装/torch/GPU。验证只用本机127.0.0.1:18082和platform/research-20260929独立DB；10:34:02UTC重启后保留审阅API parent53520/child62828（上一parent59656），无永久worker，不启main18080。服务权威记录D:/video/platform/research-20260929/services.json，隔离DB+uvicorn命令见研究报告。截图全在D:/video/platform/research-20260929/browser-ui-evidence，不入Git。
- G-03容量：proxy额外880MB、exact72MB，另有worker128MB协议预留，顺序释放。09:43:04UTC完整快照platform196664848B/60GB、runtime/platform1048280806B/10GB，D盘free943960891392B；非全模块700GB总审计。真实负例预留16MB已释放，目录177280B；截图独立16MB预留后写入并校验hash，不覆盖原件。
- 失败/未测/下一步：产物身份与索引执行依赖已修复/回归；最终真实#61任务job-06a35bd0cd134c9d8c919a4ee3ec0e9a成功，5条proof匹配、旧成片Range206、私有无queued/running；约1秒回调等待与长片线性成本OPEN。模型质量、专家细标签/个人录像真值及产品阶段总验收未由本轮替代。跨聊天发送交接受到自动审批拒绝（当前可见用户指令未明确授权消息），已询问用户，未重试或绕过；本地实现与验证已完成，主任务负责集成。

## 先前基线（work/platform）

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
- 环境/容量：Windows Python3.12.11；D:/video/runtime/platform/env独立venv，FastAPI0.141.1/Pydantic2.13.5；锁定清单docs/platform/requirements-lock.txt。当时快照platform约52,921,277bytes/60GB；runtime/platform约1,048,280,806bytes/10GB（含LS与所有pip缓存）。新增约50MB为有来源记录的真实原片无损probe回归派生。任务协议/日志峰值预留128MB，日志单attempt上限8MB。只读复用FFmpeg9.0.2；GPU仅使用models已建WSL Python3.11/torch2.7.1cu128环境。computer-use技能使用本机Edge，未新增插件。
- handoff：D:/video/platform/handoff/platform-real-flow.json、platform-restart-check.json、events.v1.json、assets-imported.v1.json；成片由render owner持有，路径见VALIDATION.md。

## 上一轮 work/platform 历史：独立审查修复与 GPU 后续

- 大于8MB的probe结果直接使用worker全量hash结果入库，避免二次异步导入返回值类型错误；应用前检查文件存在和大小，Web不重复hash大文件。
- 检索改为全局有界top500，后出现的精确匹配不会被前500个未知候选挤掉。
- 时间线保存可携带明确human/agent审核人；绑定完整时间线hash及事件revision。正式导出需要当前人工事件与当前剪辑审核，向renderer传segment_options.editorial_review；变化后须重新审核。首页显示标注事件总数与人工确认数。
- LS可信同步游标与事件/track在同一事务：二次编辑基于上次导入revision做CAS，旧已收hash幂等、未收旧时间409、本地修改冲突409。具体见LABEL_STUDIO.md。
- 该历史轮次236 passed/2 skipped；原生WSL CPU watchdog另行实机1 passed。GPU租约33项包含争锁后新时间、孤儿锁、显式停止证据与提前撤销。
- 真实平台GPU：Edge→job-3dc9ece15e914eecb9616ac306ece6b8/attempt-1→Windows worker→WSL pose，6秒24帧、RTX5090、28.7026秒含加载解码，两产物hash/大小核验成功；events=[]，accuracy/recall=null。done证实停止，lease released，window已revoke正式归还models。不是全比赛吞吐或分层精度验收。
- 真实>8MB probe修复：job-d1e09c26b26e449193b209871a9e7d5b处理50,049,933bytes无损派生，worker成功→apply HTTP200入库；报告platform-wsl-pose-real-flow.json。
- 存储修复：慢容量扫描由独立SQLite容量锁串行，不持queue写事务，心跳不被扫描阻断；写目录每级拒绝symlink/junction/reparse，platform/models/render物理owner不可借链接绕过。
- 集成启动：新增configure-platform-adapters.ps1默认使用其所在集成仓库构造argv/PYTHONPATH；旧工作树仅本轮临时联调。服务交接前API父26020/子52252，worker父772/子34568；LS18081保持。主任务接管前由本任务核对精确命令并停止这组进程。
- 后续已提交：923bb76（业务审查修复）；0a60a83e38f90fdadc6025cbad1fa56f4abda41c（不可变LS快照，旧任务不能借新seed/CAS权限，无snapshot旧导出409须重导）；e4c2749ed9bc3c5fbd55b73790ce63f3e0c8d2c2（GPU/WSL/容量扫描/物理owner/启动配置）。主任务负责cherry-pick审查与最终服务切换，本任务未推送。
- 最终复核修正：取消等待保持running/cancel_requested且两条心跳继续；停止核验后才发布终态，无证据failed/WORKER_INTERRUPTED并保留GPU orphan。Queue获得写事务后重新采时，5项实际SQLite争锁回归覆盖过期续租/完成拒绝与领取时钟。未重跑GPU，未新增模型能力。

本轮最终容量快照 2026-09-29T10:40:15.626571+00:00：platform 198503318B/60GB、runtime/platform 1048280806B/10GB，D盘free 930113617920B。原快照保留于[容量记录](../platform/capacity-final-snapshot.json)，非全模块总审计。
