# 主线集成状态

2026-10-22：按用户要求发布完整项目至GitHub，同时排除媒体、API Key和本机私有配置。18个分支已推送并从GitHub重新克隆核验，GH-01至GH-05全部PASS，本轮相关回归369 PASS。发布采用隔离脱敏副本，原仓库历史保留本地；正式远程状态与GH-01至GH-05验收见[发布记录](../PUBLICATION_2026-10-22.md)，新会话从[GitHub交接](../GITHUB_HANDOFF.md)继续。不要把原始未脱敏分支直接推入远程。

## 2026-10-19集成结果

设计：先冻结P-01至P-08，再由页面、部署、模型环境三个worktree开发，主任务集成。模块保持一个产品的合同与数据流。

已实现并运行：四视图工作台；五模块与完整源码包；CPU独立环境实际安装；WSL模型分环境计划；SQLite备份与真实异路径恢复；重新校验视频；9页说明书。源码基线66aad19，最终文档提交及发行包的精确SHA见包内source-manifest.json。

验收：P-01–P-08在[本轮明确范围](../ROUND_VALIDATION_2026-10-19.md)PASS；1838 PASS/27条件SKIP。新GPU环境、物理新设备、跨盘Windows网页模型桥、统一trainer和模型精度分别保持NOT_RUN/BLOCKED。

当前环境：主API127.0.0.1:18080/human，新CPU venv为D:/video/runtime/platform/portable-envs-20261019/workbench-cpu；没有worker/GPU。启动参数见[环境交接](../ENVIRONMENT_HANDOFF.md)。独立18086仅用于本轮agent验收，交付后关闭。大文件/测试副本在D:/video内；platform测试/分发预留500MB，CPU安装单独由runtime/platform预留2GB并自动释放。

失败已记录并修复：[迁移问题](../issues/platform-portable-migration.md)。未解决：[跨盘模型桥](../issues/models-new-device-bridge-root.md)、[GPU重建容量](../issues/models-device-rebuild-capacity.md)。下一步：把选定包和所需数据带到实际目标设备，按对应profile复验，再按合格真值推进训练；不自动同步运行中的数据库。
