# Models 模块设计 v0.1

日期：2026-09-28；任务 01a0e88b-416f-7ca2-bfec-c09ec1462866；分支 work/models。

## 接口与流程

遵守 docs/CONTRACTS.md v1.0。纯标准库入口 `python -m packages.models run --request REQUEST --result RESULT`，不让平台导入 torch。管理员设置 `BTV_STORAGE_ROOT`（Windows D:\video，WSL /mnt/d/video）；请求 output_dir 只允许 models 下的相对路径，源资产只读，以 asset_id/relative_path 引用。结果原子发布；stdout 为带 job_id/seq 的 JSONL；失败和未安装均有 result 与非零返回码。预测不改写人工事件。

模型注册表先交付 query_parse（受限规则/兼容端点/本地 Qwen）、pose、video_embedding、movement_classification。依赖和权重缺失返回 not_installed/blocked。只报告实际完成的阶段，未知总量使用 null。模型输出中没有经人工确认的 player_id；track_id 只在一次镜头内部有效。

查询流：中文文本 → 规则或 LLM → 严格 QuerySpec 验证 → query artifact；解析不能变成视频事件或执行代码。兼容端点仅接受管理员配置，密钥环境变量引用，不写日志；默认仅 loopback，可显式配置远程端点。仅发送中文查询与固定 schema，不发送媒体。

视频流：Asset 校验 → 有界时间窗解码 → 预训练姿态/视觉特征 → 原始特征 artifact + 速度/显存报告 → 可解释候选预标注（若证据不足不产生细标签）→ 平台人工审核。特征不是 Event：姿态坐标单独保存，不能为了满足 events 字段造动作。模型回传 events 可为空。

## 实施顺序与验收

1. 先检查现有 WSL Conda；复用可用安装，创建独立 prefix。记录原生已有 base 的实际占用但不归咎为本项目新增。项目缓存、环境写 D:\video\runtime；HF/torch/临时文件写受控目录。
2. Python 3.11 + 官方 PyTorch CUDA 12.8 wheels 为首个兼容候选。验证 GPU matmul、conv、attention、torchvision NMS（如使用）而不只检查 cuda_available。没有必要不安装 MMCV 编译链。
3. Qwen3-0.6B 为小模型中文 QuerySpec 候选；规则实现用于离线合同基线；实际 LLM 输出需要 schema、序列语义核验。未配置端点不能声称端点验证成功。
4. 优先采用无需 MMCV 的轻量姿态候选，短真实视频实测；MMPose/RTMPose 的复杂编译兼容另记状态。姿态框架成功不等于羽球细动作识别成功。
5. A 视频召回、B 骨骼时序、C 融合使用同一整场划分；缺人工真值时只做预训练前向与预标注。轻量骨骼分类训练必须有完整标签与独立比赛；不得无标签盲训。

## 存储与交接

models 最大180GB；runtime 公共15GB、models35GB、其余20GB保留。下载前统计、原子独占预留、检查物理空间；流式下载硬字节上限；不覆盖已有数据。先有限小样，首轮预计模型/缓存不超过6GB，runtime不超过20GB。原片从 data 只读，绝不复制比赛。

交接：configs/models/catalog.json；docs/models/HANDOFF.md；D:\video\models\handoff 下结果、manifest、查询与特征文件（完成才发布）。平台仅消费 JSON，不依赖训练框架。安装来源与版本、实验失败和真实限制逐次记录在 environments/models* 与 docs/experiments/models-*。

## 当前事实与风险

首次普通沙箱 WSL 返回 E_ACCESSDENIED，已授权提升后只读成功。5090 32607MiB、driver591.86，GPU已用1658MiB，未终止任何进程。发现 /home/ubuntu/miniforge3，下一步核验。D盘可用968079273984 bytes（瞬时值）。个人素材与细标签真值尚未交接，不能报告精度/召回。
