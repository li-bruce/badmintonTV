# 公开素材权限和时间对齐缺口

记录日期：2026-09-28；影响：真实样本可作取回/探测联调，不能据此宣布可商用、已完成细标签真值或整场泛化评测。

## FineBadmintonBenchmark

一手入口：https://huggingface.co/datasets/iLearn-Lab/FineBadmintonBenchmark 。已核验版本 ff86093a51efdf9a243a0635704952d404e99e52、gated=false；单条mp4和QA JSON可通过正常resolve URL取得。发布者dataset card声明Apache-2.0；赛事原画面版权/再分发链未另行提供。因此视频rights.status=unknown，allowed_uses为空；原标注记录Apache-2.0声明，仓库/数据许可不替代原片许可。仅进行用户授权本地研究，不自动发布视频。

QA字段只有video_uid、问题、选项和答案；没有原整场canonical match_id、原场起点、击球时间或确认后的球员ID。所有小样split=unassigned，归入共同隔离组。后续必须取回原场来源映射，按整场统一分组，检查与Finebadminton-20K训练库的源场重合后才能用于评测。

QA中的block/net shot和ShuttleSet放小球、擋小球，均不证明net_zhan_cuo/net_shou_cuo；移动描述也不证明backward_small_hop_start。原标注保留，不生成伪细标签或假接触时刻。

## ShuttleSet

一手入口：https://github.com/wywyWang/CoachAI-Projects/tree/main/ShuttleSet 。原CSV可直接从固定commit的raw URL取回；保留仓库MIT LICENSE和README，未发现单列标注例外许可。所选Antonsen–Axelsen年终总决赛CSV未配套取回原赛事视频，不能将其时间码绑定到FBBench任意视频。事件转换暂不执行，避免错误对齐。

## BFMD / TrackNet / 经典比赛

分别核验记录见 docs/library/SOURCES.md；入口受限时只登记候选和具体状态，不使用cookies破解、付费绕过或搬运站替代。BFMD作者说明不再提供完整原视频；TrackNet的代码/权重MIT不说明原轨迹包及广播视频的许可。官方BWF/Olympics播放器是观看来源，不等于自动获得本地下载/公开剪辑权。

下一步：与合法持权素材或用户个人录像建立原片映射；争取原比赛ID/时间轴和许可证据。没有这些外部输入也可继续完成本地导入、探测、人工标注和受控研究样片。
