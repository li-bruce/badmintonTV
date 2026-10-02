# A-07/A-08 触球逻辑范围：真实输入可用性

核查时间：2026-10-02 15:02:59–15:03:01 UTC（北京时间23:02:59–23:03:01）。依据 [本轮实施要求](../IMPLEMENTATION_ROUND_2026-10-02.md) A-07/A-08。本记录只说明真实资产、现存完整PTS和用途门禁输入可用，不把输入核查写成四种范围策略或全部制作入口的最终验收。

本次没有启动FFmpeg/ffprobe、GPU或浏览器，没有复制、截取、解码、编码训练原片，没有安装依赖、改动生产DB或registry。运行环境为现有 `D:/video/runtime/platform/env/Scripts/python.exe -B`，只使用Python标准库及现有合同校验器。新增文件只有本文；预期本轮JSON/文档新增峰值小于5,000,000 bytes。

## 清单与实读范围

以下路径以 `D:/video/` 为根。三份清单均是 `{"schema_version":"1.0","assets":[...]}`；15个Asset均通过当前 `packages.contracts.models.Asset.model_validate`。

| 清单 | Asset数 | 本次实读SHA-256 |
| --- | ---: | --- |
| `data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json` | 10 | `2725970f4485732e67ba249b72262c51dbba24ee17e5e97d901b18ec8a29e286` |
| `data/handoff/assets.v1.json` | 4 | `f6a646668ec688ecbbe85386f64db9d81b4c6b951a8284a1a581195cd57563aa` |
| `data/handoff/assets.doubles.v1.json` | 1 | `3b8b76738bc8a5ca1197fec71cd7a5d48efea22d6977bd614ff6f1ffa001815f` |

可信用途登记为 `data/training/handoff/training-registry.v1.json`，10行，本次前后SHA均为 `63eb86de88e6c760be8ff3464318d8fd55a923e7bfa1d1c177dc2bdd643e52aa`，未写入。路径存在不能代替用途判断；旧general样片也重新对照当前registry。

本次读完全部15份PTS：36,348,859 bytes、981,432行，其中训练10份980,703行。逐份实际SHA、字节数、`frame_index=0..N-1`、整数且严格递增的PTS均匹配manifest；`complete=true`且行数等于既有全片CPU解码报告的frames。这里复核的是**已有真实完整索引**，不是本轮重新解码。原片SHA本轮只重算推荐训练源及旧制作三片；其余原片的SHA/解码状态沿用既有library证据，不能称本轮15源全量重验。

训练视频目录可见 [library交付记录](../library/TRAINING_DATA_ACCEPTANCE.md) 和 [画面QA](../library/TRAINING_VISUAL_QA.md)。BFMD虽有标注文件，本地没有对齐的视频Asset/PTS，不选作本次真实时间输入。

## 推荐固定训练Asset

选现存10条中原文件和PTS都最小的一条，便于重复核验。不得根据发行文件名中的“4K50FPS”推断技术规格：实际probe是1280×720、H.264、25/1 fps。

```text
asset_id:
asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913

source:
D:/video/data/training/fine-badminton-2026-zenodo-20292976-v1.0/extracted/876ddac3abe9141b8ce7f2fe.mp4

source SHA-256:
b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913

PTS:
D:/video/data/training/fine-badminton-2026-zenodo-20292976-v1.0/probes/b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913.5bdc8c2639e241309b21e15bbf9e87cb.pts.jsonl

PTS SHA-256:
b18a822e0c66dd7aa810b0d1c5684e1e9c923e2d0982ea7f520341798a2b10b9
```

原文件231,500,744 bytes，本次从原字节流式重算SHA匹配。Asset时长1,306,040 ms；PTS文件1,175,271 bytes，32,651行，time_base=`1/12800`，PTS来自`best_effort_timestamp`。完整索引实际行格式如下，**JSONL中的键为`pts`，不是`best_effort_timestamp`**；time_base在manifest的`probe.pts_index`，行内没有毫秒字段。

