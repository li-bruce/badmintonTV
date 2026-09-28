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

工具链检查点：render已安装FFmpeg/FFprobe 9.0.2并完成合成技术烟测，主协调验证版本可运行；已向platform/library/models共享只读路径。详见[环境交接](ENVIRONMENT_HANDOFF.md)。

真实素材检查点：`D:/video/data/handoff/assets.v1.json` 已发布4段FineBadmintonBenchmark小样，长度4634/5367/3900/6000ms、1280×720/30fps，保留逐帧PTS；library已完整解码，主协调独立复核文件大小与SHA-256全部匹配。源比赛映射、球员身份与细手法尚未核验，统一split=unassigned，不用于宣称训练/测试独立或细动作准确率。已交给其他三模块开展真实素材联调；端到端业务闭环仍待完成。

渲染检查点：已协调research_preview显式预览参数，允许未确认片段形成带状态标记的本地样片；不等待细标签真值即可验证成片流程。render报告已修复约21.333ms的AAC拼接起点偏移，合成音视频双流起点为0、完整解码通过；真实3片段样片制作中。

首轮集成：contracts、library已合入main，分别69与53测试独立复跑通过。models协议初版与审查修复已合入，Windows100测试98通过/2权限跳过（模块WSL100全过），合同互验通过；真实GPU推理仍待完成。render三项边界修复中，尚未合入。平台工作树已完成真实Web→worker→14.8秒MP4链路，主协调核验QA与视频hash；平台源码待提交并在main复验。所有真实样片都保留agent来源/细技法未知，不称人工真值。细节见[集成记录](INTEGRATION_LOG.md)。

模块持续报告：`docs/status/platform.md`、`library.md`、`models.md`、`render.md`。
