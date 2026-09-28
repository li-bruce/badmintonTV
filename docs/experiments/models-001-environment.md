# 实验001：隔离环境与协议

2026-09-28。设计先于实施，来源见 docs/models/SOURCES.md。

初查：普通沙箱WSL E_ACCESSDENIED；授权只读成功。Ubuntu uid1000，kernel6.18.33.2-microsoft-standard-WSL2；5090 32607MiB、driver591.86、初始已用1658MiB，不终止其他用户进程。WSL提示localhost代理未映射，但官方PyPI/PyTorch/HF小文件可连接，未绕过网络安全配置。

发现已有 /home/ubuntu/miniforge3 conda25.9.1、base Python3.12.12，history证实conda-forge构建。现有env deepseek-ocr/embedding/vllm均未修改。整体34911557859 bytes，其中env28987060966、pkgs5756364977；base+pkgs约5.925GB保守计入公共15GB。没有新装Miniforge，不伪造installer hash。

新prefix /mnt/d/video/runtime/models/env，Python3.11.16；固定torch2.7.1+cu128/vision0.22.1；安装正在进行，实际GPU算子未测不能称已就绪。初次将pycache放DrvFS导致Python启动/遍历缓慢；改为PYTHONDONTWRITEBYTECODE=1。其他owner容量改为固定配额保守占满计数，避免跨OS链接遍历与并发变化。

Qwen首次下载因容量扫描耗时调试中收到本任务SIGINT，已保留46,137,344 bytes partial；随后Range连接超时。新下载器绑定source metadata，旧无metadata partial改名保留，不能默默覆盖。网络中断不同于模型/显存失败。

协议与规则在Windows标准库测试已运行，非模型精度。最终算子、依赖锁与完整测试结果将在handoff中记录。
