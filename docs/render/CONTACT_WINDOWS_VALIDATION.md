# 触球逻辑窗口：A-07 / A-08 验证

日期：2026-10-02；2026-10-03追加主任务P2复核修复。branch `codex/render-contact-windows`，main 基线 `3dab169`。先登记断言见 [交接与规则](CONTACT_WINDOWS_HANDOFF.md)；失败事实见 [P2问题记录](../issues/render-contact-window-review-p2.md)。公共合同依赖 `6fec08f` / `2128568`；不修改 Event/Timeline 合同。

## 实际结果和范围

P2新增断言先登记再修复：非首拍serve/同刻/闭合包络重叠不得产出完整回合；矛盾时间别名与点区间必须拒绝；冻结PTS引用必须匹配clock来源与实际帧数/时基；未归属冲突记录的证据进入完整时间上界，无时间信息保留unknown/null等待。修复前已复现发球9个失败子例，其余反例由主任务复核提供。规则与adapter升至1.0.1，新增16项回归及本版真实只读复验全部PASS，证据如下。

| ID | 目标 / 方法与输入 | 预期 | 实际 / 状态 | 证据与未完成项 |
|---|---|---|---|---|
| A-07 | 给定发球、触球、死球与阶段记录，派生球路/手法/步法/整回合 | 半开范围不越源/回合；不同策略不混用；缺终点、不确定、交替球员、越界均明确处理 | PASS：core 46 项 + 公共 adapter 30 项全通过，0 skip（含本轮16项P2回归） | `tests/render/test_contact_windows.py`、`test_training_window_adapter.py`；包含四人/对手插拍、不确定竞争终点、死球截断、阶段倒序、not_applicable、证据水印和嵌套训练段 |
| A-07 P2 | 更早/同刻/包络重叠触球；矛盾证据时间；冻结PTS引用换源；未归属触球的晚时刻/帧/未知证据 | 不声称完整回合且冲突refs完整；时间矛盾拒绝；PTS身份/实际帧数/时基匹配；所有被引用证据进入latest/未来信息 | PASS：candidate/null与严格分离正例、非法时间拒绝、8类PTS字段篡改/缺字段与无clock兼容、8500ms/7960ms/unknown完整闭包均实际通过 | P2问题记录保留初始失败；unknown等待为null；ROI等JSON未丢，不声称ROI裁剪或动作真值 |
| A-07 | 固定 b210dc39…真实训练源及32,651行完整PTS，技术 marks 与六阶段 | 实际源/索引 hash正确；四策略逐帧独立枚举与二分映射一致；原片只读 | PASS：10 个逻辑窗口；unknown阶段仍 candidate | [机器报告](CONTACT_WINDOWS_VALIDATION.json)、[输入核查](CONTACT_WINDOWS_DATA.md)；技术 marks 不证明画面在该时刻实际触球 |
| A-07 | 已有真实 VFR 索引 `[9160,9220)` | 不用frame/25；应选229、230，排除231 | PASS：229/230对应9160/9180ms，231为9220ms | 报告 VFR 节；本轮只核完整索引，未重新hash约1GB的VFR原片或解码 |
| A-07 | 01正式 bundle/snapshot 与明确serve/phase修订映射 | 点/区间和人物正确映射；原始标签/角色/revision/hash保留；不升级人工真值或trainable | PASS：真实b210源/PTS的技术bundle和snapshot各10窗口，范围/PTS/status/reasons相同；快照重建和JSON回载一致，eligible前后均0 | 11条revision2/previous1记录、unknown、agent pending、匿名unconfirmed及质量阻塞项保留；未进行服务/UI注册或人类动作真值验证 |
| A-07 | root实际网页导出的6条记录快照（d2deb512…），不给serve/phase映射 | 7窗口；缺serve使rally unavailable，缺阶段使footwork candidate；源PTS/原始修订/unknown/快照质量不丢 | PASS：bundle rev2→7窗口，rally null/missing_serve，两项footwork candidate/conservative_context_without_phases；6项实际范围PTS逐帧核对通过 | `platform/integration-20261002/snapshot-before-restart.json`；unknown2/unobservable1、eligible0/excluded3不变，只核adapter消费，不替代root的网页/重启记录 |
| A-08（04边界） | 真实训练源、元数据来源衍生物、训练清单、嵌套训练段、general原片训练窗口 × normal/preview/research-preview | render先返回blocked/TRAINING_ONLY，0媒体/预留/产物 | PASS：18/18；进程审计和renderer哨兵均0调用 | [机器报告](CONTACT_WINDOWS_VALIDATION.json)；元数据衍生物仅内存fixture，未制作任何训练视频 |
| A-08（general兼容） | 原制作三片现有请求→公共guard、实际SHA、逻辑normalize及旧render测试 | general仍可走旧流程；原3段/512帧/30fps逻辑不变 | PASS（上述范围） | 本轮未重新编码/播放；此前真实成片证据不冒充本轮新运行 |
| A-08（其他模块） | 制作导入、Candidate、平台Timeline API、主线浏览器真实全链 | 每个入口独立拒绝训练来源 | NOT_RUN（本模块） | 01/root维护全链验收；这里不宣布整个A-08或S4阶段达标 |

