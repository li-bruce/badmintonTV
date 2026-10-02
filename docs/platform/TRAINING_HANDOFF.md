# 2026-10-03 拖拽与区域增补交接

本轮平台提交：合同 `a0fc1db` → 功能 `c97f39f` → 快速已有块投放修复 `8ba5cc2`；root已回执集成。详细固定A-11～A-14子项见 [本轮验收](TRAINING_INTERACTION_VALIDATION.md)，原协议见 [区域合同](TRAINING_REGIONS_CONTRACT.md)。区域只在原record.evidence中兼容扩展，没有旧snapshot默认字段变化。

真实18082已完成空轨道/已有块原生投放、同主体去重/不同主体、整段/左右边界拖动/越界拒绝/键盘1ms，矩形/多边形/移动/角点/顶点/黑边/取消/删除及save/reload。836合同平台+8skip；跨模块四批1506PASS/23skip，另1039subtests单列；最终71前端PASS。旧实际hash不变，新agent快照0eligible/5excluded/正式下载409。

交接实际数据：`D:/video/platform/training-interaction-20261003/snapshot-with-regions.json`，快照 `training-snapshot-a4533d2de09143aeae9d3dfe76e1b2ea` / SHA `f0a57ada2b902edde5128a78719e69c98dd86f98e933ebd7aec70255b96c53a9`，2人物/5记录/2区域。最终project8/bundle6；原片只读、不复制。root/03/04应独立消费实际区域证据，不把这里的单元测试当作跨模块实际验收。

私有CAS真实409保留草稿与服务端已验；随后原生confirm让Edge自动化恢复失败，已请用户关闭测试弹窗。最终截图/旧tab恢复/临时viewport reset尚BLOCKED，详见 [问题](../issues/platform-browser-confirm-recovery.md)；不能据此声称服务端数据丢失，也不把恢复写成PASS。18082仍agent运行，PID73300，2GB预留已释放。18080 human未写，无推送、GPU或新增依赖。

最终root回执已独立完成18084保存重载/集成截图，以及真实区域的models/render/WSL CPU消费，阶段总表由root更新。本模块停止Edge恢复尝试，不再要求用户关闭弹窗；保留本tab未完成恢复的限制，提交本轮事实报告即可。

# 2026-10-02 训练工作台交接（此前轮次）

- 分支：`codex/platform-training-workspace`；基线：`3dab169`。
- 状态：平台功能、真实浏览器保存/冲突/导出及私有重启验证完成。详细固定ID结果见 [TRAINING_VALIDATION.md](TRAINING_VALIDATION.md)，不声称整轮或主线全部A用例通过。
- **合同独立提交 SHA：`6fec08f`**。仅14份训练合同、schema、fixture、测试与合同说明，可单独 cherry-pick。全合同 258 PASS / 1.63s；新增主体四角色、同源 SHA/祖先/session 分组连通、正负证据与可见性门禁、修改内容清审核、不可变快照。详细字段见 [TRAINING_CONTRACT.md](TRAINING_CONTRACT.md)。
- **合同语义修复独立 SHA：`2128568`**。规范化继承/显式主体后检查重复判断，防止同主体同时 present/absent；75训练合同 PASS，schema 字段未改。03/04 应一并同步。
- 已复用主任务手册 `5aff6b1`（本分支 cherry-pick 为30c084f），models词表 `1a44123`（本分支6d4ac4a）；主任务无需重复集成这两份。
- 当前私有18082已完成浏览器新建项目、可信目录登记真实b210原片（231,500,744bytes）与真实32651帧PTS、1280×720播放/seek、60–70秒Agent演示回合和匿名人物。不得作为真人回合/动作真值。
- **功能提交 SHA：`370ddfe`**。已通过下述回归，主任务可集成主线18080独立验收；私有浏览器/重启报告见本交接链接。
- **UX补丁 SHA：`146f598`**。常见快照质量阻塞与标签维度中文显示；质量未通过时隐藏正式训练下载链接，保留审计下载。对应主线反馈的英文blocker修复。
- **来源显示补丁 SHA：`37cd7f2`**。内容修改清除旧审核后，仍显示revision_audit中的编辑来源；审核状态与审核人独立显示，不把human编辑来源升级为human confirmed。最终新前端18/18 PASS。
- **标签栏补丁 SHA：`4258f16`**。默认短名称/判断/理由，完整定义与证据收进逐项“定义与判断依据”；原文和全文搜索保留。18/18回归及真实浏览器默认折叠/展开/隐藏内容筛选PASS，无合同变化。请在146f598、37cd7f2之后集成。
- 功能已通过全后端回归 **748 passed / 8 skipped / 81.84s**，新前端 **18/18 PASS**，JS语法与diff检查通过；8项条件跳过不计PASS。真实训练制作隔离旧负例 **16/16 PASS**（2026-10-02重跑），证据 `D:/video/platform/research-20260929/r04b-real-negative-20261002-training-workspace/evidence.json`。
- 真实浏览器已保存2人物、1回合、独立死球、2触球、1动作、手法/步法unknown与双方image_normalized点位；CAS409保留草稿，重载最新版本后修改成功。最终project6/bundle4/动作record2，4版历史保留。
- 浏览器实际下载审计JSON 516452B，逐字段与冻结快照相等。快照 `training-snapshot-ed4c98ec1bdd4beb9baa7e9caffed83e` 固定project4/bundle2，canonical SHA `62ad9a1c5b5be7a269ddc206d183a6e474c6a7dfc59835eb12271454d6167378`；后续编辑与重启未改变。0 eligible/2 excluded，正式训练下载409；真实训练仍缺专家定义/人审/确认独立分组。
- 最终18082后端重启于15:54:21UTC，project/bundle/revisions/snapshot逐字段相等，数据库各表计数不变；实际browser重载及console检查通过。原冲突tab在确认框后自动化超时，已新tab恢复，未声称原tab原地恢复；详见验收报告。
- 启动：`.\start-platform.ps1 -Port 18082 -DatabasePath D:/video/platform/training-20261002/platform.sqlite3 -TrainingReviewer agent`。正式人工使用：在人工操作的本机服务启动命令加 `-TrainingReviewer human`，界面才开放人工确认；不需改代码，Agent不得以此冒充人工。缺省仍agent。
- 入口 `/training`、`/guide/`；模型词表自动读 `configs/models/taxonomy.v1.json`，或用 `-TrainingTaxonomy <管理员路径>`。目录默认固定 `data/training/handoff/annotation-catalog.v1.json`，兼容旧可信manifest；不接受用户任意路径。
- 设计与验收断言：[TRAINING_DESIGN.md](TRAINING_DESIGN.md)。
- 证据根 `D:/video/platform/training-20261002`：final-validation.json、final-ui-validation.json、before-final-restart.json、browser-downloaded-audit.json、browser-ui-evidence/、services.json、capacity-ui-final.json。父PID50456/server59504；无永久worker。后端源码146f598启动，后续37cd7f2/4258f16为即时提供的静态JS/CSS。
- 最终容量16:07:48UTC：私有目录约3.82MB；platform204739901B/60GB、runtime/platform1048360620B/10GB、D余量922181832704B，2GB和最终截图16MB预留均已释放。原片未复制，无安装/GPU；非全模块700GB总审计。
- 固定结果：A-01/02/03/04/05工程PASS；A-08原始来源隔离、A-09平台手册入口、A-10私有持久化子范围PASS，整项留主任务验收。A-06/07由03/04；不将子范围PASS替代完整A或专家真值。
- 主任务负责集成，未推送、未发布；不要求跨聊天发送消息。
