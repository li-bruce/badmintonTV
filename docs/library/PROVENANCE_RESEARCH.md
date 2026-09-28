# FBBench 四个小样的原片溯源调查

核验日期：2026-09-28。仅查官方 HF/GitHub 元数据、文本与 JSON；本轮没有下载媒体、修改 Asset、修改代码或给样本分配训练/测试集。

## 结论

**四段的原整场映射和裁切偏移仍未证实。** 官方来源给出两个合理的候选来源组，但没有足以写回 `match_id` 或 `source_match_offset_ms` 的 `video_uid → 原视频 ID → 原片区间` 关联。继续保持 `match_id=unknown`、`split=unassigned`、偏移为 null，球员身份未确认。

| 已有片段 | 现有画面观察，仅作线索 | 20K 官方标注中的候选来源 | 已证实到哪里 | 仍不可证 |
|---|---|---|---|---|
| `video_000001` | CHOU T.C. / CHRISTIE；Vantaa | `0001.mp4` | `0001_updated.json` 首条标注的 playerList 为 Chou Tien Chen / Jonatan Christie；0001 在官方重叠名单中 | 此 UID 是否由 0001 裁出、比赛日期/轮次/原始链接、起止帧/毫秒 |
| `video_000002` | 同上 | `0001.mp4` | 同上 | 同上；不能因 UID 相邻认定同场或相邻片段 |
| `video_000003` | 同上 | `0001.mp4` | 同上 | 同上 |
| `video_001951` | LEI L.X. / AXELSEN；Changzhou | `0003.mp4` | `0003_updated.json` 50 条均引用 0003.mp4，playerList 名称集合为 LEI Lan Xi / Viktor AXELSEN；0003 在官方重叠名单中 | 此 UID 是否由 0003 裁出、具体回合和原片偏移 |

