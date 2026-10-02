# 2026-10-02 平台训练工作台验收

本报告对应 `IMPLEMENTATION_ROUND_2026-10-02.md` 的固定 A 用例；开发前断言见 [TRAINING_DESIGN.md](TRAINING_DESIGN.md)。这是01平台模块的私有18082验收，不替代主任务的main集成、03模型消费、04范围策略或专家动作真值。

## 交付与环境

- 分支 `codex/platform-training-workspace`，基线 `3dab169`。独立合同 `6fec08f`、主体语义修复 `2128568`、完整功能 `370ddfe`、中文质量提示与禁用训练链接 `146f598`、编辑来源独立显示 `37cd7f2`、标签说明折叠 `4258f16`。最终提交顺序见 [TRAINING_HANDOFF.md](TRAINING_HANDOFF.md)。
- 新增独立训练合同、training_*表、可信目录后台登记与只读媒体服务、项目/人物/回合/独立死球/触球/区间/多主体判断/图像态势、CAS修订、冻结快照和中文工作台；受控 `/guide/` 复用主任务静态手册。旧制作入口继续检查training_only。
- Windows Python 3.12：`D:/video/runtime/platform/env/Scripts/python.exe`；Node 18.16：`C:/Program Files/nodejs/node.exe`。CPU，无安装、GPU或全局Python修改。
- 浏览器使用已安装 `computer-use` 技能，来源 `openai-bundled/computer-use/26.928.20755`，仅自动化本机Edge。未引入外部前端库或CDN。
- 私有服务 `127.0.0.1:18082`；数据库 `D:/video/platform/training-20261002/platform.sqlite3`，actor=agent。主线18080和生产数据库未由本任务打开或修改。
- 末次重启：2026-10-02 15:54:21 UTC，启动父PID50456、实际server PID59504。命令已核对，旧server48732停止。服务记录 `D:/video/platform/training-20261002/services.json`；日志 `server-4.stdout.log` / `server-4.stderr.log`。保留服务供审阅，无永久worker。

```powershell
.\start-platform.ps1 -Port 18082 -DatabasePath D:/video/platform/training-20261002/platform.sqlite3 -TrainingReviewer agent
```

真实人工使用时，管理员用 `-TrainingReviewer human` 启动该人工操作服务；无需改代码。缺省agent，浏览器请求不能自升权限。本轮未使用human模式冒充真人审核。

## 固定用例结果

整项尚有其他owner未执行的部分时，状态记NOT_RUN，已验证子范围单列；不将其计入全阶段PASS。

| ID | 目标、方法与输入 | 预期 | 实际与证据 | 状态 / 剩余项 |
|---|---|---|---|---|
| A-01 | 新旧合同fixture、非法点/区间/引用/标签；原有平台API回归 | 严格拒绝无效对象，旧Event/API兼容 | 全后端748 PASS/8 skip；75训练合同包含继承/显式同主体重复拒绝；旧合同不改结构 | PASS（工程） |
| A-02 | 真实b210原片经可信目录登记；Edge播放、seek及源PTS步进；越界/未登记/身份变化负例测试 | SHA/来源/PTS/用途可核，原片只读，未授权文件不暴露 | 实际231500744B SHA校验；32651帧PTS；1280×720视频从62.020715s播放到82.249111s；seek62000ms、下一源PTS62040ms；catalog/API安全回归通过 | PASS；浏览器呈现不宣称逐帧精确 |
| A-03 | 浏览器创建2人物、回合、死球、2触球、动作；保存/重载/修改；第二写者制造CAS冲突 | 常规标注无手写JSON、时间不漂移、历史保留、409不覆盖 | bundle1→2；另一写者同内容保存到3；旧页面409且草稿仍可见；新页重载3后编辑保存4，动作record1→2/previous1，原时间不变；4版历史和截图可查 | PASS（私有浏览器工程）；确认框后该标签页自动化失去响应，已用新页恢复，见下文 |
| A-04 | 同一动作保存手法/步法unknown、双方图像点位、源证据；浏览器下载完整审阅JSON | 多标签独立、来源/可见性/词表保留，粗类不映射确认细类，图像坐标不称米制 | 下载516452B，与冻结服务端JSON逐字段一致；两unknown理由、两image_normalized点位、agent来源、visibility=unknown、词表1.0.0完整保留 | PASS（保存/导出工程）；不等于专家标签 |
| A-05 | 正负/未审核/同源关系合同与API夹具；真实Agent快照后修改、重启、再下载 | 内容冻结、拆分无同源泄漏、Agent不入human truth、阻塞可读 | 真实快照project4/bundle2/hash不变，当前project6/bundle4；0 eligible/2 excluded/trainable=false；缺人审/分组原因中文显示；正式训练下载409。human正向只在合成合同/API夹具中验证 | PASS（工程门禁）；真实数据可训练性仍BLOCKED |
| A-08 | 真实原始training资产的制作导入、候选、Timeline、render和研究预览负例；旧正常API回归 | 各入口拒绝，旧功能兼容 | 2026-10-02重跑16/16 PASS（14 API+2worker），adapter执行/媒体打开均0；真实原始资产和metadata alias，不是实际转码衍生视频 | NOT_RUN（整项）；已测平台原始来源隔离子范围PASS，真实衍生物与主线旧制作链由04/root补齐 |
| A-09 | 工作台“框架手册”入口→7页手册，搜“触球”；缺HTML和Windows junction负例 | 应用入口可读，缺失如实，固定目录不逃逸 | 浏览器打开 `/guide/` 并搜到3章节；受控路由/缺HTML503/三层实际junction拒绝回归PASS；复用主任务生成HTML | NOT_RUN（整项）；平台入口子范围PASS，完整构建/离线/手机宽度由root验收 |
| A-10 | 私有18082停止并以最新后端重启，API逐字段比对及浏览器重载 | 项目、标注、历史、快照持久且无生产污染 | project/bundle/revisions/snapshot完全一致；各表行数不变；Edge显示project6/bundle4/record2及原快照，console error空 | NOT_RUN（整项）；私有持久化子范围PASS，main完整链与旧数据由root验收 |
| A-06 / A-07 | 模型消费和四种mark范围策略 | 对应模块真实验收 | 本模块未运行，交由03/04 | NOT_RUN（本报告范围） |

