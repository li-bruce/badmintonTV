# 2026-09-29 平台研究实施轮验收快照

本记录对应 [实施轮固定用例](../IMPLEMENTATION_ROUND_2026-09-29.md) R-02a、R-02b、R-04b，以及既有 G-01/G-02/G-03 的本轮补充。**有界代理后端、源帧操作与修复后的循环路径已实测通过；流畅预览仍无达标证据。** 浏览器寻帧的源帧误差满足一个源帧以内，但目标帧 rVFC 回调等待约一秒。以下浏览器操作由平台任务实际执行，本文只读归档原始测量及其操作回执，不补造新的运行结果。

## 用例与当前状态

| ID / 目标断言 | 输入与验证方法 | 实际结果 | 状态 / 边界 |
|---|---|---|---|
| R-02a：CFR、明确派生 VFR、不支持格式均有有界代理，30 点源 PTS 误差≤一个源帧，可回查原分辨率 | 旧 general 真实 4.634 秒片段，另明确派生 VFR、FFV1、60→30；实际 FFmpeg、ffprobe 与独立原 PTS 图片选择交叉核验 | 四例 H.264/yuv420p/faststart、短 GOP、连续 coverage、完整源帧索引与原尺寸 JPEG 通过；后端映射最大误差<0.000334ms | **PASS（有界后端）**；派生 VFR 不冒充原生 VFR 摄录，短片不代表整场吞吐 |
| R-02b：浏览器 30 点冷/重复访问寻帧并报告中位数/P95 | 四例各两组，每组固定 30 点；同时记录 seeked、目标帧 rVFC callback、源帧误差、可见性 | 240/240 完成，最大绝对误差一个源帧；总耗时中位数 990.55–996.80ms，P95 997.30–1001.60ms | **PASS（测量与误差断言）**；流畅性没有通过证据，见下表及独立问题单 |
| R-02b：逐源帧、原图、标记、修订保存及重载 | 浏览器查看 60→30 派生源帧 #61/#62，原图 native/2x，设置边界与接触点，保存后重载 | #61 原图 1280×720、2x 显示宽 2560；界面 marks=1016/1034ms、contact=1016ms；逐帧到 #62，end=1050ms；事件 revision2 重载保留 | **PASS（该操作路径）**；没有提升为人类技法真值 |
| R-02b：区间循环 | 浏览器实际播放源区间 [1000,1800)ms，暂停回跳并等待目标帧后继续播放 | 首轮超时 count=0；修复后 DOM=23 次、last_source_ms=1000、notice 为空；独立截图=22 次 | **PASS（修复后真实复跑）**；两次证据抓取不原子，分别记录，保留首轮失败 |
| R-02b：缩略图定位并保留显示帧/覆盖区间区别 | 浏览器实际点击 1.267s 缩略图，读取代理、源帧及 coverage | proxy#38→source#76，PTS19456×1/15360=1266.6667ms，coverage=[1266.6667,1300)，精确源帧区间=[1266.6667,1283.3333) | **PASS（该真实点击路径）**；记录原始有理 PTS，不用代理 FPS 推算源帧 |
| R-01a 平台 UI 接入补充：60fps/安全区设置经任务进入实际导出 | 浏览器保存配置、正确 Agent 快照取消后显式 retry，单次 CPU worker 调用 render；技术 QA 及浏览器播放 | attempt1 succeeded；1秒、1080×1920、60帧/60fps、H.264/AAC，12项QA全true；浏览器播放到0:01/0:01 | **PASS（该 UI→CPU 输出路径）**；不替代 render 模块30/60对照或人类内容审核 |
| R-04b：真实训练用途制作链隔离 | library真实清单7项和最终10项两个时点，registry均10条；实际API/Store/worker，私有历史fixture；关联render独立CLI | 14个API均422/TRAINING_ONLY，普通render及research worker均blocked；独立render四模式拒绝 | **PASS（已列真实拒绝入口）**；无媒体读取/子进程，最终10项仅metadata/stat关联，不称重hash或decode原片，详见[真实负例报告](REAL_TRAINING_ISOLATION.md) |
| G-01：本轮工程回归 | 平台任务全套及前端回归 | 最终后端 **607 passed / 7 skipped / 59.12秒**；前端 **38 passed** | **PASS（冻结源码全套）**；skip不算通过，历史计数不累加 |
| G-02：真实 CPU 编码中取消并可继续下一任务 | 独立 queue、真实 render CLI/FFmpeg，观察自有锁和计算进程后取消 | 终态 cancelled、attempt 标记匹配、锁释放、已观察自有 PID 退出；下一 1 秒 job succeeded | **PASS（G-02a-render-cpu-cancel）**；不包含宽限超时强杀或 CUDA 中途取消 |
| G-02：心跳共享冲突有界恢复，持续错误fail closed | 故障注入、本机真实Windows共享竞争/DELETE ACL | 最新 **60 passed / 1 opt-in skipped**；已有publisher证明下Win5竞争消退恢复，持续故障截止失败、ACL立即失败 | **PASS（CPU/Windows覆盖）**；models后续两个真实短片任务成功；未触发Win5诊断，见下文 |
| G-03：本轮写前预留与 owner 容量记录 | 代理、精确帧、独立取消测试预留；只读扫描平台两个 owner | 预留和实际目录量分别记录，见末节 | **PASS（本轮已测范围）**；不是所有 owner 总用量审计 |

