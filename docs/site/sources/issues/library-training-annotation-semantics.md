# 训练标注语义与许可缺口

状态：原文件完整获取不解决以下语义问题。来源、原值和差异必须保留；不通过翻译猜测、去重或选择端点规则制造通过。

- Fine-Badminton的10 CSV实测9817行。九份英文覆盖README29类，2010Asian另有31种中文原字串；总60原字串不是60确认语义类。5条完全重复、3条start=end均保留。0/1帧基、端点开闭、location、原广播偏移缺作者明确规则；四种假设只做越界诊断，0个Event转换。
- Fine包分发processed clips，包含近景及非比赛镜头；未知身份与原比赛内容重叠不能因文件名或不同SHA排除。split保持unassigned，网前展搓、收搓、后退小跳启动均unknown。
- Fine API CC BY4.0与包内CC BY-NC4.0冲突；README额外禁止未经书面允许再分发，与LICENSE的Share文字也有差异。视频画面许可不能从代码或数据许可推导。
- BFMD单打metadata为1058回合，手工Rally为1054：Malaysia Shi–Li差1、China Chou–Shi差2、England Lee–Lanier差1。19场手工Rally1688与作者overview1687差1，不能调整规则凑齐。
- BFMD的11301拍是12单打口径；双打另5450拍。hit_inferred为派生、caption含自动生成/清理及作者宣称的修订，不是独立逐条人工真值。1份双打有943条shotType/manual_caption，与其他6份和README概括不同；不能当额外943拍。
- BFMD无实际视频/PTS；作者宣称迁移到0基原广播坐标，但frame/30与具体本地视频的对应无法验证。自动轨迹/姿态、手工声明、备份和活动标注分别记录。只持有标注不会生成可播放Asset或可信Event。
- BFMD许可限制非商用学术研究及再分发；作者代码、标注、原BWF视频各自的来源/许可不混同。

解除方式：取得作者规则或独立人工复核及持权原片，建立准确原片/PTS映射、双语类别映射和整场分组；未知项未确认前保持隔离。逐文件证据见 `docs/library/FINE_BADMINTON_2026_DATA_REPORT.json`、`docs/library/BFMD_DATA_REPORT.json`。