```jsonl
{"frame_index":0,"pts":0}
{"frame_index":1,"pts":512}
{"frame_index":2,"pts":1024}
```

本次从完整索引确认的定位点：

| frame_index（0起） | 实际整数PTS | `pts × 1000 / 12800`（ms） |
| ---: | ---: | ---: |
| 25 | 12,800 | 1,000 |
| 50 | 25,600 | 2,000 |
| 75 | 38,400 | 3,000 |
| 150 | 76,800 | 6,000 |
| 16,325 | 8,358,400 | 653,000 |
| 32,650（末帧） | 16,716,800 | 1,306,000 |

所有相邻差为512 ticks（40 ms），共32,650个差值。Asset末端1,306,040 ms是媒体范围上界；最后一个实际呈现时间戳是1,306,000 ms，不能制造一个末端PTS行。半开区间可使用媒体上界，但需区分“源时间边界”和“实际帧PTS”。

该Asset及其provenance均为`training_only`；registry按ID、原SHA、路径均命中。当前只读 `UsageScopeGuard.check` 返回`allowed=false, usage_scope=training_only`。`match_id=fine-badminton-2026:2011-world-championships-ms-lin-lee-round-unverified`；球员名称来自发行文件名、identity未确认、整场偏移null、split=unassigned。不得把此分组名当作已独立核实的比赛身份。

来源是Zenodo record20292976/v1.0的原包成员；Asset rights为research_only/非商业学术研究。包内CC BY-NC与API CC BY元数据冲突及转播画面权利缺口沿用library记录，不升级为制作或发布授权。CSV帧基、端点、类别语义及对齐未确认，细手法/步法仍unknown。

已有中点收据位于 `D:/video/data/training/fine-badminton-2026-zenodo-20292976-v1.0/quality-control/b210dc39a219d5ec5bb87ef9.middle.json`，引用frame16325、PTS8358400、653秒及同一PTS SHA。收据保存的是当时较早manifest SHA；其源/PTS绑定与当前最终manifest一致，不应强行将旧收据改成新manifest hash。本轮只读收据，没有重新生成图片。

## 可选真实VFR边界输入

训练Asset `asset-80d9c5be022baef9ce57773cbadfb28647d8e11c651fc4528eec5d8e7b32c4b7` 的完整索引适合验证不得用frame/fps替代源PTS。原片是同数据集 `extracted/dad96556571445665120c49a.mp4`，1,055,036,097 bytes；本轮没有重算这条大原片SHA，沿用manifest及既有library全源核验。

```text
D:/video/data/training/fine-badminton-2026-zenodo-20292976-v1.0/probes/80d9c5be022baef9ce57773cbadfb28647d8e11c651fc4528eec5d8e7b32c4b7.10eec47b50c74a02aa6e23759f933e4b.pts.jsonl
SHA-256: d4c517227b310b47bff15bcc34e6c8686508755caaf92ef139d0fce157706b8c
```

本轮完整读取并校验这份4,538,568-byte索引：120,015行，time_base=`1/90000`；1800-tick差值316个，3600-tick差值119,698个。frame229/230/231实际PTS依次824400/826200/829800，即9160/9180/9220 ms；frame230按25fps推算会得到9200 ms，与真实PTS差20 ms。末PTS431481600即4,794,240 ms，Asset duration4,794,280 ms。该源与其逻辑派生范围继续training_only。

## 旧general制作样片PTS

固定制作回归仍取 `configs/render/real-research.request.json` 中原三片，真实源位于 `D:/video/data/raw/finebadmintonbenchmark/`，完整PTS位于 `D:/video/data/probes/`。本轮分别重算三源SHA并与Asset及`probe.source_sha256`匹配；只读用途守门均返回general/allowed=true。旧manifest未显式写usage_scope，general来自兼容合同默认及本次registry检查，不能把旧路径当永久许可。

