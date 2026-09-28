# 集成记录

## 2026-09-28：统一合同与首条真实研究样片

- platform合同原提交：`6a3e3deb4ff34bf4eb22f18d20e995f9e8d28e1d`；main集成提交：`8900958`。
- 主协调独立执行 `D:/video/runtime/platform/env/Scripts/python.exe -m pytest -q tests/contracts/test_contracts.py`，64 passed。包含源时间、路径和junction、attempt/退出码、修订与结构验证。
- 在main中的统一合同代码上读取 `D:/video/data/handoff/assets.v1.json`，4条真实Asset通过。
- 使用JobRequest/JobResult与validate_job_result校验真实render handoff，通过；request/result对应相同job与attempt，返回状态succeeded。
- 首条真实研究样片：`D:/video/render/jobs/real-research-cddceec7d5/attempt-01/export.mp4`，17.066667秒、1080×1920、512帧、H264/AAC、1,010,245 bytes。
- 主协调核对全部4项产物（MP4、时间线、源时间映射、QA）的文件大小与SHA-256均匹配；读取QA技术检查均通过；抽帧联系图可见完整球场、两侧球员和可读状态文字。未把抽帧检查当全程人工观看或细动作确认。
- 成片只读消费3段原视频，含一段0.75倍慢放；research_preview=true，人工确认与细手法仍未完成。它是流程研究样片，不是已验证展搓/收搓专题。

已修复：交叉代码审查复现了confirmed事件来自model时可被后续model/rule修订覆盖的缺口。platform提交 `09be6ffc6c7d60a18a3c5d86e687298b1ae35aad`，main集成为 `1da8b7a`。现按确认状态和服务端可信actor保护，默认automatic，人工调用显式提供human及审核信息，保留原始预测来源。交叉复核通过；主协调独立复跑新增回归后的69项合同测试全部通过。

复跑环境记录：默认pytest临时目录出现沙箱/用户账户ACL访问错误；改用主工作区`.runtime/pytest-contracts-<uuid>`并禁用共享pytest cache后通过。没有修改系统临时目录权限或删除其他测试目录。

后续检查点：library提交9a33fe9+cd1ad74，主协调独立53单元测试通过、只读代码审查无阻塞，已集成main `8207a40`+`5c48688`；合并后4条真实Asset/PTS/hash与canonical合同互验通过。已在原任务内继续补充源场映射和双打小样，新增下载预算先限1GB。

models提交611eb39尚待集成。主协调Windows复跑90项，88通过、2项符号链接权限跳过，models报告同一组在WSL90全部通过。独立审查另发现零字节partial续传与unknown match进入formal评测两个场景，已交模型任务修复并补回归。模型依赖与真实GPU推理仍在进行，不能将标准库测试当推理效果。

整体验收仍待平台工作流实际导入→标注→检索→选片→调用render；首条样片来自模块CLI，不宣称Web闭环已完成。

## 2026-09-28：render源码集成审查

候选提交 `9762e90`（状态补充`16a903a`）。主协调独立48单元测试：47通过、1Windows symlink权限跳过。最新真实handoff `D:/video/render/handoff/real-research-e071063a44` 的request/result、内部与输出Timeline、22条JSONL进度均通过当前main合同，全部4产物大小/hash核验通过。新版MP4与已查看版本hash一致。

只读代码审查另发现3项已有快测未覆盖的边界，暂缓合入并交render独立修复：

1. research_preview合并不同审核状态的重叠段会把未审核扩展区间提升为human confirmed。
2. 物理空闲空间条件额外完整预留其他owner的610GB，重复预留已占用空间，合法大量数据时提前失败。
3. preview实际360×640被写入工程Timeline，但再次导入只接受1080×1920，工程无法重用。

platform可继续使用默认不合并的真实片段做联调；工程正式规格应独立于预览实际编码规格。已通知两任务，不把模块技术测试通过等同于源码所有边界通过。
