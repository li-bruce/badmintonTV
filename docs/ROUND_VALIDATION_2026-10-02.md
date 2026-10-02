# 训练标注工作台实施轮：验收记录

日期：2026-10-02至03。计划基线main `3dab169`，拖拽/圈选增补基线`c7e68ce`。本页按实际证据更新，工程通过不代表模型准确率通过。

## 当前进度

01–04实现及拖拽/圈选已集成，A-01至A-14本轮工程断言全部PASS。主任务完成真实网页操作、重启及WSL数据准备，人工入口已更新。没有新增专家动作真值，原模型精度与人类验收状态保留；这不是整个产品的识别能力达标。

| 用例 | 当前实际结果 | 状态 | 下一步 |
|---|---|---|---|
| A-01 训练合同 | 主线75训练合同通过；规范化主体判重修复已集成，旧合同兼容由01全量覆盖 | PASS（基础合同） | 新区域证据另验A-14 |
| A-02 真实训练目录与媒体 | 10视频hash/PTS/11sidecar校验；b210原片浏览器播放、源时间定位、Range206、未知路径拒绝 | PASS | 原片不复制 |
| A-03 标记、保存与修订 | main真实网页6条记录，四次bundle修订；实际409草稿保留，显式重载后成功保存 | PASS（原表单交互） | 新拖放另验A-11 |
| A-04 多标签与态势 | 手法/步法3判断，unknown与unobservable保留；2匿名人物、本人图像点/对手缺失原因分别保留 | PASS（工程保真） | 无人工技法结论 |
| A-05 不可变数据集快照 | main快照固定bundle2；后续bundle4及重启后原内容/hash不变，agent默认训练视图为0，正式下载409 | PASS | 专家定义/人审/独立比赛组仍缺 |
| A-06 模型侧数据准备 | 同一真实网页快照WSL/CPU两次真实源帧解码，readiness字节相同，无GPU/模型训练 | PASS（数据准备） | trainable=false是如实结果 |
| A-07 触球驱动范围 | 04真实PTS/网页快照7窗口通过；审查4反例修复并独立复验，root main CLI真实源10逻辑窗口通过 | PASS（逻辑范围） | 不代表触球或技法真值 |
| A-08 制作用途隔离回归 | root实际训练导入/媒体拒绝，旧6素材保留；01真实16入口、04 render18负例；主线全量回归及新ROI派生范围拒绝通过 | PASS | training_only不可制作 |
| A-09 MD转Web手册 | 7页重建；搜索/窄屏导航/构建边界通过，18080入口打开，拖拽与圈选步骤已加入 | PASS | 后续随Markdown重建 |
| A-10 主线闭环与重启 | main project/bundle4/历史1–4/旧快照重启逐字段不变，已恢复人工服务 | PASS（基础链） | 新增交互另验，不把本项当整轮达标 |
| A-11 时间线拖放 | 两个独立浏览器实际拖新标签/已有块、左右边界和整段平移；越界拒绝、保存重载、实际CAS409保留草稿通过 | PASS | 半途捕获取消由事件测试覆盖；Edge恢复限制另记 |
| A-12 多维标签拖放 | 156叶/8域/37目录检查；真实手法/步法/球路叠加，本人和对手分别绑定、重复去重；基础人物手填，全部待审 | PASS | 不是逐个手工拖156次，也不是156类识别通过 |
| A-13 画面圈选 | 真实矩形/多边形、移动/调点、黑边拒绝、Escape取消、临时区域删除、保存重载保真 | PASS | 单帧图像区域，不是自动轨迹或米制位置 |
| A-14 区域兼容链 | 旧hash不变；新网页2区域经模型审计/render/WSL真实12帧准备原字段不变；0人工真值、用途隔离保持 | PASS | 无训练/GPU/模型精度结论 |

## 证据规则

2026-10-03用户新增拖拽标签与画面圈选要求，实施前已在[实施计划](IMPLEMENTATION_ROUND_2026-10-02.md)第7节登记A-11至A-14；初始均NOT_RUN，须另做真实浏览器验收。原表将在最终集成后汇总已有证据与新增项。

后续每项写清代码SHA、输入资产/快照、运行命令、预期与实测、产物路径及未通过原因。agent标记只验证软件流程，不成为人类动作真值。专家可判性和模型准确率仍见[长期阶段表](STAGE_ACCEPTANCE.md)及[能力方案](END_TO_END_CAPABILITY_PLAN.md)。

## A-09 手册先行验证

2026-10-02，主任务在临时本机静态服务 `127.0.0.1:18089` 实际打开网页；本轮最终入口将由平台 `/guide/` 提供。

