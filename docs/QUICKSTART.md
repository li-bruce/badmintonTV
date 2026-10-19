# 本机启动与第一条工作流

新设备先按[迁移指南](MIGRATION_GUIDE.md)和[部署命令](deployment/README.md)选择workbench-cpu或desktop-cpu环境，运行plan、setup和doctor。播放/标注不需要安装GPU框架，完整源码包也不强制安装全部环境。当前设备已有控制面环境，无需重复安装。

以下D:/video是本机示例；其他设备替换为自己的storage root。根启动脚本支持显式环境与数据路径，并从脚本所在仓库启动；部署入口为`python scripts/deploy/manage.py --help`。本轮结果见[2026-10-19验证](ROUND_VALIDATION_2026-10-19.md)。

## 先使用人工训练标注与手册

已有本机服务时直接打开`http://127.0.0.1:18080/training`；手册为`http://127.0.0.1:18080/guide/`。否则在项目目录运行：

```powershell
./start-platform.ps1 -StorageRoot D:/video -Profile workbench-cpu -TrainingReviewer human
```

单纯打开训练原片、标记、保存和导出数据不需要worker或GPU。项目、人物和队伍手填；从已登记目录添加视频。操作见[标注使用指南](FRAMEWORK_GUIDE.md)。自动化验收另用agent实例和独立数据库；旧worker/GPU窗口记录均属历史，不表示现在仍运行。

## 启动制作网页与 CPU worker

在完整源码包中安装desktop-cpu环境并配置FFmpeg。使用两个PowerShell终端分别启动API与worker；只装workbench-cpu时继续用上面的标注入口，不启动渲染worker：

```powershell
# 两个终端分别设置当前设备的实际工具路径：
$env:BTV_FFMPEG = 'D:/tools/ffmpeg/bin/ffmpeg.exe'
$env:BTV_FFPROBE = 'D:/tools/ffmpeg/bin/ffprobe.exe'
# 第一个终端：
./start-platform.ps1 -StorageRoot D:/video -Profile desktop-cpu
# 第二个终端：
./start-worker.ps1 -StorageRoot D:/video -Profile desktop-cpu
```

打开 http://127.0.0.1:18080 。已存在的资料、标注、修订、任务和时间线保存在 `D:/video/platform`，重启后继续使用；启动脚本不会终止已有服务。Label Studio 的独立启动与配置见 [标注工具说明](platform/LABEL_STUDIO.md)。

## 第一个可用案例

1. 素材与片段：使用已有研究资料库，或导入 `D:/video/data/handoff/assets.v1.json` / `assets.doubles.v1.json`。目前是五段真实下载小样，另有一条大文件回归派生；不能当成六场独立比赛。
2. 选择素材后展开“预览设置”，设置不超过120秒的窗口和720p/1080p，提交生成；worker完成后“刷新预览”。用缩略图、源时间定位、逐源帧和区间循环选择区间。降帧代理显示帧与源帧覆盖分别展示；需要看拍面时显式点“原始画面”（同样需要worker），可1:1/2x/4x查看。普通逐帧不创建原图提取任务。
3. 设置区间、球员/回合和可见标签。不确定细手法时保留 unknown。普通用户选 human，自动化演示选 agent；二者分别记录。
4. 技战术检索：解析中文后检查并修改条件，再检索；候选附原片时间、命中条件及不确定原因。
5. 确认选片，生成时间线，调整排序、边界、标题和速度，选择30/60fps预设、安全区和可选平台时长规则，保存当前剪辑审核。导出设置随工程修订回载。
6. 提交竖屏导出，在任务页查看真实进度、日志和成片。当前研究样片需勾选研究预览；正式导出要求对应的人类确认记录。

默认使用规则解析。LLM 端点可在设置中配置，密钥通过环境变量提供，不保存到数据库或 Git。本地 Qwen 0.6B 是开发实验，当前提示配置未通过可靠解析验收，不作为默认入口。

## GPU 姿态实验

以下是原设备历史GPU实验的说明，不是新设备CPU部署步骤。`configure-platform-adapters.ps1`依赖旧的D:/video环境布局；新设备先按模型部署指南独立运行，跨盘接回网页仍需改造WSL桥。

网页经 Windows worker 调用 WSL 环境，不让 WSL 打开 SQLite。默认登记规则解析、COCO17稀疏/连续姿态和TrackNet；`-EnableExperimentalYolo`显式映射独立`yolo-env`。VL使用`-EnableVlEmbedding`及独立`vl-env`，须以模型卡与实测状态为准；未完成依赖时不启用。`-EnableExperimentalBst`只启用命令映射，当前缺少连续有效输入，不能当作粗球种已可用。没有GPU窗口时任务明确blocked。

历史上2026-09-29 19:08–20:08曾开放pose/continuous-pose/TrackNet/YOLO/VL试用窗口；补充验收后已归还。这不代表当前worker或GPU窗口仍有效。后续每次先与models任务协调，确认独立实验已停止且账本没有 active/orphaned 计算，再为交互会话开启至多一小时窗口；下面命令示例只授权COCO17：

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
