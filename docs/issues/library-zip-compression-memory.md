# library：拒绝可能无界分配解压缓冲的ZIP压缩方式

- 状态：已修复；来源为主协调追加独立review。
- 问题：限制`ZipExtFile.read(65536)`返回字节数不足以限制所有压缩器的内部解压缓冲。Python 3.12的BZIP2/LZMA路径未向解压器传入输出上限，可在一次小read中展开远大于请求长度的数据，构成内存耗尽风险。
- 最小修复：选中成员仅允许`ZIP_STORED`和`ZIP_DEFLATED`；其他压缩方式在`container.open`及任何解压之前返回明确`unsupported_compression`。只读inventory仍可报告这些格式的元数据。
- 验证：新增真实BZIP2、LZMA本地ZIP夹具各1项，mock禁止打开成员，确认拒绝发生在解压前，失败记录保留错误code，原ZIP hash不变，无partial/成品/遗留锁或活动预留。
- 完整回归：`C:/Users/USER/miniforge3/python.exe -m unittest discover -s tests/library -q`，77/77通过、0跳过，9.151秒；ZIP测试24项。原STORED/DEFLATED、CRC、配额和防覆盖检查继续通过。
- 范围：无新下载，不改任何共享盘素材或handoff；不声称完成真实ZIP采集。当前五段真实视频走单文件下载，不受此漏洞影响。
- 边界说明：max_bytes仍是解压流输出/落盘上限，不是进程RSS严格上限；目录、Python对象、DEFLATED最小读取及内部缓冲仍有额外开销。
