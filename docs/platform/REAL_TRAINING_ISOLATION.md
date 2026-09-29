# R-04b：真实训练 handoff 的平台制作隔离负例

本轮平台负例 **16/16 PASS**：真实训练清单与路径导入被拒绝，普通 render 与 `research_preview=true` 的 worker 任务在执行 adapter 前被阻塞，人工种入的历史业务行也不能进入制作流程。本验证运行真实 Store、FastAPI 路由和 worker 用途检查，没有改实现代码；独立 render CLI 证据由 render 任务提供，另列于下。

实际运行时间为 **2026-09-29 10:05:14–10:05:20 UTC（18:05:14–18:05:20 北京时间）**，以证据 JSON 的时间为准，目录名只是独立运行标识。

## 输入与证据时点

读取 library 发布的 `D:/video/data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json`，以及固定可信 registry `D:/video/data/training/handoff/training-registry.v1.json`。本次没有对原片重新求 hash；以下媒体 SHA 来自 library 清单和 registry 的一致声明，脚本仅核对文件存在、stat 大小与清单一致。

| 项目 | 本次实际观测 |
|---|---|
| 负例选用 Asset | `asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913` |
| 原素材相对路径 | `data/training/fine-badminton-2026-zenodo-20292976-v1.0/extracted/876ddac3abe9141b8ce7f2fe.mp4` |
| library 声明的原素材 SHA-256 | `b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913` |
| 原素材 stat 大小 | 231,500,744 字节；与清单一致 |
| manifest 时点 | `2026-09-29T10:05:19.966037+00:00`；7 Asset；30,672 字节 |
| manifest 文件 SHA-256 | `f5709b7895f321a509956984817da5e34ebabbbf8594fe15905a292697dd810b` |
| registry 时点 | `2026-09-29T10:05:19.966704+00:00`；10 条；21,381 字节 |
| registry 文件 SHA-256 | `96c7154a2c1fd26ce0e833a5e6140a832a925ea53adeff9774a0e9ab30abcc6c` |

以上两个小型 JSON 文件实际读取并求 SHA；结束时再次读取，其 hash 与数量均未变化。7 个 manifest Asset 均完成合同验证、stat 大小核对及 registry 的 ID/SHA/path 关联核对。registry 已有 10 条不等于本任务验证了全部 10 个来源文件，更不等于全部原片重新 hash 或播放成功；后续 library 增量发布不改变本报告的时点结论。

完整 API 响应、两个 worker 的错误、前后 metadata hash/count、全部观测 Asset 及容量信息保存在：

`D:/video/platform/research-20260929/r04b-real-negative-20260929T100800Z/evidence.json`

该证据文件 SHA-256 为 `0ad8a15315fe3f5f509799cf0e8b2fa855efcb097b274c83d668e836e3438dc9`。

## R-04b 目标断言与结果

| 入口 / 方法与输入 | 预期 | 实际 | 状态 |
|---|---|---|---|
| TestClient 导入当时完整的真实 7 Asset manifest | 制作导入拒绝，库为空，不排任务 | HTTP 422 / `TRAINING_ONLY`；raw assets 与 queue 均为空 | PASS |
| TestClient import-path，真实首素材路径、不提供用途元数据 | 依据训练路径拒绝 | HTTP 422 / `TRAINING_ONLY` | PASS |
| 用途冲突：改成 typed/provenance general，保留真实训练路径 | general 不能覆盖路径/registry 限制 | HTTP 422 / `TRAINING_ONLY` | PASS |
| 元数据别名：保留真实注册 SHA，改 ID/path、移除用途/来源字段 | 在文件读取或入库前由注册 SHA 拒绝 | HTTP 422 / `TRAINING_ONLY`；**只改请求元数据，没有复制媒体或创建别名文件** | PASS |
| 私有 queue 排入真实 Asset 的普通 render；调用原 `run_once` | adapter 前阻塞，无任务输出目录 | `blocked` / `TRAINING_ONLY` | PASS |
| 同样排入 `research_preview=true` render | 研究预览不豁免 | `blocked` / `TRAINING_ONLY` | PASS |
| 历史 fixture：原片访问、候选审核、候选转时间线、保存时间线 | 当前用途检查仍拒绝 | 4 个 API 均 HTTP 422 / `TRAINING_ONLY` | PASS |
| 历史 fixture：正式 render API 与 research preview API | 即使旧选择/审核状态已存在也拒绝 | 2 个 API 均 HTTP 422 / `TRAINING_ONLY` | PASS |
| 历史 fixture：旧失败任务 retry、旧成功 probe/verify_manifest apply、旧成功任务 artifact 下载 | 不因历史任务状态跳过当前用途限制 | 4 个 API 均 HTTP 422 / `TRAINING_ONLY`；原任务状态不变 | PASS |

worker 普通 render 的 job ID 为 `job-1056bd6724fb405792ce4651dd0c66f7`，research preview 为 `job-fa1e8378b9334dbda449b8497d47f268`。两者均在用途预检处终止，adapter 哨兵执行次数为 0，没有创建对应 `platform/jobs/<job_id>` 目录。

历史入口使用私有 DB 的 SQL `INSERT` / `Store.put` **人工种入**真实 Asset 与模拟候选、时间线、任务。为了达到正式 render API 中较后的用途检查，还种入明确标记 `SIMULATED` 的历史 confirmed/human 审核 fixture；这不是实际人类审核、真实事件标注或成功生产导入，不能用作模型真值。原始导入阶段库始终为空；种入后 raw 表只有 1 条 fixture，制作库列表仍为 0，候选/时间线内容未被拒绝请求更改。模拟产物没有创建媒体文件。

## 隔离、容量与复现

