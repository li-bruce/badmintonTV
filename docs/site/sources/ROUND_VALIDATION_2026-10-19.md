# 页面整理与设备迁移：验证记录

日期：2026-10-19。基线main `321a30d`。断言先登记于[实施计划](IMPLEMENTATION_ROUND_2026-10-19.md)。

| ID | 目标与验证输入/方法 | 预期结果 | 实际结果 | 状态 / 证据 |
|---|---|---|---|---|
| P-01 | 真实训练原片；1280×720浏览器切换四视图 | 常用操作清晰，长说明按需展开，基础信息仍手填 | 标注/数据集/设置/帮助分开；视频、标签、时间线和保存可达；属性默认只显示已加标签 | PASS；[界面设计](platform/PLAIN_WORKBENCH_DESIGN.md)、实际截图回执 |
| P-02 | 实际拖入“并步”、拖动右边界、画矩形/三点多边形、保存重载 | 保留标签/角色/时间/区域；不升级人审 | bundle 6：62051–64616ms，4标签、2新ROI；角色self，来源agent，审核pending；浏览器重载和API逐字段核对通过 | PASS；[机器证据](PORTABILITY_VALIDATION_2026-10-19.json) |
| P-03 | 五模块清单、七环节表；独立包导入与CLI --help | 输入输出、依赖、设备和未实现内容可区分 | core/library/workbench/models/render+完整包；轻入口全部可导入，三个业务CLI可执行；检索未独立、统一trainer缺失明确列出 | PASS；[模块表](MODULES_AND_DEVICES.md)、deployment/modules.json |
| P-04 | 干净提交66aad19导出6包、验hash、解包；Git bundle verify并clone | 依赖闭合、可继续开发、不含环境/媒体/数据库，不覆盖输出 | 六ZIP共6,217,930B；逐包导入无torch；历史恢复HEAD=66aad19；正式交付再从最终文档提交导出并校验 | PASS；D:/video/platform/distributions/20261019-validation/packages.json及历史包 |
| P-05 | 新建workbench-cpu venv实际联网安装；从独立解压包、非仓库cwd启动 | 参数化路径、依赖自洽、无训练框架 | setup成功，pip check无冲突，doctor ready；未安装torch/tensorflow；/training、/guide及资源HTTP200；新数据根运行成功 | PASS；[机器证据](PORTABILITY_VALIDATION_2026-10-19.json)、安装收据 |
| P-06 | SQLite双库备份恢复到新根；复制真实231.5MB原片及索引；浏览器重新校验 | 一致性副本，不覆盖；复制后恢复媒体，标注/快照保真 | 5文件232,832,223B哈希一致、文件身份确实变化；重校验前422，完成后Range206/1024B且画面恢复；bundle逐字段相同，旧snapshot hash保持a0b463…；runtime新路径绑定成功 | PASS；迁移回执与[机器证据](PORTABILITY_VALIDATION_2026-10-19.json) |
| P-07 | 四种模型profile计划/路径测试、WSL语法及23测试、已有CPU真实2帧 | CPU/GPU隔离、缺项真实报告、无自动训练/权重下载 | cpu-prep/gpu-base/gpu-pose-tracknet/gpu-vl分别定义；Windows委托正确转WSL；真实CPU源PTS/RGB哈希通过；新GPU环境未安装且明确不可用 | PASS（部署入口范围）；[模型分项验收](models/DEVICE_SETUP_ACCEPTANCE.md) |
| P-08 | 分支集成；全CPU回归、后续定向检查；9页MD→Web与实际页面 | 有可执行指南和真实验证，不拿未测冒充完成 | 全CPU及新增部署/前端共1838个不同用例PASS、27条件SKIP；本轮新模型测试另在WSL23/23通过；新版API/手册真实可访问 | PASS（本轮工程范围）；下面的命令与限制 |

