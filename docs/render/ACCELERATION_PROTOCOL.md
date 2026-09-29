# CPU / NVENC 对照协议

日期：2026-09-29。协议版本：1。设计基线：main `ff2c700`；工作分支 `codex/render-presets-acceleration`。对应正式用例 **R-03a**，关联 R-01a 的30/60fps规格与 R-04b 的训练素材隔离；不代替 R-03b 的NVDEC或模型分阶段测量，也不代替 S4-03/04 的人类内容、真实音画听感验收。

本轮实际工作只有：阅读项目合同/阶段断言、当前engine及 `docs/REUSE_RESEARCH_2026-09-29.md`，核查官方文档，运行现有FFmpeg的 `-h encoder=h264_nvenc` 帮助查询。**没有GPU编码/解码，没有安装、下载素材或生成媒体，没有性能或画质实测结果。R-03a维持NOT_RUN。** 下述数值为预先登记的实验配置，不是NVIDIA对羽球质量或速度的保证。

## 1. 先冻结断言与比较范围

| R-03a证据项 | Given / When / Then | 当前状态 / 下一步 |
|---|---|---|
| 同输入与时间 | 相同Asset hash、Timeline、源PTS、布局、音频和输出fps，只改变已登记编码配置；输出尺寸、帧数、逐段输出帧边界和源映射一致，完整解码无错 | NOT_RUN；先保存输入及两臂实际argv |
| 成本 | 每个配置执行首轮1次、重复3次，记录分阶段wall time、最终文件及视频流字节、CPU/GPU测量范围；不能把CPU布局时间称作NVENC编码时间 | NOT_RUN；补计时和报告，不承诺加速倍数 |
| 质量 | A/B分别与同一编码前无损布局参考比较SSIM/PSNR；记录比赛区域与小球/脚步截图、时序观看和不可判项 | NOT_RUN；先冻结截图点与参考生成方法 |
| 设备与失败 | 经GPU排期后执行NVENC；不可用返回明确blocked/failed，成功必须有真实硬件运行证据；取消不影响其他进程，CPU回退有独立记录 | NOT_RUN；先取得协调窗口/租约 |

完成对照并如实报告“B更慢/更大/质量更差”仍是有效研究结果，不得为通过而调低原断言。是否推荐B为默认是另一项选择：至少技术断言通过、所有约定质量检查完成且没有无法解释的退化，并在报告中明确速度/大小代价。缺GPU窗口时记录BLOCKED及解除条件；只有编译支持不算硬件通过。

## 2. 当前实现与首轮改动边界

当前 `packages/render/engine.py` 的事实：

- 原片先做hash和ffprobe；每段启动一个FFmpeg进程，使用CPU解码和CPU `setpts/scale/pad/fps/subtitles/format`，字幕字体来自已配置系统字体。
- 视频为 `libx264 / veryfast / crf=21 / maxrate=8M / bufsize=16M`，默认4线程；中间MOV含H.264和PCM 48k stereo。
- 拼接阶段复制视频，最终只编码一次AAC 160k、faststart；接着ffprobe、全解码QA、产物hash和发布。现有进度时间不等于性能分阶段wall time。
- 预览的effective尺寸与可复用Timeline正式规格分开。该A/B主结果须用1080×1920，360×640只能单列预览实验。

首轮B保持CPU解码、同一CPU滤镜图、PCM中间音轨和最终AAC路径，只把分段视频编码改成 `h264_nvenc`。不得同时加入 `-hwaccel cuda`、`scale_cuda`、GPU字幕或新缩放算法后把差异全部归因于编码器。CPU到GPU帧上传成本属于B的真实流程成本；是否显式upload须写入argv，不能把它藏在“纯编码”数字里。

同一输出fps档冻结：源区间、顺序、速度、contain/crop、背景、字幕/字体、review标记、颜色矩阵/范围、yuv420p、音频、线程预算、GOP策略、存储盘和QA范围。30与60fps分别比较；把30fps片升到60fps不增加原片运动信息，不声称原生60fps细节已验收。

## 3. 官方核查与参数起点

NVIDIA的P1–P7表示速度/质量取舍；HQ适合容忍延迟的离线导出。CQ属于VBR目标质量，码率上限可能使目标无法达到；NVENC逐帧multipass不等于整文件两遍编码。H.264不选HEVC/AV1的UHQ或split-frame方案。[NVIDIA FFmpeg指南13.1](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/ffmpeg-with-nvidia-gpu/index.html)

空间AQ可能改善观感却降低PSNR；lookahead、多遍率控和部分AQ分析会增加资源或延迟。不能只按一个全画面PSNR决定小球是否清楚。[NVIDIA编码API指南13.1](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/nvenc-video-encoder-api-prog-guide/index.html) 使用明确P编号和显式参数，避免依赖旧preset别名迁移。[官方preset迁移说明](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.1/nvenc-preset-migration-guide/index.html)

