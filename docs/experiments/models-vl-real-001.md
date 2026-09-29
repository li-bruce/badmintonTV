# Qwen3-VL：固定真实视频窗口与 CLIP 对照

日期：2026-09-29。冻结请求为 `configs/models/reuse-payloads/qwen-vl-001.json`：旧 FBBench Asset `asset-5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90`，原片 669,106 B，6 秒，1280×720、30 fps、time_base=1/15360。窗口为 `[0,3000)`、`[3000,6000)` ms，各取 6 帧、缩至 672×384；三条中文及对应三条英文查询，启用同帧 CLIP 均值对照。不修改窗口或查询来挑选结果。

源 `data/raw/finebadmintonbenchmark/video_001951.mp4` 只读。usage_scope=general 不代表公开/商业版权；原片 rights=unknown、match_id=unknown、split=unassigned、身份未确认。查询是开发者诊断输入，不是人工真值；准确率、P@K 和细手法结论仍未测。

## 实际环境和完整安装

同一个 `/mnt/d/video/runtime/models/vl-env`，Python 3.11.16。17 个官方核心 wheel 共 3,916,256,631 B，全部固定 SHA 通过；Qwen revision `9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda` 的 18 文件共 4,271,068,726 B 校验完整。下载来源、许可和代码审阅见 `docs/models/VL_EMBEDDING_REUSE.md` 与 `VL_WHEEL_TRANSFER_REVIEW.md`。

恢复安装 run `runtime/models/vl-resume-runs/20260929T105054Z-3c3fa8e2` 全部步骤成功，pip check 无冲突，实际 CPU 导入 Qwen3VLModel/PreTrainedModel/ForConditionalGeneration/Processor 成功且 cuda_initialized=false、model_weights_loaded=false。版本为 torch2.8.0+cu128、vision0.23.0+cu128、transformers4.57.3、qwen-vl-utils0.0.14、PyAV15、Pillow11.2.1、NumPy2.4.6、safetensors0.5.3。44 个本次安装包的实际来源/归档 hash、原始 pip report 引用、freeze 和 CPU probe 留存在 `environments/models-vl-installed-20260929.json` 及同名 `.freeze.txt`。

安装后 models runtime=19,164,852,807 B <35 GB；shared disk+既有 native base/pkgs=7,169,319,439 B <15 GB；加其余 runtime 20 GB 预留为46,334,172,246 B <70 GB，D 盘剩余922,903,875,584 B。未改旧 models/env、YOLO 子环境、全局驱动或用户环境；安装与探针不能当作 GPU 推理成功。

## 首次真实作业：加载失败，原记录保留

`job-a258df27cc5d4598896dd1d6495c955a / attempt-1` 由 native platform Python、统一 Queue/worker/WSL bridge、GPU 租约执行。失败阶段 `cold_load`，异常 `AttributeError: 'str' object has no attribute 'from_pretrained'`。根因是本适配器的 `from __future__ import annotations` 被动态 `compile(source,...,'exec')` 隐式继承；官方子类的 `config: Qwen3VLConfig` 注解因此变为字符串。Transformers4.57.3 的 `__init_subclass__` 将该子类注解作为 config_class，from_pretrained 在未显式提供配置实例时再调用该字符串的 from_pretrained，导致失败。不是权重损坏或缺依赖。

此前源 SHA、4.27 GB 权重清单及完整 SHA、实际依赖版本、两窗真实解码均已通过。源 PTS 分别为 `0,7680,15360,23040,30720,38400` 和 `46080,53760,61440,69120,76800,84480`，每个窗口内对应0/0.5/1/1.5/2/2.5秒。报告 elapsed=59.0191秒，weight verification=12.7056秒；没有视频/查询向量，没有排名，也没有用替代结果写成功。

| 保留文件（storage-root 相对路径） | bytes | SHA256 |
|---|---:|---|
| models/jobs/job-a258df27cc5d4598896dd1d6495c955a/attempt-1/failure.json | 9760 | 71d12f1ea5941392f2c3ddf9530bdff758cda10fa780365debe9f8083aa999a8 |
| platform/jobs/job-a258df27cc5d4598896dd1d6495c955a/attempt-1/result.json | 302 | 498c084453f9b34dc679295063c258b384505a8a60980ce9bc6edaa9d199a846 |
| platform/jobs/job-a258df27cc5d4598896dd1d6495c955a/attempt-1/bridge.done.json | 292 | a9576a55d847230ce0ae2bb33760683065c0c9f2c7fec3c09b9174efa63f8efd |

bridge receipt `compute_stopped=true`、`exit_code=1`；平台作业为 failed，GPU lease/window均null。receipt reason=completed只说明进程正常收尾，不能把非零exit code解释成推理成功。

后续仅修适配层 `compile(...,dont_inherit=True)` 恢复官方独立模块语义，并显式加载本地 Qwen3VLConfig 实例；先做实际 CPU API 验证，再以新 job 重试同一请求。不修改上游固定源码、权重、环境版本、输入窗口或查询；不覆盖本次失败。

修复提交 `c609b53`，26 项定向 CPU 测试通过。真实 vl-env CPU复现旧 future 语义下 `config_class='Qwen3VLConfig'`；修后类字段与 `__annotations__['config']` 均为真正的 Transformers Qwen3VLConfig 类，本地实例 hidden_size=2048，固定官方代码 SHA 未变，cuda_initialized=false、model_instantiated=false、weights_loaded=false。

## 重试前实际 CPU processor 检查

