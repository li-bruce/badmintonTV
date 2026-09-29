# Render 状态

## 2026-09-29 实施轮（本模块交付完成）

- 设计：已读main ff2c700新轮与复用调研，见 `docs/render/ROUND_2026-09-29.md`。新分支 `codex/render-presets-acceleration`，旧work/render干净保留。
- 已实现：30/60fps命名档、安全区文字布局、Shorts总输出180秒限制、可信CPU/NVENC/auto后端、共享GPU租约核验、原始全部引用逐字节hash+公共训练用途门禁、actual fps/field_order/faststart QA。
- 已运行：最终150快测通过/1旧timeline symlink权限skip/378subtests（含新增8个固化benchmark异常回归，3.12秒）。训练门禁正反向及benchmark目录真实Windows junction均PASS；新增可达祖先实际hash核验，覆盖双方共同伪造source hash、多跳、仅hash来源及缺失/篡改父原片。FFmpeg9 CPU30/60各首次+重复3共8job技术PASS，CPU全流程约10.3–11.6秒/17秒片。证据 `D:/video/render/benchmarks/presets-controlled-cpu-beb256d1c5fc/`。
- 真实预览：`render/handoff/preset-preview-f1d7b353db`，60fps实际360×640、canonical1080×1920、定制safe_area完整保留；typed/provenance/preview/confirmed四类真实素材请求负例TRAINING_ONLY拒绝，无输出目录。
- 平台取消联测：平台独立账本实际观察FFmpeg partial.mov后取消，计算停止/.render.lock释放、后续1秒job成功；证据 `platform/research-20260929/render-cancel-cpu-r1/render-cancel-validation.json`（平台持有worker实现及报告）。
- 失败：第一次真实NVENC probe blocked/backend_unavailable，FFmpeg9要求NVENC API13.1而驱动提供13.0，见独立issue；没有静默fallback。该job/lease已停止释放，窗口4e5823beb9ca已revoke。
- 协调：平台GPU7354b1f、合同a7fff391已同步（本分支等价987848b、29d47c4）。library独占初始化有效空registry；正在下载的职业数据不进入本基准。兼容NVENC窗口`render-benchmark-6e21d23d0d7f`已在09:32:18Z撤销，active_window/lease均null，明确归还models；后续仅CPU质量任务。
- 同版本实测：FFmpeg8.0.1 CPU/NVENC各8job全部技术PASS。30fps中位10.356806/11.194288秒、文件1,009,926/2,889,238 bytes；60fps中位11.514771/12.861280秒、文件1,086,423/3,635,540 bytes。CPU/NVENC对应512/1023帧与源映射一致。当前NVENC没有速度/体积收益，默认CPU保留；不同CRF/CQ/实际码率不称等质量。详见`docs/render/ROUND_2026-09-29_RESULTS.md`。
- 质量：30/60各512/1023帧A/B/R PTS最大差0。比赛ROI SSIM/PSNR分别CPU .987977/43.194564、.986072/42.315934；NVENC .993735/48.324594、.994158/48.648447。每档9脚/3球候选ROI与五个邻近时间取样由agent技术审阅，无明显新增缺失/错帧；模糊/不可见保留unknown。独立质量报告与补证路径见结果页，不把静帧变成人工确认或连续观看验收。
- 环境/容量：独立FFmpeg8.0.1已实际NVENC成功，原9.0.2保留。09:45:43Z render646,588,608 bytes/40GB，runtime/render873,315,597 bytes/5GB，磁盘剩余943,805,825,024 bytes；09:42共享可见23,948,960,885 bytes/700GB（非原子快照，其他模块仍工作）。无端口/新Python依赖/驱动修改；质量两轮各1GB和ROI200MB预留均释放，所有本模块FFmpeg已停止，.render.lock不存在，render owner已归还platform。
- 失败/限制/下一步：FFmpeg9 API不兼容原失败保留；可显式使用compat8，默认CPU不变。原生60fps源、NVDEC、长片吞吐、连续播放听感和平台上传未测；细技法、人类内容审核和权利未知。后续由主任务集成本轮工具/报告、platform完成设置持久化与取消补丁集成，不把本模块技术通过宣布整个产品验收通过。
- 核心实现SHA：`4ecaf6dfcf0536fe95e720a612c7bfd3a9a54206`，来源闭包修复`db587aa179ea100a199fe1c67c758b74810f9307`；主任务已集成等价6518a09/281c137。平台独立render_options与Timeline ID/CAS绑定保存，重开恢复预设/安全区/profile；canonical Timeline根合同不私自增加字段。
- 本轮验证交付SHA：`f2bd7bbb0bd929ad7ebce7cf57a8a0663a17f648`，包括兼容环境/安装器、固定输入双后端基准、质量脚本与报告、8个固化异常回归、只读开销诊断。最终测试150 passed/1 skipped/378subtests，Git差异检查和脚本AST/JSON通过；未推送、未合并main、未发布媒体。

