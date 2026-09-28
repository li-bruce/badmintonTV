# Library 设计与数据流程

日期：2026-09-28；合同：`docs/CONTRACTS.md` v1.0；所有权仅 library。

## 输入、输出与阶段

1. 一手来源核验：先登记 source candidate；分别记录代码、标注、画面的许可，候选不能作为已下载 Asset。
2. 采集前检查：确定固定 owner 目录、URL、有限 max_bytes、预期 SHA（如发布者提供）、下载/解压/派生的峰值；检查 owner 300GB、总项目700GB和实际磁盘空间。
3. 配额预留：owner 内共享 SQLite 事务账本（本任务 Windows 单环境，禁止 Windows/WSL 混用同一账本）；BEGIN IMMEDIATE 下统计现有文件和活动预留。下载写入 `.part`，完整验证后同目录原子改名；已存在文件不覆盖。
4. 网络取回：HTTP(S) 正常公开下载，默认 TLS 验证；流式实际字节上限，不信任 Content-Length。断点须匹配 ETag/Last-Modified 和 Content-Range；无安全验证器时失败保留，不盲目拼接。错误、进度与 hash 写入记录；不绕过登录/付费/限流。
5. 探测：ffprobe 保存版本/流/fps/time_base/时长；ffmpeg CPU 全段解码验证。未探测文件不发布 Asset。保留 VFR 的逐帧 PTS 索引；原文件只读共享。
6. 去重和划分：SHA-256 去重相同字节；人工 canonical match_id 合并同场剪辑、回放、重上传。持久 split registry 按 match_id 固定划分，未知场次保持 unassigned；不能仅按文件名随机划分。
7. 标注：原始文件和许可原样保存。转换必须保存源行号/帧率或PTS/版本依据；无法对齐视频时只交付原标注，不造 Event。网前球不能映射展搓/收搓，步法细类保持 unknown。
8. 交付：`D:/video/data/handoff/assets.v1.json`、annotation inventory、来源/下载/探测报告及小型仓库副本。相对路径以 `D:/video` 为根；其他模块只读，不复制原片，不直接写平台DB。

## 实现边界

纯 Python 标准库核心，避免训练依赖。`packages/library` 提供配额、下载、探测、manifest；`scripts/library` 提供 CLI/小样采集。首次目标预算100MB视频+少量标注，绝不自动扩展到300GB。runtime/library 5GB，本轮优先复用现有 Python 和 render 提供的 FFmpeg，可独立轻量环境但不安装公共Conda。

配额保守计数：现有文件（含part、ledger、临时文件）+活动预留全额，允许双计避免低估；每次写入仍验证流字节上限。崩溃遗留预留不自动释放，人工核实无运行进程后显式释放。跨 owner 由固定配额防止冲突，读取全根占用作额外守门，禁止借50GB余量。

## 验证与限制

本地HTTP测试覆盖超限、失败记录、HTTP Range/校验器、错误范围、SHA冲突、不覆盖与并发配额；manifest覆盖路径穿越、重复hash和整场划分。真实下载另作实测，不把合成测试当视频识别成功。首次小样只验证素材和解码，球员身份/细动作需复核；未取得的双打/经典比赛明确保持候选。
