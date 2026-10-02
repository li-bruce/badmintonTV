# 2026-10-03 拖拽与圈选：开发前断言

续分支 `codex/platform-training-workspace`，起点44bd583。已只读主任务工作树实施轮第7节A-11～A-14；本文件在新增交互代码前冻结范围。主线18080供人工使用，本轮只写agent模式18082。

## 接口与数据流

仍为同一训练项目与原子bundle保存/CAS。原生拖放的标签ID只能来自项目冻结词表的可选叶节点；拖到已有记录追加待审判断，拖到源时间位置生成适合标签kind的记录。角色/人物从明确选择器读取，多维判断按label/role/解析人物去重；项目、人物与队伍继续手动填写。拖放不是审核或自动识别。

时间线模块独立于核心controller；Pointer拖动只显示预览，pointerup由controller对克隆记录做范围/回合/死球/区域锚点检查后原子应用。Escape/pointercancel和非法修改不改变数据；已关联子记录不会被回合边界裁掉，区域原片时刻不会随拖动悄悄改写。全片/当前回合/缩放保持原片毫秒。表单与键盘仍可操作。

圈选模块在实际video画面上加SVG，扣除contain黑边。矩形两对角点，多边形3–64顶点；绘制、移动、顶点调整均有取消，结束才提交。区域只绑定单一原片时刻，不做跟踪或自动场地标定。

兼容扩展仅在已有 `record.evidence` 中使用 `type=image_region`：schema_version=1.0、evidence_id、record_id、asset_id、at_ms、coordinate_system=image_normalized、shape=rectangle/polygon、points=[{x,y}]、subject_role、subject_person_id、observation_source、precision=browser_time。后端严格校验但保留原字典，不添加默认字段，不修改旧证据。point区域等于record.at_ms；interval区域位于[start,end)，且小于媒体duration。非human会话不能新增或篡改human区域；已有未改区域可保留。图形修改会失效旧审核。

## 固定验收断言

| ID | 方法/输入 | 预期 | 初始状态 |
|---|---|---|---|
| A-11 | 真实视频拖标签到时间位置/已有记录；拖区间/左右边界；取消/非法范围；保存重载和CAS | 源时间正确、无静默越界或历史覆盖，真实Pointer/拖放成功 | NOT_RUN |
| A-12 | 全156叶标签/8域/37分组；多轴/角色投放和重复；点击/键盘回退 | 分组不落库、多轴独立、同主体去重、基础信息手填，始终待审 | NOT_RUN |
| A-13 | 实际视频矩形/多边形、移动/调点/删除/取消，含画面缩放和黑边，保存重载 | 坐标/主体/原时刻正确、非法拒绝、不伪称场地或帧精确、不跟踪 | NOT_RUN |
| A-14 | 旧实际web快照与新区域bundle/snapshot；新旧合同/API测试；他模块消费 | 旧hash不变、区域证据保真、agent不能升级human、训练隔离不放宽 | NOT_RUN |

旧实际快照只读：`D:/video/platform/integration-20261002/snapshot-before-restart.json`，预期canonical SHA `d2deb51291cbb8ad5ac100e7a95d60afb6670e8c3762f05304daee77410a67dd`。A-14的03/04消费整项由对应模块/root补验，不能只凭本模块测试标整项PASS。

## 分工与资源

contracts代理负责区域证据合同；labelstudio代理负责独立时间线JS/CSS/测试；runtime代理负责独立圈选JS/CSS/测试；本任务负责标签拖放、controller原子变更、HTML集成、API测试及真实CUA。共享文件只由本任务编辑，所有stage/commit串行。

复用现有Python/Node/Edge，不安装库、不用GPU、不复制原片。源码/文档<50MB；私有数据新增峰值沿用2GB上限，在D盘写入前重新检查与预留。真实演示仍agent/unknown，不是专家真值。技能复用此前已读取的computer-use，用途为本机浏览器真实拖动与圈选。
