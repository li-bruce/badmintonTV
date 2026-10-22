# 从 GitHub 接手完整项目

仓库：https://github.com/li-bruce/badmintonTV 。这是同一产品的完整源码仓库；模块按设备选择环境，不需要在标注电脑安装训练框架。

## 1. 获取源码和 Git 记录

```sh
git clone https://github.com/li-bruce/badmintonTV.git
cd badmintonTV
git switch main
git log --graph --oneline --all
git switch -c codex/your-next-task
```

普通 clone 会取得远程分支记录；不使用浅克隆才能保留完整可达历史。`main` 是集成版本，其他 `codex/*`、`work/*` 分支是各模块的历史工作点，可能落后于主线，也可能有尚未集成的探索，不应全部重新合并。新任务默认从最新 main 开始，沿用旧任务时先看与 main 的差异。

2026-10-22 首次发布针对历史个人路径、私人邮箱、原始共享对话链接做了脱敏。保留提交顺序、父子关系、时间、说明与项目分支；因此 GitHub SHA 与原设备上的旧 SHA 不相同。公开作者邮箱使用 GitHub noreply 地址。`docs/history/published-commit-map.json` 保存旧 SHA → 公开 SHA 对照，以便解释旧实验报告中的版本号；这不表示旧实验在新设备重新运行过。

原设备未经脱敏的仓库与 Git bundle 只作本地备份，不能直接推送或上传。后续开发从这个 GitHub 仓库克隆，基于公开历史提交；不要把旧仓库的原始分支重新推入远程。

## 2. 文档从哪里读

| 要了解什么 | 文件 |
|---|---|
| 产品目标、当前范围 | `PROJECT_PLAN_SIMPLE.md`、`docs/PRODUCT_CONTEXT.md` |
| 架构、接口、执行顺序 | `docs/ARCHITECTURE.md`、`docs/CONTRACTS.md`、`docs/EXECUTION_PLAN.md` |
| 模块输入输出、CPU/GPU分工 | `docs/MODULES_AND_DEVICES.md`、`deployment/modules.json` |
| 环境安装、运行和诊断 | `docs/deployment/README.md`、`docs/models/DEVICE_SETUP.md` |
| 数据库、媒体和设备迁移 | `docs/MIGRATION_GUIDE.md` |
| 已达标、未测与阻塞 | `docs/STAGE_ACCEPTANCE.md`、`docs/ROUND_VALIDATION_2026-10-19.md`、`docs/status/` |
| 给领域用户的操作指南 | `docs/FRAMEWORK_GUIDE.md`；启动后 `/guide/` |

## 3. 会话迁移交接

源码仓库保存任务状态、接口、决策、实验与验收结果，不保存私人完整聊天记录、原对话访问链接或本机 Codex 配置。换设备后新建对话，使用下面的交接内容即可继续；不依赖原设备的会话 ID。

> 这是 badmintonTV 项目。先读 AGENTS.md 和其中要求的计划、架构、合同、验收、模块及迁移文档，再读 docs/status 中对应模块的状态。以当前 GitHub main 为基线，本次只推进【模块/目标】，输入是【清单或快照及其版本】，输出应为【可验证产物】。先列固定验收 ID、输入、预期输出和达标条件，再实施。每阶段写真实 PASS/FAIL/BLOCKED/NOT_RUN 和证据。只修改自己模块，用独立分支/worktree；主任务负责集成。不要自动下载大模型、复制旧环境、公开服务或覆盖原片。训练资料不得转入制作素材库。模型未知/未安装必须如实报告。API Key 和本机路径配置只在目标设备保存，不进入 Git。

原四个任务的后续入口：

| 模块 | 读取状态 | 下一步建议 |
|---|---|---|
| 01 平台 | `docs/status/platform.md` | 在目标 CPU 设备复验播放、拖标签、圈选、保存/重载、快照；再完善业务流程 |
| 02 资料 | `docs/status/library.md` | 维护来源与许可、Asset/PTS 清单、训练与制作隔离；不重复下载已有资产 |
| 03 模型 | `docs/status/models.md` | 先补真实人审标签和比赛分组；从 CPU 准备开始，再决定 GPU 实验和训练器 |
| 04 渲染 | `docs/status/render.md` | 用有制作权限的原片和 Timeline 验证竖屏输出、声音及源时间映射 |
| 集成/部署 | `docs/status/integration.md` | 维护共享合同、设备 profile、跨模块验收与主线合并 |

## 4. 在目标设备部署

先安装 Python 3.11+，创建目标数据根目录，再查看部署计划。例如下方 D:/video 只是 Windows 示例，可替换为本机目录；Linux 使用本机绝对路径。不要把源码仓库当成数据根目录。

```sh
python scripts/deploy/manage.py profiles
python scripts/deploy/manage.py plan --profile workbench-cpu --storage-root D:/video
python scripts/deploy/manage.py setup --profile workbench-cpu --storage-root D:/video --dry-run
```

按[部署说明](deployment/README.md)安装后执行 doctor，再启动工作台。播放/标注选 workbench-cpu，资料选 library-cpu，剪辑选 render-cpu，普通完整桌面选 desktop-cpu。模型准备和 GPU 使用各自隔离环境；不复制旧 venv，不修改全局驱动。

仓库中的默认路径、环境版本和旧实验参数用于理解/复现。个人用户名已使用 USER 占位；不要直接执行含占位路径的历史命令。新的安装以参数化部署入口为准。旧 Windows→WSL 模型桥仍限制 D:/video；换盘的独立模型 CLI 与网页自动调度要分别验收。

## 5. 哪些东西需要另行迁移

Git 中只有源码、通用配置/例子、词表、依赖版本、测试夹具、文档及少量文本验证报告。报告中的媒体路径、hash、公开数据源 URL 只是引用，原视频和训练标注库不在仓库内。

视频、音频、权重、真实项目数据库、训练快照、下载缓存、虚拟环境、API Key、cookies、登录凭据与私人设备配置另行保存在受控本地位置。通过 manifest 的 asset_id、相对路径和 hash 迁移需要的数据；SQLite 用一致性备份，不能同步运行中的 WAL。总体 700 十进制 GB 限额不会因换设备重新计算。

不要在问题单、提交说明或日志中粘贴真实 Key。若需要通用配置模板，只提交空值或示例变量名；目标设备的实际配置放 `.env`、`*.local.json` 等忽略位置，API Key 由环境变量提供。`.gitignore` 只是第一道防护，推送前还须检查暂存区和本次可达历史。

## 6. 当前可用性

截至 2026-10-19，工作台标注、模块源码打包、轻量环境安装、真实视频异路径迁移和重新校验已有证据；当轮回归为 1838 PASS、27 条件 SKIP。此次仓库发布不把旧结果改称新设备实测。

细手法/步法/技战术统一训练器、合格专家真值和正式精度评测仍未完成。新 GPU 环境、物理新设备、跨盘网页模型桥分别保持原 NOT_RUN/BLOCKED，见对应状态与问题记录。下一步优先在目标设备用少量真实输入复验，再推进标注和训练。