最终全量命令 `python -B -m pytest tests/render tests/contracts -q -p no:cacheprovider`：**502 passed，1 skipped，583 subtests passed，8.03秒**。唯一跳过为既有 timeline symlink 权限条件；触球窗口76项测试/174个子例全部实际通过。首次交付的486/528及60项结果保留在Git历史，本次新增16项。测试数量不替代上表的真实输入证据。

## 可复现命令

在本工作树根目录，使用已有隔离Python；无需安装工具、开端口或GPU：

```powershell
& 'D:/video/runtime/platform/env/Scripts/python.exe' -B -m pytest tests/render tests/contracts -q -p no:cacheprovider
& 'D:/video/runtime/platform/env/Scripts/python.exe' -B scripts/render/verify_contact_windows.py --storage-root D:/video
& 'D:/video/runtime/platform/env/Scripts/python.exe' -B -m packages.render.contact_windows --request configs/render/contact-windows.example.json --storage-root D:/video
```

第二条只更新工作树内小型机器报告（上限500KB）；审计禁止其他写入与任何媒体/子进程调用，不复制或改原片。P2修复后最终运行时间2026-10-02 UTC16:35:38–16:35:42（北京时间10月3日00:35），报告237,138bytes，8项源码SHA在运行前、后及本模块最终复核均一致。13项跟踪输入stat、原片/可信registry及网页快照SHA均未变。第三条只输出 JSON；本轮按同一 CLI 参数入口在验证器进程内运行，exit0、10 windows、stdout 41,219 UTF-8 bytes、stderr0，媒体/子进程调用0。它不是独立shell启动CLI的记录。

## 环境、容量和真实限制

复用 `D:/video/runtime/platform/env/Scripts/python.exe`（Python3.12及既有Pydantic）；本轮未引入外部代码、依赖、技能或安装。无服务端口、GPU或render容量预留，D盘新增写入0；新增源码/测试/配置/文档/报告合计预算小于5MB。

23:03北京时间只读快照：render 647,917,504 bytes/40GB；runtime/render 873,315,597 bytes/5GB；D盘可用922,754,990,080 bytes。它是可见逻辑bytes、非原子快照，不称为NTFS分配簇大小，也不把旧全局统计当本轮重测。详见输入核查文档。

本模块固定marks、人物和回合为agent技术fixture，追加的实际网页快照也保留agent/pending与unknown，原始发行标注语义、专家触球/步法真值仍未知。`ready`仅指给定记录下的逻辑边界完整，不表示动作识别成功或人类确认。非整数帧时刻与整数毫秒存在取整差时保留PTS、差值并给candidate，不能冒称零误差帧标记。详见 [真值与支持范围问题](../issues/render-contact-window-semantic-ground-truth.md)。

下一步由01/root将纯逻辑函数接入训练工作台并复核真实浏览器全链；模型侧自行消费训练窗口和原快照训练视图，不把本清单当生产Timeline或新人工真值。原general成片调用和默认CPU保留。
