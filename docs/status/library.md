# Library 状态

## 2026-09-29 当前状态：本轮实现与完整数据核验已完成

- Fine完整原ZIP、22成员提取、10/10视频全CPU解码+完整PTS、9817原CSV全部完成；980703帧与作者精确一致，实际38592556ms。真实VFR时基误报已修复并完整复验。代码提交`acd0225a748d1b2751668a2b4eca73078f3f12db`已由主任务集成为main4dc9125；独立主线又核对10个原片与PTS哈希全部通过。
- BFMD原顺序下载器自然完成121/121，1825439459 B、0失败、121次尝试、0续传，未杀进程或实际切双流。全量严格审计121份（115活动JSON+1备份+根5）20.297秒、exit0、缺项/JSON/完整性错误0；Pose12份含317734个组内帧记录，不能称唯一原片帧数。
- 全部新素材双training_only，Fine split=unassigned，BFMD unmatched；新Event0、生产DB写入0。最终typed/guard检查新10拒绝、旧5允许、20纯metadata别名拒绝；原生产manifest哈希不变，未知比赛内容重叠不由SHA交集0替代。
- 真实QA10/10，共397365 B；4张可见球场主体（1张清洁场地），6张人物/场边镜头，未挑图、未认身份或标注边界。
- 语义/许可限制仍BLOCKED：Fine双语类别映射及帧端点未确认、processed clips非无剪辑整场；BFMD无原视频/PTS并有回合数差异；细手法/步法unknown，不具新公开再分发许可。详见`docs/library/TRAINING_DATA_ACCEPTANCE.md`与两份数据报告、独立问题单。
- 18:32:18容量：data14802357491 B（300GB额度）、active reservations0、物理剩余931035758592 B；项目保守账92.252GB包括runtime70GB配额上界。runtime/library新增0、无安装/端口/GPU；所有原媒体与原失败/孤立PTS保留。
- 最新完整工程回归181/181、0skip、19.476秒。新BFMD两worker/停止标记27目标测试通过，独立审阅确认submit登记、停止入口和Python3.12重复中断join三个竞态已修，另6项关键回归通过。真实网络双流/Range恢复/停止仍NOT_RUN，不为获得该成绩重下数据。
- 实际数据审计已独立提交`af9d5e8b658d5c2574d3bf4a995dff2ddca409b8`；最终并发实现和测试结果独立交主任务集成。library本轮完成；后续仅由主协调进行模块集成，并在有作者规则/持权原片/人工复核后解除已列语义限制。完整字段/路径/SHA、许可、启动命令及资源见`docs/library/TRAINING_DATA_ACCEPTANCE.md`、`RUNBOOK.md`、`TRAINING_CAPACITY.json`。不推送、不自行合并main。

## 2026-09-29 18:17 历史执行快照

