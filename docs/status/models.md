# models 状态

## 2026-09-29 复用实验轮：实验完成，最终交接

- 已实现：TrackNetV3、连续COCO17 pose、YOLO11n-pose+ByteTrack、Qwen3-VL、严格BST输入适配，统一协议、usage_scope、源/权重完整校验、分项计时与失败保留。没有伪造模型进度、细标签或身份。
- 实际已运行：旧FBBench 6秒TrackNet离线/因果回放、90帧连续pose/YOLO；新职业training_only源b210dc39的120000–123000ms共75帧TrackNet/YOLO；最后旧FBBench两个3秒窗Qwen视频嵌入及同帧CLIP对照。均经统一worker/WSL bridge/GPU租约，详细job/hash见models-004-reuse-forward与models-vl-real-001。
- VL最终job-604bf54336ae449a88e004622efd6d1f/attempt-1 succeeded：2视频+6中英查询、2048维finite/unit向量，CLIP对照也成功，events=[]。总elapsed73.481262s含权重校验/框架/冷加载/CLIP，Qwen峰值allocated4,421,021,184B；不把单窗forward0.054s当完整比赛吞吐。原PTS保留；官方时间token仅0.1s精度。
- VL首次job-a258df27cc5d4598896dd1d6495c955a cold_load失败保留：本适配器compile隐式继承future annotations，造成官方config_class字符串化。修复c609b53用dont_inherit=True及显式本地Qwen3VLConfig，26项定向CPU通过、实际环境复现/修复验证通过；同payload仅重试一次后成功。失败done exit1/compute_stopped=true，成功done exit0/compute_stopped=true。
- 模型目录已完成：configs/models/catalog.json与docs/models/catalog-final-20260929.json相同，11卡（1 ready/7 experimental/3 unavailable），91,275B，SHAdfda3195040afba3b67a71d1acb8aeb3c288403322767749af4d57a7a02e4a1c。旧env9卡、YOLO1卡、VL1卡分别实机probe；源码签名一致，主ModelManifest全部通过；5个真实成功job及产物/独立退出证据核验。BST unavailable说明真实缺口，VL experimental不等于准确率通过。
- YOLO真实比较：旧片同PTS/场地H下旧pose87/90、YOLO81/90满足输入守卫，远端漏人未解决、54帧关联改善但41/66出现重复候选。9帧Agent原图QA发现65脚踝高分错位及场外ID13，不能称整体改善/稳定身份。新片YOLO75帧完整覆盖，execute至features发布35.0752s，D2H/序列化等有实测计时。
- BST阻塞保持：旧60帧55可用；新职业独立冻结[3016,3068)52帧仅27 observed/25连续missing，还有34帧双人不足。场地H/击球边界为Agent提案，不是人类真值。未生成pack或分类前向，不补零、不删帧、不把场外ID当球员。
- Inpaint静态诊断已完成：目标25帧两端y=5未过作者36px门槛，mask全0；仅窗外3068/3069可补。没有作者max_gap规则，未为得到结果强改mask或新增GPU实验。报告models-inpaint-applicability-001及纯stdlib复现脚本保留。
- 失败保留：早期causal3757及新源TrackNetd1ef/YOLO440e被bridge可靠取消，后两次明确WinError5心跳写失败；主线fd6155b后新jobd9c/57c成功。新源TrackNet44observed/31missing，training_only完整继承。不得将bridge失败计为识别准确率或覆盖旧attempt。
- 环境/下载完成：Qwen18文件4,271,068,726B及17官方核心wheels3,916,256,631B全SHA通过。同一vl-env为Python3.11.16/torch2.8.0+cu128/vision.23.0/transformers4.57.3，pip check、CPU真实导入通过且探针未初始化CUDA；44安装包来源/hash/冻结版本见environments/models-vl-installed-20260929.json及freeze。旧models/env保持torch2.7.1/vision.22.1；yolo-env为只读共享父框架的小venv。旧下载/182MB partial归档保留，无用户文件删除。
- 环境/容量：安装后models runtime19,164,852,807B<35GB，shared7,169,319,439B（含native base/pkgs）<15GB；加其他runtime20GB预留共46,334,172,246B<70GB，D可用922,903,875,584B。模型/数据总量最终由main按五分区汇总，小型结果新增约0.62MB；大文件只在D:/video，原片只读。
- 运行/端口：本模块无服务端口。最后job结束时GPU lease/window均null，已明确归还main共享queue/GPU；无models GPU/下载/安装/常驻worker进程，不再排新实验。main后续用户手动窗口由main管理。
- 验证/提交：稳定适配3d018eb、YOLO579da7e、下载工具7d56df9、恢复P2 31f116a、BST/Inpaint证据b8c999b、三环境目录工具425dd3a、VL语义修复c609b53均交main。已报告完整CPU回归310项306通过4权限skip；后续恢复23项22通过1权限skip（WSL7路径专项全通过）、catalog16全通过、VL修复26全通过。main另行全套集成验证；本轮只改models边界文件，不推送、不自行合main。
- 启动：native D:/video/runtime/platform/env/Scripts/python.exe运行scripts/models/run_registered_experiment.py，--runtime-repo C:/Users/USER/Desktop/Program/badmintonTV，按payload选择--env-prefix（VL为/mnt/d/video/runtime/models/vl-env），必须先协调唯一worker/queue/GPU。复现请求见configs/models/reuse-payloads；源码/包/权重/原片许可分开记录。
- 未测/下一步：本轮受控复用实验已收尾。准确率/P@K、细手法、稳定实名轨迹、完整比赛吞吐与物理live端到端仍未验收；BST待真实输入与人类校准/击球/标签审阅，不能靠合成成功关闭。最终证据提交主任务后，由main集成UI与验收，不继续扩展训练或数据实验。

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
