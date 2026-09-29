# 本机启动与第一条工作流

从 `C:/Users/USER/Desktop/Program/badmintonTV` 运行。既有控制面环境无需重复安装；新增模型各自的安装和实际运行状态见[本轮验收](ROUND_VALIDATION_2026-09-29.md)，不能把部分下载的权重当作可用模型。

## 启动网页与 worker

在两个 PowerShell 终端分别执行下面的配置，再分别启动 API 与 worker：

```powershell
$renderTools = Get-Content environments/render-runtime.json -Raw | ConvertFrom-Json
. ./configure-platform-adapters.ps1 -FfmpegPath $renderTools.checks.ffmpeg -FfprobePath $renderTools.checks.ffprobe
# 第一个终端：
./start-platform.ps1
# 第二个已执行上述配置的终端：
./start-worker.ps1
```

打开 http://127.0.0.1:18080 。已存在的资料、标注、修订、任务和时间线保存在 `D:/video/platform`，重启后继续使用；启动脚本不会终止已有服务。Label Studio 的独立启动与配置见 [标注工具说明](platform/LABEL_STUDIO.md)。

## 第一个可用案例

1. 素材与标注：使用已有研究资料库，或导入 `D:/video/data/handoff/assets.v1.json` / `assets.doubles.v1.json`。目前是五段真实下载小样，另有一条大文件回归派生；不能当成六场独立比赛。
2. 预览原片，设置区间、球员/回合和可见标签。不确定细手法时保留 unknown。普通用户选 human，自动化演示选 agent；二者分别记录。
3. 技战术检索：解析中文后检查并修改条件，再检索；候选附原片时间、命中条件及不确定原因。
4. 确认选片，生成时间线，调整排序、边界、标题和速度，保存当前剪辑审核。
5. 提交竖屏导出，在模型与任务页查看真实进度、日志和成片。当前研究样片需勾选研究预览；正式导出要求对应的人类确认记录。

默认使用规则解析。LLM 端点可在设置中配置，密钥通过环境变量提供，不保存到数据库或 Git。本地 Qwen 0.6B 是开发实验，当前提示配置未通过可靠解析验收，不作为默认入口。

## GPU 姿态实验

网页经 Windows worker 调用 WSL `/mnt/d/video/runtime/models/env`，不会让 WSL 打开 SQLite。默认配置登记受限规则解析和 COCO17 姿态；没有启动 GPU 窗口时任务明确 blocked。

研究实施轮的模型实验正在进行，主worker暂不常驻，以便模块串行实测。后续每次先与models任务协调归还GPU，确认独立实验已停止且账本没有 active/orphaned 计算，再在仓库根为交互会话开启至多一小时窗口；下面命令仅在这些前提满足后使用：

```powershell
$gpuSession = 'interactive-' + [guid]::NewGuid().ToString('N')
& D:/video/runtime/platform/env/Scripts/python.exe -m packages.runtime.gpu grant-window --db D:/video/platform/runtime.sqlite3 --window-id $gpuSession --models torchvision-keypointrcnn --seconds 3600 --coordination-note '本机交互会话；独立模型训练已暂停'
```

然后网页选择 COCO17、填写已有素材 ID 和窗口参数。结果是带源时间的姿态特征，当前没有稳定球员跟踪或展搓/收搓分类。会话结束，确认任务停止后按 [GPU 说明](platform/GPU.md) 归还窗口；不要以到期或利用率为零代替停止证据。

## 检查与问题记录

```powershell
./scripts/integration/check-all.ps1
```

此脚本运行 CPU 合同、模块回归和真实素材清单校验；不会下载、训练或把合成测试当识别准确率。测试使用独立临时目录，不操作业务数据库。GPU 实测、Qwen 失败原因、细标签真值缺口见 `docs/experiments/` 和 `docs/issues/`。

架构与分工见 [架构](ARCHITECTURE.md) 和 [执行计划](EXECUTION_PLAN.md)；最新完成项与限制见 [状态](STATUS.md)。