- 分支 `codex/library-training-datasets`，本任务只写 library 边界。实现 `a9047d1`、BFMD稳定清单修复 `1aa32b5`、ZIP Unicode严格兼容修复 `e8331d3` 已交主任务集成；没有推送或自行合并 main。
- Fine-Badminton完整包下载已完成：6,455,837,331 B，作者 MD5 `cb3fcaca0ae9b08c564ac2a19ae4e7a0` 验证通过，本地 SHA `a3518f52d66dd6c5d2b01ce1347de8e589516ccc24a72aae818fea64e0b04439`。一次连续200连接3354.23秒，无续传。
- 真实解压22/22完成：10个作者处理过的视频片段、10 CSV、README和LICENSE，原件6,467,329,596 B。第一次Unicode Path拒绝和失败收据保留，修复后复用3项、完成其余19项。ZIP+原件12,923,166,927 B。原README并不保证完整未剪辑比赛。
- 媒体真实通过8/10：742,487帧、29,070,236 ms，全片CPU解码和完整原序PTS逐一通过，已发布双 `training_only` typed Asset。源SHA先登记10/10，再增量发布可信manifest。原生产5条和两个manifest保持不变；20项改名/改路径/去provenance的metadata-only别名检查仍全部TRAINING_ONLY，不冒称物理复制测试。
- 失败：2017World片段的FFmpeg null输出报告重复DTS，首轮停止，未发布该Asset。并行的2014Asian已生成完整PTS但没有被该失败循环发布，也不当作通过。原错误只有4000字符异常尾部保留；新独立全源PTS诊断和窗口A/B正在记录，未屏蔽stderr、排序、去重或改写视频。
- 标注实测9817行，9份English CSV覆盖29个原标签，2010Asian为31种中文原字串；合计60原字串不等于60语义球种。5条完全重复、3条零长度及其他时序诊断保留；帧基数/端点/原广播偏移仍未知，0个Event转换。具体见 `docs/library/FINE_BADMINTON_2026_DATA_REPORT.md`。
- BFMD健康单网络writer持续运行。18:11:55实测115/121，已验证861,488,631 B，剩余约947,304,684 B；近期0.19–0.20 MB/s，预计79–83分钟但会随速率变化。正在授权范围内测试同owner两连接协调器；测试通过和可安全保留partial后才切换，不另启互抢writer、不绕403/429。
- BFMD当前审计区分12单打11301拍和7双打5450拍；metadata单打1058回合与手工表1054差4，19场手工合计1688与作者overview1687差1；12 caption实际11301全部有refined字段，但作者人工修订声明未经本任务逐条复核。未下载BFMD视频，0个Asset/Event，保持unmatched/training_only。报告会在121项完整后刷新。
- 5张真实训练QA截图和收据165,998 B均只在训练子树，CPU1线程、原SHA前后与完整PTS核验。2张球场主体可见、3张转播近景，不能证明全片球场可见、球员身份或动作真值。
- 最新完整库回归165/165 PASS、0skip、15.511秒（e8331d3）；新PTS修复/并发下载器尚在独立验证，不能纳入此数字。Render实际4种入口均TRAINING_ONLY阻止且0子进程/0媒体产物，证据 `D:/video/render/handoff/training-denial-5f1e29d2eab9/validation.json`；平台和模型后续结果由对应模块验证。
- 环境：既有Miniforge Python3.12.11、只读复用平台Pydantic环境/主线contracts、FFmpeg9.0.2；没有新依赖/新环境/端口/GPU。数据在D:/video/data，library数据硬额300GB、runtime5GB；BFMD批次预留2.5GB和每流实际上限，probe曾预留1.33GB，失败退出已释放。最终容量快照待所有writer退出。
- 下一步：完成两份媒体诊断与独立复验，完成BFMD剩余文件并刷新严格审计，补齐10份QA，提交独立代码修复和实际数据报告供主线复核。精确启动命令见 `docs/library/RUNBOOK.md`。

## 2026-09-29完整训练数据实施（以下为按发生顺序保留的历史记录）

