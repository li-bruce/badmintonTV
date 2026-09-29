# BFMD 第二训练包：公开来源与枚举证据

核验日期：2026-09-29（Asia/Shanghai）。本轮只读官方页面、GitHub 元数据、Drive 公开目录及少量响应头/确认 HTML；没有下载媒体、大 JSON 正文、作者脚本原件，没有执行 YouTube 脚本或联系作者。机器清单为 `configs/library/bfmd_sources.json`，只含来源元数据。须等前一个完整 ZIP 写者退出，再由主任务执行顺序有界下载。

## 已确认的来源和数量

- [作者仓库](https://github.com/Ning-D/BFMD) 当前提交 `c7c7e8e4c815085dda42746f16e07f1172503312`；GitHub API `license=null`，完整 tree `truncated=false`，未发现 LICENSE/COPYING/NOTICE。
- [作者数据页](https://ning-d.github.io/BFMD-Dataset/) 和 [固定 README](https://raw.githubusercontent.com/Ning-D/BFMD/c7c7e8e4c815085dda42746f16e07f1172503312/README.md) 均链接 [公开 Drive 根目录](https://drive.google.com/drive/folders/1wQr4DpMbx-e8jFnvOH9WUJXxfXgTC1IJ)。以公开 HTML 内嵌目录读取文件 ID、名字、MIME 和字节数，没有使用登录态或非公开 API。
- 根有 5 个源文件/索引/文档，`annotations` 有 10 个叶子目录，每个最多 13 项，无下一层目录。完整遍历这些公开目录后得到 **115 个活动 `.json`、1 个 `.json.bak`、5 个根文件，共 121 项、1,825,439,459 B**。根 `__pycache__` 不是源数据，明确排除且未枚举。
- “116 JSON”须修正为“116 个标注目录文件”：115 个有效 JSON 为 **1,825,349,511 B**；备份 1 个 **32,751 B**；二者合计 **1,825,382,262 B**。备份不能成为额外比赛或训练标注。

| 标注目录 | 公开目录 | 活动 JSON | 备份 | 总字节数（含备份） |
|---|---|---:|---:|---:|
| caption | [Drive](https://drive.google.com/drive/folders/1mEcgbIMbxNNKVYR-hyJZWuRu-yOMd5Lj) | 12 | 0 | 11,173,070 |
| court | [Drive](https://drive.google.com/drive/folders/1fe9YFm6acu0Zj9dj_Hwc7V7x1IHdJDQF) | 12 | 0 | 8,717 |
| court_perframe | [Drive](https://drive.google.com/drive/folders/1pW98_xk6LQsMLnuaq1nXLuQufLxL4wg8) | 12 | 0 | 7,888,324 |
| hit_inferred | [Drive](https://drive.google.com/drive/folders/10lN_p3GP0hfPcMAgpTOqGvjQOvClUPWQ) | 12 | 0 | 1,484,466 |
| hits_doubles | [Drive](https://drive.google.com/drive/folders/1S3qFp2mAn1xl7_hSthXZT3cz-AOdGlE8) | 7 | 0 | 3,474,499 |
| metadata | [Drive](https://drive.google.com/drive/folders/1Bs5AguCVUS1o0I5yZQ_qChZQbLzwUi7V) | 12 | 1 | 343,524 |
| player_bbox | [Drive](https://drive.google.com/drive/folders/1Zr0ZnU8nOyiQ3lj6-S202pVQkjLl9E5M) | 12 | 0 | 111,112,275 |
| pose | [Drive](https://drive.google.com/drive/folders/1S4ahFqbfzn9CHFWwm7-5EZUzKaREavEg) | 12 | 0 | 1,636,679,388 |
| shot_type | [Drive](https://drive.google.com/drive/folders/1X4kO3QP9JUaUAVvaDQHeXNpjYKsg80F9) | 12 | 0 | 10,872,993 |
| shuttle | [Drive](https://drive.google.com/drive/folders/1VHsTrlQ4uDE3KSPTGZnsVCLUUT-DSSOv) | 12 | 0 | 42,345,006 |

备份原名为 `annotations/metadata/YONEX-All-England-Open-2025-Lee-Chia-Hao-TPE-vs.-Alex-Lanier-FRA-SF.json.bak`，Drive ID `1P8bIhWMovwuiK30ega9L_ZNZMMUviEXW`、MIME `application/x-trash`；清单 kind 为 `annotation_backup_archive_only`，只作原件归档。

| 根文件 | 精确字节 | 正常公开下载 URL | 本轮处置 |
|---|---:|---|---|
| Badminton_video_list.csv | 4,514 | [下载入口](https://drive.usercontent.google.com/uc?id=1bG5ZIjfE0CWyAnGqPdpq7u0s8Ygzz7OM&export=download) | 来源索引；不执行其视频下载用途 |
| download_youtube.py | 3,311 | [下载入口](https://drive.usercontent.google.com/uc?id=1S25zSdIMNX8_TfL2yzvXOtADGBa6enwn&export=download) | 仅列元数据，后续归档原件，禁止执行 |
| match_index.csv | 1,804 | [下载入口](https://drive.usercontent.google.com/uc?id=1EzJ3khkIBr9aKDQm6DUcTGvqqnFAyUaX&export=download) | 比赛索引；正文待主任务读取 |
| README.md | 11,855 | [下载入口](https://drive.usercontent.google.com/uc?id=1nFsJW6ffCZhM_dT8zxJkASDqH4MbDOi6&export=download) | 使用说明，已 HEAD 核验 |
| vis.py | 35,713 | [下载入口](https://drive.usercontent.google.com/uc?id=1a1VBqbtUUCj9qRMBVN_G2lgIz7j8KQRW&export=download) | 仅列元数据，后续归档原件，未执行 |
| 合计 | **57,197** | | |

清单逐项提供 `relative_path`、`google_drive_id`、`expected_bytes`、`source_page`、`source_folder_url` 和正常下载格式 `url`。所有项为 `download_status=not_attempted`，作者 MD5/SHA256 均为 null，因为本次目录没有提供可核实的作者校验值。精确大小是发布元数据，不是已下载校验。Drive ID 也不保证内容永远不变，下载应再次核对大小并计算本地哈希。

## 正常下载路径的实际证据

对 README、最小 court JSON、最大 pose JSON 的公开文件页，实际提取到了 `https://drive.usercontent.google.com/uc?id=...&export=download` 链接；这些与清单模板一致。其余项由已观察到的文件 ID 构造同一正常 URL 格式，未逐一 HEAD，不能声称 121 个内容都已下载验证。

| 样本 | 发布字节数 | 实际响应 |
|---|---:|---|
| README.md | 11,855 | HEAD 200，`application/octet-stream`，Content-Length=11855，attachment filename=README.md |
| `court/VICTOR-China-Open-2025-Shi-Yu-Qi-CHN-3-vs.-Wang-Zheng-Xing-CHN-F_court.json` | 713 | [公开入口](https://drive.usercontent.google.com/uc?id=1enBs5wDL9iKpN_LFKQCAlfcq-JEk0lLb&export=download) HEAD 200，`application/octet-stream`，Content-Length=713 |
| `pose/PETRONAS-Malaysia-Open-2025-Kodai-Naraok-JPN-8-vs.-Anders-Antonsen-DEN-2-SF.json` | 193,481,043 | [公开入口](https://drive.usercontent.google.com/uc?id=11alosIr7znUiPOfw53wlPNZD-neTaYc_&export=download) HEAD 200、`text/html`、Content-Length=0；不是 JSON 内容成功 |

随后只对最大文件读取了 **2,497 B HTML**（硬上限 65,536 B，先核对 Content-Type）；确认为 Google Drive 标准“无法扫描病毒／Download anyway”确认页。正常表单 `method=get`、action=`https://drive.usercontent.google.com/download`，隐藏字段名称为 `id, export, confirm, uuid`。动态值未存入文档/清单，未提交表单，JSON 正文读取量 **0 B**。未来下载者应从当时正常页面读取表单值；遇登录、配额或其他限制就停，不改身份或绕过限制。

结论：公开目录可有限枚举，小文件正常下载头可达；大型 JSON 需要标准下载确认。大文件实际传输与逐文件校验仍 **NOT_RUN**，不存在“完整包已下载”证据。

## 已知语义和权利边界

作者 README 的 released package 说明是 **19 场：12 男单（2025 四赛事）+7 男双（2023–2024），1,058 回合、11,301 拍**。这与 overview 的 1,687 回合/16,751 hit events 不同；采用发布包断言作待核对目标，不能把两个统计混用。目录数量支持 12+7 的结构，回合/拍数须读取正文后实测。

README 约定完整转播 0 基解码帧、1280×720/30fps；这些没有替代真实原片/PTS 核验。`court` 只适用于主机位，`court_perframe` 是自动检测/修复；`pose` 的框为像素、关键点归一化，`player_bbox` 和 `shuttle` 为百分比坐标。`shuttle` 明确是 TrackNet 预测，`hit_inferred` 从其他标签和球员位置推导，均不得标成人工真值。`shot_type` 是作者手工时间线；`hits_doubles` 只有泛化 hit/bounce/net_hit 和结构区间，不能声称双打有细球种或全模态标签。caption 的人工/生成来源本轮未读正文核实，保持未确认。细手法展搓/收搓、后退小跳仍 unknown。

[官网权限声明](https://ning-d.github.io/BFMD-Dataset/) 为仅非商业学术研究、不得再分发；代码独立许可未知，不能因公开源码而假定 MIT；视频属于 BWF TV，包内不提供视频。此下载候选仅限 `training_only` 的训练/验证/测试/内部诊断，原件保留到训练专用路径，不能进入制作库或公开成片。未下载权重，也不推断权重许可。

本页可支撑 `R-04a` 来源/字节预检和 `R-04b` 用途设计，但 BFMD 的实际下载、哈希、标注统计及制作链路拒绝实测在本子任务均为 **NOT_RUN**；后续由主任务记录相应用例证据。
