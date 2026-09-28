# models 状态

- 任务：01a0e88b-416f-7ca2-bfec-c09ec1462866；cwd `C:/Users/USER/.codex/worktrees/c5b1/badmintonTV`；branch `work/models`。
- 设计：统一Asset/QuerySpec/Event/JobResult数据流、严格attempt边界、未知不等于阴性、专家冻结标签、整比赛留出和A/B/C公平比较；详见docs/models/DESIGN.md、annotation-and-evaluation.md、HANDOFF.md。
- 已实现：纯stdlib CLI/attempt_id/JSONL/排他结果；有限中文规则、兼容端点、schema与条件语义校验；本地Qwen/COCO17姿态/CLIP抽帧适配器；有上限的官方权重下载、哈希校验与模型目录单写者容量预留；正式评测拒绝不合格真值；实验原文与源PTS可追溯。
- 已运行环境：复用既有Miniforge25.9.1，新建隔离WSL Python3.11.16；torch2.7.1+cu128/vision0.22.1+cu128/transformers4.51.3/PyAV15.0.0；pip check通过；RTX5090 CUDA12.8五项实际算子通过。未动base/用户已有env/全局Python/驱动，未安装额外技能或MCP。原样锁、便携锁及复现说明在environments/models-*、docs/models/ENVIRONMENT.md。
- 已运行真实视频：FBBench单打6秒，pose24帧26.399s，CLIP24帧44.853s；DroneBD高校双打4.404秒，pose9帧28.254s。均为含解码/权重加载的冷启动，不是整小时吞吐；events为空。单双打各3时点人工overlay检查，场边额外人物/重复框和编号互换已发现；没有track/player身份或细手法分类。准确率/召回均null，证据见docs/experiments/models-002-real-baselines.md。
- 已运行中文模型：Qwen基线24条开发探针0通过；加入3示例后2/24通过（20格式失败、1schema、1语义）；无OOM/截断，约50token/s，不能归因算力不足或外推所有LLM。默认CLI复杂查询明确blocked2，无静默规则fallback。原始输出保留于D:/video/models/handoff/query-diagnostic-001、002，实验与独立issue已写。
- 已运行验证：原100tests在WSL全过，Windows98过+2权限skip，主任务独立复核通过。最新适配器定向35tests在Windows34过+1symlink权限skip，含新增二进制加载错误阻塞测试；新容量核算5项CPU测试全过。共享合同通过6模型清单、5真实Asset、5实际JobResult及canonical fixtures。
- 已保留失败：普通sandbox WSL E_ACCESSDENIED，授权提升恢复；WSL大权重HTTP超时后由Windows同官方URL下载成功，未改代理/DNS；中断partial保留。PyAV14.4源码构建失败，换15.0官方wheel；运行中编辑bootstrap引起退出（推断），独立脚本补齐。Qwen真实失败不修写。独立issues均在docs/issues/models-*.md。
- 未测：正式细手法分类、稳定跨帧跟踪/错人率、独立用户查询准确率、个人录像/跨机位泛化、完整比赛速度、P@20/召回/时间边界、正式A/B/C和融合分类器、干净环境重建。
- 阻塞：细标签专家定义与人工真值缺失，现有比赛组未人工确认且split unassigned，DroneBD另一视角CSV未对齐；没有训练checkpoint。skeleton-temporal-v1明确unavailable/TRAINING_DATA_REQUIRED。具体输入和关闭条件见docs/issues/models-fine-label-ground-truth.md；Qwen问题独立于视频真值。
- 下一步：主任务集成本轮checkpoint；platform受控WSL launcher与GPU租约完成一次真实pose端到端。本轮模型GPU进程已结束，窗口已释放给platform；不再追加模型下载/试验。随后补专家/比赛隔离/球员轨迹审阅，才比较和训练时序模型。
- 提交 SHA：611eb39（初版）、00de444（边界修复）均已由主任务集成；本轮实际环境/ML实验checkpoint提交后补记。没有推送远程或自行合main。
- 启动：WSL仓库根目录 `source environments/models.env.sh`，`/mnt/d/video/runtime/models/env/bin/python -m packages.models run --request REQUEST --result NEW_RESULT`；新attempt必须新目录。Windows平台无需torch，以参数数组受控调用WSL。精确复现命令在HANDOFF和实验报告。
- 环境/端口：WSL Ubuntu x86_64；repo对应`/mnt/c/Users/Li/.codex/worktrees/c5b1/badmintonTV`；prefix`/mnt/d/video/runtime/models/env`；HF/Torch/tmp/pip路径受控、离线加载；无监听端口。
- 容量快照：2026-09-28本轮实测后models=2,426,383,733bytes，runtime/models=7,282,586,968bytes，runtime/shared=1,081,355,680bytes。既有原生base+pkgs=5,924,496,893bytes另计shared（合7,005,852,573bytes），其他既有用户env=28,987,060,966bytes单独记录不修改。models<=180GB、runtime/models<=35GB、shared<=15GB，其余runtime20GB保留。D可用955,508,568,064bytes；后续platform小产物另增，写前再查。没有删除数据。
- 交接：`D:/video/models/handoff/models.runtime-001.v1.json`为WSL实机快照，三个ML状态experimental；configs/models/catalog.json同快照，weights-lock.json含官方来源/revision/hash。真实结果均在models/handoff各job/attempt-01。权重/缓存/环境/媒体不进Git。
