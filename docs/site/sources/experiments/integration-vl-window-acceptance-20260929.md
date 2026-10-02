# Qwen3-VL 4秒/6秒单窗补充验收

日期：2026-09-29；执行者：root。源码 main `5f1577c`，服务运行代码 `a9bdc42`（两者间只有目录与文档变化）。本实验补足原模块要求，不覆盖先前两个3秒窗口的原报告。

| 目标/预期 | 实际 | 状态 |
|---|---|---|
| 主API提交，常驻Windows worker桥接WSL，完整保存请求/结果/停止回执 | `job-eda75da8ce02476ebbdcbbf3f25bad27`，attempt-1 succeeded，bridge exit0、compute_stopped=true、events=[] | PASS |
| 4–6秒单窗，各6帧，沿用冻结的3中文+3英文查询 | 先保存本目录request.json，后POST；窗口[0,4000)、[0,6000)，Qwen与CLIP成功 | PASS |
| 向量有限归一，排序可重算，源PTS可回查 | 8个2048维向量，范数0.9999999727–1.0000000272；root逐项重算12相似度、核对12源PTS及有序窗口范围 | PASS |
| 实际产物大小/SHA与请求结果合同匹配 | features 602149B / `bef8c4f3587cc34d5fd79cb6ef7c576283b90904289d3265e3864ba5aadf407a`；report 10705B / `ca86660a120712416c2f4c518b1c05f7d780536972067f3264b277a0c0af329d` | PASS |
| 任务结束释放GPU，Web显示真实成功 | API health ready；lease=null；队列无queued/running；浏览器显示该job succeeded及11卡实际状态 | PASS |
| 细动作准确率/正式检索P@K | 没有冻结专家真值，两个窗口相互重叠，accuracy/P@K为null | BLOCKED |

输入为原general FBBench `asset-5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90`，6秒669106B；不是新Fine2026训练视频，也不是两场独立比赛。主API使用既有Asset，不修改元数据以制造机位/动作真值。两窗各采6帧，max_pixels=262144，batch_size=1。

运行使用既有`/mnt/d/video/runtime/models/vl-env`：torch2.8.0+cu128、transformers4.57.3；官方模型固定revision `9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda`。无新下载、无新安装、无训练，原失败attempt保留。源视频由PyAV CPU解码，不含NVDEC加速。

报告elapsed=73.5327956s，包含校验、冷加载、向量与CLIP对照，不包含结果JSON发布及最初参数校验。Qwen冷加载31.9048972s，分配显存峰值4,421,021,184B、预留4,519,362,560B（不是整机或驱动进程峰值）。两窗前向0.8798177s和0.0538071s，不能据后者推断整场/直播实时性。

复核命令：`D:/video/runtime/platform/env/Scripts/python.exe scripts/integration/verify-job-artifacts.py --job-id job-eda75da8ce02476ebbdcbbf3f25bad27 --require-bridge`。可重复只读检查；无需再跑GPU。冻结请求见[请求](integration-vl-window-acceptance-20260929.request.json)，持久化汇总见[本轮机器验收](../ROUND_INTEGRATION_VALIDATION_2026-09-29.json)。本机详细数值重算收据为`.runtime/root-vl-window-numeric-verification.json`。

该一次补充作业使用root已接手的有限GPU窗口；窗口初始记录写的是供手动交互，本次额外验收在这里明确记录，不能再宣称该窗口内自动作业数为0。现无持续自动GPU任务；窗口按原定20:08到期。

独立reviewer只读复核也为PASS：原片及PTS index真实SHA、12点源时间轴、Qwen 8×2048与CLIP 8×512全部有限归一；24个点积和12组排序一致，最大点积误差分别1.11e-15、3.33e-16。六条中英查询与原job604精确一致；未重复GPU。该复核已嵌入本轮机器验收JSON。
