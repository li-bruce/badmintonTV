# Render 状态

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
- 下一步：主任务复核独立修复提交后集成，platform完成网页真实闭环；人工审阅通过后按明确来源导出正式confirmed版本。
- 实现提交SHA：`9762e9000dd90e6a23bf1e3673e8d40149310388`（work/render）；随后仅补本状态SHA记录。不推送、不自行合并main。
- 启动命令：`python -m packages.render run --request <json> --result <json> --storage-root D:/video --ffmpeg <env检查路径> --ffprobe <env检查路径> --cancel-file render/handoff/<job>.cancel`。完整PowerShell/Python示例见README。