## 真实原片与标注内容

目录：`D:/video/data/training/handoff/annotation-catalog.v1.json`（10资产）；原片只读，不复制到worktree或平台目录。登记来源与许可随资产及快照保留；仅研究用途，不据此授予公开商用权限。

- asset_id：`asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913`；SHA为去掉 `asset-` 的内容。
- 相对路径：`data/training/fine-badminton-2026-zenodo-20292976-v1.0/extracted/876ddac3abe9141b8ce7f2fe.mp4`。
- 231500744B，1306040ms，1280×720；PTS索引32651行，time_base=1/12800，SHA `b18a822e0c66dd7aa810b0d1c5684e1e9c923e2d0982ea7f520341798a2b10b9`。
- project：`training-project-f0b6dbcbd6e74c98865eefc991a5b808`，名称“真实训练视频流程验证 · Agent 2026-10-02”。两人物近端/远端匿名球员，identity_status=unknown。
- 演示回合 `[60000,70000)`，独立dead_ball=70000；contact=62000/67000，分别关联两人物；stroke动作 `[62000,63000)`。这些是流程测试锚点，未人工核对真实回合/触球边界。
- 同一动作的 `stroke.net.zhan_cuo` 和 `footwork.start.backward_small_hop` 都为unknown，分别保留理由。不能将前者视为确认展搓，或将后者unknown当阴性。
- 本人图像点 `(0.549687,0.590172)`、对手 `(0.499552,0.423058)`，source=agent，取自62000ms浏览器画面；无米制场地标定，不表示精确落点或专家身份。
- 词表冻结1.0.0：193节点/156可选标签/37目录，完整models原词表与hash放入provenance，当前定义均待专家审核。

## 快照、导出与重启证据

快照 `training-snapshot-ed4c98ec1bdd4beb9baa7e9caffed83e`；冻结project revision4/bundle2，5记录，2判断排除，0训练判断。canonical内容hash：

`62ad9a1c5b5be7a269ddc206d183a6e474c6a7dfc59835eb12271454d6167378`

浏览器点击“完整审阅JSON”的实际下载复制存档到 `D:/video/platform/training-20261002/browser-downloaded-audit.json`，516452B，文件SHA `2ae99ed4587ed71e7c2c202074c5ebcaceeb88fc1e1e02972241563825b76904`。文件排版hash与canonical内容hash是不同口径。下载与API对象相等；canonical hash独立重算相等。

同目录其余证据：

