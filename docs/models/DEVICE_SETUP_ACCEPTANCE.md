# P-07：跨设备模型环境验收

2026-10-19，开发前冻结。P-07 验收部署入口与环境隔离，不等于模型训练或准确率达标。

| 子项 | 目标要求 | 验证方法 / 输入 | 预期结果 | 状态 |
|---|---|---|---|---|
| P-07.1 | CPU 数据准备独立于 GPU 与旧机器环境 | 检查独立 requirements、执行计划与依赖测试 | 无 torch/CUDA、无父环境继承、无用户名/旧盘符依赖 | PASS |
| P-07.2 | 四种环境可选择，冲突框架隔离 | CPU、基础 GPU、姿态/球路、VL 四份计划 | 各自新 prefix；2.7.1/cu128 与 2.8.0/cu128 不混装 | PASS |
| P-07.3 | 参数及路径安全 | 空格/特殊字符、越界、符号链接、已有 prefix、缺依赖测试 | argv 调用不执行 shell；拒绝根外写入和覆盖 | PASS |
| P-07.4 | 容量与安装边界明确 | dry-run、配额/磁盘不足测试 | 700GB 总量、35GB 模型环境及峰值检查；默认无写入，apply 才安装 | PASS |
| P-07.5 | 缺 GPU、环境、权重可读 | doctor 与模拟缺依赖测试 | not_installed/unavailable，不把框架安装等同模型可用 | PASS |
| P-07.6 | WSL 可运行且现有 CPU 数据链不回退 | bash -n、真实 WSL dry-run、已有 CPU 环境读取真实帧 | 实际结果记录；不训练、不下载数据或权重 | PASS |
| P-07.7 | 新设备能理解输入输出及边界 | 部署文档和模块表审阅 | 标明已实现 CLI、缺失 trainer、设备要求、未来交接和旧脚本边界 | PASS |

干净设备联网安装、GPU 新环境安装、GPU 推理/训练与原生 Linux 部署属于另外的未测项目。本轮不以脚本测试替代这些实际运行。

## 实际结果（2026-10-19）

- WSL Ubuntu：`bash -n scripts/models/setup_device.sh` 成功；新测试 **23/23 PASS**，包含真实 argv 子进程特殊字符测试、symlink、失败保留/释放本人锁、拒绝已有锁、依赖版本不符、Windows 路径到 WSL 元数据映射。
- Windows 既有平台虚拟环境：models 全套 **416 项，398 PASS / 18 SKIP**。原有跳过 14 项；新增 4 项为 Linux 进程组/可执行权限和 Windows symlink 权限，均在 WSL 新测试中实际通过。
- [CPU dry-run 原样结果](device-dry-run-20261019.json)：2GB 新峰值预留通过；runtime/models **19,198,700,926 B**；外部 Conda base/package **5,924,496,893 B**；受控存储 **46,350,062,482 B**；磁盘可用 **919,192,240,128 B**。没有执行安装，没有新环境或缓存目录写入。
- 当前 runtime/models 再加 GPU base 的 18GB 峰值是 **37,198,700,926 B**，大于 35GB；新 GPU 重建应被拒绝。不要把本机现有 GPU 环境全部再安装一次。换新计算设备时可选择需要的一个 GPU profile。
- [GPU doctor 原样结果](device-gpu-doctor-20261019.json)：5090 / 32607 MiB / 驱动 610.88 可见；新 VL prefix `not_installed`，模型 `unavailable`。只有 `nvidia-smi` 只读元信息，没有 CUDA 算子或 GPU 任务。
- [CPU 真实片段结果](device-cpu-smoke-20261019.json)：读真实网页快照和同源 AssetManifest，核验原片/PTS，在既有 annotation-env 解码 **1 个窗口、2 帧**，保留源 PTS 和 RGB 哈希；`gpu_used=false`、`model_imported=false`、`training_run=false`。这个旧环境依赖父环境，所以只证明数据链不回退，未证明新 CPU 环境独立安装成功。
- 实现中一次函数插入位置错误导致 `SyntaxError`，修正后重跑 WSL 测试与实际 dry-run 成功；未执行过失败的安装流程。

复现：仓库根运行 `python -s -B -m unittest discover -s tests/models -p test_device_setup.py -v`；使用同一份真实输入运行 [device_cpu_smoke.py](../../scripts/models/device_cpu_smoke.py)。完整参数见 [设备部署说明](DEVICE_SETUP.md)。