## 四种实际代理与原图证据

原片为 `data/raw/finebadmintonbenchmark/video_000001.mp4`，SHA256 `057d2d6dd52eb892719b36aa1f017ac6272e19502dd93efbc0ca9f97f35b6fe0`，642,017 字节、1280×720。原片只读，新测试使用独立队列；没有将训练文件导入制作测试。

| 真实测试 case | 源帧→代理帧 | 最大映射误差 ms | 代理字节 | 后台总秒 |
|---|---:|---:|---:|---:|
| real_cfr | 139→139 | <0.000334 | 732,611 | 5.506 |
| derived_vfr（明确派生） | 73→73 | 0 | 841,054 | 6.323 |
| derived_ffv1（明确派生） | 139→139 | 0 | 734,204 | 7.681 |
| derived_60_to_30（明确 60fps 派生） | 278→139 | <0.000334 | 679,946 | 5.617 |

后端正式复跑为 **32 passed / 79.17秒**，随后分页连接关闭回归为 **28 passed / 5 deselected**，不重复相加。证据在 `D:/video/platform/media-proxy-test-20260929-r2/<case>/R-02a-report.json` 和 `R-02a-independent-frame-check.json`。独立 `select=eq(pts,原始PTS)` 图片与 handler 的绝对 ordinal 选择图片 SHA 相同；JPEG 仍是有损图像。全部源 PTS 保留，包括 60→30 代理没有显示的原帧；覆盖区间连续不意味着每幅源图都曾显示。[实现边界、命令与失败历史](MEDIA_PROXY.md)保留了 r1 目录权限失败及后续完整复跑。

历史四例报告的派生 Asset 继承了旧 fps/probe 侧车字段，不能把这些字段视为派生视频权威元数据；上述实际帧数、PTS/图片核验来自重新 ffprobe 和本次 SQLite 索引。原始报告保持不变。后续 fixture 已改为实际文件 hash/尺寸核对后重新 ffprobe 的 fps、duration、time_base 与尺寸，清除父文件 probe/PTS/thumbnail 绑定和被误继承的 publisher hash，只保留明确 source lineage；旧报告作为输入也经过同样刷新。准备脚本默认生成新的 UTC state 子目录，并拒绝已有内容，setup.json 使用排他创建，避免覆盖本次证据。只执行相关轻量回归：**31 passed / 5 deselected / 0.69秒**（含3项新增），未重跑四种媒体编码，未改历史 JSON 或当前验收 DB。

## 浏览器 240 点寻帧原始统计

