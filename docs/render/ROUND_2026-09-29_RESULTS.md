# 2026-09-29 渲染实测结果

本轮实现30/60fps档、安全区、Shorts总输出限制、训练用途拒绝及受租约保护的NVENC。兼容FFmpeg8.0.1下，CPU与NVENC各8次真实研究样片均通过技术QA；这组约17秒短片的NVENC端到端耗时更长、文件更大。默认继续CPU；`auto`只判断硬件可用性，不是自动选择最快或最小文件。画质结论见独立质量报告，不能把CRF21与CQ21当成等质量。

## 用例状态和范围

| 用例 | 本模块证据 | 状态范围 |
|---|---|---|
| R-01a | 同一三段真实时间线，30/60fps、1080×1920、H.264/yuv420p、AAC48k、逐行、faststart、帧数、源映射、完整解码；额外360×640预览保留canonical1080规格 | 技术PASS；平台上传NOT_RUN，人工内容审核pending |
| R-03a | 同FFmpeg8.0.1 CPU/NVENC各首次+3复测，分阶段计时、大小、无损参考指标和GPU租约证据 | 编码/映射/指标PASS；agent视觉观察单列，人工业务审核pending |
| R-04b | 直接CLI/preview/research_preview/confirmed、typed/provenance、物理/逻辑路径、可信registry、去重前引用及多跳来源实际字节 | render侧PASS；整个产品导入/选片门禁由主任务汇总 |
| 原生60fps / NVDEC | 当前源均30fps；本轮CPU解码及CPU滤镜 | 原生60fps源缺口；NVDEC NOT_RUN |

library真实训练Asset到位后的补证：固定ID `asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913`在standalone、preview、research-preview、测试confirmed四个独立CLI模式中均exit2/TRAINING_ONLY，0媒体子进程启动尝试、无渲染job输出。见`REAL_TRAINING_DENIAL_2026-09-29.md`及`render/handoff/training-denial-5f1e29d2eab9/validation.json`；不是把旧general小样改flag冒充本轮实际训练Asset。

最终单元回归为150 passed、1旧timeline symlink权限skip、378 subtests（3.12秒）；包含新固化的8个benchmark异常回归。训练门禁与基准目录边界的真实Windows junction均运行PASS。新来源闭包验证覆盖共同伪造hash、仅hash来源、多跳、缺失/篡改祖先文件。依赖公共合同helper；未宣称能识别完全抹去且无法追溯的来源信息。

## 固定输入和设置

原请求 `configs/render/real-research.request.json`，只读引用旧general小样；未使用本轮新`data/training`职业数据。每次对原始引用和所有可达祖先校验实际SHA，再经公共用途门禁检查。

| 源asset SHA（asset_id为`asset-`加SHA） | 相对路径 | 源区间ms | 速度 |
|---|---|---|---|
| `5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90` | `data/raw/finebadmintonbenchmark/video_001951.mp4` | 0–6000 | 1.0 |
| `9051c7ba4daba25f1206555d73c5ee2f5c5dfff8f5749a2cc883571379536956` | `data/raw/finebadmintonbenchmark/video_000002.mp4` | 0–5367 | 0.75 |
| `58aecdab108bd1e1332fb5b45811cc5c4f6e0f2f5987b7da3e98c7345ddc1a13` | `data/raw/finebadmintonbenchmark/video_000003.mp4` | 0–3900 | 1.0 |

三源均1280×720、30fps、无音轨，成片补静音；contain完整保留原画面并加研究预览标记，未生成/替换比赛动作。源比赛身份、细手法和原视频公开发布权未知，数据集标注许可证不等于原视频授权。

Windows本机：Intel i9-13900K，24核/32逻辑处理器，物理内存68,482,469,888 bytes；RTX5090、32,607MiB、驱动591.86。Python复用`D:/video/runtime/platform/env/Scripts/python.exe`，无新Python依赖、Conda/驱动/PATH改动。CPU解码、缩放/补边、ASS和完整解码QA均4线程。NVENC只负责视频编码。

CPU：`libx264 -preset veryfast -crf 21`；NVENC：`h264_nvenc -gpu 0 -preset p5 -tune hq -rc vbr -cq 21`，目标码率30fps为8M、60fps为12M。两者相应maxrate8M/12M、bufsize16M/24M，yuv420p，中间PCM48k，最终一次AAC160k。完整命令见每job的`stage_timings.json`。

默认safe_area为`{x:0.06,y:0.10,width:0.82,height:0.78}`；只影响文字布局，不裁源画面、不烧入边界线。Shorts profile可选，以速度及剪辑后的总帧数/fps严格限制180秒。30fps素材导出60fps不增加真实动作信息。

## 同版本速度、大小与映射

环境精确路径/hash/来源见 `environments/render-runtime-compat.json` 与 `ENVIRONMENT_COMPAT.md`。CPU先30再60，随后NVENC先30再60，分组顺序没有交错随机化；首轮前已读源hash，不能称冷缓存。每档复测仅3次，不报告P95、显著性或长片泛化。