独立在真实 vl-env 运行本地 Qwen3VLProcessor/Qwen3VLVideoProcessor，采用上述原片、两窗和适配器同样的 `videos_kwargs/video_metadata`。两窗输入均 `[6,384,672,3]`，输出 input_ids/attention_mask=`[1,800]`、pixel_values_videos=`[3024,1536]`、video_grid_thw=`[[3,24,42]]`；全部在 CPU，未加载模型权重、未运行模型前向或 CUDA。`do_sample_frames=False/do_resize=False` 路径实际可用，没有二次采样或缩放。

时间函数实际收到 indices0..5/merge_size2，返回 `[0.25,1.25,2.25]` 秒。官方 processor 文本保留一位小数，本例实际显示 `<0.2 seconds>/<1.2 seconds>/<2.2 seconds>`；不能声称 token 时间精度等于原始 PTS。完整 PTS/时基仍单独保留。processor load=0.86594秒、两窗 CPU call=0.04569/0.01037秒，不含框架导入；该检查不是向量或识别结果。

## 同请求重试：真实视频与 CLIP 对照均成功

修复后仅重试一次，`job-604bf54336ae449a88e004622efd6d1f / attempt-1`，Qwen与CLIP comparison均 succeeded，events=[]。平台result、两个Artifact、独立bridge退出回执均通过当前主合同与哈希检查。GPU为RTX5090；done compute_stopped=true/exit0/reason completed，runner核验lease/window均null并归还共享queue。本轮模型实验到此结束，没有常驻模型worker。

| 产物（models/jobs/job-604bf54336ae449a88e004622efd6d1f/attempt-1/） | bytes | SHA256 |
|---|---:|---|
| features.json | 602179 | 3c449c04a746c5cdddf6d2b1959726bcf5331db0cf7b644c6c66b26988483fb3 |
| report.json | 10593 | 95bb77c52cb286258ddd9f4ef54bec74c5a8e734f6e944e339e69bbbb1ab0a98 |

Qwen产生2条视频向量+6条查询向量，每条2048维，全部finite，范数范围0.9999999978–1.0000000350。CLIP同样2+6条512维向量，范数约1。两窗源PTS与前述完全一致，视频各800tokens；三条中文28/29/25tokens，英文31/32/28tokens。没有丢失原片时间基准或把采样metadata的fps用于恢复原片PTS。

独立只读QA再次核对源媒体及PTS index的SHA、两份Artifact的字节与SHA、主request/result合同、退出回执，并重算Qwen/CLIP共24个余弦分数和12组排序，一致；分数最大浮点差分别1.33e-15/3.33e-16，范数最大误差3.50e-8/4.51e-8。六条查询与冻结payload一致、无乱码，全部计时非负、报告版本与真实vl-env probe一致。该QA不提供人工语义真值。

| 查询 | Qwen第1/第2窗（cosine，已排序） | CLIP第1/第2窗（cosine，已排序） |
|---|---|---|
| net_zh | 02:0.699779 / 01:0.689570 | 02:0.221500 / 01:0.218676 |
| overhead_zh | 02:0.626411 / 01:0.618422 | 02:0.228116 / 01:0.224865 |
| serve_zh | 02:0.651801 / 01:0.648021 | 02:0.223944 / 01:0.220661 |
| net_en | 01:0.701452 / 02:0.696134 | 02:0.317515 / 01:0.311130 |
| overhead_en | 02:0.646723 / 01:0.645275 | 02:0.329235 / 01:0.325233 |
| serve_en | 01:0.627880 / 02:0.624097 | 02:0.286539 / 01:0.279161 |

这些只是两个相关短窗内的诊断排名。Qwen三条中文均把02排首位，且网前/发球两组中英文排序不同；CLIP六条都把02排首位。没有冻结人工相关性真值，不能据此判胜负、声称区分发球/网前细手法或报P@K。Qwen与CLIP的cosine不在同一校准尺度，较大的数字不代表更高正确率，也不是概率。

## 实测时间和显存边界

| 项目 | 秒或bytes |
|---|---:|
| 总elapsed（含请求内CLIP对照） | 73.481262 s |
| Qwen权重完整核验 / cold load | 12.101369 / 31.977933 s |
| 两窗CPU decode合计 / RGB缩放合计 | 0.255548 / 0.120499 s |
| Qwen窗口01 / 02模型forward | 1.531801 / 0.054443 s |
| 6条Qwen文本forward | 每条0.01756–0.02480 s |
| Qwen peak allocated / reserved | 4,421,021,184 / 4,519,362,560 B |
| CLIP权重核验 / cold load | 2.956675 / 4.619849 s |
| CLIP peak allocated / reserved | 617,554,944 / 664,797,184 B |

总elapsed从容量reservation前到产物发布前，包含源/权重核验、依赖导入、CPU解码、两模型冷加载、嵌入和排名；不包含初始参数校验和最终JSON发布/hash/worker IPC。各GPU计时前后同步，D2H/归一化/CLIP窗口池化有独立postprocess计时。已记录子阶段合计54.160077秒，与总elapsed相差19.321185秒，属于未独立归因的框架启动、控制流等时间；这是报告后计算的差额，不伪造实测阶段。GPU allocator峰值不等于进程总显存。

第一次窗口的forward含首次运行开销，第二窗不能代表全比赛稳定吞吐。这里只处理12个采样帧，不能把6秒视频、0.054秒forward或总耗时推成直播/完整比赛速度，也没有NVDEC或物理live端到端测量。

复现使用 `scripts/models/run_registered_experiment.py --payload configs/models/reuse-payloads/qwen-vl-001.json --runtime-repo C:/Users/USER/Desktop/Program/badmintonTV --env-prefix /mnt/d/video/runtime/models/vl-env --coordination-note <已协调窗口>`。native Python为D:/video/runtime/platform/env/Scripts/python.exe；必须先协调唯一worker/queue/GPU租约，后续重跑使用新job，不覆盖现有结果。原失败与成功均保留，模型状态为experimental，准确率和precision_at_k仍null。
