# models 状态

## 2026-09-29 复用实验轮：当前状态（进行中）

- 已运行：真实旧FBBench单打6秒TrackNet离线与因果回放成功，连续pose3秒90帧成功；三项均经过平台worker/WSL bridge/GPU租约，计算已停止、窗口已归还。报告和job见models-004-reuse-forward.md；10时点Agent球点视觉QA已完成，非人工真值。
- 已实现：TrackNet、Qwen3-VL、连续pose、BST四个标准适配器，固定源/权重校验、usage_scope传播、严格预算和真实分项计时。稳定提交3d018eb435624e4d6d7b20d34cc860d68dc32d41已交main；240项CPU回归237通过/3个Windows权限skip。
- Qwen下载及隔离环境已完成：18文件4,271,068,726B与17个核心wheels3,916,256,631B全SHA校验通过；同一vl-env安装torch2.8.0+cu128/vision.23.0/transformers4.57.3，pip check、CPU实际类导入、安装后容量复核通过。models runtime19.165GB、shared7.169GB（含native base/pkgs），配额均满足。安装/源/hash记录在environments/models-vl-installed-20260929.json；旧完整/partial保留。
- VL首真实job-a258df27cc5d4598896dd1d6495c955a在cold_load失败，done compute_stopped=true/exit1，GPU已归还。原因是适配器compile继承future annotations使官方config_class变字符串；正修dont_inherit=True并显式本地Qwen3VLConfig，26项定向CPU测试通过。独立真实processor两窗CPU验证通过（各800tokens/原PTS保留），还不是embedding成功；固定同payload新job重试一次。详见models-vl-real-001。
- 新实跑：YOLO11n-pose+ByteTrack job-98cb65954fab42408f3b6fd1082d6330成功，同旧片700–3700ms完整90帧；cold load32.2095s、pose1.7377s、ByteTrack0.0608s、allocator151,847,424/176,160,768B。原报告尚缺D2H/序列化等计时，不能把阶段和当总端到端；后续已补计时和首尾完整覆盖守卫（16定向CPU tests通过）。无命名身份、细标签或准确率；独立视觉QA和同PTS比较进行中。bridge compute_stopped=true/exit0，GPU lease/window均null。
- YOLO对照已核对：同PTS/同Agent场地H下旧pose87/90通过输入守卫，YOLO81/90；31/32远端漏人未解决、54关联跳变改善，41/66重复候选新失败。9帧原图Agent QA另发现65帧脚踝高分错位与场外ID13；不能称整体改善或稳定身份。适配器+比较器19项CPU守卫通过，报告在models-yolo-input-comparison-001与models-yolo-visual-review-001。
- 当前阻塞/未测：BST旧60帧仅55帧满足输入检查，新职业独立52帧窗口还有25帧连续缺球和远端人体缺失；实际分类尚未执行，不补零或删除失败帧。Qwen实际embedding、物理live端到端、正式P@K/动作准确率仍未测；新职业Asset两项真实诊断已完成，不能与这些未验收项混同。
- 失败保留：TrackNet首次causal job3757因bridge心跳写失败可靠取消，随后新job4081成功；原始底层原因未证实。平台已在main修有界心跳重试，后续runner自动用新main，但不改写旧失败。
- 新训练首次TrackNet jobd1ef与YOLO job440e均被bridge取消，日志明确heartbeat.replace PermissionError/errno13/winerror5/attempts1。两份done都compute_stopped=true，GPU已释放，未得到模型产物；平台在其边界处理，models不绕watchdog直跑。
- 新训练重试已完成：main fd6155b后TrackNet jobd9c832与YOLO job57c635都succeeded，固定b210dc39的120000–123000ms/75帧，全部training_only；done exit0/compute_stopped=true、GPU已归还。TrackNet44observed/31missing；YOLO execute到features发布35.0752s（cold31.9151s），新计时及首尾覆盖实测。独立52帧击球窗口有25帧连续缺球和远端人体缺失，BST仍blocked；不能因前向成功报精度。详见models-004新节。
- 分提交：YOLO代码与旧片真实比较579da7e已由main集成3a8aa35；当前新增下载恢复工具有55项传输/获取CPU测试通过、恢复脚本WSL17项通过（Windows16通过1权限skip）。官方VL核心wheels按固定SHA在Windows续传，七个完整包及182MB中断文件已保留；Qwen暂停时3,104,309,248B，GPU试验结束后继续。尚未把下载/安装称为VL推理成功。
- 当前完整CPU回归310项，306通过/4个Windows权限skip；VL adapter另修failure.json与协议的blocked/cancelled状态一致及CLIP聚合/D2H计时，25项定向通过。官方Inpaint mask静态诊断拒绝目标25帧缺口（前后y=5，未过36px门槛），仅3068/3069两帧可补且在冻结BST窗之外；不改变规则强行GPU试跑。
- GPU/端口：目前models无计算进程，无服务端口。render完成兼容NVENC后明确归还GPU；下一模型启动前仍检查同账本。当前只网络和轻CPU准备。
- 环境/容量：旧WSL models/env保持torch2.7.1/vision.22.1；VL独立vl-env；YOLO为yolo-env小venv只读共享旧框架、不修改父环境。安装前runtime/models8.581GB，追加VL24GB+YOLO0.6GB、shared2GB保守峰值均通过35/15/70GB；数据/缓存/权重只在D:/video。来源/版本/锁见environments/models-*和各模型文档。
- 恢复安装审查修复：active_environment_pip读取/proc的exe及必要的cwd，识别激活后的裸python、相对解释器和pip脚本；区分其他环境，PID消失跳过、存活PID身份不可读则拒绝。23项定向测试22通过/1个Windows symlink权限skip；没有读取进程environ或发信号。修复提交前不运行安装。
- 下一步：完成Qwen同一固定请求的适配修复重试，随后按旧env/YOLO/VL各自实机状态生成11个模型卡。组合工具425dd3a及16项CPU测试已提交，实际base/yolo的9+1张卡已采集，最终catalog尚未更新。Inpaint目标缺口不可按作者mask补点，BST仍blocked。真实失败全部保留，主任务负责集成，不推送。

