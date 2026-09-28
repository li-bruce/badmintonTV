# Canonical v1.0 fixtures

这些文件只用于跨模块合同兼容检查，所有资产、事件和产物均为显式 synthetic 结构夹具；它们不是已下载视频、人工真值、模型预测或实际渲染成功记录。固定的 hash/size/路径用于结构校验，不能据此读取或发布产物。

`asset-manifest.json`、`events.json`、`query.json`、`candidate.json`、`timeline.json` 和 `model-manifest.json` 覆盖主要交换对象。`render-request.json` 有非空已确认的合成片段，`model-request.json` 展示模型入口；assets 只放顶层数组。`result-{succeeded,failed,blocked,cancelled}.json` 与请求的 job_id/attempt_id 一致，分别匹配退出码 0/1/2/130。`progress.jsonl` 无 attempt_id，归属由启动该子进程的 worker 记录。所有未校准置信度、未知手法与未观测值保留 null/unknown。

schema 文件在相邻 `../schemas/`；可重新导出：

```powershell
D:/video/runtime/platform/env/Scripts/python.exe -m packages.contracts --output packages/contracts/schemas
D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/contracts -q
```

需要真正运行非空 render 示例时，用同目录 `generate_media.py` 生成短小 CPU 合成媒体，并输出基于实际 SHA256、大小和 ffprobe 的 request 文件。生成器只写 platform owner，使用平台统一容量预留账本，不覆盖已有目录；渲染器输出仍在自己的 render owner。示例命令（FFmpeg 和 ffprobe 路径替换为实际已安装工具）：

```powershell
python -m packages.contracts.fixtures.generate_media --storage-root D:/video --ffmpeg D:/video/runtime/platform/tools/ffmpeg.exe --ffprobe D:/video/runtime/platform/tools/ffprobe.exe --fixture-id contract-smoke-01
```

输出位于 `platform/contract-fixtures/<fixture-id>/render-request.json`；调用 render 时必须传入该实例化请求，不能拿本目录的虚构源片 metadata 冒充媒体。生成器本身不承担真实视频验收。
