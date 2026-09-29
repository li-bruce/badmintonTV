# 连续源帧姿态诊断

`torchvision-continuous-pose@0.1.0` 使用既有 COCO17 Keypoint R-CNN 权重，
在旧 WSL `/mnt/d/video/runtime/models/env` 执行。通过标准
`python -m packages.models run`，operation 为 `pose` 或 `analyze`。

参数为 model_id、可选 model_version=0.1.0、start_ms/end_ms、
score_threshold（默认0.7，范围0.1–0.99）。单 Asset、最多3秒、100帧、
100M累计像素；逐帧使用原始 PTS/rational time_base，不在舍入毫秒网格重采样。
输出真实 bbox/keypoints_xyv/keypoint_scores，track_id/player_id保持null。
解码为CPU PyAV；不宣称NVDEC。源hash、用途和研究诊断标记传播到产物。

输出 features.json、report.json，失败单独failure.json；各阶段计时和CUDA
allocator峰值独立记录。连续姿态只是BST潜在输入；需要同PTS球点、场地标定、
稳定匿名track及击球窗口审查后才可分类。替换作者MMPose为torchvision意味着
输入分布发生变化，不能把前向成功称为论文精度复现。

16项CPU测试已通过（明确mock模型/原片，不作为识别证据）；实跑记录见
docs/experiments/。运行需通过Windows同账本GPU窗口/worker与WSL bridge。
