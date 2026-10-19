# 模块迁移实现与验收

日期：2026-10-19。基线：main 321a30d。部署工具仅使用 Python 标准库。检索属于工作台内部能力，不伪装为独立服务。

## 开发前固定断言

| ID | 目标要求 | 验证输入与方法 | 预期结果 | 当前状态 |
|---|---|---|---|---|
| P-04 | core/library/workbench/models/render/full 源码包依赖闭合，含接口、环境定义、开发说明和源码哈希 | 干净 Git 构建、解包、校验清单和导入；坏路径、链接、凭据、媒体、输出冲突负例 | CPU 包不包含训练依赖；拒绝不安全输入和覆盖；独立包可继续开发 | NOT_RUN |
| P-05 | 任意工作目录可规划、建立隔离 CPU 环境、启动或诊断；GPU 安装由专用脚本负责 | dry-run 命令、轻环境隔离烟测、参数化路径、CPU 依赖和导入检查 | 无硬编码用户名/盘符，CPU 无 torch；缺少 FFmpeg 明确提示，未安装不冒充通过 | NOT_RUN |
| P-06 | 源码与数据迁移区分；状态导出用 SQLite backup API，媒体只输出引用 | 活跃 WAL 小夹具备份、完整性校验、asset_id/路径/hash 清单；冲突/越界测试 | 不直接复制 WAL、不复制媒体、不覆盖输出；备份可读，数据仍须另行同步 | NOT_RUN |

## 交付边界

- deployment/modules.json 声明模块、依赖、设备档位；scripts/deploy/manage.py 提供 profiles / plan / setup / doctor / run / export / export-state。
- ZIP 只取 Git 已跟踪允许路径；默认拒绝脏树。显式允许脏树只用于试包，清单标注未提交状态。
- ZIP 不含数据库、媒体、权重、环境、凭据或 .git。完整 Git 历史由主任务最后另建 bundle。
- 源码发行包支持解压开发，不是预装离线软件。初次 pip 安装需要联网，FFmpeg 需另行预装。
- 新设备从定义重建环境，不复制 venv；原片按清单单独同步；运行中 SQLite 不能直接文件同步。

## 进度

设计已记录；实现/运行待进行。Windows，现有轻量 Python，CPU，无端口，不下载训练数据或运行 GPU。下一步：实现工具、测试负例与解包烟测。提交 SHA：本文件所在提交。


## 子任务实际验证（2026-10-19）

- 24 项标准库 unittest 全部 PASS，0 跳过。覆盖依赖闭合、任意工作目录、CPU 不导入 torch、安装 dry-run 不写磁盘、路径穿越、输出 junction、Git symlink、凭据/媒体禁入、覆盖与脏树拒绝、ZIP 篡改、活跃 WAL 备份、队列/GPU 租约拒绝与备份副本清理。
- 基于干净提交 0ffe641 真正导出 6 份 ZIP，合计 6,043,840 bytes，全部 verify 通过并在 D 盘独立目录解包。core 等共享包可导入；library/render 的 CLI --help 可执行；workbench/full 的真实路由 /training、/guide/、/static/training.js 在解包根通过 TestClient 返回 200。
- P-04：PASS（子任务源码包范围）；最终合并代码还须主任务重新打包核验。P-05：局部 PASS（计划、任意 cwd、隔离源码烟测），新 venv 实际 pip 安装 NOT_RUN，留给主任务在最终源码执行。P-06：PASS（活跃 WAL 小夹具、路径/容量/并发版本检查代码与源库不变；实际跨物理设备恢复 NOT_RUN）。不把旧环境 smoke 当成新设备安装成功。
- 机器摘要：VALIDATION_2026-10-19.json。测试包目录：D:/video/platform/distributions/deployment-subtask-0ffe641，由主任务已协调 500 MB platform 预留覆盖，源码 ZIP 约 6 MB，连同解包/小 DB 低于 40 MB；没有复制媒体或源业务数据库。
- 首轮测试发现并修复：路径返回处误插入解析器代码、SQLite backup 连接未显式关闭、合法 .gitattributes 白名单缺失；Windows 默认文本编码造成 README GBK，已转为 UTF-8 并扫描全部新增文本。共享 CapacityLedger 的 SQLite 构造连接由 GC 最后释放，测试在清理临时目录前显式 gc.collect；未改 runtime 模块。
- 后续边界：GPU/模型安装由 models 任务验证；Linux/macOS 本机安装、真实素材编码、跨物理设备恢复尚未执行。源码分发与工程测试不提升模型识别能力或人工真值状态。
- 代码提交：84ee9d6（实现），1fc23b0（Git 属性），0ffe641（UTF-8）；本记录所在后续提交补充结果和配置检查。

迁移补验：发现 runtime_metadata.business_database 含旧绝对路径会阻止新目录启动，已在 quiesced 备份副本中移除绑定；新设备首次 API 启动重新绑定，源库不改。新增异路径恢复断言，最终测试数 25 PASS。模型/工具路径及复制后原片身份须在目标设备重新配置/校验。
