# Library 状态

- 日期：2026-09-28；任务：01a0e88b-31fa-7fd3-939c-b7e0c895deef。
- cwd：C:/Users/USER/.codex/worktrees/9163/badmintonTV；分支：work/library。
- 设计：已读取六份约定文档；见 docs/library/DESIGN.md。
- 已实现：stdlib配额事务账本、流式受限下载/校验/安全断点、CPU媒体探测与PTS、v1.0 manifest校验/去重/整场划分、CLI、小样脚本；13个来源候选与一手来源报告。
- 已运行：4段真实FBBench视频（合计2,402,653 bytes、约19.901秒）发布者SHA核验和全段CPU解码；10个来源文件完成取回；原QA200+250条、ShuttleSet原CSV366条；4张1秒处画面检查。handoff已通知四模块。
- 失败：普通沙箱 Git 分支写入受主仓库路径边界限制，改用获授权的提升执行；使用单命令 safe.directory，不改全局Git配置。
- 测试：最终53/53通过、0跳过（8.202秒）；原符号链接权限不足项改用真实Windows junction越界测试。包含4进程配额争抢、HTTP中断/超限/不覆盖、split冲突、模拟probe边界、CLI owner/大小限制、孤立PTS恢复与审计。真实probe另有4段全部通过，不能将模拟probe测试算真实识别成绩。
- 合同：平台原提交6a3e3deb / main集成8900958对应Pydantic AssetManifest接受4个真实Asset，library校验器接受1个canonical结构fixture（不声称fixture媒体存在）；原片及PTS哈希4/4再次验证。
- 幂等重跑：10来源文件全部verified_existing，0新下载、0错误；原片/探测未覆写，acquired_at取原下载时间，handoff再生成保存前后hash审计。rear/singles及计分牌观察入provenance，球员身份仍unconfirmed。
- 失败与恢复：Windows无法遍历models WSL环境链接导致第一次预留失败，无视频写入；已改为其他owner按完整配额上界计数，实际下载成功。详见docs/issues/library-windows-wsl-capacity.md。
- 未测：个人录像、双打真实下载与识别、细手法真值、完整比赛检索泛化；平台DB/UI导入与下游渲染由相应任务报告，library已完成共享合同兼容检查。
- 阻塞/限制：原广播画面再分发权未知；FBBench无整场ID/原场偏移，保持unknown/unassigned，禁止训练测试泄漏；ShuttleSet所选CSV未配原场视频，不转换伪Event。详见source-rights-and-alignment问题。
- 下一步：首版已可交付，主任务集成；外部后续需要持权赛事/个人原片、原整场映射和人工身份/细标签复核。保留unknown/unassigned直到证据齐备。
- 实现与验证提交SHA：`9a33fe992efc526c2f932ea01d6929fa432baaf7`（work/library）；随后仅更新本状态引用的文档提交以分支HEAD为准。未推送、未合并main。
- 环境：Windows，已有Python 3.12.11；不装公共Conda，无服务端口，无GPU使用。
- 容量：data≤300,000,000,000 bytes；最终实测4,221,747 bytes（含QA/PTS/审计/账本），活动预留0；runtime/library新增0，≤5,000,000,000。共享runtime不可读部分按70GB完整上界计数，不重计。实际快照见D:/video/data/handoff/capacity.v1.json。
- 启动命令：`python -m packages.library --help`；`python -m scripts.library.acquire_small_sample --ffprobe <render共享ffprobe.exe> --ffmpeg <render共享ffmpeg.exe>`；`python -m unittest discover -s tests/library -v`。精确命令见docs/library/RUNBOOK.md。
- handoff：`D:/video/data/handoff/assets.v1.json`、annotations.v1.json、downloads.v1.json、splits.v1.json、capacity.v1.json；原片data/raw/finebadmintonbenchmark，其他任务只读。