只读输入：[preview-seek-all-cold-warm.json](preview-seek-all-cold-warm.json)，8 组、每组 30 点，UTC 09:09:50–09:28:11。文件 SHA256：`3af74369e55f8ec8ebfb2f81bb2c3470edf650ef0cea02610810291fed69cde5`。下表 total 沿用原始 `summary` 并与 `elapsed_ms` 重算核对；seeked/presented 中位数取中间两值平均，P95 为排序后第 29 个值（nearest-rank，n=30）。单位均为 ms。

| 输入 / 条件 | total 中位数 / P95 | seeked 中位数 / P95 | rVFC 回调 presented_ms 中位数 / P95 | 源帧误差范围 | viewport 完全可见点数 |
|---|---:|---:|---:|---:|---:|
| CFR / cold_media_load | 996.15 / 998.90 | 33.80 / 84.00 | 953.10 / 958.90 | 0 | 30/30 |
| CFR / repeat_access | 995.70 / 1001.60 | 7.30 / 29.40 | 995.70 / 1001.50 | 0 | 26/30 |
| 派生 VFR / cold_media_load | 996.30 / 999.10 | 6.65 / 38.30 | 956.35 / 961.80 | 0 | 30/30 |
| 派生 VFR / repeat_access | 996.80 / 1000.20 | 6.70 / 16.40 | 996.70 / 1000.20 | 0 | 30/30 |
| 派生 FFV1 / cold_media_load | 995.65 / 999.30 | 23.40 / 75.80 | 952.95 / 963.00 | 0 | 30/30 |
| 派生 FFV1 / repeat_access | 995.35 / 1000.80 | 8.20 / 14.60 | 995.35 / 1000.70 | 0 | 30/30 |
| 派生 60→30 / cold_media_load | 995.75 / 999.00 | 9.60 / 73.30 | 954.90 / 959.40 | -1…0 | 30/30 |
| 派生 60→30 / repeat_access | 990.55 / 997.30 | 11.45 / 20.70 | 990.55 / 997.30 | -1…0 | 30/30 |

`cold_media_load` 每点重载媒体元素、使用唯一 URL，服务端 `no-store`；**未清 OS 文件缓存，不是全系统冷缓存**。其 total 包括媒体重载及后续寻帧，seeked/presented 从寻帧开始计时；单独重载中位数为 39.90–42.05ms。`repeat_access` 复用当前媒体元素，不重载，浏览器与 OS 缓存未清；不保证 HTTP 缓存命中。两种 total 的计时范围不同，不宜相减估算缓存收益。

`presented_ms` 实际是目标帧 `requestVideoFrameCallback` 到达时以 `performance.now()` 计算的回调等待时长，不是实际屏幕呈现耗时。原始记录没有保存 metadata.presentationTime、expectedDisplayTime、processingDuration，因此不能把该差值归因于解码或 compositor。seeked 事件完成明显早于目标帧 rVFC callback；仅报 seeked 会隐藏本次约一秒回调等待。所有 240 点 `status=ok`、`frame_observed=true`、`within_one_source_frame=true`，没有测量超时或 no-op；但零误差为 **212 点**，其余 **28 点为 -1 源帧**（60→30 两组各 14 点，约 -16.6667ms）。显示图像与请求原帧不同，符合降帧 coverage，不可写“240 点全部零源帧误差”。先前口头汇总仅取带符号误差 `max()` 得到 0，遗漏了 -1，本记录据原始 JSON 更正。

全部点 `document_visibility=visible`。CFR repeat 的第 27–30 点 `visible_area_fraction=0`，其他 **236 点=1**；只取该组完全可见的 26 点，total 中位数/P95 仍为 **996.25/1001.60ms**。因此现有证据不能把延迟归因于播放器离屏，原因仍未知。详见[呈现延迟问题单](../issues/platform-preview-presentation-latency.md)。

## 浏览器操作与导出配置

