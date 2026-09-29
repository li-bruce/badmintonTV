# 研究实施轮验收记录

本轮目标由 [实施计划](IMPLEMENTATION_ROUND_2026-09-29.md) 定义。本表区分工程实现、真实运行与模型效果，旧轮次的 `INTEGRATION_VALIDATION.json` 不作为本轮通过证据。状态仅使用 PASS / FAIL / BLOCKED / NOT_RUN；阶段中部分断言通过不代表整阶段达标。

## 当前检查点：2026-09-29 18:56（北京时间）

| 检查 | 目标 / 预期 | 实际 / 证据 | 状态 |
|---|---|---|---|
| 公共合同 | 旧清单兼容；训练用途不能降级；登记来源字段有效；大来源图有界 | 主线 `aae0c99`，root 独立 `pytest tests/contracts`：186 passed；先前独立性能反例修复已复核 | PASS |
| 完整职业数据 R-04a | 作者完整ZIP下载，大小/MD5/SHA及媒体/标注清单核实 | ZIP6,455,837,331B、作者MD5一致；10/10视频全解码/PTS、980703帧、38592556ms（约10.72小时）、9817标注行。BFMD121/121、1,825,439,459B。root独立重hash全部Fine原视频/PTS及BFMD121文件通过；作者声明差异已逐项记录 | PASS（完整公开包；不是十场未经剪辑转播；标注语义另为BLOCKED） |
| 制作用途隔离 R-04b | 入库、检索到时间线、保存、执行、独立CLI及研究预览均拒绝训练数据 | 最终10资产真实清单的14个API负例及2个worker负例通过；独立render四模式均拒绝；原5份制作素材hash与2份manifest不变 | PASS（列明入口与来源闭包；不声称识别外部去来源转码） |
| 播放代理 R-02a | CFR、VFR、浏览器不支持格式有代理，回写源PTS误差≤一源帧 | 4种实际输入（VFR/FFV1/60fps为明确派生），代理、分页原PTS与原尺寸JPEG通过；main新3秒预览和Range206再次通过 | PASS（有界短片；非整场吞吐） |
| 网页交互 R-02b | 定位、逐帧、循环、缩略图和标注保存；30点冷/热统计 | 4输入×30点×2条件=240点，212零误差、28为−1源帧；修订回载与23次循环通过。seeked与rVFC回调分别记录，后者约1秒 | PASS（操作/误差/测量断言）；流畅性尚未达标，见独立issue |
| 竖屏输出 R-01a | 1080×1920，30/60fps，H.264/AAC，安全区及工程设置可复用 | 真实三片时间线两档技术QA通过；平台Web持久化/60fps播放通过；main已集成，旧工程回载和新增2秒CPU导出通过 | PASS（技术与agent流程；人类内容确认未测） |
| 硬件编码 R-03a | 同版本同输入CPU/NVENC，技术/质量/实际耗时证据齐全 | FFmpeg8同版本CPU/NVENC各8次真实job技术QA通过，root核对全部产物bytes/SHA。全帧无损参考质量对照完成，A/B/R原始PTS差0；有限agent ROI审片已记录，代码与报告合入main046582a | PASS（固定短片技术/指标范围；FFmpeg9首次FAIL保留） |
| 分项计时/NVDEC R-03b | 解码、预处理、模型、后处理与冷启动分开；硬件解码需实际路径证据 | 轨迹已有阶段计时；旧pose报告不含完整墙钟分解，已改代码待新输出。PyAV实际软件解码，未使用NVDEC，不声称解码加速 | NOT_RUN（部分计时已实测，NVDEC未测） |
| 轨迹 R-07a | 官方权重、真实输入、源PTS球点/缺失及时间记录 | 旧片180帧两模式与新职业片75帧均跑通，root核验合同/产物/bridge；新片44点/31缺失、0补轨；首轮心跳失败保留 | PASS（真实提取链和缺失报告；精度/召回未测） |
| 姿态/位置 R-07b | 坐标可回查，校准和跟踪含义明确 | 连续Keypoint R-CNN与YOLO旧片各90帧、新职业YOLO75帧跑通；原图坐标及匿名ID保留。自动可靠场地标定未完成，已有人工/agent校准只作实验且注明适用窗 | BLOCKED（原图姿态子项PASS，完整场地位置链未达标） |
| 视频向量 R-05a | 隔离WSL对真实短窗及中文查询产生有限向量/排序 | Qwen3-VL-Embedding-2B18文件4,271,068,726B全部hash校验；17核心安装wheel3,916,256,631B全部SHA通过。WSL独立环境安装中，真实embedding待运行 | NOT_RUN |
| 实时 R-07c | 因果输入，稳态RTF≤1，延迟/积压/丢帧有测量 | 因果6秒文件回放active steady RTF=0.606，模拟到达完成P95=36.04ms/max=150.46ms，12/180帧超40ms，0主动丢帧；非物理直播，持续整链未验收 | NOT_RUN（短窗paced子项PASS，直播未测） |
| 粗动作 R-07e | 作者权重以真实双人姿态、场地与球轨迹运行 | 新职业视频按预先agent审阅的作者窗[3016,3068)固定52帧，27有球/25缺失；不能因缺球改窗或补零冒充观测。checkpoint已取得，真实完整输入尚不满足 | BLOCKED（缺连续真实特征；不等于硬件不足） |
| 战术方向 R-07d | 路线与可运行组件分开，缺模型/事实日志保持unavailable | 已核对MADR/CoachAI等一手路线；MADR代码未发布，依赖已标注逐拍日志。规则统计为建议未实现，自动意图识别unavailable；没有输出无证据战术判断 | PASS（研究与能力边界登记）；战术识别效果BLOCKED |
| 细手法及正式检索 R-05b/R-06a | 专家定义、独立真值与整场划分后评测 | 缺展搓/收搓/后退小跳专家真值；不因下载粗球种标注而解除 | BLOCKED |

