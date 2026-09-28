# WSL权重下载网络差异

2026-09-28。WSL启动提示localhost代理未映射。官方PyTorch wheel大文件可逐项下载（实测速率约1.8–5.9MB/s），但Qwen权重重定向与Torchvision官方模型URL数次连接超时。诊断 curl -4 --connect-timeout10 官方Torchvision URL失败；getent返回198.18.0.13。不修改DNS/代理、host映射或防火墙。

对同一官方URL使用Windows已有Python标准库下载成功，HTTP200/237034793 bytes，官方hash前缀fc266e95与全SHA256记录到weights-manifest。Windows仅下载并写D:/video/models，WSL继续在隔离环境做推理；没有替代第三方权重源或绕过登录。

Qwen旧46,137,344-byte partial源meta尚未建立，明确改名保留为model.safetensors.partial.unverified-80edef1f，记录未删除。新partial绑定固定revision/source/hash/size，有界续传；不把未完成权重列为ready。

状态：可通过同源Windows下载规避WSL连接差异（非绕过访问控制）；根因尚未修改或确认。模型执行保持offline，不能在from_pretrained隐式联网。
