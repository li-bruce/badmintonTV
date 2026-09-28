# 真实双打追加小样

核验日期：2026-09-28。此轮已实际下载、探测和检查画面；来源检索经过及公开目录链见 [DOUBLES_RESEARCH.md](DOUBLES_RESEARCH.md)。本次无需 ZIP，备选包没有下载或解压。

## 可交接资产

- 独立 manifest：`D:/video/data/handoff/assets.doubles.v1.json`，只有 1 个新增 Asset；原 `assets.v1.json` 仍为原四片。
- Asset ID：`asset-52e45b704dc32cb049b879673087e7935e4b4172b43e06f734684de250f0e118`。
- 原片：`data/raw/dronebd/study-bd12-rally1-camera1.mp4`（所有相对路径以 `D:/video` 为根）。
- 来源：[作者仓库固定提交](https://github.com/Ning-D/Drone_BD_ControlArea/tree/14a6a74969f54adb57e013faa4fb24298794e985) → Study_Videos/BD12/Rally-1 → `(1).mp4`；公开 Drive 正常下载，无登录、确认表单或限制绕过。
- 来源文件：视频 5,857,600 bytes、README 3,769 bytes、CSV 28,707 bytes，实际落盘来源共 **5,890,076 bytes**。另有有界网页/JSON 溯源读取；该数不是所有 HTTP 流量统计。新增媒体仅此一段，远低于本轮 1GB 上限。

| 检查 | 实际结果 |
|---|---|
| 大小与本地 SHA-256 | 发布目录大小与实收一致；`52e45b704dc32cb049b879673087e7935e4b4172b43e06f734684de250f0e118`。发布者未提供 SHA，不能声称发布者 SHA 匹配。 |
| 编码、尺寸、时长 | H.264，3840×2160，4404 ms |
| 解码 | FFmpeg 9.0.2，CPU 全视频流解码通过，132 帧 |
| 时间信息 | avg_frame_rate=41100/1367，r_frame_rate=30000/1001，time_base=1/600；保留原有理数，不强行写 30 fps |
| PTS | 132 帧完整 JSONL，3926 bytes；SHA `01260e59618bd9bc996688a6f31dbc37df2aceceb65ef182d72e666bf853cdf4`；间隔20/21 tick，CFR/VFR状态仍 unknown |
| 画面检查 | 已查看 1 秒帧：同场四人、两边各两人，室内高位后场视角。camera_type=rear、discipline=doubles；姓名身份未确认。 |
| 共享合同 | main 的 Pydantic AssetManifest 接受 1 个真实 Asset，原片与 PTS 哈希校验通过 |

完整 probe 在 `data/probes/dronebd-study-bd12-rally1-camera1.probe.json`；PTS 同目录 `.pts.jsonl`；画面检查图在 `data/qa/stills/dronebd-study-bd12-rally1-camera1.jpg`。截图仅供共享盘本地 QA，不纳入 Git 或公开再分发。

作者论文说明大学社团男双自拍数据；此小样**不是职业前十球员或个人基准样本**。`match_id=dronebd-study-recording-bd12` 只是按作者 BD12 文件夹保守合组，完整比赛日期、跨回合边界和整场偏移未确认。`split=unassigned`；同 BD12 的另一个机位或其他回合不得自行分入不同 train/test。

## 配套 CSV：保留原件，未转换 Event

`data/annotations/dronebd/BD12-Rally-1-1.csv`，SHA `2c1919ee1f9f0ac327e7ab802afb1e1dc9c32dfa31c133f9cc17139f32954384`。清单在 `data/handoff/annotations.doubles.v1.json`。

实际为 130 行、44 列，frame 连续2–131，含四人的中心/框顶点、shuttle_x/y 与 status。原始 status 值计数：0=127行、1=2行、2=1行；43行羽球坐标均非负。这里只统计原始值，没有把 status 或非负坐标解释为已验证的击球真值。

README 的数据表明确球员框与羽球标注只列在 Top-View Camera 下；已下载的 `(1).mp4` 是后视画面。同 BD12/Rally-1 目录只能证明关联，不能证明坐标对应本机位或帧号与视频 PTS 的精确关系。故 `alignment_status=unverified`、转换 Event 数为0。缺失/负坐标不是“没有羽球”；网前展搓、收搓、后退小跳启动均维持 unknown。

代码、标注和原视频均未找到独立明确许可，分别保留 unknown，allowed_uses为空。作者采集背景与参与者知情同意不等于向第三方授予再分发或商用许可。

## 原四片保护与容量

追加脚本先后核对原四片 SHA；原 `assets.v1.json` SHA 始终为 `f6a646668ec688ecbbe85386f64db9d81b4c6b951a8284a1a581195cd57563aa`。旧清单、原片、探测文件和旧 handoff 仓库副本不修改；新 JSON 再生成均保存前后 hash 审计。

配额预留50,000,000 bytes覆盖新来源、PTS、截图和元数据；下载流分别受确切文件上限约束。幂等重跑复用三个来源收据，0新增下载，原媒体和 probe 未覆写。最终容量/测试结果见 [VALIDATION_DOUBLES.json](VALIDATION_DOUBLES.json)。共享 runtime 不可遍历部分仍以70GB分配上界记账，并非实际使用70GB。本任务新增runtime为0，无端口、无GPU。

原四片详细追溯见 [PROVENANCE_RESEARCH.md](PROVENANCE_RESEARCH.md)：前三片候选20K `0001.mp4`，第四候选 `0003.mp4`，仍缺少精确 UID→原片/裁切偏移连接，不能写回确定身份或时间。[独立问题单](../issues/library-provenance-mapping-gap.md) 记录补齐证据所需字段。