## 跨模块复核与修复

- 登记来源：library发布器和公共 `TrainingRegistryEntry` 均已拒绝非法 `source_asset_id/source_sha256`，公共修复 `aae0c99`、library `041a5a9` 已合入并复核；避免一个坏登记阻塞所有制作请求。
- 渲染来源闭包：直接片段与提供的可达父资产均核验实际文件hash。独立反例曾共同伪造父hash和子来源hash越过旧检查，修复已合入 `281c137` 并重新复核通过。
- 取消与锁：新worker取消文件协议已接通，真实CPU编码中取消后锁与已观察进程退出，下一任务成功；超时强杀及GPU中途取消仍另计未测。
- 工程设置：导出Timeline保留正式尺寸；preset、安全区和平台profile以独立修订保存，实际Web回载及60fps请求快照已通过。
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

新训练Asset为 `asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913`，来自作者发布的2011林李视频，实际25fps；使用120000–123000ms固定窗口。`job-d9c832fd94384ee3950918badc767b15`（TrackNet）与 `job-57c6354813b94ad1ba12d42b24e5968e`（YOLO）均成功、各75源帧，四产物实际SHA与bridge停止/exit0由root核对通过，保留training_only和空events。TrackNet离线pipeline2.26188s、cold13.09365s、44observed/31missing/0inpaint；非因果、未做paced/live。本次心跳没有触发重试诊断，只能说明修复后的真实链路跑通，不能声称生产中实际复现并恢复了Win5。

## 主线源码与分环境验证

- render `4ecaf6d + db587aa` → main `6518a09 + 281c137`；独立来源闭包反例复核通过，main 142 passed / 1 Windows symlink skip。
- models `3d018eb` → main `9975361`；平台轻环境227 passed / 13 skip，其中10个NumPy/OpenCV算法用例已在既有WSL模型env独立补跑10/10通过。剩3项为Windows symlink权限。未向平台安装训练依赖；这些检查不加载GPU权重。
- heartbeat `21e1694` → main `e9b2d7c`；main 47 passed / 1显式WSL集成opt-in skip，独立实际Windows短暂共享冲突恢复检查已通过。原故障缺详细errno，不能追溯断言它一定由共享冲突造成。
- 新职业片首两次启动实际报Win5且安全取消。后续 `ec8a7fc` → main `fd6155b` 加同一publisher既有文件身份与DELETE权限探针，有界0.7s恢复、真正ACL仍失败；root60 passed / 1 opt-in skip，包含真实Windows竞争与临时ACL检查；随后两个新真实job成功。失败attempt不删除或覆盖。
- YOLO `579da7e` → main `3a8aa35`；独立官方wheel SHA及260个实际源码/配置文件复核通过，root19定向用例/14subtests通过。
- render最终 `f2bd7bb/0f0c7f9/52cc009/2797b72/bfbf336` → main `93a2446/ef57204/86a17d0/5665d22/046582a`；root165 passed / 1既有symlink skip / 409subtests。质量脚本曾仅相信旧成片路径，修复现绑定只读队列成功attempt与四产物真实SHA，替换成训练字节在任何媒体进程前拒绝。该缺口不影响已另行核验的16真实基准；报告保留原实验不改写。
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

主API18080已从main启动，root新预览 `job-93c4658e2a0644a5b74903568465d3b5` 与CPU研究渲染 `job-8a03b4ab5ff94074ac94bb84021088d9` 共24.41475s完成，7份产物bytes/SHA一致，Range206及源帧分页通过。浏览器再次加载旧工程，源帧#0→#1对应PTS512×1/15360；只复用既有general小样。主worker仅运行两次`--once`后退出，queue已归还models，API不自动计算GPU任务。

首次root验收脚本错误地给worker传入业务库`platform.sqlite3`，未领取队列任务；已修正为同目录`runtime.sqlite3`，原queued任务成功完成。没有删除或重写业务数据；错误建入的空queue表保留，见[验收脚本路径问题](issues/integration-worker-database-path.md)。模块失败与root验收失败均不隐去。

主线等待VL实际运行、下载器最后中断竞态修复和最终全套回归；完成后追加机器可读本轮汇总，不覆盖第一版JSON。
