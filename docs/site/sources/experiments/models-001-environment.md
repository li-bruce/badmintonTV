# 实验001：隔离环境与协议

2026-09-28。设计先于实施，来源见 docs/models/SOURCES.md。

初查：普通沙箱WSL E_ACCESSDENIED；授权只读成功。Ubuntu uid1000，kernel6.18.33.2-microsoft-standard-WSL2；5090 32607MiB、driver591.86、初始已用1658MiB，不终止其他用户进程。WSL提示localhost代理未映射，但官方PyPI/PyTorch/HF小文件可连接，未绕过网络安全配置。

发现已有 /home/ubuntu/miniforge3 conda25.9.1、base Python3.12.12，history证实conda-forge构建。现有env deepseek-ocr/embedding/vllm均未修改。整体34911557859 bytes，其中env28987060966、pkgs5756364977；base+pkgs约5.925GB保守计入公共15GB。没有新装Miniforge，不伪造installer hash。

新prefix /mnt/d/video/runtime/models/env，Python3.11.16；固定torch2.7.1+cu128/vision0.22.1，安装已完成且pip check通过。初次将pycache放DrvFS导致Python启动/遍历缓慢；改为PYTHONDONTWRITEBYTECODE=1，旧pycache保留并计runtime。其他owner容量改为固定配额保守占满计数，避免跨OS链接遍历与并发变化。

Qwen首次下载因容量扫描耗时调试中收到本任务SIGINT，已保留46,137,344 bytes partial；随后Range连接超时。新下载器绑定source metadata，旧无metadata partial改名保留，不能默默覆盖。网络中断不同于模型/显存失败。

协议与规则在Windows标准库测试已运行，非模型精度。

后续实际算子：torch2.7.1+cu128/torchvision0.22.1+cu128、Python3.11.16、CUDA12.8、cuDNN90701，设备capability12.0且compiled arches含sm_120。matmul、conv2d、bf16 SDPA、CUDA NMS、ROI Align全通过；算子段1.097s/峰值8,974,848bytes。这是合成算子验证而非真实视频识别。完整原样数据见environments/models-gpu-smoke.json。

安装失败也保留：torch安装成功后首次bootstrap因运行期间脚本被编辑导致shell继续读取错位内容（推断）退出1，随后使用独立脚本complete_environment.sh继续剩余依赖。PyAV14.4.0官方只有sdist，实际因缺pkg-config/FFmpeg7开发依赖构建失败；未安装全局编译链，改选官方15.0.0 cp311 manylinux_2_28 wheel并加only-binary。之后执行脚本保持不修改直到进程退出。

最终环境完整包清单/Conda URL锁、可移植pip锁及复现步骤见environments/models-*.txt和docs/models/ENVIRONMENT.md。GPU原始报告已进Git；权重不进Git，固定来源/revision/hash小清单在configs/models/weights-lock.json。Qwen/pose/CLIP均只从已校验本地权重加载，下载与推理解耦。WSL官方大权重URL超时后使用Windows stdlib同官方URL下载成功，未改代理/DNS，详情独立issue。

2026-09-28安装完成后du快照（后续小型JSON/overlay另计）：runtime/models=7,282,586,968bytes，runtime/shared=1,081,355,680bytes，models=2,409,653,268bytes，D盘可用955,528,028,160bytes。models<=180GB、runtime/models<=35GB；shared新增1.081GB加既有base+pkgs约5.925GB低于15GB；其余runtime20GB保留。所有数字为十进制bytes，无数据删除。最终交接容量以status最新快照为准。