- 7页、38份引用Markdown，首次构建约0.62MB；本地链接检查无缺失。构建命令见[构建说明](DOCS_BUILD.md)。
- 实际浏览器搜索“触球mark”只显示命中章节；清空恢复全文。390×844视口下页面无整页横溢出，文档菜单可展开、Esc收起；已恢复桌面视口。浏览器没有console error。
- 独立临时fixture实测：重复构建全部hash一致；缺失引用时旧网页不变；撤下引用后旧source消失但原Markdown保留；源文件经junction指向docs外以及输出本身为junction均拒绝并保留原内容。6项PASS。没有模拟操作系统rename故障，不能宣称此项实测通过。
- 被验构建脚本SHA-256：`329ef1fda9c2ebe469e1dfb9e67c732ecd67bc29a8b8b2f1dfa79025420f5634`；Node 24.19.0、Marked17.0.5，未新增安装。
- 当时截图保存在本机Codex可视化目录 `C:/Users/USER/.codex/visualizations/2026/09/28/01a0e880-e2f7-7e93-b05e-9fb28548aca0/framework-guide.jpg`，未把媒体加入Git。当时整体NOT_RUN；最终已挂载18080 `/guide/`并重建核验，临时18089已关闭。
- 最终版7页/41份Markdown源，主线浏览器实际读到新增“拖拽与圈选的具体操作”，搜索“拖拽”显示2个章节，清空恢复；console error为0。新版页和源副本均由同一构建生成。

## 真实主线链证据

2026-10-02晚至03凌晨，main `ebc7e7f`时运行的agent实例完成以下实际浏览器操作，随后仅重启本任务自建服务为human，未改记录审核来源。测试工程名为“主线工程验收示例（Agent，非人工真值）”。原片为可信目录中b210源，1280×720、32651源帧、1306.04秒；目录标题的4K50FPS是原发布名称，不当作实际视频参数。

- 先建2匿名人物，保存60–70秒回合、70秒死球、63/65秒两触球、62.5–64秒动作、62–64秒步法。3标签判断全部unknown/unobservable；本人点坐标为工程点击，不是精确人工位置。
- API旧版本保存409且内容不变；浏览器出现冲突提示并保留本地草稿，显式重载后新修改成功，最终bundle4、历史1/2/3/4。`snapshot-cfac...`固定bundle2不变；训练视图0，正式下载409，审计可读。
- 原片Range0–255返回206/256B；未登记训练媒体404、制作媒体访问训练源404、制作导入训练manifest400。原6条制作Asset及普通媒体Range206保持可用。
- 重启自建API后项目、bundle4与旧快照逐字段相等。主线恢复human供用户使用；之后root不再向human实例写测试标注。

证据摘要：[API/持久性](experiments/integration-training-api-20261002.json)、[训练目录](experiments/integration-annotation-catalog-20261002.json)、[WSL重复解码](experiments/integration-training-wsl-20261002.json)。完整标注/快照仅存D:/video/platform/integration-20261002，不进入Git。

WSL两次使用annotation-env CPU准备2个窗口，各6张真实源帧RGB摘要；readiness均85912B，SHA `4bc67db3fe78e5b21019039be497a4931a2b05644f7b5fb79617a20175460b5d`。`trainable=false`、strict_judgements=0、GPU/model/training=false。原快照内容SHA `d2deb51291cbb8ad5ac100e7a95d60afb6670e8c3762f05304daee77410a67dd`；原片只读，输出在models/handoff/root-annotation-20261002/prepare-01与02。

模型/资料/平台/渲染模块自己的详细用例和环境见各handoff。新增环境仅模型标注小依赖约35MB，无新增视频下载；700GB总上限不变。

## A-07 审查修复与主线CLI

四项独立审查反例由04以badbc3c修复，main集成为9e75f16：晚发球/重叠包络不能称完整回合；相互矛盾的证据时间拒绝；后加入的未归属触球纳入未来时间上界；冻结快照的PTS引用必须与实际clock绑定。独立review逐一复现后复验通过，保留原失败记录于[问题单](issues/render-contact-window-review-p2.md)。

root从main独立shell运行`python -B -m packages.render.contact_windows --request configs/render/contact-windows.example.json --storage-root D:/video`，exit0；真实b210源身份与完整PTS校验后得到10个逻辑窗口（球路/手法/步法各3、回合1；7 ready/3 candidate），规则1.0.1，全部training_only。只读源片、无媒体产物/GPU；marks为工程fixture，不称专家真值。[CLI证据摘要](experiments/integration-contact-cli-20261003.json)。

## A-11至A-14：拖拽与区域的实际主线证据

