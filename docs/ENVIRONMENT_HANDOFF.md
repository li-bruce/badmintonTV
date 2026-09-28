# 共享工具交接

更新：2026-09-28。运行环境是机器本地事实，路径可随安装更新；改路径时由owner更新记录并通知消费者。

## Windows FFmpeg / FFprobe

owner：render。状态：工具可运行；尚不代表真实羽球集锦验收完成。

- FFmpeg 9.0.2 essentials，Gyan发行构建，启用GPLv3、libx264与AAC。
- `BTV_FFMPEG=D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe`
- `BTV_FFPROBE=D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe`
- 安装ZIP SHA-256：`60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`。
- FFmpeg二进制SHA-256：`3256173f3f8bffd7df12227c68adf68025edb1832273a9530688a7bb1ed8edec`。
- FFprobe二进制SHA-256：`f0d36ecbbdd3bcfac3efa078c96c7271c2e68b3810595552ac3b7f17e9a65c52`。
- render报告：来源校验、CPU libx264/AAC、中文字幕、1秒合成MP4完整解码烟测通过；人工用户观看验收待完成。
- 主协调核验：已读取环境记录，并实际运行FFmpeg版本检查成功。
- 安装包、解压目录与烟测产物计入runtime/render额度，报告占用444,047,356 bytes，不重复计入其他owner。

完整安装/检查记录当前在render工作树 `environments/render-runtime.json`，待该模块提交后集成。其他任务只读复用，不重复安装相同Windows工具，不修改此安装目录。该exe不是Linux原生工具；WSL调用需明确路径转换或另装受控Linux依赖。

## 跨系统容量统计

Windows不能解析部分WSL环境链接时，不得把读取错误等同于0字节。可对无法读取的其他owner目录按完整已分配额度保守计数，并确保不与已统计子树重复计算；自己的目录必须完整核算，否则停止新增写入并记录问题。不得跟随重解析点到受控根外，也不删除其他模块链接。初始650GB分配和总700GB硬上限保持不变。

## WSL RTX 5090 算子检查点

models任务已实际运行，主协调读取了其记录；完整记录待ML提交后集成为 `environments/models-gpu-smoke.json`。

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

均result=succeeded、events=[]，每个输出features/report两项artifact。姿态关键点和向量是特征，不是细动作真值；没有球员身份、击球接触时刻、时序动作分类或准确率结论。单短片的冷启动时间不用于声称整场稳态吞吐。Qwen诊断与姿态overlay检查另行交付。平台尚需验证经Windows worker受控启动WSL模型的完整路径。