平台任务实际核查派生 60fps 源帧 #61、#62。精确图任务分别为 `job-35facfae1d684d38a53cc1e1b59826d1`、`job-38baeb8df6564d929aaedbbc680c1d07`，均 succeeded、1280×720，原始 source PTS 为 15616/15872。native 图片和 2x 显示已核查；2x 是显示缩放，不增加原始图像细节。

实际点击缩略条 **1.267s** 后，readout 为 proxy#38→source#76、原 PTS19456×1/15360=1266.6667ms；coverage 至1300ms，精确选择源帧仅至1283.3333ms，二者分别呈现。可持久复核 [browser-thumbnail-proof.json](browser-thumbnail-proof.json)；notice 是先前成功提交 retry 的状态文本，不是寻帧错误。

浏览器界面标记 start/end=1016/1034ms、contact=1016ms；源逐帧到 #62 后 end=1050ms。事件 `35b85b38-0321-4157-ac03-c73bee056b48` 的 revision2 保存后刷新仍保留。这里的界面毫秒记录不取代精确图里的原始整数 PTS；Agent 操作不构成专家细技术真值。

导出 UI 60fps、安全区 `{x:0.08,y:0.12,width:0.8,height:0.76}`、`youtube_shorts` 配置已保存并重开恢复。平台任务随后以 Agent 来源排队 `job-7f8fb7431dac4a92b571d485fd1f9152`：options revision3、`portrait_1080p60`、Timeline.output.fps=60、backend=cpu、gpu_required=false、editorial_review=agent。排队时的完整快照为 [browser-render-options-job.json](browser-render-options-job.json)，保持原样。首次在 worker 停止期间取消，取得 render owner CPU 窗口后从 UI 显式 retry，用单次 worker 执行，**attempt1 succeeded**。

实际产物 **1.000秒、1080×1920、60帧/60fps、H.264/yuv420p/AAC48k、109,708字节**，SHA256 `be377469da2b4b55f0c5d7af1368338d65d703adc661c624b31220512d6ea59f`。QA 全部12项为 true，含 full_decode；preset、安全区、profile 与 UI 一致。render 代码只读使用3e52的 `db587aa`，FFmpeg9.0.2，CPU libx264，GPU未用；single worker 已退出且 render 自有锁释放。平台任务在当时已含用途校验的r5 API版本上实际播放，截图显示 **0:01/0:01**、真实场地与“Agent流程验证”标题，见[最终结果与4产物](browser-render-options-result.json)、[播放截图](D:/video/platform/research-20260929/browser-ui-evidence/browser-render-options-playback.png)。技术证据另在 `D:/video/render/jobs/job-7f8fb7431dac4a92b571d485fd1f9152/attempt-1/{qa,source_map,timeline}.json`，本文只读核对。

此次 `research_preview=true`、`human_confirmed_segments=false`、`editorial_review.reviewer_type=agent`，原音静音策略，不能称专家认可或真实原音试听通过；未做平台上传。派生测试 Asset 继承了原30fps片段的旧 fps/probe sidecar 字段，而实际 source_probe 明确是60fps/278帧；source_map 中旧139帧 source_pts_index **不是派生文件的权威索引**。本轮预览与原图核查使用 actual ffprobe 生成的独立全源 SQLite 索引；此旧测试元数据限制不隐去，也不据输出60fps宣称增加了真实动作信息。

保留失败历史：刷新后默认 reviewer 类型导致首个 `job-cef905c866494c6a8e8515c3c3a21e6a` 使用错误 human 快照，已在 attempt0 cancelled。该快照不是真实人类审核证据，不能用于确认真值；后续 Agent 快照另建任务，不覆盖旧证据。

区间循环先前真实失败：未暂停就回跳，浏览器目标代理帧提交等待超时、count=0。修复改为先 pause，再 seek 并等待目标 rVFC，最后 play。平台任务复跑 [1000,1800)ms： [DOM 证据](browser-loop-proof.json)记录 **23 次**、last_source_ms=1000、notice 为空；[截图](D:/video/platform/research-20260929/browser-ui-evidence/browser-loop-proof.png)记录 **22 次**。两者先后采集，不把截图数字改成 23，也不删初次失败。抓取后已暂停并取消循环。