本轮不测新GPU机器上的训练性能，不把环境脚本可运行当作训练成功。用户工程数据不用于自动化人工确认。

## 运行与证据

- 集成代码验收基线：`66aad19f56123fd33de3cf2493cfb602805fc388`，包含三个工作树提交及迁移审查修复。后续提交只补文档、证据和发布清单；每个最终ZIP的`source-manifest.json`记录精确提交。
- 全CPU：`scripts/integration/check-all.ps1`，合同/平台836 PASS、8 SKIP；library219 PASS；models398 PASS、18 SKIP；render241 PASS、1 SKIP；前端初始109 PASS。重校验补丁后前端112 PASS；部署最终32 PASS。去重合计1838 PASS/27 SKIP，后续19项API/文档定向检查属于已计用例，不重复相加。
- 轻环境：`D:/video/runtime/platform/portable-envs-20261019/workbench-cpu`。由`manage.py setup --profile workbench-cpu --storage-root D:/video --env-root D:/video/runtime/platform/portable-envs-20261019`新建；没有`--system-site-packages`。`btv-deployment.json`记录实际安装命令；pip check和doctor通过。CPU工作台不要求FFmpeg；编码/探测profile才必须配置。
- 独立解包：`D:/video/platform/distributions/20261019-validation/workbench`。新root为`D:/video/platform/portability-20261019/copied-device`，新库位于其platform目录，测试端口18086。从系统临时目录通过`manage.py run --python <新CPU解释器> --storage-root <新根> --reviewer agent`启动。没有worker/GPU。
- 迁移备份：`D:/video/platform/portability-20261019/state-backup`；媒体回执`media-copy-receipt.json`。已有用户主库另存于`D:/video/platform/backups/20261019-before-portable-start`，未用测试标注覆盖用户库。
- 原片/PTS/模型交接：全回归核对4+1真实Asset、6模型manifest/5实际结果、训练目录10原片/11sidecar/980703 PTS；人类真值仍为0。
- 本机日志位于`.runtime/portable-20261019`：full-cpu-regression.log、deployment-regression.log、clean-install-retry.log。源码包不含这些运行日志或数据库，机器摘要已收录本页链接的JSON。
- 构建手册：marked17.0.5，9页及关联Markdown原文。直接访问预构建手册不需要Node；仅重新构建时需要。

## 失败、修复和未测范围

本轮审查中发现并修复：长视频标题挤占标签区；Windows默认编码导致部署文档GBK；FFmpeg环境变量被默认值覆盖；WSL特殊链接使容量扫描失败；迁移队列保留原机绝对路径；精简迁移引用丢失完整用途/来源字段；Windows模型委托路径错误；复制后已登记视频缺少重校验入口。失败未删除，最终均重新检查对应行为。

| 后续目标 | 状态 | 原因和下一步 |
|---|---|---|
| 另一台物理电脑、macOS/原生Linux部署 | NOT_RUN | 本轮是同机新环境、独立源码和异路径真复制演练；拿到目标设备后按doctor及本页用例再验 |
| 新Conda cpu-prep环境实际安装 | NOT_RUN | 独立定义/计划已验；本轮模型CPU帧用现有环境，不能代替新Conda安装 |
| 当前机器再建完整GPU环境 | BLOCKED | 模型runtime固定35GB配额不足以同时保留旧环境并新增18GB峰值；未清理旧文件，见模型问题记录 |
| 新盘模型由Windows网页自动调用 | BLOCKED | 旧WSL桥仍固定D:/video；独立模型CLI可用，接回网页需另改并验证桥，见[问题记录](issues/models-new-device-bridge-root.md) |
| 细技战术训练和正式精度 | BLOCKED | 缺合格真值、专家定义、正式比赛划分及统一trainer；本轮不提高长期产品阶段达标计数 |

以上范围不由1838个工程用例替代。当前可交付的是模块源码、轻工作台、环境定义、迁移工具和继续开发的明确接口。
