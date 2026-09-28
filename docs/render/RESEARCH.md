# Render 技术与来源核验

核验日期：2026-09-28。范围：按仓库 v1.0 Timeline + Asset 合同做本机 CPU 渲染；此文是官方资料调查和实施建议，不代表相关版本已经安装或真实样片已经通过。已阅读 AGENTS、简版计划和 PRODUCT_CONTEXT / ARCHITECTURE / CONTRACTS / EXECUTION_PLAN / ACCEPTANCE。只查阅一手页面，未下载软件、权重或素材，未安装插件；无新增媒体容量占用。

## 选型结论

| 组件 | 核验的上游版本 / 许可 | 本轮决定 |
|---|---|---|
| FFmpeg / ffprobe | 官方下载页列 9.0.2，2026-09-18；也列维护分支 8.1.3。FFmpeg 基础 LGPL-2.1-or-later，启用 GPL 部分后构建整体受 GPL 约束 | 必选外部进程；CPU libx264 + AAC。实际安装版本、构建参数和哈希以运行记录为准，不因为官网最新版就自动升级现有可用环境 |
| OpenTimelineIO | 发布页首条 v0.18.1（页面标 pre-release），文档 latest 为 0.19.0.dev1；v0.18.1 LICENSE 为 Apache-2.0 | 可选导出，v1.0 Timeline JSON 继续作为业务工程真源；缺包不阻塞 MP4 |
| Auto-Editor | 发布页 31.6.0；该标签源码 LICENSE 为 Unlicense | 暂不纳入运行依赖。只评估以后辅助建议区间；不替代人工确认、不自动裁掉准备/结果阶段 |

