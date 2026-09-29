# Fine-Badminton 2026 实际数据核验

生成时间：2026-09-29T10:25:57.156621+00:00。固定用例 R-04a；用途 training_only，split=unassigned。

本快照已提取 22 项：10 CSV、10 MP4；原 member stem 精确配对 10 组，完整 probe/PTS 已核验 10 组。解压完成标志：True。

包内 README 明确分发的是 processed video clips，不能将10个视频称为10场无剪辑整场。start表示启动击球动作的第一帧，end表示球拍—球接触及紧接随挥完成的帧；0/1基、结束端点开闭、location含义及原转播偏移尚未确认。类别顺序仅复录README，不构造数字ID。

LICENSE和README均指向CC BY-NC 4.0；API的CC BY 4.0另行保留。LICENSE允许Share与README限制未经书面许可再分发也有冲突；这里仅记录证据，不推断新的画面或再分发授权。

| 项目 | 作者声明 | 本快照实测 | 状态 |
|---|---:|---:|---|
| exact_original_stem_pairs | 10 | 10 | PASS |
| annotation_rows | 9817 | 9817 | PASS |
| category_mapping | 29 | 语义类别未确认；60种原始字符串 | BLOCKED |
| decoded_frames | 980703 | 980703 | PASS |
| duration_hours | 10.72 | 10.720154444444445 | BLOCKED |

未完成时上表实际值只是已就绪子集，不能将差值解释为完整包缺失。作者的约10.72小时未给比较容差，完整实测时长仅作证据，一致性判定保留BLOCKED，不自行设定阈值。归档完整性沿用已验证获取报告，本脚本不重复读取整包或重哈希媒体；CSV/README/LICENSE及就绪PTS均实际读取并校验SHA。

README外原始标签有31种，不能擅自翻译合并后宣布29类已对齐。总数据行包含5条精确重复；不删除、不以去重数替换作者总量。数值/结构诊断：`{"equal_start_end_semantics_unverified": 3, "label_not_in_readme": 1301}`。

| 原 member stem | 数据行 | 精确重复 | 原值标签数/README外 | 最小start / 最大end | probe |
|---|---:|---:|---|---|---|
| 2011 OSIM BWF World Superseries Finals-MS-MS - Group A-Chong Wei Lee vs. Peter Hoeg Gade | 549 | 0 | 29/0 | 7423 / 58291 | PASS |
| 2011 OSIM BWF World Superseries Finals-MS-MS - Group B-Dan Lin vs. Kenichi Tago | 795 | 0 | 24/0 | 7239 / 70251 | PASS |
| 2014 THE STAR AUSTRALIAN BADMINTON OPEN-F-MS-Lin Dan (CHN) VS Simon Santoso (INA) | 1333 | 1 | 28/0 | 12244 / 125198 | PASS |
| SF - 2014 China Open -  Lin Dan vs Chou Tien Chen | 921 | 0 | 26/0 | 1934 / 74837 | PASS |
| TOTAL BWF World Championships 2017 _ Badminton F M3-MS _ Lin Dan vs Viktor Axelsen | 763 | 0 | 28/0 | 11581 / 92500 | PASS |
| [1080P] Lee Chong Wei vs Kento Momota - 2018 Badminton Asian Championship Semi Final | 995 | 0 | 28/0 | 849 / 92925 | PASS |
| [4K50FPS] BEST MS MATCH！Lin Dan vs Lee Chong Wei _ 2011 World Championships | 690 | 0 | 27/0 | 1048 / 31821 | PASS |
| [Full] Badminton Lin Dan vs Lee Chong Wei 2010 Asian Games MS Final | 1301 | 0 | 31/31 | 3749 / 126971 | PASS |
| [HD] SF - 2014 Asian Games - MS - LIN Dan vs LEE Chong Wei (1) | 1217 | 3 | 29/0 | 7465 / 114473 | PASS |
| videoplayback (1) copy | 1253 | 1 | 27/0 | 9273 / 121834 | PASS |

已就绪视频的完整解码与PTS实测如下。末列依次为0基闭、0基开、1基闭、1基开的越界或空区间数；只是四种假设的诊断，不选择真实约定。

