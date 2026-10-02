# 训练工作台设计与冻结断言（2026-10-02）

基线 main `3dab169`；分支 `codex/platform-training-workspace`。本轮范围来自 `IMPLEMENTATION_ROUND_2026-10-02.md`，不改变既有 S0–S5 的专家真值门槛。

## 数据流与边界

服务端固定可信目录 → 后台串行校验原片 SHA256、真实 PTS 与身份 → 独立 training_assets → 项目内每原片的标注 bundle → CAS 历史 → 不可变 snapshot。媒体只读，使用已验证文件句柄提供 Range；不接受用户路径或 allow_training。生产 Store、候选、Timeline、render 原门禁保留。

训练使用独立 training_* 表；人、点、区间和引用在整个 bundle 内原子校验。回合终点必须由独立 dead_ball 点描述。源时间为整数毫秒；普通播放器定位和 ±40ms 时间步进不声称帧精确，真实 PTS 可另外核对。

审核身份由服务端 `BTV_TRAINING_ACTOR_TYPE` 决定，缺省 agent。仅管理员明确以 human 模式启动才开放人工确认；请求体不能升级身份。Agent 演示保存为待审核。快照包含实际项目、词表、资产和标注版本，默认训练视图仅包含符合合同的人工确认判断；审计视图保留全部未知及排除原因。项目 split 不修改资料库 registry。

界面为独立 `/training`，中文选择器完成项目、目录、人物、回合、触球、区间、多标签、状态及导出。保存失败、并发冲突、未保存切换和输入框快捷键均明确处理。`/guide` 固定读取主任务生成的 docs/site/index.html，缺失时显示未生成，不任意暴露工作树文件。

## 验收断言（开发前冻结）

| ID | 输入与验证方法 | 必须得到 | 初始状态 |
|---|---|---|---|
| A-01 | 新旧 fixtures、非法时间/标签/引用 | 新合同严格拒绝错误，旧 Event/API 兼容 | NOT_RUN |
| A-02 | 真实目录一条视频登记、播放、seek；根外和未登记负例 | 实际 SHA/PTS/来源可核，不复制原片 | NOT_RUN |
| A-03 | 浏览器回合、两触球、动作、保存/重载/修改；CAS 请求 | 中文操作、源时间不漂移、历史保存、409 不覆盖 | NOT_RUN |
| A-04 | 手法/步法多标签、unknown、双方图像状态保存导出 | 字段与来源独立，图像坐标不变米制，粗类不变细类 | NOT_RUN |
| A-05 | 审核和未审核 fixture、同源分组、快照再读 | 冻结实际内容/hash，隔离 agent，拒绝泄漏，显示原因 | NOT_RUN |
| A-08 | 真实训练源及派生到旧制作入口；旧素材回归 | 包括研究预览全部拒绝，旧正常工作流兼容 | NOT_RUN |
| A-09 | 受控 `/guide`、缺失 HTML | 导航明显，缺失如实；完整手册由主任务验收 | NOT_RUN |
| A-10 | 私有 18082 重启后重载 | 项目/标注/快照持久；主线完整用例由主任务验收 | NOT_RUN |

测试夹具与 Agent 浏览器操作仅证明工程流程，不证明羽毛球标签真值或模型准确率。A-06、A-07 分属 models/render；阶段总表由主任务维护。

## 环境与资源

复用 D:/video/runtime/platform/env 的 Python，CPU；不安装依赖、不启动 GPU、不触碰 18080/生产库。私有目录拟 `D:/video/platform/training-20261002`、端口 18082。写入前检查实际目录与物理余量并使用统一 CapacityLedger；本轮峰值上限 2GB，代码/文档 <50MB。原片不复制，媒体不入 Git。

实现分工：contracts 子代理仅合同；runtime 子代理仅可信目录 helper；labelstudio 子代理仅训练前端；本任务整合 Store/API、受控手册路由、测试与真实浏览器。所有 stage/commit 串行由本任务执行。
