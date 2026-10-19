# 页面简化验收记录（2026-10-19）

范围：用户使用的标注和制作页面。基线为321a30d；功能提交cd4e354，首屏密度修复ba7dbc7。没有改动数据合同或后端审核规则。

| 用例 | 要求与方法 | 实际结果 | 状态 |
|---|---|---|---|
| P-01 页面结构 | 打开标注、数据集、设置、帮助；保存常驻，基础信息可手填，技术详情可展开 | 模板实现118个唯一ID；两个页面标签闭合正确；挂载测试能切换视图且不改草稿 | 工程子项PASS，真实布局由主任务复验 |
| P-01 720px首屏 | 1280×720实际窗口，无需放大窗口即可看到标签与常用时间线 | 主任务首次看到长视频卡片占高、标签只露一行；ba7dbc7限制标题2行、卡片列表128px、单视频时收起搜索，圈选移到时间线后的折叠入口 | 修复后真实复验NOT_RUN |
| P-01 窄屏 | 390px页面不横向溢出；各入口可达 | 已编写响应式布局，尚未由本模块执行浏览器测试 | NOT_RUN |
| P-02 数据和操作 | 标签投放、人物维度、区间移动/边界、圈选、保存与冲突不退化 | 109项前端回归通过；后续密度补丁相关64项通过 | 逻辑回归PASS；真实鼠标操作由主任务验收 |
| P-02 保存与隔离 | 标注/圈选保存重载，409保留草稿，非人工不能确认，训练素材不能进入制作 | 69项平台API与安全边界测试通过，无跳过 | API子项PASS |
| P-02 视图切换 | 数据集/设置/帮助切换不丢未保存内容；隐藏播放器不响应标注快捷键；查标签不自动加标签 | 新增挂载断言通过；来源保存在修改详情，下载准入仍受质量审核限制 | PASS |

上述P-01/P-02总体状态由主任务结合真实浏览器记录决定。单元测试不代表真人标注效率、标注正确率或模型质量。

## 页面操作变化

- 标注：选项目、选视频、左侧拖标签；右侧只显示当前主体已添加的标签。搜索或“全部标签”仍可选择其它标签。
- 人物：点击左侧“人物设置”或顶部“设置”，手填姓名和队伍；顶部“保存”保存当前视频全部修改。
- 圈选：时间线下展开“画面圈选”，使用矩形或多边形。位置仍只对应当前一帧。
- 数据集：顶部“数据集”进入比赛分组和导出版本。完整标注可下载；训练文件仍需先通过审核。
- 帮助：快捷键、精确定位说明和完整手册入口集中在帮助中。修订和来源仍在详情中可查。
- 制作：首页提供标注、素材、检索和剪辑入口。技术JSON、定位信息和性能检查按需展开。

## 实际命令

Windows工作树：C:/Users/USER/.codex/worktrees/6991/badmintonTV。复用独立Python环境和Node，不安装新库。

```powershell
node --test tests/platform/training_ui.test.cjs tests/platform/training_interactions.test.cjs tests/platform/training_timeline.test.cjs tests/platform/training_regions.test.cjs tests/platform/preview_ui.test.cjs

D:/video/runtime/platform/env/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp .runtime/pytest-plain-20261019-b tests/platform/test_training_api.py tests/platform/test_training_regions_api.py tests/platform/test_training_review_boundaries.py tests/platform/test_production_usage.py tests/platform/test_render_options.py
```

109前端PASS/0 SKIP；69后端PASS/0 SKIP，24.38秒。后端有已有FastAPI/httpx弃用警告。首屏补丁后相关三份前端64 PASS；这些重跑数字不累加为新用例数量。

首次Python测试未开始业务断言：旧系统pytest临时目录拒绝访问，指定独立目录并创建父目录后恢复。首次前端旧文字断言及新测试选中记录夹具已修正。没有重置用户数据、降低安全门槛或伪造人工审核。

本模块没有启动服务，没有接触18080人工库、GPU、原始视频、权重或D盘长期数据。仅在工作树.runtime生成小型测试夹具。主任务使用18086隔离Agent库执行真实交互。