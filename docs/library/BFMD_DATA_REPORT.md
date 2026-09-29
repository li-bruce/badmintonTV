# BFMD 真实标注审计（完整包）

实测时间：2026-09-29 18:32:26 +08:00。`R-04a` 的 BFMD 完整包数据核验；121个原件全部完成本地大小/SHA256复核，115个活动JSON与1个备份全部严格解析成功。输入仅为 `data/training/handoff/bfmd.annotations.v1.json` 中状态已验证的文件；未访问 `.part`、未联网、未写D盘、未执行作者脚本。

执行：`python -B scripts/library/audit_bfmd_annotations.py --output docs/library/BFMD_DATA_REPORT.json`，exit 0、20.297秒。脚本只接受本仓库 `docs/library` 内的输出路径，单文件上限200,000,000 B，逐文件释放解析对象；报告硬上限1MB。输出 [机器报告](BFMD_DATA_REPORT.json) 为281,316 B，含来源hash、schema、计数和文件指针，不含字幕正文或视频URL全表。

## 当前覆盖与可复现性

| 断言 | 实际结果 | 状态/范围 |
|---|---|---|
| 121文件/115活动JSON+1备份+根5全部检查 | 已核验121文件、1,825,439,459 B；115活动JSON+1备份+根5；pose 12/12，缺项0 | PASS，完整包；JSON `handoff_complete=true`、`missing_files=[]` |
| 原件来源/字节/严格JSON | 121份大小和本地SHA与stable清单一致，0解析/结构错误；无重复JSON键或NaN/Infinity/溢出浮点 | PASS；没有作者哈希，不称作者哈希校验 |
| 严格解析器拒绝异常 | 嵌套/非嵌套重复键、NaN、±Infinity、1e400六类均拒绝；有限数值正常解析 | PASS，内存检查，无媒体结论 |
| inferred到metadata的引用和保守帧包络 | 12场11,301条的game/rally引用有效，帧在metadata的`start <= frame <= end`内；其中6条等于start、0条等于end | PASS，仅引用与确定越界检查；未选择端点开闭语义 |
| 完整pose结构统计 | 12文件、1,054 rally groups、317,734帧记录；非整数/负帧键均0 | PASS，仅结构/记录计数；不是唯一原视频帧或视频覆盖率 |
| 时间与画面关联 | 没有BFMD原视频，无法核对实际PTS、原片时长、画面中的球员或动作边界 | BLOCKED；未生成Asset/PTS/Event |
| 新双连接/Range恢复的真实运行 | 本包由原单连接自然完成，未中止、未真实运行新并发或Range恢复 | NOT_RUN；离线代码测试不能代替真实下载证据 |

九个单打模态（metadata、caption、hit_inferred、shot_type、court、court_perframe、player_bbox、pose、shuttle）各12份，另7份hits_doubles；1份metadata备份独立归档。报告中的文件 `status=PASS` 表示读取/严格解析与统计路径成功，不表示人工内容真值、许可已解决或跨模态语义一致。

## 实际计数及作者声明差异

| 来源/口径 | 实测 | 与作者表述的关系 |
|---|---:|---|
| `Badminton_video_list.csv` 数据行 | 19：12 singles+7 doubles | 19场索引成立；19个`VERIFIED`是作者字段，未在本机取得或验证视频 |
| `match_index.csv` | 12单打行+1 TOTAL行；逐行回合和=TOTAL=1,054 | 没有双打索引行；不能拿此表作19场统计 |
| 单打 metadata 的 `games.*.rallies` | 1,058 | 与README开头数字相等，但范围仅12单打 |
| 单打手工 `shot_type` 的 `Rally` ranges | 1,054 | 与match_index一致，与metadata差4 |
| 单打 `hit` ranges / `hit_inferred.hits` / `caption.shots` | 均11,301 | 12场caption与inferred的有序`frame/game/rally/shot_type/player/side`签名全部一致；这些不同表示不能相加 |
| 双打手工 `Rally` ranges | 634 | 独立于单打统计 |
| 双打手工 `hit` / `bounce` / `net_hit` | 5,450 / 583 / 209 | 三类分别报告，不把全部之和当拍数 |
| 19场手工 `hit` 总和 | 16,751 | 与仓库overview的hit数一致；README的11,301不是19场合计 |
| 19场手工 `Rally` 总和 | 1,688 | 与overview的1,687差1，当前未解释；不能调计数规则凑齐 |
| 单打metadata+双打手工Rally | 1,692 | 这是混合来源口径，明确标注；不是新的统一真值 |

