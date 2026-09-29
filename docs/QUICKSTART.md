# 本机启动与第一条工作流

从 `C:/Users/USER/Desktop/Program/badmintonTV` 运行。既有控制面环境无需重复安装；新增模型各自的安装和实际运行状态见[本轮验收](ROUND_VALIDATION_2026-09-29.md)，不能把部分下载的权重当作可用模型。

## 启动网页与 worker

在两个 PowerShell 终端分别执行下面的配置，再分别启动 API 与 worker：

```powershell
$renderTools = Get-Content environments/render-runtime-compat.json -Raw | ConvertFrom-Json
. ./configure-platform-adapters.ps1 -EnableExperimentalYolo -EnableVlEmbedding -FfmpegPath $renderTools.checks.ffmpeg -FfprobePath $renderTools.checks.ffprobe
# 第一个终端：
./start-platform.ps1
# 第二个已执行上述配置的终端：
./start-worker.ps1
```

打开 http://127.0.0.1:18080 。已存在的资料、标注、修订、任务和时间线保存在 `D:/video/platform`，重启后继续使用；启动脚本不会终止已有服务。Label Studio 的独立启动与配置见 [标注工具说明](platform/LABEL_STUDIO.md)。

## 第一个可用案例

1. 素材与标注：使用已有研究资料库，或导入 `D:/video/data/handoff/assets.v1.json` / `assets.doubles.v1.json`。目前是五段真实下载小样，另有一条大文件回归派生；不能当成六场独立比赛。
2. 选择素材后展开“兼容预览窗口与画质”，设置不超过120秒的窗口和720p/1080p，提交生成；worker完成后“刷新预览”。用缩略图、源时间定位、逐源帧和区间循环选择区间。降帧代理显示帧与源帧覆盖分别展示；需要看拍面时显式点“原分辨率核查”（同样需要worker），可1:1/2x/4x查看。普通逐帧不创建原图提取任务。
3. 设置区间、球员/回合和可见标签。不确定细手法时保留 unknown。普通用户选 human，自动化演示选 agent；二者分别记录。
4. 技战术检索：解析中文后检查并修改条件，再检索；候选附原片时间、命中条件及不确定原因。
5. 确认选片，生成时间线，调整排序、边界、标题和速度，选择30/60fps预设、安全区和可选平台时长规则，保存当前剪辑审核。导出设置随工程修订回载。
6. 提交竖屏导出，在模型与任务页查看真实进度、日志和成片。当前研究样片需勾选研究预览；正式导出要求对应的人类确认记录。

默认使用规则解析。LLM 端点可在设置中配置，密钥通过环境变量提供，不保存到数据库或 Git。本地 Qwen 0.6B 是开发实验，当前提示配置未通过可靠解析验收，不作为默认入口。

## GPU 姿态实验

网页经 Windows worker 调用 WSL 环境，不让 WSL 打开 SQLite。默认登记规则解析、COCO17稀疏/连续姿态和TrackNet；`-EnableExperimentalYolo`显式映射独立`yolo-env`。VL使用`-EnableVlEmbedding`及独立`vl-env`，须以本轮最终模型卡与实测状态为准；未完成依赖时不启用。`-EnableExperimentalBst`只启用命令映射，当前缺少连续有效输入，不能当作粗球种已可用。没有GPU窗口时任务明确blocked。

本轮模型实验已结束、GPU与队列已归还，main worker现已常驻。2026-09-29 19:08–20:08已开放pose/continuous-pose/TrackNet/YOLO/VL试用窗口；root补充一项4秒/6秒单窗验收后已归还，供手动使用，过期后如实blocked。后续每次先与models任务协调，确认独立实验已停止且账本没有 active/orphaned 计算，再为交互会话开启至多一小时窗口；下面命令示例只授权COCO17：

```powershell
$gpuSession = 'interactive-' + [guid]::NewGuid().ToString('N')
& D:/video/runtime/platform/env/Scripts/python.exe -m packages.runtime.gpu grant-window --db D:/video/platform/runtime.sqlite3 --window-id $gpuSession --models torchvision-keypointrcnn --seconds 3600 --coordination-note '本机交互会话；独立模型训练已暂停'
```

然后网页选择 COCO17、填写已有素材 ID 和窗口参数。结果是带源时间的姿态特征，当前没有稳定球员跟踪或展搓/收搓分类。会话结束，确认任务停止后按 [GPU 说明](platform/GPU.md) 归还窗口；不要以到期或利用率为零代替停止证据。

## 检查与问题记录

```powershell
./scripts/integration/check-all.ps1
```

此脚本运行 CPU 合同、模块回归、Node前端回归和真实素材清单校验；不会下载、训练或把合成测试当识别准确率。测试使用独立临时目录，不操作业务数据库。GPU实测、失败原因与细标签真值缺口见 `docs/experiments/` 和 `docs/issues/`。

新职业数据仅位于`D:/video/data/training/`，不导入上述制作资料库，研究预览也不豁免。完整数据与差异见[训练数据验收](library/TRAINING_DATA_ACCEPTANCE.md)。当前浏览器rVFC寻帧回调约一秒的问题仍有[独立记录](issues/platform-preview-presentation-latency.md)；原分辨率截图使用后台源校验/解码，不承诺瞬时完成。

架构与分工见 [架构](ARCHITECTURE.md) 和 [执行计划](EXECUTION_PLAN.md)；最新完成项与限制见 [状态](STATUS.md)。
