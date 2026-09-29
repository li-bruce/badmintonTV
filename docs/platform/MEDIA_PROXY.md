# 有界预览代理与源帧索引

本轮依据 `docs/IMPLEMENTATION_ROUND_2026-09-29.md` 的 R-02a / S1 开发。原 Asset、原文件和标注时间不因代理改变。输出是 CPU 预览与核查产物；720p 画面不证明拍面、手腕或细技术可见。R-02b 的浏览器逐帧、循环、修订往返与冷/热 seek 延迟由平台整体验收另记。

## 后台接口

`packages.runtime.media_proxy.create_proxy(context, exchange_dir)` 接收 `WorkerContext`，payload 为 `{asset: Asset快照, start_ms:0, end_ms?:整数, max_height:720|1080, max_fps:null|30}`。省略 end 时截到源末尾或120秒。先调用共用 `assert_production_allowed`，再流式 SHA-256 核对原文件；用途登记缺失、路径/字节/hash不符会阻断，不根据扩展名猜格式。读取 actual ffprobe 参数，CPU libx264 输出 H.264 / yuv420p / faststart，最大30帧 GOP 且每秒请求关键帧，首版 `has_audio=false`。

`exact_frame(context, exchange_dir)` 的 payload 为 `{asset,index_relative_path,source_frame_index}`，同样检查用途、完整源hash以及索引的 asset/hash身份。后台选取源解码序列中绝对帧序号，输出原像素宽高 JPEG，不缩放、不插帧。取消由同一 `context.check/execute` 受控进程树处理。JPEG有损压缩，不能称像素无损回查。自动旋转被显式禁用，宽高和序号对应编码源帧。

两函数返回标准 job envelope，额外分别放 `preview` / `frame`。不写业务DB，不改变 Asset。主worker负责固定operation注册、结果落队列、取消终态及128MB协议预留。每函数另向同一队列DB的 `CapacityLedger` 预留媒体峰值并在finally释放；不要重复添加这一预留。显式重试必须使用新 attempt 目录；已有输出不会覆盖/自动删除。

`estimate_peak_bytes(payload, operation='media_proxy')` 返回额外预留：proxy 880,000,000字节；exact_frame 72,000,000字节。它只校验配置，实际容量检查在函数内部执行。限制与预留不含原文件复制，原文件始终只读。

## 映射形状

成功 `result.preview` 含 `schema_version,source_asset_id,source_sha256,usage_scope,source_time_base,source_origin_pts,source_index_scope='full_source',source_frame_count,proxy_frame_count,requested_start_ms,window_start_ms,window_end_ms,relative_path,index_relative_path,thumbnail_relative_path,thumbnail_count,thumbs,width,height,max_height,max_fps,has_audio,codec,pixel_format,peak_reserved_bytes`。

窗口起点向前落在覆盖请求时刻的真实源帧。`window_start_ms` 是实际起帧PTS，`requested_start_ms`保留请求；终点按已解码末帧时长截取，窗口不外推。源毫秒以首视频帧为零；原始有理时基和整数PTS保留，可精确还原原始时间戳，不采用 `frame/fps`。

SQLite `source_frames` 保存全片所有已解码源帧（包括30fps代理丢弃的帧）：`source_frame_index` 为全片从0起绝对ordinal，字段 `source_pts,source_pts_ms,source_end_ms,key_frame`。`proxy_frames` 保存显示帧 `proxy_frame_index,proxy_pts_ms,source_frame_index,source_pts,source_pts_ms,coverage_start_ms,coverage_end_ms`。显示源PTS只指那幅图像；coverage是该显示帧承担的连续源区间，结束等于下一显示源PTS，最后延至窗口终点。因此60→30被丢的源帧仍在source表，区间回写不留洞，也不声称每幅原帧都已显示。

