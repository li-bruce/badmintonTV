# Platform 初版设计

日期：2026-09-28；合同 v1.0；控制面 Windows 本地 127.0.0.1:18080，Label Studio 127.0.0.1:18081。GPU 不占用。

## 数据流和边界

只读引用共享根 D:/video 下 manifest 资产，后台 probe/hash/缩略图 → Asset 入库 → 手工 Event 修订 → QuerySpec 规则查询 → 带源证据的候选 → 明确确认 → 可编辑 Timeline → render CLI。模型入口由管理员环境配置固定注册，缺失直接 blocked/not_installed。UI 不加载 torch，不执行编码。

跨模块统一类型位于 packages/contracts，Pydantic v2 输出 JSON Schema。模块调用统一 run --request --result，stdout JSONL 进度，结果和退出码均须验证。render/models 未合入时保留固定入口配置与真实 unavailable。

## 持久表和修订

SQLite 采用原生 Windows 数据目录 D:/video/platform/platform.sqlite3，不由 WSL 同时操作。libraries(id,name)，assets(id,sha256 UNIQUE,library_id,body)，players(id,body)，events(id,asset_id,revision,body)，event_revisions(event_id,revision,body,reviewer,created_at)，queries(id,body)，candidates(id,body)，timelines(id,body)，settings(key,body)。运行时 job/job_logs/reservations 使用独立 runtime.sqlite3，同平台独占写入；独立 worker 写队列，不写业务表，平台在结果同步时验证导入。

修改标注必须 expected_revision 并事务 compare-and-swap；模型预测不能覆盖 confirmed 人工标注。Asset 去重按 sha256 且 match split 不得矛盾。毫秒区间须在 Asset duration 内。受控媒体接口只从 asset_id 解析相对路径，禁止穿越和根外符号链接。

## API 和页面

/api/v1: libraries、assets/import、assets/import-path、assets/{id}/media、players、events、events/import/export、queries/parse/search、candidates/{id}/confirm、timelines、timelines/{id}/render、models、jobs、settings/llm、annotation/label-studio。页面导航：工作流 / 素材与标注 / 检索 / 时间线 / 模型与任务 / 设置。服务端模板配少量原生 JS，无前端构建。

检索按原片时间关系，不要求相邻数据行。same_player/same_rally 对未知身份不认作已满足；未知标签保留不确定，默认只搜索 confirmed 事件。中文规则解析只映射明确词汇；未识别文本要求编辑 QuerySpec，不泛化成命中所有。

## 队列协议

Queue(db_path): enqueue(operation, payload, idempotency_key=None, max_attempts=3)，get/list/logs，claim(worker_id,lease_seconds)，heartbeat，append_log，finish，request_cancel，retry，recover_expired。queued → running → succeeded/failed/blocked/cancelled；cancel_requested 仅为请求。租约过期记 interrupted 后 failed，必须显式 retry，避免重复外部效果。CPU 单 worker；模型 GPU 仍由 models 排期。进度不捏造总量。

worker 使用固定 operation handler；probe/hash/thumbnail 与 render/model 子进程属于 worker；取消只终止本任务子进程。容量预留按 owner 和峰值，platform 60GB、runtime/platform 10GB；已有文件不删除。

## 标注工具与 LLM

Label Studio 需官方 TimelineLabels + VideoRectangle 实测，保留 task/annotation/version 原始导出、PTS 帧索引；不依赖 frame/fps 简单换算。无真实安装时明确 integration_unverified。内置标注作为人工闭环保证。

LLM 只存 endpoint/model/timeout/key_env，页面只回 masked/present；密钥不进 DB/日志。请求只发查询文字和 schema。输出校验后可编辑；无 LLM 使用规则解析。

## 验证和交接

API/合同、修订409、重启持久化、租约/取消/重试、路径与密钥、同球员同回合对手插拍、unknown 语义。真实视频 API+浏览器闭环单列；外部 LS 安装与 render 到位后接通，否则独立 issue 写明。阶段提交与运行环境记录在 docs/status/platform.md。