### 本轮阶段记录（以下是当时状态，不代表当前尚未运行）

- 分支codex/models-reuse-experiments，从主任务指定ff2c700创建；旧work/models全部提交保留，无未提交覆盖。范围R-03b/R-05/R-07，细手法真值门槛不变。
- 已读本轮实施/调研与跨模块合同，三条线并行审阅TrackNetV3、Qwen3-VL-Embedding-2B、BST官方来源和固定版本。实际GPU顺序执行，render先获得短硬件基准窗口。
- 已核对GPU：RTX5090约1891MiB桌面占用，无compute进程；平台同一runtime账本状态GPU_LEASE_REQUIRED、window=null、lease=null。模型不直接操作SQLite，后续通过受控Windows worker/WSL bridge与同账本租约执行。
- 容量预检快照：models2,427,005,391bytes，runtime/models7,282,598,927bytes，runtime/shared1,081,355,680bytes；D free955,429,896,192bytes。新VL env安装额外峰值预留24GB+shared2GB，安装前GNU du检查35/15/70GB边界；不改旧torch2.7.1环境。Qwen官方固定revision全仓18文件4,271,068,726bytes，models单写者预留4.6GB，逐文件大小/hash校验下载进行中。
- 17:18之前已落盘：TrackNet官方ZIP131,653,952B、TrackNet_best.pt136,190,877B（SHA df867641a02712b021f04548ff4b1208ddfdb47f629ab2094ceb978667e83b1a）和单独Inpaint6,264,451B；BST7,514,133B（SHA997f43e52b20cb47517132c71d3e147d7d717a2d9651cfbe7651a5003bd66809）。代码固定commit、下载计算hash；发布者无权重hash，不虚构发布者认证。CPU受限weights_only读取：TrackNet seq_len8/bg_mode=concat，BST是OrderedDict；当时还未GPU前向。
- 已实现TrackNet与VL标准execute适配并接lazy dispatcher/catalog，明确experimental/not_installed；TrackNet固定官方执行源码hash并使用同份bytes执行。CPU总回归176 tests，173通过、3项Windows symlink权限跳过。正在增加逐帧pose和BST输入链。训练专用输入只写models诊断产物，继承usage_scope/源关系，不进入制作库或成片。
- 失败与恢复：Qwen全响应下载初读停在0byte，核对仅本任务PID54176后中止，partial及来源保留，writer锁归档为.models对应interrupted-qwen记录。经16项mock边界验证后采用正常HTTP Range严格206/Content-Range续传；2026-09-29 17:12本地时间已实际收到1,084,489,728B。不能把partial称安装成功。新VL隔离env仍在下载torch2.8依赖。
- 仅补装旧模型env的opencv-python-headless4.11.0.86（CPU官方PyPI wheel，--no-deps、不改torch/vision/transformers）；pip check与cv2 import成功。预检runtime/models7,651,687,906B、shared1,244,822,546B、native base/pkg5,924,496,893B、D free952,402,558,976B；新VL24GB+OpenCV0.3GB及shared2GB保守预留仍通过35/15/70GB。pip-only旧env安装与新env独立tmp，未同时运行Conda安装。
- 早期GPU窗口：render首次NVENC因FFmpeg/驱动API版本不合失败后已明确释放/撤销；当时models尚未GPU运行。下载单writer期间允许render先重试兼容构建，不空占窗口。
- 17:18–17:22已运行：TrackNet offline job16153…与causal paced job4081…成功；6秒180帧分别165/160 observed，missing15/20，无inpaint。离线pipeline4.42s；因果active稳态RTF0.606、回放p95到达完成36.04ms、12/180超过40ms期限、0主动drops，物理live端到端仍未测。第二job3757…bridge心跳写失败可靠取消/释放，证据保留交platform修；不能算模型失败率/算法精度。
- 连续pose jobb8a4…成功：真实90源PTS帧，700–3700ms，raw COCO17且track/player=null。旧报告elapsed41.52s而阶段约6.29s，未计入的framework startup已在代码补计时及unattributed项，旧报告保留；下一实跑核对。BST真实2秒预备检查60帧精确join、55可用；2帧人脚点缺失/筛选不足、1帧关联跳变、2帧缺球，严格输入尚blocked，未伪造分类成功。
- 17:22后GPU已全部停止、lease/window=null并明确归还render。Qwen第二次因调度主动暂停保留1,409,810,432B，归档旧锁；新下载支持每个已flush Range边界协作暂停，已继续下载。原始env/weights文件不覆盖。
- BST小依赖positional-encodings6.0.3、torchinfo1.8.0按官方wheel SHA和--no-deps安装通过，pip check通过，freeze另存；没有变动框架。安装前models runtime8,242,384,320B+24.01GB保守剩余峰值仍<=35GB，shared总7,169,319,439B+2GB<=15GB、70GB全界通过。
- 当前CPU验证240 tests：237通过、3个Windows symlink权限skip；git diff --check通过。BST源码same-bytes pin、worker model_version和stroke_classification兼容均补齐。真实实验详见models-004-reuse-forward.md及10时点Agent视觉QA（不是humanreview/accuracy）。稳定实现正提交；Qwen、新职业窗口和BST实际前向仍继续。
- 稳定实现提交SHA：3d018eb435624e4d6d7b20d34cc860d68dc32d41，已交main集成，未推送。当前动态catalog实机快照含10模型；四新ID/env映射已通知platform。之后实验将另行追加，不能把此提交当本轮全部验收完成。
- 下一步：完成官方文件/环境来源锁，接入统一CLI，旧真实短片有界前向；待library训练handoff后至少一个新职业窗口。分项时延/显存与因果限制单列；无真值不报准确率、召回或P@K。

