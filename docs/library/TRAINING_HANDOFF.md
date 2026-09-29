# 训练专用数据交接

日期：2026-09-29。对应固定用例 **R-04b**，并延续 S0-01 的合同校验和 S0-04 的整场分组要求。本文件只定义 library 发布环节；不将单元夹具的通过当作十场真实数据或 platform/render 隔离验收。

## 开发前冻结的断言

| R-04b 的 library 子断言 | 输入/验证方法 | 预期结果 | 实际结果 |
|---|---|---|---|
| 新合同与双用途字段 | 临时根内完整 Asset，注入 typed validator；另注入丢弃新字段的旧合同/失败回调 | 两处 usage_scope 均为 training_only；回调未确认时不发布 | PASS（守门夹具及a7fff39真实typed合同回调）；真实媒体发布另行验收 |
| 可信用途登记先于清单 | 故障注入和写入顺序检查 | 用途 registry 完整原子落盘后才出现训练 manifest；manifest失败不回滚用途 | PASS（临时目录故障注入） |
| 旧用途记录不能丢失/降级 | 连续批次、同 SHA 改 ID/路径、冲突用途、并发发布 | 每个 ID/路径独立登记，旧记录保留，冲突拒绝；重命名不能改变用途 | PASS（临时目录并发/冲突夹具；a7fff39 helper识别两行别名） |
| 整份登记严格读取 | 坏行、嵌套重复键、NaN/Infinity、旧行扩展JSON | 任一坏行或非法JSON拒绝整份且不覆写；合法条目扩展字段保留 | PASS（原文件字节不变及扩展JSON保留回归） |
| 来源引用与消费者一致 | provenance及每条provenance_history的source_asset_id/source_sha256 | 允许null；非null ID须为非空白字符串，SHA须64位十六进制；新旧坏记录均不发布 | PASS（16类主/历史坏引用、旧文件字节不变；4fdd200真实helper空批检查通过） |
| 整场与文件一致性 | 同 SHA 改 match_id、split变化、损坏源字节 | 拒绝跨场/划分改变和hash不符；本轮split保持unassigned | PASS（字节及分组夹具）；真实十场分组未由此项验收 |
| 写入与容量受控 | 非法version/路径、低配额、JSON超限、审计检查 | 原片只读；仅library owner写入；既有快照替换有前后hash，超限不发布 | PASS（临时owner和真实文件字节夹具） |

## 目录与接口

- 原始 Asset 路径：`data/training/<dataset-version>/...`；PTS索引也位于该版本子树。
- 用途 registry：`D:/video/data/training/handoff/training-registry.v1.json`。
- 训练清单：`D:/video/data/training/handoff/<dataset-version>.assets.v1.json`。
- 整场划分登记：`D:/video/data/training/handoff/training-splits.v1.json`。
- 替换审计：`D:/video/data/training/handoff/audit/`。
- `QuotaManager` 是必传实例；生产固定D盘owner，测试只能使用显式允许的临时根。

```python
from packages.library.training import (
    register_training_sources, tag_training_asset, publish_training_manifest,
)

version = "fine-badminton-2026-zenodo-20292976-v1.0"
# 若registry尚不存在，先发布明确为空的合法结构；已有记录会验证并保留。
register_training_sources([], dataset_version=version, quota=quota)

# ZIP验证并安全解压后即可逐文件登记，不必等待长视频解码和PTS扫描。
register_training_sources(
    [{"asset_id": "asset-" + sha256, "sha256": sha256,
      "relative_path": source_relative_path, "usage_scope": "training_only",
      "match_id": canonical_match_id, "provenance": source_provenance}],
    dataset_version=version, quota=quota,
)

asset = tag_training_asset(asset_from_build_asset)
result = publish_training_manifest(
    [asset], dataset_version=version,
    quota=quota, asset_validator=Asset.model_validate,
)
```

`asset_validator` 必填。返回新合同的模型对象（支持 `model_dump(mode="json")`）或已经验证的映射；返回值必须仍包含typed `usage_scope`与`provenance.usage_scope`，且不得改变hash、大小、路径、ID、比赛或划分。此回读用于检测旧合同丢字段，不能把测试中的恒等回调称为真实新合同联调成功。

`tag_training_asset` 深拷贝补两处training_only；已有冲突拒绝，不修改原对象。本轮只接收split=unassigned，不把用途自动等同于split=train。