本机帮助查询路径来自 `environments/render-runtime.json`，版本为 `9.0.2-essentials_build-www.gyan.dev`。帮助列出 `yuv420p`、`p1..p7`、`hq`、`vbr`、`cq`、`rc-lookahead`、`multipass`、`spatial-aq`、`temporal-aq`、`tf_level`、`gpu`。帮助查询不创建编码会话，不证明驱动/API或此GPU支持每个组合。

| 臂 / 用途 | 首轮登记配置 | 解释 |
|---|---|---|
| A0 / 现有产品基线 | `-c:v libx264 -preset veryfast -crf 21 -maxrate 8M -bufsize 16M -threads 4` | 保留既有30fps基线。若本轮60fps预设改成12M/24M，A/B都使用相同该档上限，并将其标为新档，不能混称旧基线 |
| B0 / 本轮NVENC候选 | `-c:v h264_nvenc -gpu 0 -preset p5 -tune hq -rc vbr -cq 21 -b:v 8M -maxrate 8M -bufsize 16M -pix_fmt yuv420p` | CQ21是独立起点，**不等于CRF21或相同观感**；GPU0与平台resource=gpu0一致。未列参数沿该固定FFmpeg构建默认值；60fps的b/maxrate/buf为12M/12M/24M |
| B1 / 有明确质量问题后才追加 | B0基础上仅改lookahead/multipass/AQ之一，其余冻结 | 未执行；须单独配置ID和完整重测，不拼接不同配置的最好结果 |

这些参数片段用于受控argv生成，不是任意用户过滤器接口。实验脚本需保存完整argv和FFmpeg退出诊断。指定配置失败就报告失败；若采用自动CPU回退，报告 `requested_encoder`、`effective_encoder` 和原因，回退耗时不能进入NVENC成功样本。

主比较是“两个完整编码配置”的端到端取舍，不是假定两个编码算法相同。GOP/B-frame默认值可能不同，应从实际输出记录；若进一步做受控编码试验，给双方显式相同 `g=2×fps`、`bf=3` 等并重新命名A1/B2，不能悄悄改变A0。暂不启用去噪/时间滤波，避免对羽球瞬时小目标增加新的变化因素。

如需要“相同码率”结论，另做VBR目标码率对照，例如30fps目标6M、峰值8M、buffer16M，60fps目标9M、峰值12M、buffer24M；双方不再用CRF/CQ锁质量。这是新增实验而非A0/B0结果重命名。以**实际视频packet总字节**衡量码率/大小，音频及容器开销另列；实际大小差超过预登记的±5%时，不能称等码率比较。若需要“同画质速度”，须先在开发小窗调到已登记质量标准，再冻结参数重测，不能拿相同CRF/CQ数值代替校准。

## 4. 样本、GPU窗口与容量

1. 只读复用 `usage_scope=general` 的现有研究素材及handoff；两个小Timeline分别覆盖2–3段单打、已有4K双打有声素材，包含1×与慢放。`training_only`、`data/training/`及用途冲突必须拒绝，研究预览不豁免。来源/球员/细标签未知照实保留。
2. 每个Timeline先把输出控制在30秒内；30/60fps单列。同一case两臂输入request除job/attempt/output和编码配置外完全一致，另存排除执行字段后的比较指纹。
3. 先和models协调实际GPU窗口或平台租约，再运行B；无GPU权限时只写协议/跑CPU。A/B都不与其他重型测试并发。记录开始/结束、GPU型号/UUID、驱动、CPU、OS、电源状态、可获取的温度/利用率、监控间隔、并发活动；无法观测的值写null，不填0。
4. 产物都位于 `D:/video/render/experiments/<case>/<profile>/<attempt>/`，不复制library原片。复用render独占锁/预留账本；40GB总额度包括历史产物、参考、截图、全部重复轮次、失败中间件。runtime/render仍为5GB，不能借50GB总安全余量。
5. 下节的1080×1920 yuv420p无损参考，按未压缩上界预留约3,110,400 bytes/帧：30秒30fps约2.80GB，60fps约5.60GB，再加封装/日志余量；不得假定FFV1一定压到某比例。先5秒参考小窗再按额度扩展，两种fps可分次建立参考。若一次保留A/B各4轮，按8套完整job峰值加参考/截图估计，不只算最终MP4。无损参考不受旧engine的8Mbps成片估算覆盖，需单独预留并监控实际字节。已有文件不自动删除或覆盖。

## 5. 冷1热3与分项时间

使用单调高精度时钟，例如 `perf_counter_ns`，另保存UTC开始/结束。以下是**本项目测量定义**，不是设备标称吞吐。

