# 训练标注目录交接

2026-10-02，library / 实施轮02。基线 `3dab169`，分支 `codex/library-annotation-catalog`。

## 开发前冻结的断言

只读消费已有 Fine-Badminton 2026 的10个视频、原始CSV、完整PTS及训练用途登记。输出 `data/training/handoff/annotation-catalog.v1.json`，保持 AssetManifest 1.0 兼容；额外信息放内容寻址的不可变 sidecar。平台由目录生成可选视频列表，用户不必手填路径。共享训练合同由01负责，本模块不改公共合同。

| 子项（隶属固定ID） | 输入与方法 | 预期结果 | 当前实际 / 状态 |
|---|---|---|---|
| A-02.library-integrity | 真实10 Asset，重算视频/PTS/CSV/来源文档SHA，核对登记、完整帧顺序、解码记录和来源快照 | 每条均可回查只读原件；双training_only；任何缺失、篡改、越界或未登记文件拒绝 | 开发前 NOT_RUN |
| A-02.library-publication | 构建与独立verify CLI；模拟写入失败、并发与重跑 | sidecar先完成且不可变，最后原子切换兼容manifest；切换前失败保留旧发布，重跑幂等；写入前额度预留 | 开发前 NOT_RUN；后续故障审查明确切换是commit point，见下文 |
| A-02.library-browse | 按asset_id读取目录附加信息，展示标题、时长、画质、PTS、来源和原始标注提示 | 浏览选择有稳定ID；不提供任意路径媒体服务；来源资产快照可逐字段对照 | 开发前 NOT_RUN；真实浏览器注册/播放由01验收 |
| A-05.library-semantics | 原CSV逐行保留，含重复/零长度/乱序；检查所有输出记录 | 原帧号/标签/位置只作未审核提示；无Event、无确认毫秒、无human真值或细标签映射；帧基数/端点/原广播偏移/双语映射未知 | 开发前 NOT_RUN |
| A-05.library-groups | 10份publisher文件名、已登记SHA和现有split清单，构建前后对照 | 真实比赛组未确认，来源hash是去重依据而不是独立比赛证明；split保持unassigned；不得改registry/splits | 开发前 NOT_RUN；正式分组仍BLOCKED |
| A-05.library-exclusions | BFMD现有handoff，无原视频/PTS | 可说明未匹配资料；不能伪造可播放Asset或正式视觉训练真值 | 开发前 NOT_RUN |

A-02完整用例需要01真实浏览器注册、播放和源时间定位；A-05完整用例需要01/03快照导出与消费。本文件只判定library数据前提，不以单元测试替代完整验收。S0-03/04及CTX专家定义/独立比赛划分仍BLOCKED。

## 资源与执行约束

原片只读，不下载、不复制媒体、不启动GPU、网络服务或新环境。复用既有Python及平台Pydantic环境。发布元数据峰值暂定50,000,000字节，需由library容量台账在写入前确认并预留；任何生成内容超过预算停止。现有registry与training-splits只读。记录实际容量、命令、hash、测试与失败后更新本文件。

## 已发布接口与消费方法

- 入口：`D:/video/data/training/handoff/annotation-catalog.v1.json`，标准 `AssetManifest` 1.0，10条资产，47,656B。SHA256 `3fc6adf81e6f5229e4b4e4ae7de215be89bc415838d5e5aea64fb28ec85bea32`。
- 每个Asset的 `provenance.annotation_catalog` 指向同一个details sidecar，包含 `schema_version/relative_path/sha256/size_bytes`。当前details为 `data/training/handoff/annotation-catalog/600eb42efb2c80093d1b40e79abccc34728261944848fc24fe1c7e35c8d5d225.details.json`，84,179B，SHA与文件名前缀相同。
- details.schema_version=`library.annotation-catalog/1`，这是本模块附加表版本；不占用或修改01的训练合同。`assets[]`按 `asset_id` 关联，`source_asset`是源handoff中的原始dict快照。发布Asset只在provenance新增上述引用，原字段逐一相等；不经model_dump添加默认值或改时间。
- `display_title`来自提取清单保存的canonical ZIP Unicode原名。早期Asset一条题名含替代字符；不改源Asset，用此字段展示。时长/画质/帧率/PTS在source_asset中，界面可以列出标题、时长、分辨率、CSV行数和待审核原因供选择，不需用户输入媒体路径。
- `raw_annotations`指向该视频专属的不可变hints文件，schema=`library.annotation-hints/1`。`rows[]`保留CSV顺序、`source_record`（从1开始）、`source_line_end`（CSV物理行末）、`row_id=CSV_SHA:record`、四个原始字符串及诊断；不清除重复和零长度。`semantics`对整个表声明unreviewed、human_confirmed=false、training_truth_eligible=false。
- `match_group.confirmed_group_id=null/status=unconfirmed`；publisher_match_id只是原来源登记。source_sha256可去重，但不同hash不证明不同比赛。没有自动train/validation/test分配，也没有将10个文件计为10个已确认比赛。
- `inputs`锁定源AssetManifest、用途registry、split清单、提取清单及BFMD摘要的原始字节SHA；`rights`保存原README/LICENSE引用与冲突。`excluded_collections`中的BFMD只有摘要引用，无视频/PTS/可播放Asset，不深复制1.8GB标注数据。

