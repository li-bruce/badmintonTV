# 研究实施轮验收记录

本轮目标由 [实施计划](IMPLEMENTATION_ROUND_2026-09-29.md) 定义。本表区分工程实现、真实运行与模型效果，旧轮次的 `INTEGRATION_VALIDATION.json` 不作为本轮通过证据。状态仅使用 PASS / FAIL / BLOCKED / NOT_RUN；阶段中部分断言通过不代表整阶段达标。

## 当前检查点：2026-09-29 18:02（北京时间）

| 检查 | 目标 / 预期 | 实际 / 证据 | 状态 |
|---|---|---|---|
| 公共合同 | 旧清单兼容；训练用途不能降级；登记来源字段有效；大来源图有界 | 主线 `aae0c99`，root 独立 `pytest tests/contracts`：186 passed；先前独立性能反例修复已复核 | PASS |
| 完整职业数据 R-04a | 作者完整ZIP下载，大小/MD5/SHA及媒体/标注清单核实 | ZIP6,455,837,331B、作者MD5一致，22/22文件完整提取（10MP4+10CSV+README/LICENSE），10视频hash已登记；逐场全解码/PTS探测进行中。CSV实测9817行，但中英文类别与少量坏区间须保留差异。BFMD已下载114/121条目，无原视频 | NOT_RUN（完整下载/提取子项PASS；首次格式兼容FAIL保留） |
| 制作用途隔离 R-04b | 入库、检索到时间线、保存、执行、独立CLI及研究预览均拒绝训练数据 | 公共合同通过；发布器/平台/渲染跨模块边界仍在修复和复核，不能仅据合同测试宣称全链通过 | NOT_RUN |
| 播放代理 R-02a | CFR、VFR、浏览器不支持格式有代理，回写源PTS误差≤一源帧 | 模块真实CPU测试和浏览器测量进行中；最终源码未集成 | NOT_RUN |
| 网页交互 R-02b | 定位、逐帧、循环、缩略图和标注保存；30点冷/热统计 | 源帧映射、seeked事件、最终画面呈现分别记录；仍在测量 | NOT_RUN |
| 竖屏输出 R-01a | 1080×1920，30/60fps，H.264/AAC，安全区及工程设置可复用 | 模块旧普通真实素材CPU各4轮完成，主线集成与设置持久化尚待验证 | NOT_RUN |
| 硬件编码 R-03a | 同版本同输入CPU/NVENC，技术/质量/实际耗时证据齐全 | FFmpeg9首次因API不兼容失败；隔离FFmpeg8同版本CPU/NVENC各8次技术检查通过，root核对16任务全部产物bytes/SHA。全帧无损参考质量对照完成，A/B/R原始PTS差0；agent有限ROI审片已完成，最终提交待集成 | NOT_RUN（兼容方案技术/指标子项PASS；首次FAIL保留） |
| 轨迹 R-07a | 官方权重、真实输入、源PTS球点/缺失及时间记录 | 旧真实6秒视频离线与因果回放均成功；root核验合同、产物SHA、bridge停止、180帧单调PTS与坐标边界。新职业数据和诊断画面待核 | NOT_RUN（旧真实小样运行子项PASS） |
| 姿态/位置 R-07b | 坐标可回查，校准和跟踪含义明确 | 连续Keypoint R-CNN与YOLO11n-pose+ByteTrack各90真实源PTS帧成功，root核对两次产物SHA/合同/bridge停止；匿名跟踪不等于球员身份，场地坐标与质量另待验证。新职业片实测正在进行 | NOT_RUN（旧真实小样运行子项PASS） |
| 视频向量 R-05a | 隔离WSL对真实短窗及中文查询产生有限向量/排序 | Qwen3-VL-Embedding-2B权重与独立环境下载中 | NOT_RUN |
| 实时 R-07c | 因果输入，稳态RTF≤1，延迟/积压/丢帧有测量 | 因果6秒文件回放active steady RTF=0.606，模拟到达完成P95=36.04ms/max=150.46ms，12/180帧超40ms，0主动丢帧；非物理直播，持续整链未验收 | NOT_RUN（短窗paced子项PASS，直播未测） |
| 粗动作 R-07e | 作者权重以真实双人姿态、场地与球轨迹运行 | 不能用随机或补零特征代替真实链；实际输入准备中 | NOT_RUN |
| 细手法及正式检索 R-05b/R-06a | 专家定义、独立真值与整场划分后评测 | 缺展搓/收搓/后退小跳专家真值；不因下载粗球种标注而解除 | BLOCKED |

## 跨模块复核与修复

- 登记来源：library发布器和公共 `TrainingRegistryEntry` 均已拒绝非法 `source_asset_id/source_sha256`，公共修复 `aae0c99`、library `041a5a9` 已合入并复核；避免一个坏登记阻塞所有制作请求。
- 渲染来源闭包：直接片段与提供的可达父资产均核验实际文件hash。独立反例曾共同伪造父hash和子来源hash越过旧检查，修复已合入 `281c137` 并重新复核通过。
- 取消与锁：旧worker强杀可留下render owner锁。新取消文件协议须与worker接通，并实际证明取消后下一任务可运行；仅 `compute_stopped=true` 不足。
- 工程设置：导出Timeline保留正式尺寸；preset、安全区和平台profile应随工程设置保存并回载，避免只在一次CLI请求生效。
- 模型环境：管理员按model_id映射WSL环境，VL使用新隔离环境，不能把所有新模型投到旧torch环境；无权重或无GPU窗口如实显示。