这里的“候选来源”是**画面文字与发布者标注姓名相符后的推断**，不是发布者给出的 UID 映射，也不是人脸身份识别。`0001.mp4` 等只是该数据集命名空间下的源文件 ID，尚不是跨数据集的 canonical match_id。来源：[0001 标注](https://huggingface.co/datasets/iLearn-Lab/Finebadminton-20K/blob/72cae601e08c83ee8ec7e19f8fd7850e9158af7d/finebadminton-20K/0001_updated.json)、[0003 标注](https://huggingface.co/datasets/iLearn-Lab/Finebadminton-20K/blob/72cae601e08c83ee8ec7e19f8fd7850e9158af7d/finebadminton-20K/0003_updated.json)。画面观察来自本模块已有 `REAL_SAMPLE_REPORT.md`，本调查未新增视觉确认。

## 已固定的一手版本

| 来源 | 本轮 API 核验结果 | 范围 |
|---|---|---|
| [FBBench API](https://huggingface.co/api/datasets/iLearn-Lab/FineBadmintonBenchmark) | `ff86093a51efdf9a243a0635704952d404e99e52`；lastModified `2026-03-06T07:09:14.000Z` | 与已下载小样相同版本，gated=false |
| [Finebadminton-20K API](https://huggingface.co/api/datasets/iLearn-Lab/Finebadminton-20K) | `72cae601e08c83ee8ec7e19f8fd7850e9158af7d`；lastModified `2026-04-02T02:03:43.000Z` | 后续来源核验均固定此 SHA，不依赖漂移的 main |
| [官方 GitHub](https://github.com/iLearn-Lab/MM25-FineBadminton/tree/d3fd88b61ebadd8773774b4fa95ab27da4811cc1) | `d3fd88b61ebadd8773774b4fa95ab27da4811cc1`；committer 时间 `2026-03-31T04:00:00Z` | 默认分支 master；官网演示 JSON 与 JavaScript |

## FBBench 的可用字段与缺失连接

官方 [FBBench README](https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark/blob/ff86093a51efdf9a243a0635704952d404e99e52/README.md) 只说明 QA 通过 video_uid 对应一个片段。API 列出的非媒体文件为 README、`.gitattributes` 和 12 份 QA JSON，没有额外的原视频映射表。

本轮完整读取全部 12 份 QA JSON，合计 **3,840,013 bytes、2,413 条记录**。共有字段为 `video_uid, duration, spatial, temporal, question, options_en, options_zh, answer`；roundcount 另有 `start_score/end_score`，detail_count 另有 `count/hit_type`。没有 `source_video_id`、`video_id`、`start_frame`、`end_frame`、原片 URL 或裁切偏移。`duration` 是 short/mid 等分类，不能替代精确时长或偏移。

| 现有 UID | 所在官方文件 | 零基行号 | 可以关联的内容 |
|---|---|---:|---|
| `video_000001` | `benchmark_action_classification.json` | 0 | 该 QA 与同名片段；最后击球的粗分类 |
| `video_000002` | 同上 | 1 | 同上 |
| `video_000003` | 同上 | 2 | 同上 |
| `video_001951` | `benchmark_round_comment_updated.json` | 0 | 该 QA 与同名片段；回合描述选择题 |

来源：[action_classification](https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark/blob/ff86093a51efdf9a243a0635704952d404e99e52/finebadmintonbenchmark/benchmark_action_classification.json)、[round_comment](https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark/blob/ff86093a51efdf9a243a0635704952d404e99e52/finebadmintonbenchmark/benchmark_round_comment_updated.json)。UID 出现在某任务文件的第几行，不是整场身份、原片顺序或回合号的证据。

官方 [HF commit history API](https://huggingface.co/api/datasets/iLearn-Lab/FineBadmintonBenchmark/commits/main) 本轮仅返回当前这一个 `commit FBBench` 提交，未提供可读取的较早带映射版本。

## 与 20K 的已知重叠

[20K README](https://huggingface.co/datasets/iLearn-Lab/Finebadminton-20K/blob/72cae601e08c83ee8ec7e19f8fd7850e9158af7d/README.md) 明确说明其 70 个整场来源中的 20 个参与构建 FBBench。固定版本 [benchmark_source_videos.txt](https://huggingface.co/datasets/iLearn-Lab/Finebadminton-20K/blob/72cae601e08c83ee8ec7e19f8fd7850e9158af7d/benchmark_source_videos.txt) 的完整 20 项为：

```text
0001.mp4 0002.mp4 0003.mp4 0004.mp4 0005.mp4
0006.mp4 0007.mp4 0008.mp4 0009.mp4 0010.mp4
0041.mp4 0042.mp4 0043.mp4 0044.mp4 0045.mp4
0046.mp4 0047.mp4 0049.mp4 0050.mp4 0051.mp4
```

名单为 180 bytes，SHA-256 `d02a799974335c2065c6208c4cbab94264af81bb9a93049fde92d0d7b15da3ca`。**这是集合级别的重叠证明，不是每一个 FBBench UID 的交叉表；名单不含 UID、比赛日期、原始公开 URL 或裁切时间。**

为筛查候选，只读取其余 19 个来源标注文件的前 65,536 bytes，解析首个完整回合对象；实际共读 1,232,866 bytes，未读取其余正文或视频。0001 首条 playerList 与前三段文字线索相符，0003 与第四段相符。除0001、0003外，本轮未完整核验这些文件全部回合、身份或时间范围。

完整核验的 `0001_updated.json`、`0003_updated.json` 有 `video, fps, start_frame, end_frame, hitting, playerList` 等源片标注字段；但没有 FBBench video_uid。0001 的首条回合范围是 12062–12319 帧，0003 的首条回合范围是 10025–10270 帧；**这些只是各文件首条回合示例，不能当作四个小样的区间或偏移。** 未取得原整场视频的 PTS/裁切规则，也不应直接把这些帧号当合同中的整数毫秒。

## 官方 GitHub 演示能否补全映射

读取固定版本 [benchmark/combined_random_questions.json](https://github.com/iLearn-Lab/MM25-FineBadminton/blob/d3fd88b61ebadd8773774b4fa95ab27da4811cc1/benchmark/combined_random_questions.json)（36 条、51,255 bytes）。它保留 `video_id, start_frame, end_frame, question_id`，但没有 FBBench video_uid。

对四个现有 QA，以 `question/options_en/options_zh/answer/duration/spatial/temporal` 七项精确比较，**四段均为零匹配**。因此这份演示子集不能提供当前四段的有效连接。

实际反例：`video_000003` 的 question 对象单独与演示 `ACTION CLASSIFICATION_0006.mp4_29065_29191_76` 相同，其余字段不一致；20K 的 `0006_updated.json` 首条 playerList 是 An Se Young / He Bing Jiao，与该片段计分牌文字线索不同。因此“通用题干相同”不足以建立原片映射，不能采用该 29065–29191 帧区间。

另外完整读取官方演示的 dataset 英文 JSON（40 条、479,418 bytes）并查看 `script.js` 中的数据路径与帧号逻辑；它们服务于有限演示回合，没有提供全量 `video_uid` 对照或 FBBench 导出映射。第四段 QA 的正确英文选项与候选 `0003_updated.json` 全部 50 条 `evaluations_new` 文本做规范化精确比较，也没有匹配。来源：[dataset 演示](https://github.com/iLearn-Lab/MM25-FineBadminton/blob/d3fd88b61ebadd8773774b4fa95ab27da4811cc1/dataset/transformed_combined_rounds_output_en_evals_translated.json)、[script.js](https://github.com/iLearn-Lab/MM25-FineBadminton/blob/d3fd88b61ebadd8773774b4fa95ab27da4811cc1/script.js)。

## 证据指纹、限制与下一步

| 实際读取的正文 | bytes | SHA-256 |
|---|---:|---|
| 20K `0001_updated.json` | 665,617 | `88d62e4bc8492f9247a9e619b42397a19e75c608b18edcf4691c72d9c2afd8be` |
| 20K `0003_updated.json` | 604,995 | `4b7d414657665f008d33a38ffeedb46a195d8efa1e0df307d37f9110ab0ec50d` |
| GitHub 36 题演示 | 51,255 | `594a9707403b543ab4940f7eff3c165962acf7985e91c08ee070d0648d7eeaee` |
| GitHub 40 回合英文演示 | 479,418 | `ae6b5d64ee7586bba23a48b87d233f03b01d67ef631e13a5faf9dcb1f1e9b8e2` |

所有网络读取在内存处理，QA/正文单响应上限 1,000,000 bytes，API清单初次上限 2,000,000 bytes；来源筛查采用64KiB前缀。首次 GitHub 递归文件树超过1MB即停止，改为小型分层目录读取；默认分支 main 返回404后按实际 master 查询。普通沙箱网络报 WinError10013，获准的只读公开请求随后成功。这些属于访问/读取记录；本轮最终障碍是**已核验公开材料缺少精确连接字段**，不是声称整个互联网没有映射。

后续最直接的补充材料是发布者的导出映射表：每条需给出 `video_uid`、原 `video_id/question_id`、原片起止帧或时间、帧率/PTS依据、裁切和重编码规则，以及原公开比赛URL/日期。若发布者没有表，可在取得合法可读原片后对候选源片进行帧级比对，并人工核验多个连续画面；单张计分牌、题干相似和相邻 UID 都不足以替代该步骤。本轮未联系发布者、未抓取原整场媒体。

在映射补全前，20 个已知重叠源不能被称为与 FBBench 独立的训练数据；四段继续留在隔离的 unassigned 组。也不能仅把名单以外50个文件当作已证明无其他重传/同场重叠的独立测试来源。视频与标注许可仍按原调查分别记录；本溯源调查未扩大任何公开发布或商业使用许可。