平台加载顺序：读取受配置允许的目录 → 验证AssetManifest及目录SHA → 仅按该引用读取/核验details → 按asset_id列出选择项 → 注册选中源Asset并检查当前源SHA/PTS/用途 → 在独立 `/training` 媒体端点播放。hints按选中的asset_id读取，不提供任意路径文件端点。目录SHA是完整发布图的入口；不要扫描sidecar目录猜最新版本。`verify`提供完整原文件重核，不需要联网。

消费边界：可以在视频上新建独立人工标注；原CSV提示没有可确认的毫秒区间，不能当contact mark、回合终点或半开Interval。9份英文表的29个原标签与一份中文表的31种字串合计60原字串，并非60个独立语义类别。原标签不能映射成展搓/收搓/步法真值。身份和原比赛偏移未经确认；README原使用限制也通过证据保留。制作导入/检索/候选/Timeline/render继续拒绝training_only。

## 构建、核验和故障处理

在仓库根运行（PowerShell）：

```powershell
& 'D:/video/runtime/platform/env/Scripts/python.exe' -B -m scripts.library.build_annotation_catalog build
& 'D:/video/runtime/platform/env/Scripts/python.exe' -B -m scripts.library.build_annotation_catalog verify
& 'D:/video/runtime/platform/env/Scripts/python.exe' -B -m unittest tests.library.test_annotation_catalog
```

复用已装Python3.12.11/Pydantic2.13.5（平台环境已有版本）；本轮安装来源/新增依赖：无。没有FFmpeg重解码、WSL/Conda安装、GPU任务或新增常驻服务。回归旧下载测试的临时回环服务均已退出，不使用18080/18082。过去完整CPU解码记录绑定原SHA，本轮重哈希确认这些原字节仍相同，并实读完整PTS。

固定输入锚点见 [annotation_catalog.json](../../configs/library/annotation_catalog.json)。输入变化会失败，不能自动更新锚点消除错误；先审查来源变化再显式更新配置并重新验证。builder只支持本轮已审查的Fine训练子树和固定输出，不能以CLI路径覆盖原片、registry或生产handoff。

发布持有专用catalog锁与50MB容量预留，内容寻址sidecar通过temp+fsync+no-clobber发布；同名不同字节拒绝。全部附加表及不可变manifest副本就绪后才原子替换入口；替换旧入口前后留publication_audit。重跑相同输入返回unchanged。切换前失败可能留下完整但未被入口引用的sidecar，旧入口不变；不自动清理、删源、回收未知锁或修改旧代文件。进程被杀后的锁/容量预留需人工核对进程后显式恢复，不能猜过期。

故障审查补充：`os.replace`成功是发布提交点。之后若审计completed记录写入失败，目录已经完整切换，不能谎报“失败且旧入口不变”。此时返回 `published_with_audit_warning` 和明确warnings，新目录继续可验证；旧不可变代与started审计记录保留。消费者应检查warnings、运行verify并查审计存储失败原因，不自动回滚已经可能被注册的有效代。此项明确了原“失败保留旧发布”断言的提交点边界，不把部分sidecar暴露为有效目录。

verify不构造QuotaManager，不写容量账本、数据目录或报告；其JSON打印到stdout。本次报告由调用者重定向保存到仓库docs。它重新构建期望字节，重哈希原视频/PTS/CSV/来源文档并与全部发布sidecar比较；任何缺失、内容差异、路径别名、原PTS乱序或非有限JSON都会报错退出2。