| 输出/编码 | 首次观测s | 三次复测s | 复测中位s | 最终MP4 bytes |
|---|---:|---|---:|---:|
| 30 CPU | 10.388064 | 10.516722 / 10.322885 / 10.356806 | 10.356806 | 1,009,926 |
| 30 NVENC | 11.256507 | 11.160959 / 11.266110 / 11.194288 | 11.194288 | 2,889,238 |
| 60 CPU | 11.604480 | 11.738829 / 11.514771 / 11.429068 | 11.514771 | 1,086,423 |
| 60 NVENC | 12.694029 | 12.870954 / 12.861280 / 12.624131 | 12.861280 | 3,635,540 |

30fps各512帧/17.066667秒；60fps各1023帧/17.05秒。两档时长差来自各片段半帧以内量化，CPU/NVENC同档完全一致。字幕、安全区、源hash/起止/速度/映射一致。NVENC中位耗时较CPU多约8.1%/11.7%，MP4为CPU约2.86/3.35倍；不是同等质量效率结论。

计时包含同一个平台worker、全新CLI、源/环境预检、渲染、完整解码及结果校验；不含前一次job后的报告落盘和下次入队间隔。各阶段都是真实subprocess elapsed，段内同时解码/滤镜/编码，不拆称纯编码时间。

| 复测中位s | 30 CPU | 30 NVENC | 60 CPU | 60 NVENC |
|---|---:|---:|---:|---:|
| NVENC可用性probe | — | 0.249232 | — | 0.271662 |
| 段1 | 0.540250 | 0.703441 | 0.930174 | 1.173443 |
| 段2 | 0.617844 | 0.784019 | 1.067072 | 1.324866 |
| 段3 | 0.403556 | 0.537962 | 0.634398 | 0.832985 |
| 拼接/最终音频 | 0.094493 | 0.105179 | 0.092061 | 0.100294 |
| 完整解码QA | 0.208754 | 0.266173 | 0.331331 | 0.428910 |
| 其余全流程 | 8.493100 | 8.546506 | 8.473660 | 8.611464 |

各行分别取中位，不要求求和等于总中位。“其余”是worker总wall减去已记录FFmpeg阶段的差值，**原16job内没有独立剖分，保持unattributed**。代码路径包含Python启动、hash、ffprobe、用途检查、存储统计/登记和平台调度，但不能从差值直接归因GPU或某个子步骤。

收尾只读诊断另存`OVERHEAD_PROFILE_2026-09-29.json`：平台owner元数据扫描3.996629秒、owner外扫描0.403918秒、render owner扫描0.049435秒、render全局扫描4.195017秒，三段源SHA仅0.002624秒。这是稍后文件树/缓存/其他模块活动条件下的独立采样，未调用队列/预留构造器、未写D盘、未启动媒体/GPU、未重做16job，也未改变容量政策。它提示后续优先细测重复全目录统计；不能把这些数值代入原job或宣称已精确解释8.5秒。未来应给平台预留、render预留、source gate/hash和capture probe分别打点后再考虑优化。

## 无损参考质量

同一CPU输入、布局、字幕、时序生成FFV1/yuv420p无损参考。30/60fps分别完整比较512/1023帧，在任何setpts归一化前，A/B/R逐帧PTS最大差均为0。比赛画面ROI取实际contain后的`x=0,y=656,width=1080,height=608`，排除静态大背景。下表取FFmpeg最终汇总；逐帧MSE日志经舍入的重算值只保留旁证。

| 帧率/后端 | 比赛画面SSIM | 比赛画面PSNR dB |
|---|---:|---:|
| 30 CPU | 0.987977 | 43.194564 |
| 30 NVENC | 0.993735 | 48.324594 |
| 60 CPU | 0.986072 | 42.315934 |
| 60 NVENC | 0.994158 | 48.648447 |

本配置NVENC比CPU更接近无损参考，同时实际码率/体积更高；不据此推断等质量或等码率优劣。整帧和Y/U/V分项、每帧日志及9个固定时点R/A/B PNG保存在`render/quality-4343ec344d5a485c/`（30）和`render/quality-611d73097277408e/`（60），详见`QUALITY_2026-09-29.md`。取点是每段30%/60%/85%，不是已确认的触球/启动真值；小球不可见处必须保留unknown。

补证`render/quality-roi-847e13ad821b4836/`先在R上冻结坐标，再对每档9个脚部/3个小球候选区域使用相同ROI，另看五个相邻时间取样的条带。代理审阅未见编码新增的明显缺脚、可见球候选消失或位置错帧；CPU部分边缘更平滑，NVENC较接近R。小球离开固定ROI、R本身模糊或看不清的情况不算编码失败，也不算识别成功。稀疏条带不能证明连续播放的闪烁/听感已通过。原质量报告保持不变，补证保存其hash、6个无损NUT SHA和再次核对的PTS差0。

## 证据与复现

所有外部路径以下列`D:/video/`为根：

