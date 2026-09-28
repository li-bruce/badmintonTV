# 本地工作台

Windows原生控制面、SQLite和独立CPU worker；WSL模型不直接访问数据库。无需torch即可执行素材、标注、规则查询和研究样片链路。

## 启动

```powershell
# 仅首次：安装独立环境，不修改全局Python；先按EXECUTION_PLAN检查容量
python -m venv D:/video/runtime/platform/env
D:/video/runtime/platform/env/Scripts/python.exe -m pip install -e '.[test]'
$env:BTV_STORAGE_ROOT='D:/video'
$env:BTV_FFMPEG='<已核验的ffmpeg.exe绝对路径>'
$env:BTV_FFPROBE='<已核验的ffprobe.exe绝对路径>'
./start-platform.ps1
# 在第二个终端，同样设置上述环境：
./start-worker.ps1
```

浏览器 http://127.0.0.1:18080；OpenAPI http://127.0.0.1:18080/docs 。Label Studio http://127.0.0.1:18081，安装、启动、实测及PTS语义见 [LABEL_STUDIO.md](LABEL_STUDIO.md)。所有服务仅本机。启动脚本不自动终止已有进程。

管理员可登记`BTV_RENDER_COMMAND_JSON=["python","-m","packages.render"]`与按model_id精确匹配的`BTV_MODEL_COMMANDS_JSON`；不再接受通用模型fallback。worker追加`run --request ... --result ...`，命令不会从用户页面或模型卡执行。合并后的根目录可直接导入各namespace包；本次联调临时通过`PYTHONPATH`只读引用其他模块工作树，没有复制源视频。

集成后在两个终端都运行 `. ./configure-platform-adapters.ps1 -FfmpegPath '<ffmpeg.exe>' -FfprobePath '<ffprobe.exe>'`，再分别运行启动脚本。它将Python搜索路径设为当前仓库，以当前仓库自动构造WSL受控argv，默认只登记CPU规则与实验pose。可用 `-ModelsRepo` 临时指定开发工作树；最终启动无需依赖6991/c5b1/3e52等旧工作树。WSL环境默认 `/mnt/d/video/runtime/models/env`；Linux离线缓存环境由bridge固定传入，WSL不读取平台SQLite。

数据库默认`D:/video/platform/platform.sqlite3`与`runtime.sqlite3`。`BTV_DB_PATH`可改原生路径，但占用仍计platform60GB；不得跨Windows/WSL同时操作WAL。runtime/platform10GB为环境与缓存上限。运行时容量预留与异常恢复见 [RUNTIME.md](RUNTIME.md)。

## 使用流程

1. 在素材页新建逻辑资料库，导入Asset manifest或输入共享根下原视频相对路径。同hash复用；清单总媒体超过8MB时由worker核验完整hash，成功后在任务页应用结果；小清单有限同步核验。原视频只读。
2. 选择视频，播放/定位，保存区间、球员、回合、击球或移动标签。未知保留unknown。修改须带expected_revision，冲突409。每次审阅记录human/agent，自动预测不会覆盖已确认条目。
3. 中文规则解析后编辑QuerySpec，再执行检索。同球员同回合before允许对手插入一拍；不支持的否定或混合语义明确拒绝，避免猜测。候选显示条件、源时间、未知与审阅来源，不将排序分数称准确率。
4. 明确确认候选后生成时间线。可编辑入出点、速度、标题、原声/静音、顺序；传递重叠片段合并保留事件引用。默认研究预览，导出强制标识“待人工确认·本地研究样片”；正式导出需human审阅记录。公开发布权独立核查，应用不发布视频。
5. 任务页查看真实阶段/日志、取消/重试/产物下载。重启后任务和修订保留。worker中断标failed/WORKER_INTERRUPTED，显式重试产生新attempt。

LLM仅发送查询文字+schema；设置保存base_url/model/timeout/key_env，实际密钥只读环境变量并遮盖。未提供真实LLM端点时规则流程可用。GPU任务默认blocked/GPU_LEASE_REQUIRED；与models协调空窗后由管理员授予允许模型的有限窗口，独占租约须有停止证据才能释放。详见 [GPU.md](GPU.md) 与 [WSL_BRIDGE.md](WSL_BRIDGE.md)。平台网页提交6秒24帧真实pose已成功；这尚非四模块全部独立实验的统一调度器。

## 测试与边界

```powershell
D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/platform tests/contracts -q
```

当前测试227 passed、2 skipped（runtime独立symlink创建权限、显式选择的WSL实机测试；后者已另行通过）。真实视频与浏览器记录见 [VALIDATION.md](VALIDATION.md)。测试合成字节只证明合同/状态机，不是视频识别成绩。无私人录像、无细手法专家真值；自动动作识别准确率未作承诺。

库扫描/网络下载不属于当前平台长任务适配器；通过library已生成manifest与原位引用接入。前端没有复杂轨迹编辑器，视频跟踪框使用已实测Label Studio。跨WSL为按任务启动的受控模型CLI；尚无跨镜头回放自动去重与常驻模型服务。
