# models-005：公共标注快照的真实WSL CPU准备

日期2026-10-02。断言在开发前登记于`docs/models/ANNOTATION_READINESS_PLAN.md`。本轮是A-04/A-05的models消费检查及A-06；不训练模型、不产生专家标签、不关闭CTX识别质量验收。

## 输入、版本与环境

- 基线main `3dab169`；taxonomy独立提交`1a44123`，主任务已集成。公共合同消费01的`6fec08f`和解析后subject判重修复`2128568`，本分支分别为`6f851bb`、`1d75b3c`；没有自行修改合同。
- 完整taxonomy为badminton-technique-tactics/1.0.0，193节点、156 selectable标签、37 group、19家族。均未专家审定。01的`apps/platform/training_taxonomy.py`适配器SHA `6af82260d261dd0e71c6083e46b41cb4b0ddbe3b0491e617fdd2e4b381d4f2bc`读取该词表，完整原目录随public taxonomy保留。导出时合同源SHA `806dad61b1f8a5f3b2c703445c61cde3da81ba4da25e47018fa606ec84e950a9`；后续兼容修复不改变taxonomy字段。
- 公共taxonomy数据在`models/handoff/annotation-readiness-001/inputs/public-taxonomy.json`，SHA `f4ecb3290d544c2a48febec624123f8f4db801c4b1adcf4c5e7d36ee3963c713`；旁有taxonomy-export-receipt.json。路径均相对`D:/video`，原片不复制。
- 真实源manifest：`data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json`，SHA `2725970f4485732e67ba249b72262c51dbba24ee17e5e97d901b18ec8a29e286`。asset_id=`asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913`，231,500,744B、1280×720、1306040ms、time_base=1/12800、start_pts=0。用途training_only，许可research_only；比赛名来自未确认来源，不提升为确认。
- 冻结PTS引用SHA `b18a822e0c66dd7aa810b0d1c5684e1e9c923e2d0982ea7f520341798a2b10b9`，1,175,271B、32651行。完整索引与原片分别全hash，逐行核验连续frame_index、严格递增pts及源时间范围。实际解码复核原PTS并保存RGB hash；未按fps伪造时刻。
- 快照由本模块`build_agent_training_demo.py`调用公共build_training_snapshot构建，明确agent/draft/unknown，不是Web专家导出。只含1个审阅segment、2个unknown（展搓与后退小跳）；不是声称窗口出现这两种动作。人物、可见性、比赛组、回合范围未确认，缺状态也明确报告。

快照`models/handoff/annotation-readiness-001/agent-demo/snapshot.json`：349,285B；文件SHA `45baeec6df6662cefd3a0428bd583aadf5082c05de254af67698dec5440ddc30`；公共content_sha256 `4401e0d743208a96c2d95aea3c568f61a0fb673e959ab45158294088ddde1562`。两个hash用途不同；同一已冻结文件用于两次准备。

## 实际环境与容量

WSL Ubuntu原有models/env为Python3.11、PyAV15.0.0、numpy2.4.6、torch2.7.1+cu128，没有pydantic。新增`/mnt/d/video/runtime/models/annotation-env`，system-site-packages只读复用原环境，单独安装pydantic2.13.5、pydantic-core2.46.5、annotated-types0.8.0、typing-inspection0.4.4；typing-extensions4.16.0保持父环境来源。四个官方wheel共2,562,857B，许可元数据均MIT，URL/官方SHA/大小/原JSON及真实导入位置见`environments/models-annotation-installed-20261002.json`。没有新装Torch、CUDA、Conda或全局包。

`bootstrap_annotation_runtime.py --execute`成功，pip check及真实pydantic/PyAV导入通过；torch只读metadata、未import，CUDA未初始化。事前估算峰值67,119,638B<100MB；新增目录实测34,929,194B（报告写前）。安装后runtime/models19,198,684,679B<35GB，shared7,169,319,439B<15GB，其余runtime预留20GB，总分区<70GB；D余量922,484,183,040B。模型数据目录开工6,998,627,612B<180GB；每次handoff写入另用models writer reservation，所有owner固定额度保守合计不超过700GB。本轮真实snapshot/审计等小产物总量见最终evidence文件；低于100MB输出预算和2GB本轮上限。

GPU检查仅查看用户进程：桌面进程约占1.9GB，不结束任何进程。18080账本API当时连接拒绝，主任务随后确认生产服务未开；未据此推断GPU空闲，也未运行GPU。models本轮无服务端口或后台常驻进程。