| 字段 | 边界 / 含义 |
|---|---|
| `queue_wait_ms` / `gpu_lease_wait_ms` | 入队或等待排期，单列，不混入算法比较；用户感知总等待可另加 |
| `job_wall_ms` | CLI启动到result文件原子发布和进程退出；含导入/校验、hash、探测、编码、QA和发布 |
| `preflight_wall_ms` | 输入校验、额度检查、源hash、ffprobe及字幕准备，定义不可跨臂改变 |
| `segments_wall_ms` / `segment_wall_ms[]` | 每个分段FFmpeg Popen前至wait返回；包含进程初始化、源I/O、CPU解码/布局、上传、编码和中间件写盘 |
| `assemble_wall_ms` | concat、视频copy、一次AAC及faststart |
| `probe_qa_wall_ms` / `decode_qa_wall_ms` | 最终探测及全解码，双方采用相同CPU QA路径 |
| `publish_wall_ms` | 产物hash、metadata与result发布；计时区域避免与上项重复 |
| `quality_analysis_wall_ms` | 参考生成、SSIM/PSNR和截图，属于实验附加成本，另列，不塞入产品导出时间 |

逐阶段相加应能解释job wall差值；Python导入、日志与未计入准备等残差单独列明。当前FFmpeg的 `out_time_us` 只表示媒体进展，不能拿它做wall timer。FFmpeg内部解码、滤镜、编码是流水线重叠工作，未做profiling不能通过相减两个独立命令“算出纯编码耗时”。可选decode-only/filter-to-null或无损参考decode+encode只能作为标明范围的诊断。

每臂登记 **C0 + W1/W2/W3**，全部保留：

- C0定义为 `first_observed_run`：该case/config在本窗口第一次完整新进程执行，`os_cache_state=uncontrolled`、`gpu_context_state=new_per_segment`。不能称为冷磁盘或冷驱动基准：源hash已读完整原片，图像核查/另一臂也可能预热OS缓存，FFmpeg每段均创建新进程/编码会话。
- W1–W3为同机同窗口的重复运行，仍是新进程；只表示可能已有OS/驱动缓存及较稳定设备状态，不意味着复用GPU编码上下文。不能从这三次推断整场长期稳态。
- 理想研究顺序为A/B交错；本轮受GPU排期及首构建兼容失败影响，实际采用整组CPU30/60先行，然后整组NVENC30/60（每档首次+重复3）。这是明确的协议偏离，可能含热状态/系统负载顺序偏差；不宣称消除了该偏差，不报统计显著性。两臂不会并发测“各自最快”，失败轮保留。
- C0单独报告；热3报告全部原始值、中位数、min/max。n=3不报有意义的P95或统计显著性，不把冷轮丢掉后写“平均全部耗时”。失败轮不静默剔除。
- `speedup_job = median(A_W.job_wall_ms) / median(B_W.job_wall_ms)`；同时给segments级比值、`RTF_output = job_wall / output_duration`、输出帧/s。慢放另列源窗口总时长，避免把播放变长误说成处理更多独立帧。短片结果不外推100小时数据。

## 6. 质量参考、SSIM/PSNR与对齐

**参考R必须来自原片经同一CPU布局/变速/fps/字幕处理后的编码前帧**，保存为FFV1/yuv420p等逐像素无损参考或以受控管线重生成。R与两臂共用相同CPU滤镜图、颜色处理和frame selection；保存参考参数、帧数、hash、生成耗时。不能把A的有损H.264成片当唯一真值：A对A是完美分数，会系统性偏向A。原片4K横屏也不能直接和1080×1920成片算指标。

