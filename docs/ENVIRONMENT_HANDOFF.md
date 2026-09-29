# 共享工具交接

更新：2026-09-29。运行环境是机器本地事实，路径可随安装更新；改路径时由owner更新记录并通知消费者。

## 本轮运行状态

2026-09-29研究实施轮正在集成。主API/worker的00:23运行记录是历史检查点，不能据此判断端口/PID现在有效；主worker暂不常驻，models持有GPU实测排期。platform使用独立测试业务库和18082端口，仍共享受控GPU账本。恢复主服务前核对实际进程、账本及最新代码，见[本轮验收](ROUND_VALIDATION_2026-09-29.md)。

| 运行环境 | 用途与当前事实 |
|---|---|
| Windows `runtime/platform/env` | Web、SQLite、原生worker和轻量回归，不安装训练框架 |
| WSL `runtime/models/env` | 已有torch2.7.1+cu128，TrackNet与连续姿态真实小窗已运行 |
| WSL `runtime/models/yolo-env` | YOLO11n-pose+ByteTrack小环境，只读复用旧torch；旧视频真实90帧已运行，AGPL许可单列 |
| WSL `runtime/models/vl-env` | Qwen3-VL-Embedding-2B按官方torch2.8依赖单独安装，安装/权重仍在下载，不能视为ready |
| Windows FFmpeg9.0.2 | 原CPU环境保留；当前驱动591.86与该版本NVENC API13.1不兼容，失败证据保留 |
| Windows隔离FFmpeg8.0.1 | 兼容当前NVENC API13.0，同版本CPU/NVENC各8真实job已完成；管理员显式选择兼容配置，不覆盖原安装 |

所有新模型仍由管理员按model_id显式映射WSL解释器，权重/环境不完整或未映射时报告unavailable。仅有单个适配器成功不代表自动球场、稳定身份、细动作或战术识别已经达标。

## 第一版主分支运行交接（历史）

- API与worker于第一版验收时从 `C:/Users/USER/Desktop/Program/badmintonTV` 启动，Windows解释器为 `D:/video/runtime/platform/env/Scripts/python.exe`。业务数据库为 `D:/video/platform/platform.sqlite3`，任务与GPU账本为同目录 `runtime.sqlite3`。
- 工作台 http://127.0.0.1:18080；Label Studio http://127.0.0.1:18081。旧平台工作树的 API/worker 已在确认队列和 GPU 空闲后停止，Label Studio 保留运行。
- 本次启动代码版本 `a851dcbb239f8789e1566aea8031c2ee277692ae`；启动 PID、时间和日志目录仅保存在本机 `.runtime/main-services.json`。后续文档提交不改变运行代码。主分支规则任务与真实渲染、浏览器完整播放均已验证，详见 [集成验证](INTEGRATION_VALIDATION.json)。
- 启动配置、模型参数和GPU会话命令见[启动说明](QUICKSTART.md)。第一版收尾时曾停止独立GPU实验；本轮用户授权后已恢复受控实验，训练与网页推理均须检查同一GPU账本并协调排期。
- 2026-09-29 00:28:37 至 01:28:37（北京时间）曾为用户网页试用授予仅限 `torchvision-keypointrcnn` 的窗口 `user-session-REDACTED`。授予后核查为 available、lease=null；不会自动发起推理。此为历史交接记录，实时状态以 `/api/v1/resources/gpu` 为准。

## Windows FFmpeg / FFprobe

owner：render。状态：工具可运行，真实竖屏研究样片与 Web 导出已完成技术验证；人类技法确认仍待完成。

- FFmpeg 9.0.2 essentials，Gyan发行构建，启用GPLv3、libx264与AAC。
- `BTV_FFMPEG=D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe`
- `BTV_FFPROBE=D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe`
- 安装ZIP SHA-256：`60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`。
- FFmpeg二进制SHA-256：`3256173f3f8bffd7df12227c68adf68025edb1832273a9530688a7bb1ed8edec`。
- FFprobe二进制SHA-256：`f0d36ecbbdd3bcfac3efa078c96c7271c2e68b3810595552ac3b7f17e9a65c52`。
- render报告：来源校验、CPU libx264/AAC、中文字幕、1秒合成MP4完整解码烟测通过；人工用户观看验收待完成。
- 主协调核验：已读取环境记录，并实际运行FFmpeg版本检查成功。
- 安装包、解压目录与烟测产物计入runtime/render额度，报告占用444,047,356 bytes，不重复计入其他owner。

完整安装/检查记录已集成 main `environments/render-runtime.json`。其他任务只读复用，不重复安装相同Windows工具，不修改此安装目录。该exe不是Linux原生工具；WSL调用需明确路径转换或另装受控Linux依赖。

## 跨系统容量统计

Windows不能解析部分WSL环境链接时，不得把读取错误等同于0字节。可对无法读取的其他owner目录按完整已分配额度保守计数，并确保不与已统计子树重复计算；自己的目录必须完整核算，否则停止新增写入并记录问题。不得跟随重解析点到受控根外，也不删除其他模块链接。初始650GB分配和总700GB硬上限保持不变。

## WSL RTX 5090 算子检查点

models任务已实际运行，主协调读取了其记录；完整记录已集成 `environments/models-gpu-smoke.json`，环境锁见 `environments/models-*.txt`。

- 环境：`/mnt/d/video/runtime/models/env`，Python3.11.16，torch2.7.1+cu128，torchvision0.22.1+cu128，CUDA12.8，cuDNN90701。
- GPU：RTX5090、capability12.0，编译架构列表含sm_120。
- 合成算子：矩阵运算、卷积、BF16 SDPA、torchvision NMS与ROIAlign通过。算子测试段1.097秒，峰值allocated 8,974,848 bytes。
- 这些数值只描述合成算子测试，不能代表视频处理吞吐、模型显存需求或识别准确率。
- Qwen与姿态权重已下载校验，真实模型前向另行报告；底座仍以逐模型health/实测状态决定可用能力，不因GPU算子通过将所有模型标为ready。
- PyAV14.4源码安装失败（pkg-config/FFmpeg开发依赖不足）已记录，models改用官方15.0.0 Linux wheel，未往全局环境安装编译链。

## 首批真实GPU特征提取

同一6秒FineBadmintonBenchmark `video_001951`，rear/singles，离线权重，各采样24帧。主协调已用main JobResult合同校验结果并逐项核对产物大小/SHA-256。

| 模型 | handoff目录（D:/video下） | 含冷加载/解码耗时 | 峰值allocated / reserved |
|---|---|---:|---:|
| torchvision-keypointrcnn | models/handoff/real-pose-002/attempt-01 | 26.399s | 489,201,152 / 792,723,456 bytes |
| clip-frame-mean | models/handoff/real-video_embedding-002/attempt-01 | 44.853s | 616,739,840 / 664,797,184 bytes |

均result=succeeded、events=[]，每个输出features/report两项artifact。姿态关键点和向量是特征，不是细动作真值；没有球员身份、击球接触时刻、时序动作分类或准确率结论。单短片的冷启动时间不用于声称整场稳态吞吐。Qwen诊断与姿态overlay检查已交付在 `docs/experiments/`；Windows worker 受控启动 WSL 模型的真实链路已由平台任务完成，主协调核验产物与计算停止证据。最终桥接代码已合入 main，未在 main 重复 GPU 实验。

第一版历史数据/环境容量快照约18.31GB，计数范围和限制见[容量记录](INTEGRATION_CAPACITY.json)。本轮新增下载和安装尚未计入该旧快照；安装容量不与整目录最新快照重复相加。