`register_training_sources` 只要求 `asset_id/sha256/relative_path/usage_scope`；实际读取原文件验证SHA，可选size_bytes也必须相符。它不要求probe、不制造已验证Asset、不发布空manifest。match_id可缺省并在后续首次补齐；已有明确match_id（含显式unknown）不能通过重新登记改变，建议采集脚本从首次登记就使用稳定来源组。最小登记的返回值为registry、registry_path和registry_sha256；完整发布另返回manifest、manifest_path、manifest_sha256。

dataset_version允许安全中间点（例如v1.0），拒绝连续`..`、尾点、路径分隔符、handoff保留目录名和Windows设备名。global lock固定为 `data/training/handoff/training-registry.v1.json.lock`，所有本模块writer共用。

## 用途 registry 语义

顶层为 `{"schema_version":"1.0","assets":[...]}`，仅这两个顶层字段，与platform合同一致。每条至少有 `asset_id, sha256, relative_path, usage_scope`，用途固定training_only。同SHA的不同ID/路径分别保留为独立行，消费者无需理解额外别名数组即可索引每个ID、每条路径和SHA。相同SHA/ID/路径重复登记时保留原provenance，不同来源证据进入provenance_history；旧条目的其他合法JSON扩展字段保留。已知match_id按SHA约束，不能利用新增别名跨场。

兼容读取旧`asset_ids`/`relative_paths`数组时，会物化为独立scalar行，并标记`registry_alias_expansion`。数组不能恢复原始ID/路径配对，故新增ID沿用该记录原路径、新增路径沿用原ID，以SHA相等为限制依据，明确不声称恢复历史配对。新发布不依赖或输出这些数组。

读取按配置字节上限进行，重复对象键（包括条目内嵌套键）、NaN和Infinity均拒绝；每个既有条目都校验，不能跳过坏行继续发布。任何非法既有登记会停止追加并保留原文件。条目允许合法JSON扩展字段；顶层未知字段按platform的VersionedModel规则拒绝。

`provenance`及每条`provenance_history`都校验来源引用：`source_asset_id`允许null，非null必须为非空白字符串；`source_sha256`允许null，非null必须为64位十六进制字符串，大小写均接受且原值保留。这与共享helper的来源字段要求一致；无效引用不能先写入registry再让消费者整份失效。独立审查发现旧实现仅验证usage_scope，可能把非法来源写入；已修正并覆盖新登记、旧登记及完整Asset发布三个入口。

platform/render只读固定registry，并以实际原文件SHA为用途判定依据。别名帮助追溯，不取代按SHA查用途；重写Asset ID或搬到另一条路径不能解除training_only。调用方不可用不含旧条目的新批次替换registry，不提供删除或降级API。

该信任来自library独占写入职责和受控固定路径；它不是数字签名服务。部署需保持消费者只读，不能声称能抵御任意有共享盘写权限的外部程序篡改。

## 发布流程及失败语义

完整发布先校验源文件、用途/路径和新typed合同；随后持有同一用途发布锁及配额预留，合并旧registry并检查上限。以现有SplitRegistry固定整场划分，审计记录替换前后hash；用途registry原子落盘后才发布训练manifest。manifest再次验证原字节，故中途改变原片会失败；已登记的training_only记录保留，重试可继续，不为恢复而移除用途限制。最小源登记使用同一个锁、合并校验、原子写和审计流程；旧文件后来不存在也不能让其SHA用途记录消失。

JSON默认单文件上限10,000,000 bytes，调用方只能降低；每次发布预留 `5 × max_json_bytes + 262,144` bytes，覆盖registry、split登记、manifest及审计/账本。publication_audit按被审计路径将训练替换记录写入 `data/training/handoff/audit/`；训练与非训练路径混合批次拒绝。

崩溃锁不自动猜测过期，恢复前须人工确认没有存活writer。两个并发library发布者串行读取/合并/发布，不能最后写入者覆盖旧记录。媒体不会复制或写入。

## BFMD 标注交接的重跑与中断

`data/training/handoff/bfmd.annotations.v1.json`是已验证文件的稳定清单，按固定Drive ID保留记录；`complete`表示所选121项是否全部校验通过。重新运行时，不会因本轮只完成第一项就把旧完整清单缩减成单项，也不会把旧已验证条目改为本轮failed。

任何重写前，整份旧清单和原`data/training/bfmd/source-catalog.v1.json`进行有界严格JSON读取，拒绝重复键和非有限数。核对固定配置、catalog SHA、每个Drive ID与完整目标路径、URL、expected_bytes、kind/MIME及双training_only；已验证文件还须实际存在，并与原download receipt的成功状态、源URL、SHA、大小、原获取时间一致。旧文件消失、同大小字节变化、源配置或任何旧行不匹配均停止，保留旧清单及catalog原字节。旧增量格式中的failed行也校验来源及错误结构，但不计入可信文件。

