# 项目状态

更新：2026-09-28。

- 已读取共享对话与简版计划，确认四任务划分，并完成初始架构、合同、资源预算与验收文档。
- 已确认本机RTX 5090、WSL Ubuntu2 GPU可见、D:\video初始为空。
- 尚未完成业务实现、下载、Conda安装、训练或MP4交付；不得从计划推断已完成。
- 已建立Git main，设计基线提交 `a7b8e00`；四个额外任务均已启动，并回报设计和开发进展。

| 任务 | 模块 | 任务ID | 状态 |
|---|---|---|---|
| 01 Python业务底座与完整工作流 | platform | 01a0e88b-2410-7da0-970e-7f4187ed485f | 已写模块设计，开发合同/队列/标注适配与页面 |
| 02 比赛素材与训练资料库 | library | 01a0e88b-31fa-7fd3-939c-b7e0c895deef | 已写模块设计，核验来源与开发受限下载器 |
| 03 WSL模型基线、训练与评测 | models | 01a0e88b-416f-7ca2-bfec-c09ec1462866 | 已找到WSL已有Miniforge，检查兼容与设计实验 |
| 04 竖屏集锦与完整视频渲染 | render | 01a0e88b-5005-7991-9fb0-d2dec3af8b4f | 开发CPU渲染协议与受控工具链 |

工作树：`C:/Users/USER/.codex/worktrees/6991/badmintonTV`（platform）、`9163/badmintonTV`（library）、`c5b1/badmintonTV`（models）、`3e52/badmintonTV`（render）。分支分别为work/platform、work/library、work/models、work/render。主工作区保持main。

协调修订：控制面首轮Windows原生Python+SQLite；模型在WSL通过JSON接口执行；CLI统一顶层Asset数组、相对output_dir、attempt_id、固定退出码；worker中断记failed/WORKER_INTERRUPTED。各任务已通知，细节见最新ARCHITECTURE/CONTRACTS。

模块持续报告：`docs/status/platform.md`、`library.md`、`models.md`、`render.md`。