单打具体球种、`hit`、`bounce`可在同一拍并行出现。所有已知球种标签ranges直接相加会得到24,233，**这不是独立拍数**。原始标签分布保存在JSON，不做强制类别归一化。

metadata与手工时间线的4回合差异：

| 比赛文件stem简述 | metadata | timeline / auto_extracted / CSV | 差值 |
|---|---:|---:|---:|
| PETRONAS 2025 Shi Yu Qi–Li Shi Feng SF | 96 | 95 | +1 |
| VICTOR China 2025 Chou Tien Chen–Shi Yu Qi SF | 76 | 74 | +2 |
| YONEX All England 2025 Lee Chia Hao–Alex Lanier SF | 113 | 112 | +1 |

完整文件名见JSON `reconciliation.per_match`，检查指针为 `games.<game>.rallies`、`auto_extracted.num_rallies` 与 `annotations[0].result[*].value.timelinelabels/ranges`。本次没有修改原标注，也没有决定哪份更正确。

## 真实schema与来源分层

- **metadata不是统一单元素数组**：12活动文件中1份list、11份object，备份也是object；核心games结构相同。初版按README严格要求list时发现结构差异，检查真实字段后才兼容两种已观察结构。`.json.bak`独立解析但从全部比赛/回合/拍数汇总中排除。
- **caption的refined已全部非空**：11,301条都有非空`refined`，与README“约6,500、进行中”不一致。`auto`是视觉模型生成，`clean`是名字规范化，`refined`为发布者声明的人工修订；本地没有human审核。非空不证明描述正确，且refined嵌入球种，不能当独立分类真值。
- **一场双打有额外细球种通道**：`hits_doubles/VICTOR-China-Open-2024-Goh-Izzuddin-MAS-7-vs.-He-Ren-CHN-5-F.json` 除943个hit，还含943条`type=choices/from_name=shotType/origin=manual`及非空`manual_caption`。它们与hit并行，不是额外943拍。实测choices包括10种原值（如`net shot`、`net kill`、`press down`），与单打下划线词表不同；另6场没有这一通道。这是README“所有双打无具体球种”的实际例外，但不等于项目细手法真值。
- `shot_type`、`hits_doubles`为发布者声明的人工时间线，当前均只有一个有效annotation版本；仍记录为import/local unreviewed。`hit_inferred`是推导，`shuttle`是TrackNet预测，`court_perframe`是自动检测/修复；不能赋成human来源。
- 完整pose的`videos/<rally>/frames/<full-match-frame>`结构统计为12文件、1,054 rally groups、317,734帧记录；305,877条含2人、11,857条仅1人，总623,611个人物记录均为17关键点，声明分辨率/帧率均1280×720、30fps。非整数或负帧键均0。帧记录按rally group累计，未证明跨组唯一、逐帧连续或视频覆盖率；缺少人物记录不能当双人完整跟踪。pose的1,054组与单打手工Rally/index相等，仍保留metadata 1,058的差异。
- README称2026-07-10从Label Studio1基移到全转播0基。这里只记录作者声明及文件索引检查，没有原视频时不验证`frame/30`对应真实PTS，也不确证端点开闭、身份和细动作。

## 边界与下一步

所有读取原件仍为`training_only`，视频匹配`unmatched`，项目细标签unknown，未产生制作素材或事件。完整包没有缺项或严格解析错误；回合差异仍保留FAIL/差值证据，原片缺失保持BLOCKED。发布者非商业研究及不得再分发限制、代码无独立LICENSE、原视频权利未核实等分层结论不因本地完整性通过而改变。完整包下载成功与语义一致性、人类审核是分开的结论，最终R-04a/R-04b状态由主任务根据全部必需证据更新。