`read_frame_map(index_path,offset_frame=0,limit=1000,at_ms=None)` 返回 `{frames,total,offset_frame,limit}`；at_ms是代理播放毫秒，定位当前显示帧。`read_source_frames(...)` 返回 `{source_frames,total,offset_frame,limit,source_index_scope}`；at_ms是源媒体毫秒，定位覆盖该源时刻的原帧。limit必须1–1000。Web层必须从可信已应用结果解析路径，核验平台owner、源asset/hash关联；不可接收浏览器任意SQLite路径。结果sidecar没有完整帧数组。

thumbs最多12项，每项 `{source_frame_index,source_pts_ms,proxy_pts_ms,x,y,width,height}`，在单张JPEG水平条中以矩形裁片显示。代理及缩略图的源关联不是新Asset；用途、源asset与SHA随结果保留。

## 边界与执行

硬输入限制：源≤4小时、≤20GB、≤3840×2160像素、索引≤1,728,000帧；窗口请求≤120秒、选取≤14,400帧；输出≤1920×1080。超限明确失败，不返回部分成功索引。源PTS必须存在且严格递增，重复/回跳会拒绝，不能悄悄按平均FPS补造。

源PTS经私有 `_index` 子进程逐行读取 ffprobe compact 输出，单行≤64KiB，每256帧提交SQLite，SQLite上限256MB；从不将整片帧记录收集成Python list/JSON。子进程继承worker进程组/Windows JobObject，不分离，worker取消可清理 ffprobe。

保留VFR时不改帧间PTS，归零后以微秒MP4轨道时基写入；30fps选取以真实相邻已选PTS间隔约1/30秒决定，避免插帧。另对已编码proxy流式建立临时索引，实际数量和时间戳必须与选取一致（PTS容差0.01ms），才返回成功。正式source索引保留原整数精度；proxy的微秒舍入不成为标注时间权威。

编码限8Mbps、16Mb缓冲；`-fs`在144MB触发，保留muxer尾部/包余量，完成文件还须≤160MB；缩略条/原图完成后≤32MB。预留覆盖index/rollback journal、编码临时峰值/尾部、图像及内部请求。所有写路径经 `resolve_owner_path(...,'platform')` 拒绝junction/symlink越owner；原片路径经共享根受控解析。媒体不能由Web请求任意argv或GPU执行。

当前边界：全片索引和原帧查找会线性解码长源；单步骤7200秒超时，后台可取消，尚无跨job源索引复用。管理员FFmpeg运行时路径用 `BTV_FFMPEG` / `BTV_FFPROBE`，无需新安装或torch。默认无音轨；仅已有源首视频流。不支持缺PTS/非单调PTS输入时如实失败。

