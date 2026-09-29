# 研究实施轮验收记录

本轮目标由 [实施计划](IMPLEMENTATION_ROUND_2026-09-29.md) 定义。本表区分工程实现、真实运行与模型效果，旧轮次的 `INTEGRATION_VALIDATION.json` 不作为本轮通过证据。状态仅使用 PASS / FAIL / BLOCKED / NOT_RUN；阶段中部分断言通过不代表整阶段达标。

## 当前检查点：2026-09-29 17:26（北京时间）

| 检查 | 目标 / 预期 | 实际 / 证据 | 状态 |
|---|---|---|---|
| 公共合同 | 旧清单兼容；训练用途不能降级；登记来源字段有效；大来源图有界 | 主线 `aae0c99`，root 独立 `pytest tests/contracts`：186 passed；先前独立性能反例修复已复核 | PASS |
| 完整职业数据 R-04a | 作者完整ZIP下载，大小/MD5/SHA及媒体/标注清单核实 | 6,455,837,331B目标包仍在下载；partial不能算完整数据。BFMD是补充标注包，不是原视频包 | NOT_RUN |
| 制作用途隔离 R-04b | 入库、检索到时间线、保存、执行、独立CLI及研究预览均拒绝训练数据 | 公共合同通过；发布器/平台/渲染跨模块边界仍在修复和复核，不能仅据合同测试宣称全链通过 | NOT_RUN |
| 播放代理 R-02a | CFR、VFR、浏览器不支持格式有代理，回写源PTS误差≤一源帧 | 模块真实CPU测试和浏览器测量进行中；最终源码未集成 | NOT_RUN |
| 网页交互 R-02b | 定位、逐帧、循环、缩略图和标注保存；30点冷/热统计 | 源帧映射、seeked事件、最终画面呈现分别记录；仍在测量 | NOT_RUN |
| 竖屏输出 R-01a | 1080×1920，30/60fps，H.264/AAC，安全区及工程设置可复用 | 模块旧普通真实素材CPU各4轮完成，主线集成与设置持久化尚待验证 | NOT_RUN |
| 硬件编码 R-03a | 同版本同输入CPU/NVENC，技术/质量/实际耗时证据齐全 | FFmpeg9实测因NVENC API13.1/驱动13.0不兼容失败；隔离FFmpeg8已准备重测 | FAIL（首次配置；兼容方案待测） |
| 轨迹/姿态/位置 R-07a/b | 官方权重、真实输入、源PTS和坐标含义明确 | TrackNet/BST权重及受限CPU载入已完成，真实GPU任务准备中 | NOT_RUN |
| 视频向量 R-05a | 隔离WSL对真实短窗及中文查询产生有限向量/排序 | Qwen3-VL-Embedding-2B权重与独立环境下载中 | NOT_RUN |
| 实时 R-07c | 因果输入，稳态RTF≤1，延迟/积压/丢帧有测量 | 原版TrackNet离线窗口不能作为实时通过证据；因果变体待实际测量 | NOT_RUN |
| 粗动作 R-07e | 作者权重以真实双人姿态、场地与球轨迹运行 | 不能用随机或补零特征代替真实链；实际输入准备中 | NOT_RUN |
| 细手法及正式检索 R-05b/R-06a | 专家定义、独立真值与整场划分后评测 | 缺展搓/收搓/后退小跳专家真值；不因下载粗球种标注而解除 | BLOCKED |

## 跨模块复核与修复

- 登记来源：library发布器和公共 `TrainingRegistryEntry` 必须都拒绝非法 `source_asset_id/source_sha256`；否则一个坏记录会使所有制作请求因登记损坏而阻塞。公共修复已合入 `aae0c99`，library最终修复SHA待复核。
- 渲染来源闭包：直接片段核验真实hash仍不足；提供的可达父资产也要核验真实文件。独立反例同时伪造父hash和子来源hash可越过旧检查，render正在修复。
- 取消与锁：旧worker强杀可留下render owner锁。新取消文件协议须与worker接通，并实际证明取消后下一任务可运行；仅 `compute_stopped=true` 不足。
- 工程设置：导出Timeline保留正式尺寸；preset、安全区和平台profile应随工程设置保存并回载，避免只在一次CLI请求生效。
- 模型环境：管理员按model_id映射WSL环境，VL使用新隔离环境，不能把所有新模型投到旧torch环境；无权重或无GPU窗口如实显示。

## 重现

公共合同检查使用平台隔离Python，临时文件放本工作区 `.runtime`，不写媒体目录：

```powershell
$verifyDir = Join-Path (Get-Location) ('.runtime/pytest-registry-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $verifyDir | Out-Null
& D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/contracts -q -p no:cacheprovider --basetemp $verifyDir
```

主线仍等待各模块最终提交和真实实验后统一检查。当前不启动主worker，以免抢占模块协调的GPU实验。
