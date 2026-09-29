# R-04b 生产用途隔离回归

本文件记录生产入口的工程回归，属于 R-04b 的部分证据。全部文件由 pytest 在临时目录生成，媒体内容是明确的合成字节，不是可播放视频；没有读取 `D:/video/data/training`、运行 FFmpeg 或占用 GPU。不能据此将真实素材完整 R-04b 验收标成 PASS。

## 目标断言与结果

测试源：`tests/platform/test_production_usage.py`。测试先定义以下拒绝断言；Store、API 和 worker 使用实际实现，外部媒体执行入口在必要时替换为失败哨兵。

| 输入/边界 | 预期结果 | 用例数 | 实际结果 |
|---|---|---:|---|
| 同 SHA 已存在 general，传入 typed 或 provenance 的 training_only | 去重前拒绝，原记录不变 | 1 | PASS |
| 历史库记录是 training_only，重导入副本删除用途/来源字段 | 不得通过去重返回受限旧记录 | 1 | PASS |
| 注册表限制 SHA，副本改名并删除用途/来源字段 | 清单导入拒绝、无新记录 | 1 | PASS |
| 空库且训练目录无 registry；筛选库为空且 registry 损坏 | Store 和 API 均报告全局故障，不能返回空成功列表 | 2 | PASS |
| 无 hash 的 import-path 指向训练目录 | 部分元数据预检拒绝，不入队 | 1 | PASS |
| 已导入素材随后被 registry 限制 | 原媒体、候选审核、保存时间线、候选转时间线、research_preview 导出均拒绝，状态不变 | 5 | PASS |
| 老任务完成或失败后 registry 更新 | 产物下载、重试、probe/verify_manifest 结果应用均拒绝，任务/库状态不变 | 4 | PASS |
| render 排队元数据伪造 ID 和声明 SHA | 对实际字节求 SHA 后命中 registry 并拒绝 | 1 | PASS |
| render 排队快照仍 general，但当前权威库记录变为 training_only | worker 重新检查当前库记录并拒绝 | 1 | PASS |
| verify_manifest 初检后、校验期间 registry 更新 | 实际哈希完成后重新检查并拒绝 | 1 | PASS |
| probe 没有声明 ID/hash 的同字节别名 | 计算实际 SHA 后、任何媒体子进程之前拒绝 | 1 | PASS |

运行环境：既有 `D:/video/runtime/platform/env`，2026-09-29。命令：

```powershell
& 'D:/video/runtime/platform/env/Scripts/python.exe' -m pytest tests/platform/test_production_usage.py -q
```

结果：`19 passed, 1 warning in 2.47s`。warning 是 FastAPI/Starlette TestClient 关于 httpx 适配器的弃用提示，不影响断言。

共同合同的独立性能修复提交为 `4fdd200d23b6dcc7d7cf85386a12879f172702cd`，另有 `119 passed` 合同测试：500 registry 条目加 20 个待检查素材只解析 520 个物理路径；24 层双别名来源 DAG 只解析 49 个节点；每次公共调用仍重新读取/哈希 registry，节点/边/深度超预算和环均失败关闭。

## 本轮追加回归与集成结果

以下用例继续使用临时目录中的合成真实字节，文件 SHA 来自这些字节的实际计算；它们验证工程入口的放行与拒绝行为，没有新增真实训练数据实跑。对应目标仍为 R-04b，不以本轮单元/API 回归替代真实素材阶段验收。

| 测试源 | 目标断言、输入与验证方法 | 用例数 | 实际结果 |
|---|---|---:|---|
| `tests/platform/test_lineage_sources.py` | render、proxy、exact-frame 在执行前追溯当前库中可达父源并计算实际 SHA；父源实际含 registry 受限字节时，即使父声明和派生来源声明相互匹配也拒绝。覆盖祖先、同 SHA 别名、缺失文件/大小/SHA、内容或大小变化、预算、模型诊断跳过以及未知外部来源边界 | 16 | PASS |
| `tests/platform/test_artifact_usage.py` | 合成产物先成功 Range 下载，再把其实际 SHA 加入 registry，后续下载拒绝；分别检查 Artifact、producer、JobResult、preview/frame 的用途与来源链，以及训练目录路径。任一层受限均拒绝，其他层 general 不能覆盖；正常下载保持 Range 与 no-store | 16 | PASS |
| `tests/platform/test_source_identity_api.py` | 大文件带可信 worker proof 应用时不在 Web 同步重 hash；同大小/同 mtime 换源、校验证据至导入之间换源、原媒体身份变化均拒绝。覆盖旧任务大小分流、实际 SHA/registry 检查、自定义业务 DB 固定绑定与已绑定 DB 消失时失败关闭 | 10 | PASS |
| `tests/platform/test_small_manifest_batch.py` | 500 条 registry、20 个小文件导入时先实际计算全部 SHA，再批量检查用途；整条导入路径 registry 读取至多 3 次，保留 hash 时原身份。改名副本伪造声明 SHA 仍由实际 SHA 命中 registry 并拒绝 | 2 | PASS |

