# 真实小样采集与解码报告

运行日期：2026-09-28；性质：真实赛事研究数据的获取、完整性、解码和交接验证，不是模型识别准确率测试。

## 已运行结果

按固定FBBench提交 `ff86093a51efdf9a243a0635704952d404e99e52` 从发布者正常公开下载入口取得4段视频，逐个SHA-256匹配HF Git-LFS OID。另取得原始球种QA 200条、回合描述QA 250条、ShuttleSet Antonsen–Axelsen年终总决赛第1局CSV 366条（总816条原标注，不是816条已配视频训练样本）。小样仅与其中4条QA有直接video_uid联接。保留原文件与各自README/许可。

| video_uid | 视频字节数 | 时长ms | 解码帧数 | 完整PTS观察 |
|---|---:|---:|---:|---|
| video_000001 | 642,017 | 4,634 | 139 | 每帧512 ticks |
| video_000002 | 591,764 | 5,367 | 161 | 每帧512 ticks |
| video_000003 | 499,766 | 3,900 | 117 | 每帧512 ticks |
| video_001951 | 669,106 | 6,000 | 180 | 每帧512 ticks |

共2,402,653视频bytes（2.403十进制MB），总约19.901秒。全部1280×720、30/1fps、time_base=1/15360，H.264。每个原视频通过FFmpeg9.0.2 CPU全段解码；PTS不是用帧号除30临时杜撰，而是ffprobe逐帧导出整数best_effort_timestamp。时长按源流duration向上取整ms。没有20秒连续回合；video_001951虽来自回合QA，也只能声明6秒片段，不能保证包含完整准备与结果。

## 画面检查

只读提取每段1秒处一张JPEG，路径 `data/qa/stills/<video_uid>.jpg`，四张合计465,723 bytes。模型已逐张查看：均可见真实羽球场地和两位场上运动员，后场转播视角、单打。前3段计分牌文本为 `CHOU T.C.` / `CHRISTIE`，同一Vantaa场馆布局；第4段为 `LEI L.X.` / `AXELSEN`，背景Changzhou。仅记录可见文本，不以人脸识别确认身份；players待人类确认，provenance保存scoreboard_names。

前3段显然存在同场来源可能，不能作为独立比赛划分。本轮仍用unknown/unassigned共同隔离；没有假设具体年份、轮次或原整场偏移。静态帧检查不能确认动作时序，也不能确认展搓、收搓、小跳启动。下游应做动态审片。

## 容量与错误

下载前50MB批次峰值预留，每个下载再独立预留有限max_bytes和64KiB记录余量；没有解压、安装依赖或复制原片。第一次因Windows扫描WSL环境链接失败，在写入视频前停止；修复后全部完成，详见独立问题MD。数据/记录/PTS初次占3,746,937 bytes；含后续QA图片约4.22MB，最终精确值以capacity报告快照为准。runtime/library没有新增环境、模型、缓存。

共享runtime不透明时按其70GB完整分配上界计入总账；该数不是物理实际用量。data300GB上限和全局700GB仍执行，50GB余量未借用。

最终实测data为4,221,747 bytes，活动预留0。修复后幂等重跑10来源文件全部verified_existing、0新下载、0错误，原片和probe保持不变；handoff可变清单有前后hash审计。完整测试53/53通过、无跳过，包括真实Windows junction边界；4个真实Asset通过main集成8900958的共同Pydantic合同，原片/PTS哈希再次通过。详细机器记录见 `docs/library/VALIDATION.json`。

## 交接和限制

`D:/video/data/handoff/assets.v1.json` 是可导入合同清单，原路径在 `data/raw/finebadmintonbenchmark`，其他模块只读。annotations、downloads、splits、capacity另有同目录v1 JSON；小型仓库证据副本放 `docs/library/handoff/`（不含媒体/原标注）。已通知主协调、platform、models、render的真实路径。

画面rights.status=unknown、allowed_uses为空；官方研究发布者公开提供样本，未绕过访问限制，但独立赛事画面公开再分发授权链未提供。Apache-2.0数据卡和ShuttleSet仓库MIT仅作为分别记录的标注/仓库证据。林李经典比赛与双打目前是已核验官方来源候选，未取回全片；个人录像未提供、未测试。没有声称合法商用、真实细动作检索达标或完整赛事泛化通过。