## 方法、命令与实测

在WSL仓库`/mnt/c/Users/Li/.codex/worktrees/c5b1/badmintonTV`运行；`CUDA_VISIBLE_DEVICES`设为空，清PYTHONPATH，用`-s -B`禁用户site及额外pyc。

```bash
/mnt/d/video/runtime/models/annotation-env/bin/python -s -B -m unittest \
  tests.models.test_training_grouping tests.models.test_training_readiness \
  tests.models.test_training_prepare tests.models.test_training_sources -q
```

最终公共修复同步后 **60/60 PASS，0 skipped**，WSL实测0.104s。native platform环境也曾60项通过。单元测试为合成边界/元数据与fake decoder检查，不算视频识别或专家真值成功。

演示输入首次生成命令（相同输出目录再次执行会拒绝；重复验收应直接复用已有快照）：

```bash
/mnt/d/video/runtime/models/annotation-env/bin/python -s -B scripts/models/build_agent_training_demo.py \
  --manifest /mnt/d/video/data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json \
  --asset-id asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913 \
  --taxonomy /mnt/d/video/models/handoff/annotation-readiness-001/inputs/public-taxonomy.json \
  --start-ms 120000 --end-ms 123000 \
  --label stroke.net.zhan_cuo --label footwork.start.backward_small_hop \
  --output-dir models/handoff/annotation-readiness-001/agent-demo
```

实际准备命令先用attempt-01，再仅把output-dir换成prepare-attempt-02：

```bash
/mnt/d/video/runtime/models/annotation-env/bin/python -s -B -m packages.models.training_prepare prepare \
  --snapshot /mnt/d/video/models/handoff/annotation-readiness-001/agent-demo/snapshot.json \
  --manifest /mnt/d/video/data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json \
  --output-dir models/handoff/annotation-readiness-001/prepare-attempt-01 --samples 6
```

两次实际exit0；readiness.json各72,891B、逐字节相同，SHA均为`09059688739af49822d121967cf62e01a66cb35195062200a9d109c06a0d5dc3`。容量文件因磁盘实时值不同，不参加确定性比较。两次工具执行分别约4.95s和4.40s，包含启动/校验/读片/输出，非模型吞吐指标。

原窗口[120000,123000)含75帧、index3000–3074；采样index为3000/3013/3025/3038/3050/3063，PTS1536000/1542656/1548800/1555456/1561600/1568256，实际相对毫秒120000/120520/121000/121520/122000/122520。6个1280×720 RGB帧全部真实CPU解码并有各自SHA，两次一致；没有图片/视频复制、缺帧补零、模型forward或checkpoint。

报告实际：trainable=false、strict_judgements=0、present=0、absent=0、unknown=2、explicit_unlabeled=0、适用但未出现的label=129（不是负例）、navigation groups=37。缺确认身份1、缺state1及4角色均缺；match/group未确认、split unassigned、无train/validation/test严格例、taxonomy未reviewed。1个窗口review_only=true、supervision_targets=[]、context_scope=scope_unknown，明确不是已确认动作/回合边界。此结果按断言是准备工程成功、训练资格未满足。

## 负例、修复与未达标项

- 同一真实快照执行audit并带`--require-trainable`，新目录audit-require-trainable，实际exit2；保留69,457B审计报告。再要求写入已存在prepare-attempt-01目录，实际exit1并提示output directory already exists，旧文件SHA保持不变。证据`models/handoff/annotation-readiness-001/negative-checks.json`。
- 实现复核修正了无界JSONL行读取、验证后媒体替换、计划伪造、跨回合点上下文及外传监督view等边界。公共重复解析subject问题由01 `2128568`修复，本模块保留防御及回归，见对应issue。未把发现问题的合成测试写成真实识别失败。
- 开工一次WSL内联Python命令引号错误，发生在执行读取前，改为stdin脚本后成功；环境安装/两次实际准备无失败attempt，无删除或覆盖源/旧结果。
- A-04/A-05的Web保存/导出与主线验收由01/root记录；本模块不冒领。S0-03.CTX-01专家定义/双人试标、S0-04.CTX-01真实独立组及覆盖、S2-04.CTX-01细动作真值仍BLOCKED。完整态势链、消融及事实/预测解释未运行；无训练精度、召回或模型收益结论。

下一步是接入01真实Web导出继续相同审计，补经确认比赛/同源组、专家冻结定义与当前human复核；条件满足后才启动有评测设计的训练。不能把本次成功解码、agent草稿或词表条目数量当成这些门槛通过。
