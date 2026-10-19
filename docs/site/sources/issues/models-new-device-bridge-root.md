# 新盘模型环境尚不能直接接入网页作业队列

发现日期：2026-10-19。状态：BLOCKED（新存储根的 Windows → WSL 网页队列）；原设备 `D:/video` 流程不因此停用。

新模型部署入口及独立 CLI 接受 `storage-root` 参数，可在新盘保持相同相对路径读取原片、快照和权重。现有 `packages/runtime/wsl_bridge.py` 仍把 Windows 交换目录固定在 `D:/video`，把 Linux 环境及缓存固定在 `/mnt/d/video`，两者范围不同。

只读复现：`validate_env_prefix('/mnt/d/video/runtime/models/envs/models-gpu')` 通过；`validate_env_prefix('/mnt/e/badminton-data/runtime/models/envs/gpu-base')` 返回 `ValueError: env-prefix must be under /mnt/d/video/runtime/models/`。因此注册模型卡或换一条新环境启动命令不能完成跨盘重新集成。

本轮没有改平台桥接代码，也没有运行新根的网页 GPU 作业。临时路径是：工作台导出快照 → 新计算设备运行独立模型 CLI → 通过 `models/handoff` 交回有来源与哈希的结果。

关闭条件：由平台模块参数化 Windows/Linux 存储根和交换文件映射，保留路径隔离与 attempt 校验；在新根实际验证一项作业的启动、进度、产物校验、取消/中断和 GPU 租约释放，再登记受控命令。源码包与环境安装成功不能替代这次跨模块验收。
