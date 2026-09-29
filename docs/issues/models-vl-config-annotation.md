# VL 官方模块动态编译继承注解语义

状态：**已修复并真实重试验证**，2026-09-29，修复提交 `c609b53`。

首次真实作业 `job-a258df27cc5d4598896dd1d6495c955a` 在 cold_load 报 `AttributeError: 'str' object has no attribute 'from_pretrained'`。适配器的 future annotations 被 `compile(source,...,'exec')` 隐式继承，使固定官方 Qwen3VLForEmbedding 子类注解成为字符串；Transformers4.57.3 从该注解推导 config_class 后无法加载配置。源与权重哈希、依赖和视频解码均已通过，问题不是下载损坏。

修复仅在适配层使用 `dont_inherit=True` 保持上游独立模块语义，并显式离线加载本地 Qwen3VLConfig 实例。没有改固定官方源码、权重、依赖版本或请求。26 项定向 CPU 测试通过；真实 vl-env CPU复现旧错误并验证修复后的类与配置，未实例化模型或初始化CUDA。

同一请求仅用新 job `job-604bf54336ae449a88e004622efd6d1f` 重试一次，Qwen视频/中英文嵌入与CLIP对照均 succeeded，done exit0/compute_stopped=true，GPU归还。原失败及成功均独立保留。具体hash、计时、CPU processor和向量/PTS复核见[真实实验记录](../experiments/models-vl-real-001.md)。准确率和P@K未测；修复成功不扩大模型能力声明。
