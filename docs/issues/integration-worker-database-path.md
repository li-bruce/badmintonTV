# 主协调验收脚本误用业务库路径

日期：2026-09-29。状态：脚本已修复，真实后续流程 PASS。

root 的临时 `.runtime/verify-main-round.py` 首次把 `--db` 写成 `D:/video/platform/platform.sqlite3`。该文件是业务库；API 的真实队列始终在同目录 `runtime.sqlite3`。worker 初始化了自身所需的空表后退出0，没有领取任务；API 新预览 `job-93c4658e2a0644a5b74903568465d3b5` 仍 queued/attempt0，所以验收断言失败。

修正为 `runtime.sqlite3` 后执行原 queued 任务，预览成功；再完成研究渲染 `job-8a03b4ab5ff94074ac94bb84021088d9`。两任务7份真实产物大小/SHA、Range206与原帧分页均通过。没有新建重复预览，没有运行GPU，也没有修改既有素材/事件。业务库新增空表不删除，避免未经备份进行额外结构清理；生产启动脚本 `start-worker.ps1` 从始至终使用正确路径。

复现入口：`start-worker.ps1`；结果回执 `.runtime/root-main-round-flow.json`。本问题属于本机验收脚本配置错误，不把“worker进程退出0”当作任务成功。