## 已核验的真实模型产物

root使用 `scripts/integration/verify-job-artifacts.py --require-bridge` 读取实际落盘结果，不重复占GPU：

| 任务 | 实际证据 |
|---|---|
| `job-16153fad2f21429e8f88aa48fb978ccc` / offline_weight | 6秒180帧，165点/15缺失；pipeline4.42055s，冷启动13.95494s；未来帧依赖明确为true（非因果）。2产物大小/SHA与bridge停止/exit0通过 |
| `job-4081ac5e54f944b7b087c149efe43e69` / causal_last | 同源180帧，160点/20缺失（含8帧预热）；冷启动11.15211s，paced pipeline5.98484s；每项available_after_source_ms不超过该源帧PTS。2产物大小/SHA与bridge停止/exit0通过 |

两次实际输入均为旧FBBench小样asset-5ad7e41a…，不是正在下载的新职业数据。全部源PTS单调，点坐标有限且在原1280×720范围；accuracy/recall均为null，events为空。上述结构检查不能证明点落在羽球上。NVDEC未使用，解码是PyAV软件路径。首次因果尝试的bridge心跳失败由模块保留独立记录，后续成功不覆盖失败。

相同旧片700–3700ms，`job-b8a4ac96da6543f8b4f6afc5ae3c4220` 的连续Keypoint R-CNN与 `job-98cb65954fab42408f3b6fd1082d6330` 的YOLO11n-pose+ByteTrack均输出90帧。root只读校验各两份产物实际SHA与停止证据通过，events均空。YOLO记录pose1.73774s、tracking0.06082s、冷加载32.20954s；旧报告阶段计时还未覆盖整个流程，不能由pose耗时单独宣称实时达标。11帧存在此前track缺失；不以自动track ID代替姓名或已验证的整场稳定身份。

新增YOLO代码/权重为AGPL-3.0，独立小环境复用既有torch只读包，未修改全局Python。新职业视频与其模型诊断继续保留training_only，不能进入制作库或成片工作流。

## 主线源码与分环境验证

- render `4ecaf6d + db587aa` → main `6518a09 + 281c137`；独立来源闭包反例复核通过，main 142 passed / 1 Windows symlink skip。
- models `3d018eb` → main `9975361`；平台轻环境227 passed / 13 skip，其中10个NumPy/OpenCV算法用例已在既有WSL模型env独立补跑10/10通过。剩3项为Windows symlink权限。未向平台安装训练依赖；这些检查不加载GPU权重。
- heartbeat `21e1694` → main `e9b2d7c`；main 47 passed / 1显式WSL集成opt-in skip，独立实际Windows短暂共享冲突恢复检查已通过。原故障缺详细errno，不能追溯断言它一定由共享冲突造成。
- library `a9047d1 + 1aa32b5 + e8331d3` → main `041a5a9 + a2f0eaf + 5fcf5c5`；最新root全套165/165通过、311 subtests。真实ZIP合法InfoZIP Unicode Path扩展曾被拒绝；修复检查原名/规范名双重路径安全、扩展CRC/重复与局部/中央头一致性，独立32样例+7精准回归通过，真实22/22文件现已完整提取。首次失败收据保留。
- FFmpeg8同版本真实CPU/NVENC记录分别位于 `render/benchmarks/presets-controlled-cpu-7b61b195daf3` 和 `presets-controlled-nvenc-6e21d23d0d7f`。30fps三次重复中位数CPU10.356806s、NVENC11.194288s；60fps分别11.514771s、12.861280s。均含worker/CLI启动、核验等开销，不是单独编码时间。源hash预读，first-observed不称操作系统冷缓存。
- 本片CPU/NVENC分别使用CRF/CQ，不等同质量；实际较慢与文件较大不构成NVENC所有场景都无收益的结论。GPU已归还，后续质量对照用CPU。

完整ZIP作者MD5为 `cb3fcaca0ae9b08c564ac2a19ae4e7a0`，本地SHA256为 `a3518f52d66dd6c5d2b01ce1347de8e589516ccc24a72aae818fea64e0b04439`；root只读核对实际大小、下载收据和校验报告。目录声明解压总6,467,329,596B，ZIP+原件12,923,166,927B。包内许可为CC BY-NC4.0，外层API仍记CC BY4.0；README称processed clips，完整公开包不等于未经剪辑整场。

## 重现

公共合同检查使用平台隔离Python，临时文件放本工作区 `.runtime`，不写媒体目录：

```powershell
$verifyDir = Join-Path (Get-Location) ('.runtime/pytest-registry-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $verifyDir | Out-Null
& D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/contracts -q -p no:cacheprovider --basetemp $verifyDir
```

主线仍等待各模块最终提交和真实实验后统一检查。当前不启动主worker，以免抢占模块协调的GPU实验。