## 取消、心跳、容量与收束

[真实 CPU 取消报告](RENDER_CANCEL_VALIDATION.md)记录：取消任务 `job-4ae18387c6704355ada50a98f20b2abf`、下一成功任务 `job-7602f85d0dd84d95abe2f910eb3b492c`；整个独立实验 18.391 秒，下一产物 141,188 字节且 hash 通过。证据为 `D:/video/platform/research-20260929/render-cancel-cpu-r1/render-cancel-validation.json`。原片只读、只写独立队列，CPU 窗口已归还。原 JSON 的旧 case_id 误标在该报告中保留并更正归类，没有改写历史原始证据。

[心跳问题单](../issues/platform-wsl-heartbeat-sharing.md)对应独立提交 `21e16949a06b27f9b81745198cc86b1bf1a47f2d`。随后隔离加固提交 `2f3fd855f896b62234ad3e921c73779c9f2ae9cd` 强制 `PYTHONNOUSERSITE=1`，相关回归 **51 passed / 1 skipped**，未运行 GPU。新增独立提交 `ec8a7fc` 限定已成功publisher的身份与DELETE探针证明，在原0.7秒内恢复Win5竞争消退，真实共享锁及ACL反例通过，最新60 passed/1 skipped；见[新Win5问题单](../issues/platform-wsl-heartbeat-win5-race.md)。不推断旧无errno失败根因，也不假定修复已在实际模型路径验收。配置提交 `a73b485` 增加默认关闭的YOLO独立环境映射，43 passed/1 skipped；无模型或GPU运行，见[配置说明](MODEL_ADAPTERS.md)。

每个 proxy 额外预留 **880,000,000** 字节，exact_frame 额外 **72,000,000** 字节；分别另加 worker **128,000,000** 字节协议预算，实际顺序释放，不能把预算总和当实占。CPU 取消实验 setup 预留 16MB，renderer 自行预留其峰值。媒体、缓存及环境仍在 D:/video；未新增平台依赖，复用平台 Python 与管理员 FFmpeg 9.0.2，无 torch/GPU。

2026-09-29 **09:43:04 UTC / 17:43:04 Asia/Shanghai** 只读目录扫描：`D:/video/platform` **196,664,848 字节**，`D:/video/runtime/platform` **1,048,280,806 字节**，两目录均完整读取；D 盘 free **943,960,891,392 字节**。对应固定 owner 配额分别 60GB/10GB。此快照不是所有模块的 700GB 总量核算，其他模块并发写入会使物理 free 变化。

本轮浏览器验证使用独立本机 18082 及 `platform/research-20260929` 数据库；新测试没有写生产数据库。先前r5保留私有 API **127.0.0.1:18082 / parent PID59656**，后续已重启为53520供审阅，见末节，**无永久 worker，不启动 main18080**；`D:/video/platform/research-20260929/services.json` 是实际服务记录。R-02b 的已列操作与30点计时均取得证据；约一秒 callback 延迟仍 OPEN，不称流畅已达标。R-04b真实入口负例16/16通过并关联render独立四模式拒绝，具体时点与历史fixture边界见[报告](REAL_TRAINING_ISOLATION.md)；不据此把整个产品阶段标为完成。用途覆盖边界见 [PRODUCTION_USAGE_TESTS.md](PRODUCTION_USAGE_TESTS.md)。

需要重启审阅 API 时，在本工作树设置隔离库环境后运行（已有服务时不要重复启动）：

```powershell
$env:BTV_STORAGE_ROOT='D:/video'
$env:BTV_DB_PATH='D:/video/platform/research-20260929/platform.sqlite3'
& D:/video/runtime/platform/env/Scripts/python.exe -m uvicorn apps.platform.main:app --host 127.0.0.1 --port 18082
```