版本及许可来源：[FFmpeg 下载](https://ffmpeg.org/download.html)、[FFmpeg legal](https://ffmpeg.org/legal.html)、[OTIO releases](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/releases)、[OTIO v0.18.1 LICENSE](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/v0.18.1/LICENSE.txt)、[Auto-Editor releases](https://github.com/WyattBlue/auto-editor/releases)、[Auto-Editor 31.6.0 LICENSE](https://github.com/WyattBlue/auto-editor/blob/31.6.0/LICENSE)。

## FFmpeg 接入要点

以下过滤器事实来自 [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html)：`scale` 的 `force_original_aspect_ratio=decrease` 可约束画面进入目标框，`force_divisible_by=2` 使尺寸适合偶数要求；新版本 `reset_sar=1` 会结合 DAR 输出方形像素。`atempo` 允许 0.5–100，超过 2 可能跳样，可链式组合。`subtitles` 依赖 libass，`fontsdir` 补充字体，`original_size` 影响 ASS 字体缩放，`wrap_unicode` 还取决于 libass/libunibreak 构建。

本项目据此采用的实施策略：

- 默认 contain：把完整比赛画面按显示宽高比缩入 1080×1920，再居中 pad 为底色；上下留白可放标题和源时间。需要模糊背景时仅模糊另一路背景，前景仍完整 contain。显式 crop 窗口才允许裁切；不把人物居中当作球、对手和脚部均可见的保证。
- 先探测 SAR、rotation、实际 PTS、音轨。旧版本没有 `reset_sar` 时，先按源 DAR 规范化方形像素，再缩放/pad；直接 `setsar=1` 可能改变非方形像素素材的观看比例。
- 统一逐段输出 fps、尺寸、像素格式、音频采样率与布局后再拼接。视频变速按 `(PTS-STARTPTS)/speed`；音频裁切并归零后用乘积等于 speed 的 atempo 链，每级限制 0.5–2。0.25 倍速可用两级 0.5。无音轨或 mute 用等长静音，不能让 concat 流结构不一致。
- 字幕以输出时间为基准生成，不能复用源片时间码直接烧录。优先 UTF-8 ASS/SRT、固定版式和可读中文字体；字体来源/许可单列。字幕文件名由程序生成；过滤器路径与用户标题分别安全处理，不能把任意标题当过滤器表达式。避免字幕遮挡前景比赛区域。
- `-progress pipe:1` 提供键值序列，批次以 `progress=continue/end` 结束，`-stats_period` 控制间隔。适配器转换为合同 JSONL。进度 `end` 仍需结合返回码、产物存在和 QA 才能认定成功。[FFmpeg CLI 文档](https://ffmpeg.org/ffmpeg.html)
- 取消由平台发取消请求，渲染器只处理自己创建的 FFmpeg 进程；取消后不发布半成品 Artifact。结束编码后 ffprobe 检查流与时长，全文件解码检查损坏，再原子发布产物。

这些建议仍需运行验证，尤其非零首 PTS、VFR、fractional fps、非方形像素、旋转元数据、慢放音轨尾端、中文字体和 Windows 路径。官方在线文档每夜生成，可能含本机没有的参数，应以本机 `ffmpeg -version`、`-buildconf`、`-filters`、`-h filter=scale`、`-h filter=subtitles` 为能力证据。[文档版本说明](https://ffmpeg.org/documentation.html)

## 许可与交付边界

libx264 是 FFmpeg legal 特别指出的 GPL 外部库；不能把含 libx264 的可执行文件记录成纯 LGPL 构建。使用外部 CLI 不等于免除随程序分发 FFmpeg 二进制时的许可义务。保留构建来源、版本、配置、许可证和对应源码链接；不采用 `--enable-nonfree` 构建作为默认可再分发组件。源码许可、视频画面权利、字体许可和编码相关专利分别核查。[FFmpeg legal](https://ffmpeg.org/legal.html)

FFmpeg 官方只提供源码；官网所列 gyan.dev / BtbN 为第三方 Windows 构建来源，不应称作 FFmpeg 官方二进制。后续安装若选择它们，另记录确切下载 URL、提供方校验值/本地 SHA-256、实际启用编码器和许可证。[下载说明](https://ffmpeg.org/download.html)

## OTIO 的可选互操作设计

OTIO 描述剪辑、轨道、时间和外部媒体引用，不内嵌音视频，适合保存可编辑剪辑关系。[官方概览](https://opentimelineio.readthedocs.io/en/latest/)

建议保持 `asset_id`、原始毫秒区间、event_ids、审核状态、合并来源和 speed 在 metadata 中；ExternalReference 只引用经过受控路径解析的源媒体。RationalTime 可表示 `value/rate` 秒，TimeRange 表示起点与时长。LinearTimeWarp 的 `time_scalar` 并不会自动改变附着 item 的 duration，不能只挂一个 effect 就假定导出工程时长正确；写入/重读后须实测时长、源区间和速度的 round-trip。[官方 schema](https://opentimelineio.readthedocs.io/en/latest/tutorials/otio-serialized-schema.html)

本轮可先不安装 OTIO。未来安装锁定版本，记录在 render 独立环境；不将完整 OTIO 对象作为平台 DB 合同，不让 NLE 特有效果影响 FFmpeg 成片与源映射。Apache-2.0 声明只针对核验标签源码，不自动覆盖第三方 adapter 或所引用媒体。

## Auto-Editor 评估与暂缓理由

Auto-Editor 官方描述按音量、运动和字幕等信号自动编辑，提供切片前后 margin、预览、时间线/编辑器导出；当前仓库是 Nim 工程，不能假定旧 Python API 仍适用。[官网](https://auto-editor.com/)、[官方仓库](https://github.com/WyattBlue/auto-editor)、[Cookbook](https://auto-editor.com/docs/cookbook)

本项目判断：转播解说/观众声音不等于击球，静音不等于无有效准备；镜头运动也不等于特定网前手法。以这些规则自动删片可能破坏证据完整性。因此首版按已确认 Timeline 编码，并保留可接入“区间建议”的接口。没有真实羽球对照数据时，不声称 Auto-Editor 能识别回合、展搓/收搓、去除回放或智能跟随羽球。

31.6.0 源码 Unlicense 不代表它分发包里的所有编码库均为同一许可，发布记录包含捆绑 x264/x265 等库的更新。本轮未下载/运行 Auto-Editor，不估算其本机速度与内存；后续若评估须单独记录依赖许可、磁盘峰值、误删区间和人工复核成本。[版本发布记录](https://github.com/WyattBlue/auto-editor/releases)

## 实测接力清单

1. 记录实际 FFmpeg/ffprobe 路径、版本、构建参数；小样验证 libx264/AAC/字幕可用。
2. 合成技术烟测覆盖有/无音轨、混合 fps/分辨率、0.5 与 0.25 倍速、字幕、取消与失败，不计为业务验收。
3. 等 library handoff 的真实 Asset 和人工区间后，2–3 段网前案例按 contain 完成全程解码与人工观看，细手法维持 unknown，除非获得相应复核证据。
4. QA 将自动解码/流时长检查和人工音画同步、构图、动作上下文结论分开；只解码成功不能写“已人工观看/音画同步通过”。