- 新分支codex/library-training-datasets从main ff2c700创建；原work/library保留，git cherry确认既有五提交已被main等价集成，切换前清洁。
- 已读本轮IMPLEMENTATION_ROUND、CONTRACTS、STAGE_ACCEPTANCE及实际文件REUSE_RESEARCH_2026-09-29.md。仅负责library，不追加制作库/生产DB，不制作集锦。
- R-04a预期：完整公开ZIP的官方bytes/MD5、本地SHA、安全解压、10场逐场探测及原CSV真实语义/总数核对；当前下载进行中，完整验收仍NOT_RUN。
- Zenodo官方API确认record20292976/v1.0，唯一ZIP 6,455,837,331 bytes，MD5 cb3fcaca0ae9b08c564ac2a19ae4e7a0。API license为CC-BY4.0但description限定非商用学术研究，视频版权仍原权利人；同时记录并从严training_only。
- 写入仅D:/video/data/training/fine-badminton-2026-zenodo-20292976-v1.0；下载峰值暂预留40GB，解压声明总额硬限20GB，完整ZIP到齐后精确核算，超限停在原件不解压。
- R-04b预期：data/training/handoff/training-registry.v1.json可信SHA用途登记先原子发布，后发布新typed合同校验的training-only manifest；split先unassigned。publisher和共享合同夹具联调已通过；十场真实媒体端到端仍NOT_RUN。
- 并行：官方源/论文语义核验、有界ZIP64兼容（>4GB包），本轮代码和验证SHA待完成后记录。既有生产handoff不写；无GPU、端口或环境安装。
- 真实进度：2026-09-29 17:42:34本地完整ZIP下载完成（3354.23秒、1次连续200响应、无续传），6,455,837,331 bytes；作者MD5 cb3fcaca0ae9b08c564ac2a19ae4e7a0通过，本地SHA a3518f52d66dd6c5d2b01ce1347de8e589516ccc24a72aae818fea64e0b04439。连接无ETag/Last-Modified；此前额外两公开URL Range/HEAD均403，无绕过。十场实际probe及完整R-04a尚未完成。
- 空registry已原子初始化为schema_version1.0/assets[]，SHA5d7572aea12757f02e262b10a65d217103152bd1e6ffe835a2347c2fceb251a1，明确已验证媒体数0；通知platform/root/render。初次因版本名v1.0不在白名单失败，已修复安全点号并加回归，原数据路径未改。
- 最新完整工程回归149/149通过、0skip（13.868秒）：32项ZIP/ZIP64、25项training publisher、10项完整包采集边界、8项BFMD选择边界、17项Drive公开确认及既有下载/探测/CLI检查；不计作真实R-04a/b已PASS。
- 共享合同a7fff39已由root集成为main2850123；本任务cherry-pick被自动审批以越library模块边界拒绝，未重试/绕过，改用--contracts-root对main合同只读验证，不写contracts目录。
- 追加BFMD已获主任务授权：先只读独立枚举，待本ZIP writer结束后顺序下载annotations与5根文件（不运行YouTube脚本、不下载其视频），预留2.5GB；缺媒体保持unmatched，不造Asset。
- 已实现：标准单卷ZIP64、原member短路径映射、完整包三阶段采集、先登记用途后typed manifest增量发布、严格来源引用校验、训练子树审计、BFMD精确121项选择摘要锁定与公开Drive确认适配。独立review修复UUID落盘、重跑清单缩减及失败后未启动探测取消；原生产5样本和manifest不改。
- BFMD配置实测枚举总1,825,439,459 bytes：115活动JSON、1个备份、5根文件，下载NOT_RUN。两种源的逐文件真实标注核验方案见ANNOTATION_AUDIT_PLAN；不同模态不重复计拍、未知时基不造Event。
- 本机LongPathsEnabled=0，不改系统设置；解压目标按原member SHA前24位生成短名，MP4含最长收据临时后缀仅152字符。原名/对应关系保留ZIP与inventory。
- 实现提交`a9047d19b8c38ea5171682237ff975ba3c6c3517`在149项单测及review后生成，仅library所有目录；纯实现已交主线集成，下载进程继续，真实结果稍后独立提交。启动命令、现有Python/平台Pydantic/FFmpeg来源及容量预留见docs/library/RUNBOOK.md；新环境0、端口0、GPU0。
- BFMD清单重跑修复提交`1aa32b5c8f3e192d5ea86494f55a46133d4c7600`：稳定verified清单与本run进度分离，旧目录/文件/receipt严格复核，批次锁，禁止预检后将旧SHA绑定新同尺寸字节。完整155/155 PASS，0skip，15.226秒。main已集成两提交为041a5a9+a2f0eaf；不把夹具通过算真实数据下载完成。
- 实际ZIP64目录通过：22普通成员（10视频、10CSV、README、LICENSE），解压声明总6,467,329,596 bytes，ZIP+原件12,923,166,927 bytes。首轮提取3成员后在标准0x7075 Unicode Path全角！上安全停止：orig_filename为CP437原名字串，filename为正确Unicode扩展，旧检查一概视作不安全规范化；失败收据保留且无partial，严格兼容修复进行中。
- 原包实证：README/LICENSE均CC BY-NC4.0，README另外限制再分发，并称processed video clips，不能称10无剪辑整场；CSV列start/end/label/location，帧基数/结束端点规则仍未说明。API cc-by4与包内许可并列记录。
- BFMD唯一网络writer在完整ZIP校验后启动；17:47:55实测已81/121文件，0失败，仍IN_PROGRESS。已验证根CSV/README显示match_index只含12单打且TOTAL1054，与README1058待对账；11301拍是12单打口径，不是19场含双打合计。真实JSON核验进行中，不造视频Asset或Event。

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

## ZIP压缩器追加修复

- 主协调独立review指出BZIP2/LZMA的内部解压分配不受read长度约束；已在打开选中成员前仅允许STORED/DEFLATED，其他返回unsupported_compression，记录失败且不创建partial。
- 验证：新增两种真实压缩格式的本地拒绝测试，强制禁止container.open；完整77/77测试通过、0跳过（9.151秒，其中ZIP24项）。原75项交付结果保留为历史，最新结果以本节为准。
- 问题与范围：docs/issues/library-zip-compression-memory.md；本轮无下载、无共享盘素材/清单改动、无新环境/GPU/端口或数据容量增长。
- 提交：本节随`fix(library): reject unbounded ZIP codecs before extraction`独立修复提交；精确SHA随主任务交接消息提供，当前work/library HEAD可核验。下一步由主任务集成该修复。
