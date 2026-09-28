# Windows配额扫描遇WSL环境链接

日期：2026-09-28。首次真实采集在预留阶段失败，未开始视频写入。

命令：`python -m scripts.library.acquire_small_sample --download-only`。

原因：严格扫描整个 `D:/video` 时，Windows `os.walk` 无法访问其他owner模型环境的 `D:/video/runtime/models/env/lib/terminfo`（WinError 1920，WSL链接）。这是跨系统目录可见性问题，不能据此认定共享环境损坏，也不能删除这些链接。

修复策略：library自己的data树仍严格统计、不跟随链接；其他已分配owner若扫描不可得，则按该owner完整固定额度计入保守总量，并在capacity报告写明估计模式。data300GB+其他固定配额350GB≤650GB，继续保留50GB不可借用余量。无法识别的目录不静默忽略。实际磁盘free仍检查。Windows与WSL不能共享写入本library SQLite账本。

验证状态：已修复并重跑真实采集成功，4视频+原标注/许可共10文件均完成，4视频全解码成功；采集结束data实占3,746,937 bytes，runtime用70,000,000,000 bytes完整上界替代，不与已知runtime子文件重复计数。capacity报告明确 `opaque_project_owners=["runtime"]`。配额20测试中包括4进程争抢、owner上界、未知目录和自身data不可读时拒绝；19通过，1真实symlink创建因权限跳过。