- `conflict-before.json`：制造409之前的bundle2/冻结快照。
- `before-final-restart.json`：project6/bundle4、4版历史、冻结快照、数据库计数和浏览器观察。
- `final-validation.json`：重启后逐字段相等、训练下载409、截图hash、浏览器重载结果。
- `browser-ui-evidence/training-conflict-20261002.jpg`、`training-guide-20261002.jpg`、`training-workspace-20261002.jpg`：真实浏览器截图。
- `capacity-final.json`、`budget.json`、`services.json`：容量与运行信息。

重启前后训练表：projects1、assets1、registrations1、bundles1、revisions4、snapshots1。私有生产objects/assets/source_identities/events/event_revisions均0。这个计数只证明私有库隔离，不代替main旧数据保留检查。

真实制作隔离证据另在 `D:/video/platform/research-20260929/r04b-real-negative-20261002-training-workspace/evidence.json`。完整10资产清单被验证；逐入口使用同一b210资产，不声称10原片全重新hash/decode。历史候选/Timeline行是私有模拟fixture，未绕过生产导入。

证据文件SHA256：`final-validation.json` 为 `0220870a66e321e433e021ede7113860019cee5823e97f3bd5f9ea0b70cfe00f`；上述隔离 `evidence.json` 为 `76dc313b045fefb00cf72ec5971dbd2ad97fd4dcd5edcdc0a85505d8f4b004c0`。

## 执行检查、失败与范围限制

```powershell
& 'D:/video/runtime/platform/env/Scripts/python.exe' -m pytest tests/contracts tests/platform -q --disable-warnings
& 'C:/Program Files/nodejs/node.exe' --preserve-symlinks --preserve-symlinks-main --test tests/platform/training_ui.test.cjs
```

完整后端：748 passed / 8 skipped / 701 warnings / 81.84s，包含最终主体规范化、训练API门禁和审查边界修复。8条件skip不是PASS。补充真实Windows junction三层回归已运行，不能将所有Windows用例笼统说成跳过。最终4258f16新前端18/18 PASS；JS语法及git diff检查通过。未为静态中文提示重复跑整个后端。15:54UTC服务启动源码146f598，后续来源及标签折叠补丁仅静态JS/CSS，无需重复后端重启。

10-03凌晨按主任务请求缩短标签栏：短名称/判断/未知理由默认可见，完整定义/证据/易混项原文收进逐项“定义与判断依据”。真实Edge验证两个说明默认open=false，展开后原文完整；搜索仅存在于长说明中的 `in-to-out` 仍命中“展搓”；unknown理由位于折叠项之外。来源修复同时实际显示agent/local-agent、审核仍待审，console error空。最终证据 `final-ui-validation.json` SHA `86b3d82141cfbcdd290f9649be29c171fbbac23a496f719ef20a73b26a3b4dfd`；截图/DOM `browser-ui-evidence/training-workspace-final-20261003.jpg` 与同名 `.dom.txt`。

浏览器409验证后，点击放弃演示草稿并重载出现浏览器自动化 `Emulation.setFocusEmulationEnabled` 超时；确认框已关闭，但原tab仍不响应。新建同一Edge的新tab成功，服务器revision3未变；在新页重载并修订到4完成验收。未观察到服务端数据丢失，未将自动化失败隐去。保留冲突截图；没有将“旧标签页原地恢复”记成成功。

审核清除后当前记录仍保留revision_audit编辑来源；来源展示与human审核分开。普通浏览器seek和图像点击不声明精确源帧/真实场地坐标。没有真实human标签、已确认独立比赛组或专家定义，因此细标签正式训练仍BLOCKED。A-06/07及完整A-08/09/10由对应owner/root补齐；本报告不升级S0–S5或CTX模型质量阶段。

## 容量

写入前预检：platform199224674B/60GB，runtime/platform1048360620B/10GB，D盘余量922590031872B；本轮峰值预留2,000,000,000B，源码文档<50MB。

2026-10-02 15:57:19 UTC测量：私有目录3608984B（写容量报告前）；platform204512596B/60GB、runtime/platform1048360620B/10GB，二者reserved=0，D盘余量922446884864B。预留 `reservation-4eccf44d71254c9695d3acc167f1d7fd` 已释放。真实负例脚本自身16MB预留亦已释放。无原片副本、视频导出、新权重或新环境；此为平台范围测量，不冒充所有模块700GB总验收。

最终UI证据另预留16MB（`reservation-d21c7af4eae14c85b3af609253fa909a`）后写入并释放。16:07:48UTC最终测量：私有目录3816827B（写容量报告前）、platform204739901B/60GB、runtime/platform1048360620B/10GB、D余量922181832704B，reserved均0；见 `capacity-ui-final.json`。此前快照与截图证据均保留。