FFmpeg的SSIM/PSNR需相同尺寸、像素格式和逐帧对齐输入，可输出逐帧stats。先确认帧数/PTS对应，再做指标计算。[FFmpeg指标说明](https://ffmpeg.org/ffmpeg-filters.html#ssim)、[PSNR说明](https://ffmpeg.org/ffmpeg-filters.html#psnr)

测量步骤：

1. 在任何归零/重定时操作前，检查A/B/R所有解码帧的PTS、帧数、首末时刻、片段拼接边界；输出共同1/90000 time_base时，候选差不得大于1 tick。原有流起始<1ms、全解码、帧数/时长QA也必须通过。发现整体偏移先FAIL时间项，不能用 `setpts` 抹平后称时间正确。
2. 对齐通过后，指标管线可统一time_base并归零；不额外resize或插帧，不用shortest截掉不匹配尾部假装通过。实际比较帧数必须等于已登记输出帧数。
3. 分别计算 `A vs R`、`B vs R`，可补 `A vs B` 但仅称差异。记录Y/U/V和overall、每帧值、有效帧数、SSIM均值/低分位/最差帧。PSNR汇总采用全样本MSE推导，不能算每帧dB的简单平均来冒充同一指标；完全相同帧的Infinity单独编码，JSON不得写非法Infinity。
4. 报告三种空间范围：整张成片、真实比赛画面矩形、预登记小球/脚步ROI。contain背景和静态标题会抬高全画面分数，因此比赛画面指标必须单列。真实比赛矩形取实际scale/pad几何，不把固定58% band全部当成画面；16:9内容通常还在band内留边。
5. ROI在R上冻结并对A/B用同一坐标，不在看到某臂的编码效果后移动到更清楚的位置。裁剪要说明源/输出坐标、yuv420对齐方式、是否含边框。指标在未放大像素上算；截图放大仅供看细节。
6. 首轮A0/B0不声称客观质量等价；分数与大小联报，没有预先认定的“SSIM≥某常数即可看清羽球”。空间AQ候选另立配置，不能用它与关闭AQ的结果直接得出编码器固有优劣；若目标是测AQ的观感收益，仍保存分数并说明分数可能逆向变化。

若复用参考后单测encode，应命名 `reference_decode_plus_encode`，同时记录FFV1读取/解码和帧上传；该数字不能替代实际原片导出的job wall。

## 7. 小球与脚步的截图/观看取点

取点先在原片/R上进行，写入小型 `quality_points.json`；每点保存 `asset_id/source_sha256/segment_id/source_pts/time_base/source_ms/output_frame_index/output_pts/roi_xywh/selection_reason/visibility/reviewer_type`。从源PTS映射到输出显示帧，允许有明确记录的重帧；不能用原片平均fps猜源帧。未找到可见小球/脚部的案例标unknown，不补造“好看”的位置或认定某细手法。

| 取点类别 | 预登记方法 | 看什么 |
|---|---|---|
| 准备 / 击球附近 / 结果 | 每段从可见动作连续过程各选一点；“击球附近”不冒称已核验contact真值；每点额外看前后相邻2个源显示帧 | 上下文完整、羽球是否因编码新消失、拍/肢体边缘破碎与闪烁 |
| 小球高风险 | 每个可判段至少选亮球经过亮线/球网、快速飞行或远端小球中的两个不同场景 | 参考已有的球像素/轨迹线索是否保留，块化/拖影是否新增 |
| 脚步高风险 | 双脚可见时选启动、最大步幅/着地附近及回位；双打至少覆盖近/远场不同人物 | 鞋/脚踝与地面边界、两脚分离、足部是否出画；不以像素改善声称步法识别成功 |
| 拼接 / 慢放 / 字幕 | 每个拼接点前后各一输出帧；慢放区间首尾；最长中文字幕帧 | 顺序/边界、重复尾帧、字幕覆盖、音画/帧节奏是否异常 |

每点输出R/A/B同帧的全画面与相同ROI；可把原始source crop放旁边解释缩小本来已丢失多少细节，但指标参考仍为R。展示native 1×与统一4×最近邻放大，不对某一臂额外锐化/降噪。A/B视觉标签可随机盲化并保存解盲表，避免预设硬件一定更差/更好。

静帧之外，逐段正常速度和慢放连续播放，记录球闪烁/边缘跳动与脚步连续性；截图不能证明时序质量或真实音画同步。每点判定 `no_observed_regression / regression / unknown`，附具体差异和审阅者类型。agent可做技术审片记录，不能改成human选片确认、技法真值或S4-03/04通过。参考本身看不见的细节，不算任何编码器的成功。

## 8. 运行记录与交接

每次run JSON至少记录：case_id、R-03a、protocol_version、代码SHA、配置ID、完整argv、FFmpeg/ffprobe hash与buildconf、Asset/Timeline/参考hash、effective尺寸/fps、source/输出总时长和帧数、job_id/attempt_id、GPU租约证据、C0/W编号与实际执行次序、cache标注、所有wall time、输出字节、视频packet字节、QA/quality文件引用、资源监控的测量方法和缺失值、状态/失败原因。不能只保留最快一次。

实验总表按 `case × fps × profile × C0/W1/W2/W3` 分行，另附热3汇总与质量对比。技术QA、图像质量、性能收益、设备可用性、业务人类审核分别列状态。R-03a的实际输入、预期/实际、PASS/FAIL/BLOCKED/NOT_RUN、证据、未达标原因/下一步写回render状态，由主任务维护阶段总表；本协议本身不更新任何实测PASS。

交接只包含已完整写入并校验的产物；失败/取消中间件保留明确名称和容量记录。无平台上传、无公开发布、无驱动或共享Conda修改。若NVENC没有收益，保留CPU默认并报告瓶颈证据，再由主任务决定是否开展独立NVDEC/GPU缩放实验。
