# Render 初版设计（合同 v1.0）

2026-09-28；模块所有者 render；不持有业务数据库。设计先于实现。

## 输入和数据流

平台保存可编辑 Timeline 与 Asset → CLI/Python 校验 → 原片路径/哈希与 ffprobe → 时间线规范化 → 逐段 CPU 编码 → 拼接 → 全解码 QA → 原子发布 artifacts/result。`segments` 数组即人工排序；`in_ms/out_ms` 是原片毫秒，直接保留准备、触球、结果窗口，不按声音自动删掉停顿。

入口 `python -m packages.render run --request request.json --result result.json`。request 遵循公共字段，`operation=render`，`parameters.timeline`；Asset 严格使用顶层 `assets` 数组；`output_dir` 是共享根下 `render/...` POSIX相对路径（遵循主任务最新协调修订）。环境/二进制/存储根只由 CLI 参数或管理员环境变量指定，不能由 request 注入任意命令。Python `render(request, config, emit, cancelled)` 返回合同 result。

使用本模块无依赖校验器，已对平台统一合同提交8900958完成实际CLI兼容。`segment.crop={x,y,width,height}` 遵守平台定义为0..1归一化源窗口。兼容扩展集中在 `parameters.segment_options[segment_id]`：`subtitles=[{start_ms,end_ms,text}]` 为片段输出相对时间，`editorial_review`记录来源，显式 `replay_group_id` 才做回放去重；`parameters.deduplicate_replays/merge_overlaps` 默认 false。去重保留 event_ids 与 excluded segment 记录；仅同源、同速、同布局/音频/标题、无字幕的相邻重叠段可合并。审核保守汇总：任一输入unreviewed则合并仍unreviewed，完整保留各输入区间/状态/审核来源；只有全部覆盖输入均明确human confirmed，QA才可报告human_confirmed_segments。回放去重聚合事件时也保留同样的不确定性。无视觉自动去重推断。输出Timeline为纯合同结构，编辑扩展和原始输入记录放source_map。

## 编码和版式

默认 1080×1920、30fps、H.264 yuv420p、AAC 48kHz stereo；CPU libx264，有限线程，不用 GPU。contain 将完整源画面等比放入竖屏深色背景，留上方标题与下方来源/字幕空间；不切球场、对手、脚。crop 必须显式窗口，目标自动跟随暂不可用。文本用生成 ASS、固定样式、转义内容，不接受用户 filtergraph。预览使用相同流程，`parameters.preview=true` 实际编码360×640，只写入QA/source_map的effective_output；可复用Timeline工程始终保留1080×1920正式规格，重新加载可再次预览或正式导出。

统一采样到输出fps，片段时长按最接近完整输出帧量化；源映射报告理想时长与量化误差。慢放视频setpts与音频atempo成对处理，atempo分解至0.5–2；mute/无音轨输入补等长静音，源音轨不足补尾静音。音轨先按共同零点补头静音再变速，不各自归零。中间段用MOV/H264/PCM，最终只编码一次AAC，避免每段AAC priming累积；显式concat duration，QA检查双流零起始PTS。无淡入淡出改变原时间边界。已测0.5x脉冲约38ms瞬态偏移，源音画感受仍须人工观看/听音验收。

## 输出和执行

只读 library 原片；所有媒体、缓存、日志和成片放 `D:\video\render`。产物：MP4、规范化 timeline.json、source_map.json、qa.json，均带 hash/size/producer/created_at。JSONL 以顺序 seq 报告真实 FFmpeg 输出时间；stderr 保留诊断；CLI returncode 0 只对应 succeeded。取消文件（受控 render 子路径）或 SIGINT/SIGTERM 终止本任务 FFmpeg 子进程，返回 cancelled；故障保留带 partial 标记中间文件，绝不列入成功 artifacts。不自动清理已有文件。

FFmpeg 缺失返回 blocked/not_installed；未知 Asset/路径穿越/未确认片段/越界/不支持配置返回 failed。兼容参数 `research_preview=true` 经主任务明确接受，用于已授权本地研究样片，允许unreviewed但强制画面标记“待人工确认·本地研究样片”，不接受rejected。`qa.manual_review` 初始 pending；human_confirmed_segments只有confirmed且editorial_review.reviewer_type=human才true。选片审阅、技法真值和发布资格分别报告。合成输入标 synthetic，不把技术成功当真实业务通过。

## 容量与验证

render 40,000,000,000 bytes；runtime/render 5,000,000,000 bytes；共享根700,000,000,000 bytes。render 使用独占原子锁串行化内部写入与预留账本，检查已有占用和本次峰值。逻辑上分别校验共享实占+新增峰值、render实占+新增峰值+其余owner610GB分配上限（覆盖不可直接统计的环境），两者不相加。物理空闲只比较本次真实新增峰值+256MB余量，固定分配额度不是活动磁盘预留；未知其它活动预留显式记null。编码监控本次增长不得超过预留。异常退出的锁不擅自移除，管理员核实进程结束后可处理。工具安装单独受控下载且记录上限/解压峰值/校验。

先测试纯合同/映射/路径/取消，再合成有声+无声、混合fps/尺寸、0.5x慢放，完整解码并核对时长/帧数/音频。真实阶段等待 library 的只读 manifest 与人工复核窗口；选2–3网前段保留完整动作上下文，细手法保持 unknown。产出观看记录与可复现命令，不依赖模型。
