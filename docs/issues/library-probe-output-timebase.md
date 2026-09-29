# CPU decode null 输出时基误报

2026-09-29 完整 Fine-Badminton 采集到第 9/10 份探测时，2017World 源片在 CPU 全解码的 null 输出中报重复 DTS，程序安全拒绝发布。首轮异常只保留 stderr 尾部 4000 字符，不能补称已保留完整首轮日志。此前 8 份有效 Asset 保留；同时运行的2014Asian虽已生成完整PTS，却因首个future异常没有保存其报告，需重新完整验证。

真实诊断见 `docs/library/evidence/probe-timebase-world2017-20260929/`：原命令和只增加 `-enc_time_base:v demux` 的命令分别运行120秒，均解码3006帧、exit0；前者stderr746 B含6条重复DTS，后者stderr0。独立seek窗口PTS严格递增，但seek起点落在较早关键帧，不能冒称和decode窗口完全相同。

另一次独立全源扫描见 `docs/library/FINE_WORLD2017_PTS_DIAGNOSTIC.json`：120015帧，time_base=1/90000，119698个3600-tick间隔、316个1800-tick间隔，零非递增PTS、exit0/stderr0，耗158.797秒。原序canonical JSONL摘要为 `d4c517227b310b47bff15bcc34e6c8686508755caaf92ef139d0fce157706b8c`。没有排序、去重、改写源片或据此直接发布Asset。

FFmpeg默认视频encoder时基为帧率倒数；本源nominal25fps不能表示全部20ms间隔。`fps_mode passthrough`不独立保证null编码时基精度。修复显式沿用demux时基，仍保持CPU1线程、`-xerror`、`-v error`及任何stderr拒绝；不支持该选项的旧工具失败关闭，不自动退回粗时基。依据为实际A/B及[FFmpeg官方时基文档](https://ffmpeg.org/ffmpeg.html#Advanced-options)。

批次修复在一个worker失败后取消尚未开始的任务，但继续保存已在运行且独立通过的结果，最后仍抛原失败；不写成功summary。原生产manifest不会缩减。临时夹具回归验证首错后成功结果、队列取消、旧数据保持和reservation释放；独立真实线程池临时文件验证也通过。上述夹具不是视频识别成绩。

目标回归：probe/manifest29项及training acquisition10项全部通过；排除并行开发中的BFMD采集测试后，其余完整154项PASS、0skip、14.722秒。期间一次168项全库测试读到BFMD尚在修改的缓存中断断言，1项失败；一次stdin自定义runner因Windows multiprocessing不能重新打开`<stdin>`导致1项错误，改为`python -c`后上述154项通过，未修改配额逻辑。两份源片的全片修复后复验正在运行，以新日志与新PTS完成后才发布；已有孤立PTS保留。完整复验日志受每份4MB/总8MB硬限，额外预留16MB，仅写训练诊断子树。

后续真实完成：两份修正后全片decode均exit0/stderr0，完整PTS和源SHA复验通过；分别118201和120015帧，全批10/10、980703帧、38592556ms。World2017正式PTS摘要与独立诊断完全一致。日志位于训练数据集 `diagnostics/reprobe-20260929T101835Z-970261c6/`：Asian2014日志SHA `45172146e1619a7435851da897c07d1ec8f2ed83559a544bdf36917e8849bb7f`，World2017日志SHA `ca179eade5790397c14782553a2ab1e938d0fd30d2e7bf2d009fb75681254c58`。源码修复提交 `acd0225a748d1b2751668a2b4eca73078f3f12db`，主线集成为4dc9125。