| 文件 | 原SHA-256 / 原bytes | 完整PTS行数 / bytes / 末PTS |
| --- | --- | --- |
| `video_001951.mp4` | `5ad7e41a0380916fab9c73d4852ae3c4aeef6ca9c6f9cf998f23f33ffe915c90` / 669,106 | 180 / 5,626 / 91,648 |
| `video_000002.mp4` | `9051c7ba4daba25f1206555d73c5ee2f5c5dfff8f5749a2cc883571379536956` / 591,764 | 161 / 5,018 / 81,920 |
| `video_000003.mp4` | `58aecdab108bd1e1332fb5b45811cc5c4f6e0f2f5987b7da3e98c7345ddc1a13` / 499,766 | 117 / 3,610 / 59,392 |

对应索引名为`video_<id>.pts.jsonl`，实际SHA分别：

- `video_001951.pts.jsonl`：`15efa499303607c73169b62d96dc7dd0277b21220af6f2be66cf0b36cd8bc99c`。
- `video_000002.pts.jsonl`：`bad5f5161b7e9d842d74f6f8ba39f2f4eaecc593f29c74508d65a1081090793e`。
- `video_000003.pts.jsonl`：`fbb19eff4e3646db5af5053f15a90a4840945d0eb8db93a9b1c5a85422bf0fa9`。

三条都是time_base=`1/15360`，首PTS0，严格512-tick步长，即100/3 ms；源时长分别6000/5367/3900 ms。元数据rights仍unknown，general只描述训练/制作用途隔离，不证明公开画面使用权。未在本轮重新编码它们。

另外已完整核对旧双打样片132行PTS（time_base1/600，20-tick差128个、21-tick差3个）。其vfr_status仍unknown；不要仅凭20/21量化差把它标成已确认VFR。

## marks与验收界限

后续若选择上列真实PTS上的1000/2000/3000 ms等时间，或者人为设置一个回合与终点，全部必须标为**技术agent fixture**。这些数值只验证范围计算、真实PTS映射、边界夹取和用途继承；本次没有观察并确认相应时刻发生触球、发球、死球或指定人物动作。不能记为human confirmed，不能将其写入默认人工真值/训练标签，也不能用相邻行推断同一球员。

| 用例 | 本记录实际结果 | 状态与后续 |
| --- | --- | --- |
| A-07 输入前置 | 推荐源真实SHA、完整PTS及VFR备用索引可核；用途和不确定语义明确 | 输入可用性PASS；四种范围策略实际执行与边界结果由主任务另验，本记录不声称A-07整体PASS |
| A-08 输入前置 | 推荐训练源当前guard拒绝；原制作三片当前guard允许；registry未变 | 守门子检查PASS；导入/候选/Timeline/render及派生物全入口负例本次NOT_RUN，由主任务另验 |
| 人工动作真值 | 无本轮专家确认marks/动作/回合边界 | BLOCKED；技术fixture不可代替 |

## 容量与新增预算

2026-10-02 15:03:01.584034–15:03:01.644583 UTC只读目录元数据快照：

| 项目 | bytes / 条目 | 限额 |
| --- | ---: | ---: |
| `D:/video/render` | 647,917,504 / 1,300文件 | 40,000,000,000 |
| `D:/video/runtime/render` | 873,315,597 / 108文件 | 5,000,000,000 |
| D盘物理剩余 | 922,754,990,080 | 本轮新增峰值5,000,000加256,000,000物理余量 |

目录值是`lstat().st_size`的可见逻辑文件bytes，未跟随junction/symlink目录，不冒称NTFS分配簇大小；快照非原子，其他任务并发可能改变物理free。render加本轮5MB峰值低于40GB；runtime/render不新增环境。共享固定owner配额合计650GB及700GB硬上限不变；本次未重新扫描全部D:/video，不能把旧全局快照称为当前实占。无媒体新增，不产生安装缓存、端口或GPU占用。