脚本：[validate_real_training_isolation.py](validate_real_training_isolation.py)。使用既有平台环境；TestClient 在当前进程内调用应用，没有启动 Web 监听端口。

```powershell
& 'D:/video/runtime/platform/env/Scripts/python.exe' -B docs/platform/validate_real_training_isolation.py `
  --storage-root D:/video `
  --output-dir D:/video/platform/research-20260929/r04b-real-negative-<新标识>
```

目录必须是此前不存在的新目录。实际成功目录内的 `private-platform.sqlite3`、`runtime.sqlite3` 和容量锁 DB 都是本验证独有，未打开或写入主业务/任务 DB。脚本通过审计钩子禁止私有目录外的共享存储写入、训练媒体字节读取与子进程启动，并在 worker adapter 处设置失败哨兵；没有 GPU、FFmpeg、ffprobe、模型或媒体 CLI 运行，没有拷贝原片。用途 helper、路由和 worker 的拒绝实现未被替换。

容量账本在私有 queue DB 预留 **16,000,000 字节**并完成 owner/总容量与磁盘余量检查；开始时磁盘可用 935,217,795,072 字节。成功目录最终占用 177,280 字节，预留已释放。失败运行证据也保留在各自独立小目录，没有覆盖或删除已有数据。

## 保留的失败尝试

| 独立目录 | 实际结果与原因 | 后续处理 |
|---|---|---|
| `r04b-real-negative-20260929T100300Z` | 前 4 个 API 拒绝 PASS；worker 被验证脚本的 SQLite 审计误拦。脚本将私有 DB 的 `file:///...?mode=ro` URI 当普通路径，返回验证失败；主 DB 未打开 | 仅修验证脚本的本地 SQLite URI 归一化；保留该 `evidence.json`，新目录重跑 |
| `r04b-real-negative-20260929T100500Z` | API 导入、2 个 worker 和前 4 个历史入口通过；正式 render 在更早的人工审核门槛返回 409，未达到脚本要求的 422 用途断言 | 在私有 fixture 中显式模拟历史审核状态，以验证较后的用途拒绝；没有修改产品实现或降低断言，最终新目录 16 项通过 |

这些是验证脚本/fixture 的失败记录，不作为产品用途绕过漏洞，也不计入最终 PASS 数量。

## render 任务的独立 CLI 证据

另只读核验 `D:/video/render/handoff/training-denial-5f1e29d2eab9/validation.json`。它由 **render 任务实际运行**，本平台验证没有启动该 CLI，也没有复制其 33 KB 报告。报告时间 `2026-09-29T09:59:32.565142+00:00`，使用同一个真实 Asset；当时 manifest 为 4 Asset，文件 SHA `6a30244ce17b6fec560af822be71e336e52a3641e444600595cc73cc80d3403c`，registry 文件 SHA `3a0b9bf2c4677c43639929c402afcb81dbd497b3dd22b1ca193db60533aea9c4`。

其 standalone、preview、research-preview、confirmed 四种独立 CLI 请求的 `checks` 全为 true，整体 `status=PASS`：退出码 2、`blocked/TRAINING_ONLY`、无 artifacts、无 job output、无 child spawn attempt。它证明独立 render CLI 的真实拒绝路径，不表示实际渲染了训练视频；confirmed 同样是该负例请求里的模拟声明。

## 结论边界与下一步

本报告可作为 R-04b 的真实训练 metadata / 平台入口 / worker 拒绝证据，并关联 render 的独立拒绝证据；阶段总表由主任务结合各模块证据维护。没有实际复制匿名大文件再测试，没有对这批原片重新计算 SHA、解码或做模型推理，不能将拒绝成功说成识别/渲染成功。

产品内保留的 ID/hash 来源链允许执行边界追溯当前父源、核验真实字节与用途；这项父源机制的实际小字节回归见 `PRODUCTION_USAGE_TESTS.md`，本真实训练负例在读取媒体前已被拒绝，没有重新执行父源大文件求 hash。未知外部转码若已抹去来源元数据、又产生未注册新 SHA，不能据本验证断言能够识别。后续引用此报告须保留上述时点、输入范围和执行边界。

## 完整10项清单后的独立复跑

平台在产物当前身份补强版本上于 **2026-09-29 10:29:48–10:29:54 UTC（18:29:48–18:29:54北京时间）** 用同一脚本和新的私有目录再次执行，**16/16 PASS**。这次manifest与registry均为10项，前后metadata稳定。manifest SHA为`2725970f4485732e67ba249b72262c51dbba24ee17e5e97d901b18ec8a29e286`（43,956B），registry SHA为`63eb86de88e6c760be8ff3464318d8fd55a923e7bfa1d1c177dc2bdd643e52aa`（24,373B）。全部10项完成合同、stat大小及registry ID/SHA/path对应检查；没有重新读媒体字节、hash或decode这10部原片。

14个API均422/TRAINING_ONLY，普通render任务`job-d8c9ec2e65374223b06d4991c7561154`和research任务`job-f9e304a8d5224456a776a8ac2f2a7638`均在adapter前blocked/TRAINING_ONLY。逐入口历史fixture仍选前文b210真实Asset，整份10项清单导入被拒绝；不称每项各跑一遍所有入口。生产主DB未打开，导入阶段库/队列均空，历史行仅私有人工fixture；adapter执行、媒体读取、子进程均0，16MB预留释放。新目录最终187,444B。

证据为`D:/video/platform/research-20260929/r04b-real-negative-final-20260929T103600Z/evidence.json`，SHA256 `43ecab9e030fb373e8757d354870dfb87eae02d9dd87cc1043be7cfc517c1f83`。目录中的103600Z仅是唯一标识，实际时间以JSON为准。前述7项时点及两次失败记录保持原样；两个成功轮次不合并为32个不同验收用例。