FFmpeg参数依据[官方ffmpeg文档](https://ffmpeg.org/ffmpeg.html)的fps_mode、enc_time_base、force_key_frames、fs与movflags选项，[官方ffprobe文档](https://ffmpeg.org/ffprobe.html)的show_frames和compact writer。运行版本与实际命令写入真实测试报告；沿用render提供的FFmpeg，来源/许可由render运行时记录承接。

## 验收记录

2026-09-29：`D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/platform/test_media_proxy.py -q` 得25 passed / 4 opt-in skipped。覆盖边界、非零源PTS、VFR间隔、降帧coverage连续与全源帧保留、分页限制、哈希错误、取消释放预留。这些单元测试不等于R-02a真实视频验收。

R-02a真实测试预先断言：旧真实CFR、明确标注派生VFR、FFV1不兼容浏览器源、额外60→30派生；输出可解码H264/yuv420p，moov在mdat前，每个用例30固定显示点映射误差≤0.01ms（严于一个源帧），coverage连续、全源帧仍存在、JPEG尺寸等于原片。衍生测试输入明确记录来源与命令，不能当原生VFR采集证据。测试入口 `BTV_MEDIA_REAL_TEST_ROOT=D:/video/platform/<新的media-proxy-test目录>`，FFmpeg两环境变量须指向管理员提供二进制。测试先独立256MB源衍生预留，再由处理函数各自预留；仅写独立test-runtime.sqlite3与本轮报告，禁止生产业务库。初始真实状态为NOT_RUN：当时等待有效训练用途registry发布，未绕过全局TRAINING_REGISTRY_PENDING守卫。

### R-02a 实际结果：PASS（有界后端用例）

library发布真实训练登记表后，2026-09-29执行两轮，保留全部历史文件。权威复跑目录 `D:/video/platform/media-proxy-test-20260929-r2/`，每case的 `R-02a-report.json` 保存原Asset、衍生命令、两类result、30固定显示帧时间点、源帧/代理帧计数与耗时；`R-02a-independent-frame-check.json` 保存独立 `select=eq(pts,原始PTS)` 导出JPEG的命令及SHA。该独立选择与handler的绝对ordinal `select=eq(n,frame_index)` 结果逐字节一致；不是只检查图片尺寸。源固定为旧公开测试片 `data/raw/finebadmintonbenchmark/video_000001.mp4`，sha256 `057d2d6dd52eb892719b36aa1f017ac6272e19502dd93efbc0ca9f97f35b6fe0`，原1280×720、约4.634秒。源文件与生产库均未修改。

| 输入case | 源帧→代理帧 | 映射最大误差ms | proxy字节 | 后台hash/索引/编码/缩略条总秒 |
|---|---:|---:|---:|---:|
| real_cfr | 139→139 | 0.000334以下 | 732,611 | 5.506 |
| derived_vfr，明确派生FFV1/VFR | 73→73 | 0 | 841,054 | 6.323 |
| derived_ffv1，明确派生FFV1容器 | 139→139 | 0 | 734,204 | 7.681 |
| derived_60_to_30，明确60fps派生 | 278→139 | 0.000334以下 | 679,946 | 5.617 |

各例实际H264/yuv420p、faststart atom顺序、≤30帧关键帧间距通过；VFR有不等间隔且每帧被保留；60→30 source表仍保留全部278帧且coverage无洞。原图核查实际1280×720，独立原PTS JPEG SHA相等。还目视检查了12格缩略条可见同一真实羽毛球片的连续画面。映射误差指已显示图像与源PTS关联的误差，不声称任意被降掉的原帧也会显示；逐原帧核查须使用source表与exact_frame。

测试命令：设置 `BTV_FFMPEG` / `BTV_FFPROBE` 为 `D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/` 下相应exe，设置 `BTV_MEDIA_REAL_TEST_ROOT=D:/video/platform/media-proxy-test-20260929-r2`，运行 `D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/platform/test_media_proxy.py -q -p no:cacheprovider --basetemp .test-tmp-media-20260929-final`，结果 **32 passed / 79.17秒**。随后补了明确关闭分页SQLite连接的资源回归，最新非媒体单测 **28 passed / 5 deselected / 0.64秒**；真实4case与独立交叉核验共5项沿用刚完成证据，不重复CPU编码。默认不设真实环境变量时这5项明确skip。

r2全部文件68,953,070字节；r1保留约68,953,069字节。每个输入衍生256MB、proxy880MB、exact72MB、独立PTS图40MB均先通过CapacityLedger的owner/global/free检查，实际峰值不是这些预留简单相加（顺序执行，完成释放）。结束磁盘free=952,587,173,888字节；平台固定60GB、总体700GB逻辑检查由ledger执行，当前全盘物理已用不能等同于项目owner用量。

失败历史：首轮混合提权运行的14个tmp_path单元用例在pytest目录创建阶段报Windows访问拒绝，4真实case与11不依赖tmp_path用例通过（命令15passed/14errors）；没有把该非零退出当完整通过。使用独立basetemp、不写共享pytest cache后完整32项变绿，历史r1结果未删除。R-02b 浏览器冷/热seek中位数/P95、修订往返仍由主平台单列，此后端报告不替代该验收，也不证明长整场性能或细手法可见性。