| 原 member stem | 解码帧数/PTS行数 | 时长秒 | 分辨率 | 元数据fps | time_base | PTS delta最小/最大 | probe VFR判定 | 四种假设异常行数 |
|---|---:|---:|---|---|---|---|---|---|
| 2011 OSIM BWF World Superseries Finals-MS-MS - Group A-Chong Wei Lee vs. Peter Hoeg Gade | 62401/62401 | 2496.040 | 1280×720 | 25/1 | 1/12800 | 512/512 | cfr_observed | 0/0/0/0 |
| 2011 OSIM BWF World Superseries Finals-MS-MS - Group B-Dan Lin vs. Kenichi Tago | 73262/73262 | 2930.480 | 1280×720 | 25/1 | 1/12800 | 512/512 | cfr_observed | 0/0/0/0 |
| 2014 THE STAR AUSTRALIAN BADMINTON OPEN-F-MS-Lin Dan (CHN) VS Simon Santoso (INA) | 142222/142222 | 5688.880 | 1280×720 | 25/1 | 1/12800 | 512/512 | cfr_observed | 0/0/0/0 |
| SF - 2014 China Open -  Lin Dan vs Chou Tien Chen | 79469/79469 | 3178.760 | 1280×720 | 25/1 | 1/12800 | 512/512 | cfr_observed | 0/1/0/1 |
| TOTAL BWF World Championships 2017 _ Badminton F M3-MS _ Lin Dan vs Viktor Axelsen | 120015/120015 | 4794.280 | 1280×720 | 3000375/119857 | 1/90000 | 1800/3600 | vfr_observed | 0/0/0/0 |
| [1080P] Lee Chong Wei vs Kento Momota - 2018 Badminton Asian Championship Semi Final | 94861/94861 | 3165.196 | 1280×720 | 30000/1001 | 1/30000 | 1001/1001 | cfr_observed | 0/0/0/0 |
| [4K50FPS] BEST MS MATCH！Lin Dan vs Lee Chong Wei _ 2011 World Championships | 32651/32651 | 1306.040 | 1280×720 | 25/1 | 1/12800 | 512/512 | cfr_observed | 0/0/0/0 |
| [Full] Badminton Lin Dan vs Lee Chong Wei 2010 Asian Games MS Final | 130420/130420 | 5216.800 | 1280×720 | 25/1 | 1/12800 | 512/512 | cfr_observed | 0/1/0/1 |
| [HD] SF - 2014 Asian Games - MS - LIN Dan vs LEE Chong Wei (1) | 118201/118201 | 4728.040 | 1280×720 | 25/1 | 1/90000 | 3600/3600 | cfr_observed | 0/1/0/1 |
| videoplayback (1) copy | 127201/127201 | 5088.040 | 636×360 | 25/1 | 1/12800 | 512/512 | cfr_observed | 0/0/0/0 |

| 实际标签 | 行数 |
|---|---:|
| Clear Return of Serve | 23 |
| Cross-court Net Return of Serve | 81 |
| Cross-court Net Return of Smash | 45 |
| Defensive Lift | 78 |
| Drive | 711 |
| Drive Return of Smash | 16 |
| Drop Shot | 902 |
| Drop Shot Return of Serve | 13 |
| Drop Shot Return of Smash | 206 |
| Flat Clear | 259 |
| Flat Serve | 26 |
| High Clear | 459 |
| High Serve | 21 |
| Jump Smash | 78 |
| Lift | 1789 |
| Lift Return of Serve | 274 |
| Lift Return of Smash | 236 |
| Net Kill | 93 |
| Net Shot | 671 |
| Net Shot Return of Serve | 26 |
| Overhead Cross-court Net Shot | 331 |
| Push Shot | 107 |
| Short Serve | 449 |
| Short Smash | 293 |
| Smash Return of Serve | 8 |
| Smash(Full-length) | 376 |
| Soft Net Shot | 637 |
| Soft Net Shot Return of Serve | 101 |
| Underhead Cross-court Net Shot | 207 |
| 中场腾空抽杀球 | 13 |
| 低手位勾球 | 22 |
| 劈球 | 2 |
| 发小球 | 67 |
| 发平高球 | 8 |
| 发高远球 | 2 |
| 吊球 | 140 |
| 平推球 | 26 |
| 平高球 | 54 |
| 扑球 | 9 |
| 抽球 | 157 |
| 挑高球 | 299 |
| 接发球击吊球 | 2 |
| 接发球击杀球 | 1 |
| 接发球击高远球 | 1 |
| 接发球勾球 | 7 |
| 接发球挑球 | 22 |
| 接发球推球 | 1 |
| 接发球搓小球 | 10 |
| 接发球放小球 | 6 |
| 接杀勾球 | 6 |
| 接杀挑高球 | 23 |
| 接杀放小球 | 16 |
| 搓球 | 142 |
| 放小球 | 74 |
| 短杀 | 27 |
| 长杀 | 30 |
| 防守回抽 | 2 |
| 防守回挑 | 4 |
| 高手位勾球 | 57 |
| 高远球 | 71 |

位置原值频数：`{"Lower Half": 4249, "Upper Half": 4267, "上半区": 652, "下半区": 649}`。

重复、冲突、乱序、严格重叠及数值异常逐文件明细、原CSV行号、首/中/末抽样和四种帧边界假设保存在同名JSON。表中probe PASS只表示完整解码证据及PTS索引完整性通过；不表示标注时间映射已确认。重叠不自动判错；四种边界假设不选定任何一种，不转换Event。

文件解析/完整性失败数：0。语义转换BLOCKED；真实画面边界抽检NOT_RUN；三细标签保持unknown。

复跑命令：`python -B -m scripts.library.audit_fine_annotations`。仅从共享盘读取，两个报告写入本仓库docs/library。

归档SHA256：`a3518f52d66dd6c5d2b01ce1347de8e589516ccc24a72aae818fea64e0b04439`；作者MD5：`cb3fcaca0ae9b08c564ac2a19ae4e7a0`。输入清单、README、LICENSE及训练manifest的SHA见JSON evidence。
