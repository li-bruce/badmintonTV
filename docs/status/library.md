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
- 未测：个人录像、双打识别、细手法真值、完整比赛检索泛化；双打真实下载已在追加阶段完成。平台DB/UI导入与下游渲染由相应任务报告，library已完成共享合同兼容检查。
- 阻塞/限制：原广播画面再分发权未知；FBBench无整场ID/原场偏移，保持unknown/unassigned，禁止训练测试泄漏；ShuttleSet所选CSV未配原场视频，不转换伪Event。详见source-rights-and-alignment问题。
- 下一步：首版已可交付，主任务集成；外部后续需要持权赛事/个人原片、原整场映射和人工身份/细标签复核。保留unknown/unassigned直到证据齐备。
- 实现与验证提交SHA：`9a33fe992efc526c2f932ea01d6929fa432baaf7`（work/library）；随后仅更新本状态引用的文档提交以分支HEAD为准。未推送、未合并main。
- 环境：Windows，已有Python 3.12.11；不装公共Conda，无服务端口，无GPU使用。
- 容量：data≤300,000,000,000 bytes；最终实测4,221,747 bytes（含QA/PTS/审计/账本），活动预留0；runtime/library新增0，≤5,000,000,000。共享runtime不可读部分按70GB完整上界计数，不重计。实际快照见D:/video/data/handoff/capacity.v1.json。
- 启动命令：`python -m packages.library --help`；`python -m scripts.library.acquire_small_sample --ffprobe <render共享ffprobe.exe> --ffmpeg <render共享ffmpeg.exe>`；`python -m unittest discover -s tests/library -v`。精确命令见docs/library/RUNBOOK.md。
- handoff：`D:/video/data/handoff/assets.v1.json`、annotations.v1.json、downloads.v1.json、splits.v1.json、capacity.v1.json；原片data/raw/finebadmintonbenchmark，其他任务只读。

## 追加阶段（已验证，可集成）

- 主协调已将首版两提交集成main并独立验收。追加追溯原四片整场ID/偏移/训练库重叠，补1个真实双打小样；新增下载≤1GB。
- 设计与实现：采用更小的Drone_BD独立后视视频，新增固定来源采集脚本、独立Asset/CSV/会话组/收据交接；同时完成有界ZIP中央目录检查和单成员提取能力（本轮不下载ZIP）。来源证据见DOUBLES_RESEARCH，实测见DOUBLES_SAMPLE_REPORT。
- 已运行：正常公开下载真实双打MP4 5,857,600 bytes、README 3,769 bytes、CSV 28,707 bytes；来源落盘合计5,890,076 bytes。CPU全解码132帧通过，3840×2160、4404ms、rear/doubles、完整PTS；1秒画面确认同场四人，未确认身份。
- 时基：avg_frame_rate=41100/1367、time_base=1/600，PTS间隔20/21 tick，vfr_status=unknown；未强行归30fps。无发布者SHA，只验证本地SHA及发布字节数。
- 已运行检查：最终75/75单元测试通过（9.142秒、0跳过，其中ZIP22项）；新增真实Asset被main canonical合同接受，原片/PTS哈希通过。真实文件幂等重跑以mock拒绝download调用仍成功，3来源verified_existing、0下载。
- 原件保护：原assets.v1.json SHA保持f6a646668ec688ecbbe85386f64db9d81b4c6b951a8284a1a581195cd57563aa，原4视频SHA逐一保持；新manifest/CSV清单替换有前后hash审计。
- 溯源：查全12份FBBench QA、20K官方20源重叠名单、候选0001/0003及官方演示。前三片候选0001、第四候选0003，但缺UID→源片/裁切连接；不能补偏移或确定身份，保持unknown/unassigned/null。详见PROVENANCE_RESEARCH与library-provenance-mapping-gap问题单。
- 标注：CSV130行/44列、frame2–131；作者README只给顶视标注，此片为后视，未验证机位/帧对应、未转Event；细动作unknown。BD12按发布文件夹保守合组unassigned，不是确定职业赛事或独立测试集。
- 失败/修复：ZIP自查修复失败记录遮盖原始错误、伪EOCD/ZIP64 locator绕过预检；完整回归通过。最初选57.47MB ZIP备选，找到独立6MB片后无需下载归档；没有真实ZIP解压成绩。
- 未测/限制：双打模型识别、个人录像、林李整场正常下载、职业前十样本、精确全场映射仍未完成；代码/标注/原视频许可分别unknown，不扩大授权。林李官方网页仅观看候选，无抽流。
- 容量：最终data实测10,767,716 bytes、活动预留0；项目保守记账72,479,589,615 bytes，其中runtime按70GB上界；物理余量955,508,727,808 bytes。本任务无新环境、端口、GPU使用。快照和确切验证见VALIDATION_DOUBLES.json。
- 启动：`python -m scripts.library.acquire_doubles_sample --ffprobe <共享ffprobe.exe> --ffmpeg <共享ffmpeg.exe>`；合同检查加`--manifest D:/video/data/handoff/assets.doubles.v1.json`，精确命令见RUNBOOK。
- handoff：`D:/video/data/handoff/assets.doubles.v1.json`、annotations.doubles.v1.json、splits.doubles.v1.json、doubles-acquisition.v1.json；仅小型元数据复制进docs/library/handoff，无媒体或原标注进入Git。
- 协调/下一步：已通知main、platform、models、render真实样本可读。主任务合并追加提交后由下游报告导入/模型/渲染；外部补齐权利与原片映射后才能开展独立评估。
- 下游反馈：render已报告真实双打132帧竖屏研究预览全解码/合同通过，handoff为`D:/video/render/handoff/doubles-preview-c47d5492`，报告提交e06ce8b；此为render任务验证结果，library未重复渲染或声称模型识别通过。
- 追加实现与验证提交SHA：`0cc1214917d40f49a7341d3cd7887ba1d809dc68`；随后仅记录本SHA的文档提交以分支HEAD为准。只提交library所有文件，不推送、不合并main。
