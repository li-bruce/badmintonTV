# 合同包实施说明

日期：2026-09-28；源合同：`docs/CONTRACTS.md` v1.0。

## 设计与边界

`packages.contracts` 是纯 Pydantic v2 数据边界，不引入媒体、训练或数据库依赖。所有顶层交换对象固定 `schema_version="1.0"`，拒绝拼错的未声明字段；`probe`、`provenance` 等明确扩展容器保留 JSON 扩展。时间采用严格非负整数毫秒，禁止布尔值、浮点数和字符串被悄悄转换成时间。未知标签保留 `null`/`unknown`，不转换为阴性，也不从粗球种推导细手法。

数据流：JSON/JSONL → Pydantic 字段与对象校验 → 明确的跨对象校验 → 平台事务。Pydantic schema 可给其他进程用于结构检查；区间相互关系、资产时长、match split、符号链接和修订竞争仍须执行 Python 校验/服务端事务，不能声称 JSON Schema 单独覆盖所有语义。

提供 Asset/AssetManifest、Event/EventManifest（EventCollection 别名）、QuerySpec、Candidate、ModelManifest、Artifact、Timeline、JobRequest/JobResult/ProgressEvent。补充嵌套类型与安全路径、跨对象时长、事件修订辅助函数。相对路径只能是规范 POSIX 路径；实际读取时解析根目录并拒绝根外符号链接。CLI 输出目录还需调用受控 owner 根目录校验；数据 schema 不能替代管理员注册执行入口。

修订：Event 中 `revision` 从 1 开始；后续人工修订通过 `validate_event_revision` 核对 expected_revision、前一版本、稳定 ID、审阅者与时间，并拒绝模型覆盖已确认人工版本。HTTP 409 与数据库 compare-and-swap 由平台负责。

兼容扩展：Event 增加可选 `reviewer`、`reviewed_at`、`previous_revision`；Timeline crop 增加归一化窗口 `{x,y,width,height}`；不改原合同已有字段语义。

## 验证计划

合同 round-trip/schema 导出；非法路径（绝对、反斜杠、穿越、Windows ADS/设备名）、根外链接；空/反向/越界区间；unknown/null 保留；身份/回合未知不被补齐；修订冲突/覆盖；QuerySpec 缺失步骤和无效关系；模型未就绪原因；执行结果失败码、进度范围与有限数；Timeline crop 和源片边界。

## 实现与验证结果

已实现全套公开类型、12 份可重新生成的 JSON Schema、13 份 canonical JSON/JSONL fixtures（`packages/contracts/fixtures/`），以及 CLI schema 导出。按照主协调 main `40541d6` 的合同修订，request/result 的 `attempt_id` 必填；assets 仅顶层数组；output_dir 是共享根下 owner 子目录的 POSIX 相对路径。`validate_job_result` 同时验证 job、attempt 与退出码（0/1/2/130）。

环境：`D:/video/runtime/platform/env/Scripts/python.exe`，Pydantic 2.13.5。命令：`python -m pytest tests/contracts -q`。合同测试覆盖实际 Windows 根外 junction 解析，初次 symbolic link 权限不足的跳过已替换为无提权 junction 测试；不留下此项空白。JSON Schema 导出命令：`python -m packages.contracts --output packages/contracts/schemas`。

canonical render request 含 2 个非空已确认的 synthetic 结构片段；所有 fixture 都明确不是已存在媒体/产物。附加 `python -m packages.contracts.fixtures.generate_media` 可用已安装 FFmpeg/ffprobe 生成有真实哈希和探测信息的 4 秒 CPU 合成源片、实例化 render request；该命令依赖平台 runtime 容量账本，在纯合同阶段未执行，不计作真实视频验收。

最新结果：**64 passed，0 skipped（0.33s）**。合同测试只用明确标记的结构夹具，不能当真实视频或模型成绩。

参考：Pydantic 官方 [validators](https://docs.pydantic.dev/latest/concepts/validators/) 与 [JSON Schema](https://docs.pydantic.dev/latest/concepts/json_schema/)，2026-09-28 核验。没有安装额外插件或训练依赖。
