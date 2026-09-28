# 集成记录

## 2026-09-29：主分支交付检查点

以下为最终检查点；后文保留各阶段原始记录，其中“待修复/待集成”描述的是当时状态。

- 四任务全部源码与审查修复已合入 main。library ZIP 压缩格式白名单修复 `18de8a6`；platform 初版 `0263c48`、业务修复 `3569096`、LS 不可变快照修复 `b89fbf4`；models 实验交付 `1df5f14` 与环境预检修复 `15b909b`；platform 最终运行边界修复 `69b3e17`。root 启动/统一检查脚本提交 `a851dcb`。
- 独立 reviewer 已复核：大文件导入、全局检索排序、LS 重导入/CAS/旧快照隔离、完整时间线审核来源、容量扫描与 SQLite 写锁解耦、owner 物理路径检查、等待锁后重新读时间、WSL 子进程停止确认和 orphan 状态、GPU 租约释放、环境安装前容量检查。对应回归通过；未把测试数量当模型质量。
- root 在 main 运行 `scripts/integration/check-all.ps1`，478 passed、5 skipped，exit 0。条件跳过及分模块数量见 `INTEGRATION_VALIDATION.json`；另核验五条真实 Asset/PTS/哈希、六份模型清单及五份真实 JobResult。
- 数据和环境容量快照 18,311,292,486 bytes；`D:/video` 由有界 GNU du 完整核算成功，原生 Conda base/cache 使用此前未改变的快照。root 慢速 Python 扫描在核实本任务 PID 后停止，不计为成功；源码测试目录 ACL 限制未通过修改权限绕过。详见 `INTEGRATION_CAPACITY.json`。
- platform 确认 GPU 与任务空闲后停止其旧 API/worker，保留 Label Studio。root 从 main 于北京时间 00:23 启动 API 与 worker，源码版本 `a851dcbb239f8789e1566aea8031c2ee277692ae`，本地收据 `.runtime/main-services.json`。同一业务数据库继续使用，后续文档提交不改变运行代码。
- root 浏览器在 main 提交规则任务 `job-b7e1f50b1fd247449e9a34ff67a0f0bf` 与渲染任务 `job-e0ddb7aa02ec46c4874131b2ced7b372`，均 attempt-1 succeeded。请求/结果合同、全部六项 artifact 大小/SHA、QuerySpec、Timeline 与九项视频技术 QA 通过，HTTP Range 返回 206/1024 bytes；浏览器实际播放至末尾，无媒体错误。
- 新成片 `D:/video/render/jobs/job-e0ddb7aa02ec46c4874131b2ced7b372/attempt-1/export.mp4`，14.833333 秒、445 帧、1080×1920、938,753 bytes，SHA `8fb63e7587494f7d679db9f331966e06c711a9229b04fe109fe5f65d76dbf8ae`。与先前研究样片视频字节相同，但本次由 main 新任务产生并记录源映射/审核来源。agent 审核、research_preview=true、人类确认 false。
- 平台工作树此前真实 GPU 任务 `job-3dc9ece15e914eecb9616ac306ece6b8` 的两项产物与 compute_stopped=true 已由 root 核验。main 合入最终代码但没有重复 GPU 实验。models 已明确停止独立实验且不自动恢复；主分支网页试用窗口限姿态、有效至北京时间 01:28:37，授予后 HTTP 账本确认无租约，不自动提交任务。
- 细手法模型、稳定跟踪和可靠本地 LLM 解析仍未验收；分别有独立问题/实验记录。现有下载为四段 FBBench 小样与一段大学社团双打，不是完整职业比赛资料库。第一版交付不宣称完整训练目标已达到。

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

models提交611eb39及修复00de444已集成。零字节partial续传、unknown match进入formal评测两项均修复，并将资源锁竞争映射为OWNER_BUSY blocked/exit2。独立复核通过，主协调Windows复跑100项98通过/2项符号链接权限跳过，模块WSL100全过；合并后catalog/fixtures/4真实Asset/QuerySpec互验通过。模型依赖与真实GPU推理仍在进行，不能将标准库测试当推理效果。

整体验收仍待平台工作流实际导入→标注→检索→选片→调用render；首条样片来自模块CLI，不宣称Web闭环已完成。

平台工作树已报告完成第一条真实Web闭环：浏览器保存区间→编辑QuerySpec→检索3候选→以agent来源选片→中文标题/0.75倍速→后台worker导出。job=`job-3ebf04b748644087b1328283382df830`，attempt-1；输出 `D:/video/render/jobs/job-3ebf04b748644087b1328283382df830/attempt-1/export.mp4`，14.833333秒、445帧、1080×1920、938,753 bytes；SHA-256 `8fb63e7587494f7d679db9f331966e06c711a9229b04fe109fe5f65d76dbf8ae`。主协调已读取QA并重算视频hash，技术项通过，human_confirmed_segments=false且research_preview=true。平台源码尚待提交与main独立验证，不能因此宣布正式模型/人工技法验收完成。

## 2026-09-28：render源码集成审查

候选提交 `9762e90`（状态补充`16a903a`）。主协调独立48单元测试：47通过、1Windows symlink权限跳过。最新真实handoff `D:/video/render/handoff/real-research-e071063a44` 的request/result、内部与输出Timeline、22条JSONL进度均通过当前main合同，全部4产物大小/hash核验通过。新版MP4与已查看版本hash一致。

只读代码审查另发现3项已有快测未覆盖的边界，暂缓合入并交render独立修复：

1. research_preview合并不同审核状态的重叠段会把未审核扩展区间提升为human confirmed。
2. 物理空闲空间条件额外完整预留其他owner的610GB，重复预留已占用空间，合法大量数据时提前失败。
3. preview实际360×640被写入工程Timeline，但再次导入只接受1080×1920，工程无法重用。

platform可继续使用默认不合并的真实片段做联调；工程正式规格应独立于预览实际编码规格。已通知两任务，不把模块技术测试通过等同于源码所有边界通过。

## 2026-09-29：渲染修复集成与平台交叉审查

- render 原提交 9762e90 + 16a903a + 6bff133 + e06ce8b 已依次合入 main（8742d3e、62f8be8、50f5ecd、4ba01a0）。三项审查问题均由独立 reviewer 复核通过。root 复跑修复后 62 测试：61 通过、1 Windows symlink 权限跳过。
- 双打 Asset、原片 SHA 和 132 条单调 PTS 已在 main 合同上核验。doubles-preview-c47d5492 的 JobRequest/Result、全部产物大小/hash、导出 Timeline 通过。实际 360×640 预览与正式 1080×1920 工程规格分离；不声称人工技法确认。
- platform 候选提交 356b98f 的业务测试由 root 独立运行：72 passed、1 skipped。交叉审查发现六项边界需修复：probe 大文件应用异步返回处理、渲染人工审核来源、LS 二次编辑 CAS、检索先截断后排序、同库容量扫描阻塞心跳、写路径 junction 跨 owner。修复与新增 WSL GPU 桥接分别验收。
- library 追加候选 0cc1214 + 21114ec：root 75/75 unittest 通过。独立 reviewer 用纯内存反例发现 BZIP2/LZMA 解压内部无输出长度限制；已请求白名单 STORED/DEFLATED，修复前不合入新增 ZIP 工具。真实双打数据可继续只读消费。
- root 在另一 worktree 用 pytest 自动发现测试时遇到目录 ACL，改为模块现有 unittest 从该 worktree 执行后 75/75 通过；未修改系统权限。第一次双打验证脚本误用了合同参数名 exit_code，改为实际签名 returncode 后通过，此为验证脚本调用错误，不是产品缺陷。