合同a0fc1db→f1fc63e，交互c97f39f→d4685c6，快速拖入已有窄块修复8ba5cc2→eb5d34e。首次实际快速拖放失败的记录保留；修复后根和01均以真实原生拖动复验，重复投放提示“不重复添加”。平台详细输入、CAS、角色和边界见[平台交互验收](platform/TRAINING_INTERACTION_VALIDATION.md)。

主任务另开独立agent 18084，复用真实b210视频，手填2匿名人物/队伍，保存4记录。将展搓拖入空时间线，加入步法与直线球路，判断均unknown。拖终点至63623、起点至61531，再整体平移，最终区间为[62051,64143)毫秒；保存及重载仍为相同时间、3标签。01另验证对手角色和超回合拒绝；取消/失去捕获/过期上下文由事件回归断言，不称全部为真实半途手势实测。

63秒触球上实际画矩形与多边形，分别移动、缩放和调整顶点；黑边拖画被拒绝，未结束多边形Escape取消。临时第3矩形删除后原2区域保留，最后bundle4。区域全部agent/browser_time，归一图像坐标，0人审真值。重载后可继续选中编辑。[主线UI及API保真证据](experiments/integration-interaction-ui-20261003.json)。

快照`training-snapshot-9871c8dfb23945eba72a1621e0ecb043`固定bundle2，后续bundle4未改变其完整JSON或内容SHA `a0b463fb924597dfa8ee4f9958fa6a830ef9a43683dc5fb92738292aa5b6c23c`。模型audit、render原记录及WSL审计中的2个区域逐字段相等。原片231500744B全hash及32651行PTS再次核验；WSL PyAV15 CPU对冻结动作段与触球上下文各真实解码6帧，输出RGB摘要而非图片。readiness SHA `2b4665cbbc3b67f7ca7b6913ecdb7edbb56f61408c30facc08b7d87ceefd6209`；trainable=false、review_only=true、0strict/0human。原片、research_preview及派生范围均被制作guard拒绝。[下游真实证据](experiments/integration-interaction-downstream-20261003.json)。冻结动作段仍为旧61921–62921，不能与在线新时间混淆。

## 最终回归、部署与限制

- main d4685c6完整执行`./scripts/integration/check-all.ps1`：1782 PASS/23 SKIP。快速投放修复eb5d34e后时间线增加2项，重跑20时间线与7交互全部通过；去重后最终1784 PASS/23 SKIP。模块unittest与pytest计数口径不同，不把子用例和重复运行相加。10训练原片、11sidecar、980703PTS及原制作/模型产物核查通过。[机器回归](experiments/integration-cpu-20261003.json)。
- 23项为既有opt-in媒体/WSL、系统链接权限、轻环境缺NumPy等条件跳过；不是通过，也不承担本轮新增实际交互断言。FastAPI既有弃用warning未隐藏。一次root汇总脚本错误要求每条待审record都有reviewer_type=agent；实际改动会正确清空旧审核，actor仍为agent，已改为检查编辑来源与pending/非human，未改产品规则。
- 01的Edge确认框造成自动化连接超时，恢复与该tab最终截图仍未完成；服务端CAS已保持原数据。主线独立IAB已完成保存重载和截图，工程功能断言不依赖该连接恢复。触屏/更多浏览器、自动轨迹、球场标定、人类标注速度提升幅度尚未验收。
- 01:17北京时间，核对自建PID后把18080升级至eb5d34e/human，旧项目、bundle4、快照和6制作素材逐字不变；无GPU/worker。[重启证据](experiments/integration-interaction-restart-20261003.json)。启动：`./start-platform.ps1 -TrainingReviewer human`，Windows隔离Python在`D:/video/runtime/platform/env`。用户入口为`http://127.0.0.1:18080/training`，手册`http://127.0.0.1:18080/guide/`。
- 根18084和临时手册18089已关闭，agent数据库与原始证据保留在`D:/video/platform/integration-interactions-20261003`，约1.40MB；100MB峰值预留已释放，D盘剩余约920.49GB。预检owner已测总量（含当时预留）约45.88GB，不将D盘空闲量当700GB预算。没有新视频下载、模型训练或全局安装。[清理回执](experiments/integration-interaction-cleanup-20261003.json)。
- 实际工作台截图：`C:/Users/USER/.codex/visualizations/2026/09/28/01a0e880-e2f7-7e93-b05e-9fb28548aca0/training-drag-regions.jpg`，工程示例不是专家标注结果，未加入Git。

本轮工程阶段达标；专家定义、正式独立比赛分组、人工确认标签和识别精度仍缺，长期S0–S5/CTX的未达标状态不变。