后续原图任务控制已提交 `7e8a9bd`：普通step不自动生成原图，显式inspect串行创建/取消并限制16项成功缓存。真实Edge复测中，三次普通step后exact任务仍为2；源#61任务job-3232068ebb15432aacf59d96585d50c4在切帧后attempt0取消；源#62任务job-76ab9527c53146868463ebc1bc0052b3由一次CPU worker成功，切离返回后显式核查复用缓存，总数仍4、无queued/running。见[队列回执](browser-exact-request-proof.json)、[DOM](browser-exact-request-dom.json)、[截图](D:/video/platform/research-20260929/browser-ui-evidence/browser-exact-cache.png)。32项JS回归通过；未重跑240点计时，也未改变长片全源校验/从头解码成本，[长片成本问题](../issues/platform-exact-frame-long-video-cost.md)仍开放。

## models后续真实运行回执

models任务在main `fd6155b`（含ec8a7fc）上运行新职业片3秒窗口：TrackNet `job-d9c832fd94384ee3950918badc767b15`、YOLO `job-57c6354813b94ad1ba12d42b24e5968e`。本平台任务随后以SQLite `mode=ro`只读核对生产队列，两者均attempt1/succeeded、result.exit_code=0、2个artifacts、error=null，没有执行模型或写生产库。models报告对应done为compute_stopped/exit0、租约与窗口释放，且两任务均无heartbeat诊断。这是修复版本真实链路正常完成的证据，不能称此次实际触发过Win5恢复，也不替代模型质量或长片吞吐验收。旧失败与诊断仍保留。

完整10项清单后的16项负例于10:29:48–10:29:54UTC在新私有目录再次PASS（14 API拒绝、2 worker blocked，媒体/子进程/adapter=0）；历史逐入口fixture仍为同一b210真实Asset，不称每项各跑全部入口。详细metadata SHA、证据hash和新目录见[报告末节](REAL_TRAINING_ISOLATION.md)。

## 最终组合回归与独立实例

源码最终为 `e1da6ee97a61eb377e2282bd6e2355a1cd8be0ff`，已无必须源码WIP。`19a36cc`组合提交包含产物身份后端及标注epoch前端，`e1da6ee`补执行时索引依赖验证。代码冻结后全套命令 `python -m pytest tests/platform tests/contracts -q -p no:cacheprovider --basetemp .pytest-tmp-final-r7` 实际 **607 passed / 7 skipped / 1 warning / 59.12秒**；Node语法检查及 **38/38 PASS**。此前r6为607/7/64.57秒，但最后源码写入接近测试收集时点，因此以冻结后的r7为最终证据，不累加。7跳过为5个真实媒体opt-in、1个Windows symlink条件、1个WSL watchdog opt-in；既有四媒体32项实际结果另列，未重跑整批。warning为Starlette的httpx弃用提示。

独立API已于 **10:34:02UTC** 重启，仅更换本任务18082进程：parent53520/child62828，上一parent59656。无常驻worker，main18080与LS18081未操作。最终代码的真实Edge重新读取旧60→30预览、索引及缩略图正常；显式#61新任务 `job-06a35bd0cd134c9d8c919a4ee3ec0e9a` 经一次CPU worker succeeded/attempt1，浏览器显示1280×720与PTS15616×1/15360。只读核验runtime中该产物及旧预览/旧成片共5条可信proof均匹配当前path/fd身份，私有queued/running=0，worker退出0。旧成片Range GET返回206、bytes0-15/109708、video/mp4、no-store，实际16字节。见[最终运行/身份证明](browser-final-artifact-proof.json)、[DOM](browser-final-artifact-dom.json)、[截图](D:/video/platform/research-20260929/browser-ui-evidence/browser-final-artifact.png)。

重载期间日志保留两条Windows asyncio WinError10054连接重置回调；API持续ready、随后请求和上述任务成功，未将该非致命连接日志隐藏或提升为产物失败。最终新截图143387B，SHA256 b7b0d8d9f4dab4d2d99eabfccab748029e90b87863f3d73d2e73cb879eb34d82；预留16MB后独占写入D盘，没有媒体入Git。最新平台容量及此前快照见[容量记录](capacity-final-snapshot.json)。