## 真实运行结果（2026-10-02）

| 子项 | 实际结果与证据 | 结果 / 尚欠条件 |
|---|---|---|
| A-02.library-integrity | 10原视频重新SHA核验；10PTS共980,703行顺序/整数/源SHA/时基/解码数一致；总38,592,556ms，9CFR+1VFR。10CSV及README/LICENSE核验；标准AssetManifest有效 | PASS，真实原文件范围；[独立verify](ANNOTATION_CATALOG_VERIFY.json) |
| A-02.library-publication | 正式build发布10hints+1details+1不可变manifest副本及入口；再build为unchanged/metadata_bytes_written=0；50MB预留已释放。临时合成fixture另实测切换前/后故障、并发锁、不可变冲突、只读verify | PASS，真实发布与工程故障测试范围区分；[build](ANNOTATION_CATALOG_BUILD.json)、[rebuild](ANNOTATION_CATALOG_REBUILD.json)、[tests](ANNOTATION_CATALOG_TESTS.json) |
| A-02.library-browse | 10条可供选择的元数据均可按ID关联canonical标题、时长、PTS、原始提示；source_asset快照逐字段等于源manifest | 数据前提PASS；[checks](ANNOTATION_CATALOG_CHECKS.json)。浏览器注册/播放/源定位NOT_RUN，归01 |
| A-05.library-semantics | 9817原始行、5重复、3同端点、3乱序提示；0确认毫秒/0Event/0human真值；全部unreviewed、training_truth_eligible=false | PASS，仅保留语义边界；原CSV语义确认仍BLOCKED |
| A-05.library-groups | 10条group均unconfirmed/null，全部split=unassigned；原registry/splits等全部输入SHA与开工锚点相同 | 数据前提PASS；正式独立比赛组/默认训练真值仍BLOCKED |
| A-05.library-exclusions | BFMD保持unmatched、playable_assets=0、training_truth_eligible=false，只有既有handoff哈希引用 | PASS；视觉训练缺原视频/PTS |
| A-08关联数据检查 | 现生产UsageScopeGuard读取新目录10条全部拒绝，仍training_only | PASS，仅共享gate实物检查，不替代01/04完整入口验收 |

A-02和A-05完整工程用例在本模块仍NOT_RUN，不能由以上数据子项改为整体PASS；S0-03/04/CTX仍BLOCKED。原语义问题见 [library-training-annotation-semantics](../issues/library-training-annotation-semantics.md)。

初次发布写出3,366,509B目录元数据；加SQLite账本实际owner增长3,370,605B。发布后library data14,805,728,096B，项目计费92,651,497,886B，活动预留0，D可用922,584,801,280B。项目runtime不能遍历，按70GB owner配额上界保守计费；此项目数不是实际占用实测值。原片未复制，下载0、新环境0。

完整library回归 **209/209 PASS、0skip、23.233秒**，含新目录23项。测试覆盖输入/视频/PTS/sidecar篡改、合法用途别名、原CSV完整性、提交前故障旧入口保留、提交后审计失败明确警告、锁竞争和verify只读；都是工程夹具，不是动作识别成绩。运行结果及被测源码SHA见 [TESTS.json](ANNOTATION_CATALOG_TESTS.json)，完整unittest输出见 [TESTS.txt](ANNOTATION_CATALOG_TESTS.txt)。

失败记录：自定义stdin runner曾触发Windows multiprocessing无法重载`<stdin>`，一个旧并发额度测试ERROR（209项/48.036秒）；[失败收据](ANNOTATION_CATALOG_TESTS_STDIN_FAILURE.json)保留。随后使用原有 `python -m unittest`入口运行同套测试通过，无实现绕过、无skip或门槛变更。发布可靠性审查及已修问题见 [publication issue](../issues/library-annotation-catalog-publication.md)。

实现、配置和23项回归提交：`158ce5fff898a52b46de110cf53a5359ae7e14f3`。所有变更在 `codex/library-annotation-catalog`，未推送、未自行合并main；主任务应同时集成后续docs证据提交。原数据、许可证据、PTS及9,817行提示只在D:/video，Git只提交代码、配置和小型验收报告。
