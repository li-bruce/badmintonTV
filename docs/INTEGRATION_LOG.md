# 集成记录

## 2026-09-28：统一合同与首条真实研究样片

- platform合同原提交：`6a3e3deb4ff34bf4eb22f18d20e995f9e8d28e1d`；main集成提交：`8900958`。
- 主协调独立执行 `D:/video/runtime/platform/env/Scripts/python.exe -m pytest -q tests/contracts/test_contracts.py`，64 passed。包含源时间、路径和junction、attempt/退出码、修订与结构验证。
- 在main中的统一合同代码上读取 `D:/video/data/handoff/assets.v1.json`，4条真实Asset通过。
- 使用JobRequest/JobResult与validate_job_result校验真实render handoff，通过；request/result对应相同job与attempt，返回状态succeeded。
- 首条真实研究样片：`D:/video/render/jobs/real-research-cddceec7d5/attempt-01/export.mp4`，17.066667秒、1080×1920、512帧、H264/AAC、1,010,245 bytes。
- 主协调核对全部4项产物（MP4、时间线、源时间映射、QA）的文件大小与SHA-256均匹配；读取QA技术检查均通过；抽帧联系图可见完整球场、两侧球员和可读状态文字。未把抽帧检查当全程人工观看或细动作确认。
- 成片只读消费3段原视频，含一段0.75倍慢放；research_preview=true，人工确认与细手法仍未完成。它是流程研究样片，不是已验证展搓/收搓专题。

待修复：交叉代码审查复现了confirmed事件来自model时可被后续model/rule修订覆盖的缺口。已交platform添加基于可信修改者来源的保护和回归测试，修复须独立提交并再集成。现有64项通过不能替代此新增场景。

整体验收仍待平台工作流实际导入→标注→检索→选片→调用render；首条样片来自模块CLI，不宣称Web闭环已完成。
