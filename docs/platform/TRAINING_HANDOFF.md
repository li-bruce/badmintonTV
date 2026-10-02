# 2026-10-02 训练工作台交接

- 分支：`codex/platform-training-workspace`；基线：`3dab169`。
- 状态：合同已独立提交，API/界面实际浏览器验证进行中；尚未声称本轮全部 A 用例通过。
- **合同独立提交 SHA：`6fec08f`**。仅14份训练合同、schema、fixture、测试与合同说明，可单独 cherry-pick。全合同 258 PASS / 1.63s；新增主体四角色、同源 SHA/祖先/session 分组连通、正负证据与可见性门禁、修改内容清审核、不可变快照。详细字段见 [TRAINING_CONTRACT.md](TRAINING_CONTRACT.md)。
- **合同语义修复独立 SHA：`2128568`**。规范化继承/显式主体后检查重复判断，防止同主体同时 present/absent；75训练合同 PASS，schema 字段未改。03/04 应一并同步。
- 已复用主任务手册 `5aff6b1`（本分支 cherry-pick 为30c084f），models词表 `1a44123`（本分支6d4ac4a）；主任务无需重复集成这两份。
- 当前私有 18082 已完成浏览器新建项目、可信目录登记真实b210原片（231,500,744bytes）与真实32651帧PTS、60–70秒Agent演示回合草稿和匿名人物；保存/重启验收继续中。不得作为真人回合/动作真值。
- 功能提交 SHA：待填写。
- 功能已通过全后端回归 **748 passed / 8 skipped / 81.84s**，新前端 **18/18 PASS**，JS语法与diff检查通过；8项条件跳过不计PASS。真实训练制作隔离旧负例 **16/16 PASS**（2026-10-02重跑），证据 `D:/video/platform/research-20260929/r04b-real-negative-20261002-training-workspace/evidence.json`。
- 真实浏览器已将2人物、1回合、独立死球、2触球、1动作、多标签unknown与双方image_normalized点位存为bundle revision2；重载保留。第一版保存后真实服务重启保留；最终快照与冲突演示继续进行。
- 启动：`.\start-platform.ps1 -Port 18082 -DatabasePath D:/video/platform/training-20261002/platform.sqlite3 -TrainingReviewer agent`。正式人工使用：在人工操作的本机服务启动命令加 `-TrainingReviewer human`，界面才开放人工确认；不需改代码，Agent不得以此冒充人工。缺省仍agent。
- 入口 `/training`、`/guide/`；模型词表自动读 `configs/models/taxonomy.v1.json`，或用 `-TrainingTaxonomy <管理员路径>`。目录默认固定 `data/training/handoff/annotation-catalog.v1.json`，兼容旧可信manifest；不接受用户任意路径。
- 设计与验收断言：[TRAINING_DESIGN.md](TRAINING_DESIGN.md)。
- 服务、容量、实际浏览器证据：待运行后填写；只使用私有 18082。
- 主任务负责集成，未推送、未发布；不要求跨聊天发送消息。