本轮状态单独原子写入`data/training/handoff/bfmd.acquisition-progress.v1.json`，含run_id、本轮已尝试记录、尚未尝试数量、稳定清单已验证数量及IN_PROGRESS/PASS/FAIL/BLOCKED/INTERRUPTED。运行中的下载中断会明确计为interrupted，不能冒充未尝试或成功。稳定清单的PASS/IN_PROGRESS只表示可信文件的覆盖程度，实际本轮失败或中断须读进度文件。两种文件均保留training_only；稳定清单维持media/assets/events为0、scripts_executed=false，不执行来源脚本或转换事件。

整个BFMD批次持有`data/training/handoff/bfmd.annotations.v1.json.lock`，防止两个发布者读取同一旧快照后互相覆盖；崩溃锁不自动删除。替换沿用训练审计目录和单JSON 10 MB上限，累计生成元数据仍限50 MB。按当前121项配置在内存估算完整重跑：稳定清单累计21,301,808 bytes，独立进度累计10,710,486 bytes，合计32,012,294 bytes（未含小型审计），在预算内；超限则停止，不放宽预算。

已运行`python -B -m unittest discover -s tests/library -p test_bfmd_acquisition.py -v`：**14/14 PASS，0跳过**。回归使用临时真实小文件、receipt和原子发布，模拟完整两项重跑第一项后中断、活动下载中断、增量访问阻塞后恢复、旧文件消失/变化、catalog或旧来源变化；8项原配置边界检查继续通过。独立只读审查另发现预检后旧文件消失可能触发重新下载、旧SHA绑定新字节，已修为立即拒绝；同大小字节与receipt一并变化也须与旧SHA/大小/获取时间重新比较，新增回归通过。未联网、未写D盘，也不将这些夹具结果当作121项实际获取成功。

## 运行与验收边界

已运行：`python -B -m unittest discover -s tests/library -p test_training.py -v`，**25/25 PASS，0跳过，2.009秒**。本模块和单元测试仅标准库、CPU、临时目录，无网络、无共享媒体写入。新增文件为training.py、test_training.py和本文，未改manifest.py、shared contracts或其他模块。

额外合同联调：通过`git show a7fff39:packages/contracts/{models,validation,usage}.py`读取已提交平台源码，只在临时Python包加载，使用现有Pydantic 2.11.7。两份相同字节、不同ID/路径的临时源登记为**2行**，`TrainingRegistry.model_validate`通过；`UsageScopeGuard`分别通过两个ID和两条scalar路径识别限制，改ID改路径但保留SHA仍拒绝，`research_preview=True`仍返回TRAINING_ONLY。同一临时根的完整发布使用该提交的`Asset.model_validate`回调通过，两处training_only保留、既有两行未丢、预留全部释放。无新依赖安装，无媒体真实性或Web/render端到端结论。

来源引用修复后，另以`git show 4fdd200:packages/contracts/{models,validation,usage}.py`只读取得当前main合同，`python -B`加载临时包：16类主provenance/历史坏引用均在新登记前拒绝，旧有效registry逐字节不变且`UsageScopeGuard.check_many([])`保持通过；向临时旧registry注入整数来源ID时，真实helper确实报TRAINING_REGISTRY_INVALID，publisher也拒绝追加且保留原字节。恢复有效临时快照后真实`Asset.model_validate`完整发布及空批检查均通过，预留清零，合同快照未生成任何.pyc。此项仅为临时夹具合同兼容检查。

失败与修正记录：首次version正则过窄，拒绝实际既有目录 `fine-badminton-2026-zenodo-20292976-v1.0`，真实空registry调用在写入前失败；未重命名目录。已允许安全中间点并加入该精确版本名的临时文件登记测试，以及连续点、尾点和AUX/COM设备名的拒绝测试。library随后已真实重试共享盘初始化成功，内容为schema_version1.0/assets[]，SHA为`5d7572aea12757f02e262b10a65d217103152bd1e6ffe835a2347c2fceb251a1`；此时已验证媒体数明确为0。

真实十场包、完整解码及制作库/选片/独立render/研究预览入口的端到端拒绝由主任务及对应模块继续验证。上述真实R-04b总项在这些证据齐备前仍为NOT_RUN，不因本文件或publisher存在升级为PASS。