来源图的性能断言另覆盖 18 层双别名 DAG：37 个可达文件各求 hash 一次，不读取不相关库文件；元数据用途检查按批次执行，避免逐行重建 registry 索引。节点/边超预算时在读取源字节前失败关闭。

平台任务在产物身份补强前最近完整集合的测试结果为 **`550 passed, 7 skipped in 47.60s`**（2026-09-29）。这是平台任务此前实际完整运行结果；产物身份后续修复将另记最终回归，不把未完成验证计入通过。上述新增测试全部 PASS；全套的 7 个 skipped 不计为对应验收项 PASS。

## hash、身份与可追溯边界

执行边界只验证产品中保留来源关系的可达父源：从 `source_asset_id` / `source_sha256` 及同 SHA 别名找到当前库记录，读取真实父源字节，检查声明大小/SHA 与文件稳定性，再以实际 SHA 调用共同用途检查。缺失或不一致的已知父源证据会拒绝；不会为未知外部引用推造父文件，也不为每次任务扫描和 hash 全部无关库素材。

worker 的源校验证据放在内部结果顶层 `source_identities`，每项为 `[st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns]`。应用结果时比较当前路径身份并保留校验时的原 proof，不能在导入时重新取一个变化后的身份作为已验证证据；客户端 `Asset.probe` 中自报同名字段不算 proof。该证据是已执行字节校验的文件身份约束，不代替最初的 SHA 校验。

旧任务没有 proof 时，仅大小不超过 **8,000,000 字节**的源允许在 Web 重新计算实际 SHA 并检查 registry/文件稳定性；更大的源返回 `SOURCE_REVERIFY_REQUIRED`，要求重新运行后台探测或校验。产物补强后，worker在实际hash时分别保留路径与打开句柄的五字段身份，成功finish同事务存入runtime独立artifact_identities表，绑定job/attempt/artifact；任务JSON自报proof不授予信任。下载核对可信身份与当前用途，固定到已核验句柄，逐块读后检查变化。旧无proof产物仅≤8,000,000字节允许实际hash后升级；旧大产物返回ARTIFACT_REVERIFY_REQUIRED，Web不逐次全片hash大视频。Windows path/fd的ctime定义差异分别保存验证，不省略变化检测。通用下载及预览媒体/索引/缩略图均共用门禁；见[产物身份问题记录](../issues/platform-artifact-file-identity.md)。

这些校验能覆盖产品内保留且可追溯的来源链、已注册实际 SHA 和已知用途/路径；外部转码已抹除来源关系、且新字节 SHA 不在 registry 的未知素材，不能据此断言其训练来源可被识别。

## 未覆盖的验收

独立 render CLI 的真实拒绝、真实训练 handoff、浏览器实际选片、转码代理的源时间映射和真实媒体输出须引用对应模块与主任务的实际验收证据，本文件的临时合成字节回归不替代这些验证，也不替代调用方的真实文件 SHA 校验。

## 真实训练负例补充

[REAL_TRAINING_ISOLATION.md](REAL_TRAINING_ISOLATION.md)记录2026-09-29 10:05 UTC真实7项manifest/10条registry时点，平台14 API及2 worker拒绝，共16/16 PASS；关联render任务独立四模式CLI拒绝。真实片在读取媒体前已经拒绝，历史业务行与审核仅是私有模拟fixture。此报告的合成字节回归与该真实拒绝证据各自保留，不互相冒充。

产物身份新增定向工程回归29项通过，含同长度训练字节替换、同inode/size/mtime原地改写、伪proof、旧大文件不Webhash、route检查后替换、Range/HEAD/no-store及成功/失败/取消proof发布；同批关联143 passed/1 skipped。精确帧现已绑定成功preview job/attempt与唯一index Artifact，在执行、读取、解码及artifact生成后复验proof；新增11项均通过，定向185 PASS/6 SKIP。冻结源码最终组合607 PASS/7 SKIP/59.12秒；真实私有新exact任务和旧小产物兼容见RESEARCH_VALIDATION末节。声明hash与入队检查不代替执行时身份。