- 公平CPU批次：`render/benchmarks/presets-controlled-cpu-7b61b195daf3/`。
- 公平NVENC批次：`render/benchmarks/presets-controlled-nvenc-6e21d23d0d7f/`。
- CPU30/60首轮：`render/jobs/job-6f22d4657d704732a6c32f9739b78f3f/attempt-1/`、`render/jobs/job-979ec45166a0443db6d6c57a41303607/attempt-1/`。
- NVENC30/60首轮：`render/jobs/job-2171dd52987a41c5919aa6bb0459e5bd/attempt-1/`、`render/jobs/job-37d8ad54aff04cc38f667fcedc12fb2b/attempt-1/`。
- 各批次保留`batch.json`、各slot request/result/summary、`completion.json`；各job保留实际命令/日志、backend、QA、timeline、source_map、MP4。
- 后续脚本审查修复了取消竞争时外层job状态未纳入PASS的问题；本次16份原始结果经独立复核，均外层succeeded/attempt=1且内层成功，没有受此问题影响。脚本新增外层状态/attempt断言；96项内存变体回归通过，旧实测报告保持不改。
- 脚本另补实际FFmpeg/ffprobe SHA和完整版本锁定、续跑一致性、每次写入前物理目录边界校验；8项轻量回归含真实Windows junction全部通过。新增实际fingerprint函数对本机8.0.1两exe运行成功；16份QA所有checks均true且完整FFmpeg版本文本一致。修改的是未来复现入口，没有重写原批次的as-run script hash或性能样本。
- 真实360×640预览/定制safe_area/四种训练标记拒绝证据：`render/handoff/preset-preview-f1d7b353db/validation.json`。
- 平台取消真机联测：`platform/research-20260929/render-cancel-cpu-r1/render-cancel-validation.json`。实际FFmpeg生成partial后收到cancel.request，进程停止、锁释放，下一job成功；平台持有worker补丁。

共享DB为`D:/video/platform/runtime.sqlite3`。NVENC窗口`render-benchmark-6e21d23d0d7f`只允许`render-nvenc`，每job独立租约；最后worker确认计算停止后释放，窗口于2026-09-29T09:32:18Z撤销，completion记录active_window/lease均null，已明确归还models。

```powershell
# 仅在models明确交还排期、共享queue空闲、无驻留worker抢任务时执行。
& D:/video/runtime/platform/env/Scripts/python.exe scripts/render/benchmark_nvenc.py --backend cpu --repeats 3 --environment environments/render-runtime-compat.json --coordination-note '<已经取得的实际排期说明>'
& D:/video/runtime/platform/env/Scripts/python.exe scripts/render/benchmark_nvenc.py --backend nvenc --repeats 3 --environment environments/render-runtime-compat.json --coordination-note '<已经取得的实际排期说明>'
```

脚本名虽含nvenc，两个后端都通过同一worker路径；`benchmark_presets.py`另提供直接CPU API基准，未用于此公平配对。复现实验会创建新批次，保留旧失败/结果；不能把写一段coordination-note当成获得GPU授权。

## 失败、限制与后续

首次FFmpeg9.0.2真实GPUprobe失败：需要NVENC API13.1，现驱动提供13.0。保留job`job-6ddb2881f44048eda5f306f741a3b035`和失败批次`presets-controlled-nvenc-4e5823beb9ca`，未静默fallback，见独立`render-nvenc-driver-api-mismatch.md`。独立8.0.1构建解决当前硬件编码兼容性，没有修改/删除原9环境；9的失败仍成立。

先前FFmpeg9 CPU8次技术PASS仅作为旧环境证据，批次`presets-controlled-cpu-beb256d1c5fc`，不参与与8的速度/质量比较。兼容包首次慢下载partial也保留并记录精确进程取消原因。

GPU整链/NVDEC、真实原生60fps、长片吞吐、旋转/VFR源、平台上传、听感、专家动作真值与商业发布权均没有由本轮证明。设置持久化由platform以独立render_options绑定Timeline/CAS实现；renderer保存request/QA/source_map中的完整preset元数据，canonical Timeline合同保持不变。

## 容量与完成后的资源状态

2026-09-29T09:45:43Z只读快照：render **646,588,608 bytes / 40GB**，runtime/render **873,315,597 bytes / 5GB**，D盘剩余 **943,805,825,024 bytes**，`.render.lock`不存在。无源片复制、无旧文件删除或覆盖，保留FFmpeg9失败、首次下载partial、所有中间件/无损参考/PNG。

全局09:37:10–15Z独立遍历为22,386,669,805可见逻辑bytes；其他模块仍在工作，09:42:33Z ROI预留记录为23,948,960,885 bytes。这些是各时间点快照而非同一原子总数，均远低于700GB。只读遍历不跟随WSL/reparse链接，未可见的环境继续受各owner固定额度约束，见ENVIRONMENT_COMPAT报告。质量两轮各预留1GB、ROI预留200MB，均结束并释放；所有本模块FFmpeg已停止，render owner已通知platform可恢复使用。
