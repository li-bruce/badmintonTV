# 模型与环境来源记录

核验日期2026-09-28，均一手来源。没有安装额外Codex技能/MCP；使用现有exec/web和项目代码工具。

| 组件 | 来源与固定版本 | 用途与许可边界 |
|---|---|---|
| Miniforge | [官方仓库](https://github.com/conda-forge/miniforge)，已存在conda25.9.1、history显示2025-10-26 conda-forge constructor | 复用base执行新prefix创建；不更新base，不动用户既有env。未重复下载安装器，因此不伪造安装器checksum |
| PyTorch | [2.7 Blackwell说明](https://pytorch.org/blog/pytorch-2-7/)、[历史安装矩阵](https://pytorch.org/get-started/previous-versions/)，torch2.7.1+cu128/torchvision0.22.1+cu128 | 官方CUDA12.8 wheel候选，实际算子实测另记；不装Linux NVIDIA驱动 |
| Qwen | [Qwen3-0.6B官方模型卡](https://huggingface.co/Qwen/Qwen3-0.6B)，transformers4.51.3/accelerate1.6.0 | Apache-2.0模型卡；只解析文本。下载固定revision，LFS SHA256+小文件git blob核验写weights-manifest。0.6B能否保留复杂条件必须实测 |
| Torchvision姿态 | [官方Keypoint R-CNN文档](https://docs.pytorch.org/vision/stable/models/generated/torchvision.models.detection.keypointrcnn_resnet50_fpn.html)，v0.22.1 COCO_V1 | BSD-3-Clause代码；COCO预训练权重与底层图像条件独立；原比赛视频版权不能由代码许可推断。只COCO17预标注，无拍/球/身份 |
| CLIP | [OpenAI官方模型卡](https://huggingface.co/openai/clip-vit-base-patch32) | 原模型用于图像文本表征；短窗抽帧均值是本项目弱基线，无时序顺序、中文细手法未验证；MIT upstream记录与比赛画面许可分开 |
| MMPose | [官方仓库](https://github.com/open-mmlab/mmpose) | 仅候选核验，未安装；没有MMCV/Blackwell兼容实测，不能标ready |
| PyAV | [官方PyPI 15.0.0](https://pypi.org/project/av/15.0.0/)，cp311 manylinux_2_28 wheel | 源PTS解码；14.4.0源码构建失败后改15.0.0二进制，无全局FFmpeg开发库安装。wheel SHA256=e2a5f0d1817ab73370fdb35e2e2ecd4c2e5a45d43b8d96d5ae8dfe86098fb9b3；项目代码/所打包FFmpeg许可分别核验 |
| 视频 | library发布D:/video/data/handoff/assets.v1.json及assets.doubles.v1.json | 4条FBBench和1条DroneBD真实片；来源、hash、画面rights与标注许可由Asset分别保留；模型不更改unknown版权，不把双打camera1与未对齐顶视CSV合并为真值 |

安装完成后的原样锁定数据在environments/models-conda-explicit.txt、models-pip-freeze.txt；可移植pip安装锁另存models-requirements-lock.txt。完整权重来源、固定revision、每文件size/hash/license在configs/models/weights-lock.json，原始manifest仍在D:/video/models/weights/*/weights-manifest.json。环境、算子报告与真实推理报告互不替代。
