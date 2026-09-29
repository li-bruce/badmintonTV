# TrackNetV3 独立复用适配器

## 开发前断言（2026-09-29）

| 验收 ID | 目标 / 输入 | 预期验证 | 当前状态 |
|---|---|---|---|
| R-07a | 官方权重、真实连续短窗 | 每个解码帧保留原始 PTS/time_base，observed/missing 分开，无修补冒充观测 | NOT_RUN：尚未运行真实权重 |
| R-07c | 因果模式与离线模式 | 末帧模式不使用未来图像；实测稳态 RTF、服务延迟、丢帧定义，直播端到端另测 | NOT_RUN：CPU 单元测试不构成实时验收 |
| R-03b | 同一真实窗口 | 分列 cold/decode/pre/model/post；软件 PyAV 解码不声称 NVDEC | NOT_RUN：等待 root 统一实验 |
| R-07b/R-07d | 球点预标注 | 不生成球员身份、球场坐标、细动作、战术或虚构真值指标 | 设计约束；模型能力不外推 |

## 来源核实

固定官方 [commit 6eda442ada1740573f200f836d93edc9a541ee86](https://github.com/qaz812345/TrackNetV3/commit/6eda442ada1740573f200f836d93edc9a541ee86)。[README](https://github.com/qaz812345/TrackNetV3/tree/6eda442ada1740573f200f836d93edc9a541ee86) 提供公开 [TrackNetV3_ckpts.zip](https://drive.google.com/file/d/1CfzE87a0f6LhBp0kniSl1-89zaLCZ8cA/view?usp=sharing)，包含 `ckpts/TrackNet_best.pt`、`ckpts/InpaintNet_best.pt`。公开预览未暴露精确字节数；本任务没有下载，字节数须由 root 下载预检 / manifest 实测，不能猜测。

后续只读 root 已完成的 `D:/video/models/weights/tracknetv3/reuse-manifest.json`：公开 zip 131,653,952 bytes；TrackNet_best.pt 136,190,877 bytes、SHA256 `df867641a02712b021f04548ff4b1208ddfdb47f629ab2094ceb978667e83b1a`；InpaintNet_best.pt 6,264,451 bytes（未执行）。zip 的本地 SHA256 为 `8de68d34ea2457e368e22947f1309143d60a6a7f9ddccd31cd526d4c4571bcc4`；上游未发布权重校验和，本地摘要用于来源留存，不冒充发布者签名。

[LICENSE](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/LICENSE) 对软件及预训练 checkpoint 明示 MIT；须保留版权许可。比赛视频、数据标注权利单独审查。上游 requirements 固定 torch 1.10.0、NumPy 1.22.4、OpenCV 4.4.0.46 等旧版本；不在现有 CUDA 12.8 环境直接安装它们。

已读 [model.py](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/model.py)、[dataset.py](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/dataset.py)、[predict.py](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/predict.py)、[test.py](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/test.py)、[utils/general.py](https://github.com/qaz812345/TrackNetV3/blob/6eda442ada1740573f200f836d93edc9a541ee86/utils/general.py)。TrackNet 是 2D encoder-decoder，三层下采样 / 跳接，上采样后每个时序位置一个 sigmoid 热图；输入 512×288，通道由 checkpoint 的 seq_len/bg_mode 决定。InpaintNet 为另一个时序 Conv1d 网络，本适配器不调用。

## 兼容边界

仅加载受控 manifest 中经大小/SHA256 校验的官方 `model.py`，不执行上游 dataset/test/predict 及其额外依赖。checkpoint 用 `torch.load(weights_only=True)`，不自动降为任意 pickle 执行。仅支持 checkpoint bg_mode 空串或 concat；其他模式明确 blocked。运行依赖 torch、NumPy、Pillow、PyAV、OpenCV；不自动联网或安装。

官方 `model.py` 固定 5890 bytes、SHA256 `04fd51ff88e58189474677dbf11f81e52b78df00226fb97ea0678b31ef7284e3`。manifest 中源码和摘要一起更改仍不能通过；真正 compile/exec 的同一份 bytes 再核对此固定值，防止第一次 hash 后二次读取不同文件。编译内存 bytes 不会向 upstream 写入 `__pycache__`。

`offline_weight` 保留上游三角重叠权重及首尾等权平均规则，但背景为当前请求窗口内最多 32 个均匀时间点后首帧的原分辨率中位图（像素预算自动缩减样本数），并非上游默认全视频全帧中位图。因此是有界离线复用配置，未经质量对比验证。`causal_last` 是本项目新增配置：只用最初 N 个已到达历史帧建立固定背景，校准帧记 missing；之后仅取以当前帧结尾窗口的最后热图。两者都不声称官方论文精度。因果数据依赖不等于实测直播链路延迟。

输入窗口最多 30 秒，连续处理不抽稀、不为了速度丢帧；最多 1800 个选中帧、每次解码最多 10000 帧 / 累计 decoder 调用 60 秒、单帧 3840×2160、背景累计最多 96M 像素。60 秒解码预算不包含等待推理；单个底层调用的挂起由平台 watchdog 处理。源 PTS 缺失、不递增、分辨率改变或超界均失败，不偷偷修复或截短。输出缺失坐标为 null，inpainted 始终 false。

## 交接接口

默认管理员 manifest `models/weights/tracknetv3/reuse-manifest.json`，可用 `BTV_TRACKNET_MANIFEST` 设根内 models 相对路径。字段：schema_version=1.0、source_commit（上述固定 SHA）、license=MIT、checkpoint_url，以及 code/checkpoint 各自 relative_path、sha256、size_bytes。上游代码固定保存 models/upstream 下；权重在 models/weights 下。由 root 获取、留存 LICENSE 和来源证据。

标准 v1 request：operation=analyze（根协议支持 tracking 后也可用 tracking），parameters.model_id=tracknetv3-reuse，mode=offline_weight 或 causal_last，start_ms/end_ms；worker 可注入 model_version=0.1.0，其他版本拒绝。可选 device=cuda/cpu，background_frames=8（因果，1..64）。完整 Asset 必须只有一个。output_dir 在 models 内，attempt 的输出不覆盖。经标准 `packages.models run` 分发；独立脚本仅包装该协议，不另开 worker 或绕过平台租约。

训练范围采用最严格值：typed usage_scope、provenance.usage_scope、逻辑和 resolve 后的 data/training 路径任一为 training_only，features/report 及 artifact producer 均为 training_only。共享合同更新前属于模块兼容 metadata。

## 速度与真实性

报告 cold（校验/依赖/模型加载/一次零输入形状预热）、decode、pre、model、post、points publish 与 pipeline wall。零输入仅为设备预热，不写预测记录。RTF 不含 cold / 发布，但含背景准备与所有真实选中帧；分母用实际首尾源 PTS 跨度，提前 EOF 不得借未处理的请求时长加速数字。稳态 RTF 从首个真实推理窗口开始至尾部处理结束，分母为该点至最后帧的 PTS 跨度；单帧跨度为零时报告 null。单窗口服务延迟包含该窗口 resize/张量准备/推理/后处理，不含刚发生的解码与排队，不能冒充采集到输出延迟；live_end_to_end_latency_ms=null。连续文件回放无主动丢帧，codec 内部丢帧无法从容器证明，标 unknown。每点 available_after_source_ms 同时计入窗口帧和背景的最晚依赖。未进行真实推理时模型准确率 / 实时验收保持 NOT_RUN。

### 可选源 PTS 节奏回放

新增参数 `paced_replay: true`，仅允许 `causal_last`；`replay_deadline_ms` 为相对每帧计划到达时间的完成预算，默认 40ms、可显式设置 1..1000ms，不能在未启用回放时偷偷生效。默认不启用，原先离线与不设节奏的因果路径不变。仍最多 30 秒 / 1800 帧，回放阶段墙钟上限 120 秒；超界整个请求失败，不为得到较好结果提前截掉迟到帧。

以启动逐帧读取前的单调时钟为 epoch，以 `source_ms - start_ms` 为每帧的计划 arrival。至多解码前读一个源帧，到达计划 PTS 后才把它放入历史 ring / 推理；不会整窗预解码。该前读量明确记录 `decoded_prefetch_lead_ms`，因此模拟到达延迟属于此文件回放边界，并非摄像头、编码、网络与平台完整 live 延迟。codec 为获得一个解码帧而内部缓存的未来压缩包也不被声称零延迟。

每帧 `replay` 保存计划 arrival、开始读取、解码就绪、开始处理、完成的 epoch 相对毫秒；另存 `backlog_at_read_ms`、`processing_start_lag_ms`、`simulated_arrival_to_completion_ms`、实测 decode 加服务时间、deadline_lateness/missed、是否已执行预测、dropped=false。warmup missing 与 deadline 迟到分开统计。后处理仅利用时间戳计算当时计划已到达但尚未处理的 backlog 帧数，它不参与模型输入，也不分配无界队列。

report 的 `paced_replay` 汇总预测帧延迟/服务时间 mean、p95、max、迟到数、预热数和最大 pending 帧数。没有主动丢帧，所有解码帧均处理或整体失败。`steady_rtf` 用真实顺序 decode/pre/model/post 的墙钟执行时间扣除显式 pacing sleep；`steady_wall_rtf_including_pacing` 另保留等待在内的回放耗时，避免把每帧等待当模型计算能力。低 active RTF 与高回放迟到可能同时存在，必须一起报告。`live_end_to_end_latency_ms` 仍为 null；不根据文件回放吞吐自动将 R-07c 或模型精度改为 PASS。

例如原请求 parameters 增加以下字段，其余完整 Asset / attempt 字段仍必需：

```json
{"model_id":"tracknetv3-reuse","model_version":"0.1.0","mode":"causal_last","start_ms":0,"end_ms":6000,"paced_replay":true,"replay_deadline_ms":40}
```

## 运行和 CPU 检查证据

主任务把 model_id 的 lazy 分发加入 inference.execute 后，平台继续通过标准协议运行。WSL 已建立的基础环境示例（不安装依赖）：

```bash
source environments/models.env.sh
"$BTV_MODELS_ENV/bin/python" -m packages.models run \
  --request /mnt/d/video/models/jobs/TRACKNET_JOB/ATTEMPT/request.json \
  --result /mnt/d/video/models/jobs/TRACKNET_JOB/ATTEMPT/result.json
```

同等薄包装：`python scripts/models/run_tracknet_reuse.py --request REQUEST --result NEW_RESULT`。请求沿用完整 Asset，不以示例假路径冒充实际素材。每次更改 mode 使用新 attempt_id/output_dir/result；输出为 `tracknet-points.json`、`tracknet-report.json`，先持有 models 20MB 写入预留再运行。代码/权重由独立下载任务计算峰值，不在该预留内重复下载。该脚本本身不另建排队系统；生产调用仍走平台运行租约 / watchdog。

2026-09-29 Windows CPU：`python -m unittest discover -s tests/models -q` 共 124 tests，PASS，3 个 symlink 能力测试因当前 Windows 账户权限 SKIP；其中本文件新增 18 个测试，17 PASS / 1 SKIP。覆盖因果不读未来、离线背景最晚依赖、首尾平均 / 三角汇聚、原 PTS / VFR、decode 像素与帧数边界、背景预算、SHA256、manifest pin、用途传播与原子独占输出。`python scripts/models/run_tracknet_reuse.py --help` PASS。测试只用 CPU 数组、轮廓算法和假模型 / 假解码器；没有运行 torch、模型权重或 GPU。没有安装和下载，也没有写 D 盘。R-07a/R-07c/R-03b 的真实模型实验仍由主任务记录，不能由这些测试转为 PASS。

版本字段 / 节奏回放 / 固定源码字节 pin 追加后：本文件 24 tests，23 PASS / 1 symlink 权限 SKIP；完整 models suite 176 tests，173 PASS / 3 SKIP。可控 CPU 时钟覆盖快处理等待、慢处理 backlog 与 deadline missed、迟到不丢帧、仅因果模式可测、120 秒上限、worker 错版本拒绝，以及 manifest 自签假源码拒绝。真实 GPU 运行由 root 单独组织，这些计时假对象不能作为真实性能证据。
