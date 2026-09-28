# 双打小样与林李原片下载入口补查

核验日期：2026-09-28（Asia/Shanghai）。本子任务只读作者网页、论文、公开目录元数据和 HTTP HEAD；未下载媒体或压缩包，未使用登录凭据或绕过下载限制。本文的大小是发布目录元数据及响应头，不代表已经完成下载、解码或画面核验；实际结果另见 library handoff。

## 首选：作者自行采集的 Drone_BD_ControlArea 男双

[官方仓库](https://github.com/Ning-D/Drone_BD_ControlArea)，核验提交 `14a6a74969f54adb57e013faa4fb24298794e985`；[固定 README](https://raw.githubusercontent.com/Ning-D/Drone_BD_ControlArea/14a6a74969f54adb57e013faa4fb24298794e985/README.md)。作者 README 直接链接公开 Google Drive 数据目录。

[作者论文 §3.1–3.2](https://arxiv.org/html/2305.04247v2) 明确数据为大学羽毛球社团成员的男子 2 对 2 比赛，自行使用两台 DJI Air 2S 从顶部和后方拍摄，原始规格 3840×2160、30 fps，包含 11 人、14 对搭档、39 games、1,347 回合。论文记录 2022-04-14 伦理批准 AHNU-ET2022042、参与者签署知情同意；这是采集背景，不能解释为向第三方授予商用或再分发权。没有已核实名单、职业排名、正式赛事名或比赛日期；不得把这些社团样本标成世界前十球员或职业赛事。具体小样机位和分辨率须以下载后探测为准。

### 原始目录链与可选文件

视频目录链（每级均为本次实际读取的公开目录）：

1. [作者链接的 videos 根目录](https://drive.google.com/drive/folders/1sIKIDLjyhccO_y6gXeaIkr_1gu1o0vYw?usp=drive_link)
2. [Study_Videos](https://drive.google.com/drive/folders/1pviHfD3o3M7GUNDJYYaNWKzW7y64_8uf)
3. [BD12](https://drive.google.com/drive/folders/1t3Wt7dXOVuLkk-BtV2bJjh-xv3uKmILd)
4. [Rally-1](https://drive.google.com/drive/folders/1hwDNfsF2IzX3PnnjFqE1iNx9DqzLcWlB)

| 发布文件 | 发布字节数 | 正常下载链接与实际 HEAD | 用途与尚未确认项 |
|---|---:|---|---|
| [(1).mp4 文件页](https://drive.google.com/file/d/1tncTXoI4IWBBL6qg8D9QtaE1f-EPZii5/view) | 5,857,600 | [文件页公开下载链接](https://drive.usercontent.google.com/uc?id=1tncTXoI4IWBBL6qg8D9QtaE1f-EPZii5&export=download)：200，`video/mp4`，Content-Length 5,857,600，Content-Disposition `attachment; filename="(1).mp4"` | 最小候选。来源明确属于作者男双数据；尚未视觉确认四人、机位及片段边界。 |
| [1.mp4 文件页](https://drive.google.com/file/d/1TAFYQu1PD3ErHksKD2JYDNqGiTFeSdTG/view) | 6,203,964 | [文件页公开下载链接](https://drive.usercontent.google.com/uc?id=1TAFYQu1PD3ErHksKD2JYDNqGiTFeSdTG&export=download)：200，`video/mp4`，Content-Length 6,203,964，Content-Disposition `attachment; filename="1.mp4"` | 同目录另一候选；不能仅按名字判定其机位或与 CSV 的帧对齐。 |

以上链接来自文件公开页面中实际显示的下载地址，HEAD 正常重定向至 `https://drive.usercontent.google.com/download`，保留同一 `id` 与 `export=download` 参数。未出现登录、付费或确认表单。未进行 MP4 GET，因此服务器未来 GET 是否仍成功由有界下载结果决定。优先只选一个文件，避免同时下载两个来源或整库。

关联标注目录链：根目录 → [datacsv](https://drive.google.com/drive/folders/16KyrydHaV0dsog5Jm-VblKL6pyMD4qrA) → [BD12](https://drive.google.com/drive/folders/13ycBz7zKwnqL-dsMGx1pXzpUG8hKd-u9) → [Rally-1](https://drive.google.com/drive/folders/1mlGe3Qy4GsS4URXKsb_w7cTQpGOWSGNy)。该目录本次显示唯一 [1.csv](https://drive.google.com/file/d/1EdLWb-2xeCD3N0ZcnxLJbEesVnKl_wF4/view)，28,707 B；[正常公开下载](https://drive.usercontent.google.com/uc?id=1EdLWb-2xeCD3N0ZcnxLJbEesVnKl_wF4&export=download) HEAD 200、`application/octet-stream`、Content-Length 28,707、attachment filename `1.csv`，同样重定向至 `/download`。

论文与 README 提供球员框、羽球位置和击/落球相关标注说明；README 还明确学习样本选择有范围限制，不能把这些文件当成所有帧均人工确认的密集真值。本轮未读该 CSV 内容，尚未确定列结构、帧起点、机位对应和预测/人工修正来源。固定仓库 `All.csv` 中有 `BD12_Rally-1_0.csv` 与 `BD12_Rally-1_1.csv` 条目；这些名字不能证明 `_0`、`_1` 对应两个机位。

### 许可分层与入库约束

| 层 | 已证实 | 未证实／入库处理 |
|---|---|---|
| 代码 | 作者公开 GitHub 仓库与研究实现 | 核验树未见 LICENSE；code license=`unknown`，不可因公开仓库或论文称 open-source 就填 MIT/Apache。 |
| 标注 | 作者链接公开 CSV 目录 | 未见独立数据许可；annotation license=`unknown`，用途权限留空。 |
| 原视频 | 作者论文说明自行拍摄；作者公开 Drive 提供文件下载 | 未见标准视频许可或明确再分发/商业条款；video license=`unknown`，public redistribution/commercial use 未获证实。知情同意不是公开再许可。 |
| 权重 | 本轮未研究和获取 | 不推断许可，不下载。 |

若实施小样，只用于本地检索/探测研究并记录发布路径及权利未知，不公开传播。视频加 CSV 为 5,886,307 B 或 6,232,671 B；若下载临时文件与最终文件同时保留，按较大文件至少预估 12,465,342 B，再为探测报告预留，建议本次总上限 20,000,000 B。实际写入前仍须按全局和 library 配额检查磁盘，并限制流式下载字节数。

`BD12/Rally-1` 是作者分组证据，不是已知正式赛事。两机位/同目录片段均应归入同一保守来源会话组（如 `drone-bd12`，内部候选标识），`split=unassigned`；确认完整比赛边界前禁止分到不同 train/test。网前展搓、收搓、后退小跳启动均保持 unknown。

## 备选：Badminton-hit-detection 的业余双打包

[官方仓库](https://github.com/kwyoke/Badminton-hit-detection)，固定提交 `7dad97e2da86332158319451ec5c2ab1a1f4a289`。作者 README 明确 amateur doubles，示例目录包括 `am_doubles/match_clementi/doubles5`、`match_yewtee/doubles2`、`match_msia/doubles3`，提供回合视频及羽球、击球、球员框标注。核验未见 LICENSE，代码、标注和视频许可分别未知。

[README 链接的公开 Drive 目录](https://drive.google.com/drive/folders/13Ja-lZCNNbWelWcb3oP4L4if8khqTfUo) 显示 [am_doubles.zip](https://drive.google.com/file/d/14FOLegDDxgJi5WWeBs0Ok8VQvdZYbZJx/view) 为 **57,470,277 B**。文件页公开的 [正常下载入口](https://drive.usercontent.google.com/uc?id=14FOLegDDxgJi5WWeBs0Ok8VQvdZYbZJx&export=download) 本次返回 Google Drive 标准“文件过大，无法病毒扫描／Download anyway”HTML，而非 ZIP 数据。已读取其正常 GET 表单：action=`https://drive.usercontent.google.com/download`，字段为 `id`、`export=download`、`confirm=t`、动态 `uuid`；动态值不写入静态文档，若选此路径应从即时页面正常取得。没有认证、付费或验证码页面，也未提交表单、未下载 ZIP。

原包不足 100 MB，但 ZIP 与全量解压叠加的峰值未知，不能直接以 57.47 MB 宣称满足全部预算。优先较小 Drone 单片；此包仅保留备选，若后续采用须限制 ZIP 下载和选定成员解压的实际大小，禁止路径穿越，记录原始包与成员溯源。具体球员、赛事日期和精确 match 边界仍须核验。

## BFMD 双打与林李经典比赛：本轮未解决项

- [BFMD 官方页](https://ning-d.github.io/BFMD-Dataset/) 说明数据含 7 场男子双打，但不能据此把所有 demo 当双打。`demo_petronas.mp4` 邻接官网标题为 2025 Malaysia Open Naraoka–Antonsen SF，属于男单。固定版本 [demo_all_petronasm.mp4](https://raw.githubusercontent.com/Ning-D/BFMD/c7c7e8e4c815085dda42746f16e07f1172503312/demo_all_petronasm.mp4) 为 878,665 B，但本轮未解码，文件名 all 不能确证双打。网站数据非商业学术研究、不得再分发声明与原画面 BWF 权利仍分层记录，未发现专门覆盖该 demo 的 BWF 授权链。详见 SOURCES.md。
- [S2DoublesDataset 作者仓库](https://github.com/HuangYuHsien/S2DoublesDataset) 提供双打标注，视频仍指向 BWF YouTube。没有核实到一个新的小文件正常下载入口，本轮不重复已阻塞路径。
- 林丹—李宗伟 [2011 世锦赛](https://www.youtube.com/watch?v=WI8Od4jBpUc)、[2011 全英](https://www.youtube.com/watch?v=5F1Pn8-Lp0c) 及 [2012 伦敦奥运决赛](https://www.youtube.com/watch?v=ytjD4f_I0sc) 保留为官方观看候选。本轮官方来源检索没有找到明确提供的原整场公开文件下载路径；网页能播放不等于存在可授权下载原片的直链。没有使用 YouTube 抽流、第三方下载器或绕过限制。后续需权利人提供文件或正常下载渠道；“本轮未找到”不代表断言此类授权不存在。