## 已完成首轮（历史记录）

- 任务：01a0e88b-416f-7ca2-bfec-c09ec1462866；cwd `C:/Users/USER/.codex/worktrees/c5b1/badmintonTV`；branch `work/models`。
- 设计：统一Asset/QuerySpec/Event/JobResult数据流、严格attempt边界、未知不等于阴性、专家冻结标签、整比赛留出和A/B/C公平比较；详见docs/models/DESIGN.md、annotation-and-evaluation.md、HANDOFF.md。
- 已实现：纯stdlib CLI/attempt_id/JSONL/排他结果；有限中文规则、兼容端点、schema与条件语义校验；本地Qwen/COCO17姿态/CLIP抽帧适配器；有上限的官方权重下载、哈希校验与模型目录单写者容量预留；正式评测拒绝不合格真值；实验原文与源PTS可追溯。
- 已运行环境：复用既有Miniforge25.9.1，新建隔离WSL Python3.11.16；torch2.7.1+cu128/vision0.22.1+cu128/transformers4.51.3/PyAV15.0.0；pip check通过；RTX5090 CUDA12.8五项实际算子通过。未动base/用户已有env/全局Python/驱动，未安装额外技能或MCP。原样锁、便携锁及复现说明在environments/models-*、docs/models/ENVIRONMENT.md。
- 已运行真实视频：FBBench单打6秒，pose24帧26.399s，CLIP24帧44.853s；DroneBD高校双打4.404秒，pose9帧28.254s。均为含解码/权重加载的冷启动，不是整小时吞吐；events为空。单双打各3时点Agent查看overlay（非人类真值确认），场边额外人物/重复框和编号互换已发现；没有track/player身份或细手法分类。准确率/召回均null，证据见docs/experiments/models-002-real-baselines.md。
- 已运行中文模型：Qwen基线24条开发探针0通过；加入3示例后2/24通过（20格式失败、1schema、1语义）；无OOM/截断，约50token/s，不能归因算力不足或外推所有LLM。默认CLI复杂查询明确blocked2，无静默规则fallback。原始输出保留于D:/video/models/handoff/query-diagnostic-001、002，实验与独立issue已写。
- 已运行验证：原100tests在WSL全过，Windows98过+2权限skip，主任务独立复核通过。最新适配器定向35tests在Windows34过+1symlink权限skip，含新增二进制加载错误阻塞测试；新容量核算5项CPU测试全过。共享合同通过6模型清单、5真实Asset、5实际JobResult及canonical fixtures。
- 已保留失败：普通sandbox WSL E_ACCESSDENIED，授权提升恢复；WSL大权重HTTP超时后由Windows同官方URL下载成功，未改代理/DNS；中断partial保留。PyAV14.4源码构建失败，换15.0官方wheel；运行中编辑bootstrap引起退出（推断），独立脚本补齐。Qwen真实失败不修写。独立issues均在docs/issues/models-*.md。
- 未测：正式细手法分类、稳定跨帧跟踪/错人率、独立用户查询准确率、个人录像/跨机位泛化、完整比赛速度、P@20/召回/时间边界、正式A/B/C和融合分类器、干净环境重建。
- 阻塞：细标签专家定义与人工真值缺失，现有比赛组未人工确认且split unassigned，DroneBD另一视角CSV未对齐；没有训练checkpoint。skeleton-temporal-v1明确unavailable/TRAINING_DATA_REQUIRED。具体输入和关闭条件见docs/issues/models-fine-label-ground-truth.md；Qwen问题独立于视频真值。
- 平台联调已完成：2026-09-29北京时间，job-3dc9ece15e914eecb9616ac306ece6b8/attempt-1通过网页→Windows worker→受控WSL运行6秒24帧pose，28.702605725s，events=[]；result succeeded，bridge compute_stopped=true/exit0。平台/主任务核验两产物hash，models只读核对result/bridge/report。平台已提前revoke GPU窗口，active_window=null、lease=null，不再启动GPU。平台快照camera/discipline仍unknown，不声称分层验收。
- 下一步：主任务审查集成本轮checkpoint；本轮模型GPU进程已结束，不再追加下载/实验。随后补专家/比赛隔离/球员轨迹审阅，才比较和训练时序模型。
- 提交 SHA：611eb39（初版）、00de444（边界修复）均已由主任务集成；本轮实际环境/ML实验checkpoint为d8757430db8a6e15a35f58202c230eaf7f03d921，已交主任务审查。没有推送远程或自行合main。
- 启动：WSL仓库根目录 `source environments/models.env.sh`，`/mnt/d/video/runtime/models/env/bin/python -m packages.models run --request REQUEST --result NEW_RESULT`；新attempt必须新目录。Windows平台无需torch，以参数数组受控调用WSL。精确复现命令在HANDOFF和实验报告。
- 环境/端口：WSL Ubuntu x86_64；repo对应`/mnt/c/Users/Li/.codex/worktrees/c5b1/badmintonTV`；prefix`/mnt/d/video/runtime/models/env`；HF/Torch/tmp/pip路径受控、离线加载；无监听端口。
- 容量快照：2026-09-28本轮实测后models=2,426,383,733bytes，runtime/models=7,282,586,968bytes，runtime/shared=1,081,355,680bytes。既有原生base+pkgs=5,924,496,893bytes另计shared（合7,005,852,573bytes），其他既有用户env=28,987,060,966bytes单独记录不修改。models<=180GB、runtime/models<=35GB、shared<=15GB，其余runtime20GB保留。D可用955,508,568,064bytes；后续platform小产物另增，写前再查。没有删除数据。
- 交接：`D:/video/models/handoff/models.runtime-001.v1.json`为WSL实机快照，三个ML状态experimental；configs/models/catalog.json同快照，weights-lock.json含官方来源/revision/hash。真实结果均在models/handoff各job/attempt-01。权重/缓存/环境/媒体不进Git。
- 审查修正：补装脚本持锁后核对torch/vision固定版本和pip依赖状态，再以3GB额外峰值预检，约束锁内版本补装，最后复核容量。bash语法与执行顺序静态检查、3种框架metadata模拟均通过，未重复安装。新预算全目录只读扫描因DrvFS遍历超过4分钟被本任务主动中止，不称全盘检查通过；交接使用上述成功du/free与原生目录快照，问题单models-capacity-preflight-speed.md记录。