更新：2026-09-28。任务 `01a0e88b-5005-7991-9fb0-d2dec3af8b4f`；分支 `work/render`；cwd `C:\Users\USER\.codex\worktrees\3e52\badmintonTV`。

- 设计：完成 `docs/render/DESIGN.md`，先设计后实现；统一合同8900958兼容已实跑。
- 已实现：stdlib Python API/CLI、源hash与路径校验、CPU FFmpeg进度/取消/result、默认contain、归一化crop、顺序/毫秒边界/标题/ASS字幕/0.125–8x速度、显式重叠合并和回放group去重、360×640预览、1080×1920 MP4、源映射/QA/原子Artifact/容量锁。OTIO与自动目标跟随未实现。
- 已运行：48单元测试（47通过、1 symlink权限skip）；合成有声/无声、混fps/尺寸、慢放/crop，全解码。canonical实际CLI success/preview/blocked/failed/inflight-cancel全部通过，退出0/0/2/1/130。真实3段研究样片17.066667秒/512帧/1080×1920成功，中文/全场构图已代理查看，人工观看pending。
- 最终handoff：`D:/video/render/handoff/real-research-e071063a44/`；MP4与timeline/source_map/qa在`D:/video/render/jobs/real-research-e071063a44/attempt-01/`。源片只读引用library。见 `docs/render/README.md`、`VALIDATION.md`、`REAL_HANDOFF.json`。
- 环境：Windows Python3.12 stdlib；可只读复用 `D:/video/runtime/platform/env/Scripts/python.exe`。FFmpeg9.0.2 Gyan/GPLv3，官方hash核验；绝对路径见 `environments/render-runtime.json`。仅CPU libx264，线程4；无端口、无GPU、无新Python依赖或Conda/base改动。未安装技能/插件。
- 容量：最近快照render27,967,539 bytes（后续样片/回归预览仅MB级增加），runtime/render444,051,922 bytes；共享可见6,784,513,012 bytes，D盘961,284,149,248 bytes可用。所有旧失败/中间文件保留。额度render40GB、runtime/render5GB；其它owner610GB仅用于独立逻辑分配上限，不计作物理活动预留。
- 失败及修复：Git初次沙箱锁；WSL symlink容量扫描；合并审计别名；AAC21.333ms首PTS偏移；分别归零抹除源音轨延迟；GBK读UTF8；crop/fps/JSONL合同差异；fractional进度round超total。均记录在VALIDATION。
- 限制/未测：0.5x脉冲仍约38ms瞬态偏移（已量测，不宣称零偏差）；真实片源无音轨所以补静音。VFR真实输入、个人录像、NVENC/目标跟随/OTIO、旋转或非方像素crop未验。
- 外部待办：人类确认选片/身份/细手法、完整场次时间映射、原画面发布权未知；分别记录 `docs/issues/render-human-review-and-source-rights.md` 与 `render-atempo-transient-offset.md`。现有交付明确研究预览，不能声称细技法业务验收通过。
- 集成审查修复：合并审核保守汇总所有输入、容量物理free去除完整owner预算双计、预览Timeline保留正式规格可回载。62项快测61通过1权限skip；1秒定向预览实际编码与审核/回载验证通过，见REVIEW_FIX_VALIDATION.json。runtime安装器同类容量错误一并修复，历史安装报告不改。
- 追加双打：library新4K rear原片只读生成4.4秒/132帧360×640研究预览（有源音轨），全解码与统一合同通过，四人完整画面已代理查看；项目1080×1920。见DOUBLES_VALIDATION.json，handoff `D:/video/render/handoff/doubles-preview-c47d5492/`。VFR保持unknown，俯视CSV未套用，听感/身份/细标签/权利仍待核实。
- 下一步：主任务复核独立修复提交后集成，platform完成网页真实闭环；人工审阅通过后按明确来源导出正式confirmed版本。
- 实现提交SHA：`9762e9000dd90e6a23bf1e3673e8d40149310388`（work/render）；随后仅补本状态SHA记录。不推送、不自行合并main。
- 审查修复提交SHA：`6bff133e85579d4a496941440662b24ef93351ad`；追加双打验证仅增补报告，不改实现。
- 启动命令：`python -m packages.render run --request <json> --result <json> --storage-root D:/video --ffmpeg <env检查路径> --ffprobe <env检查路径> --cancel-file render/handoff/<job>.cancel`。完整PowerShell/Python示例见README。
