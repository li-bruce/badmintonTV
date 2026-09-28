# Render 验证记录（2026-09-28）

## 实际结果

1. 单元安全/编辑测试：`python -m unittest discover -s tests/render -v`；48项，47通过、1因Windows symlink权限跳过。包含非整数进度回归，覆盖路径、review、边界、浮点非finite、归一化crop、显式去重、合并审计保留、帧量化、锁/配额/不覆盖。
2. `python scripts/render/smoke.py`：真实执行FFmpeg生成合成有声25fps/640×360、无声30000/1001fps/480×360；三段0.5x/原速/静音crop输出7秒、210帧、1080×1920，H264/AAC、48k stereo、yuv420p，全解码通过。基准可读报告`D:/video/render/smoke-inputs/smoke-dcefd8e300/report.json`。合成输入绝不是羽球识别成功证据。
3. 统一合同提交8900958（platform原6a3e3de）：用只读platform Python运行`verify_contracts.py`，canonical render-request原结构/Timeline（含30.0fps）替换为已生成真实合成Asset，实际CLI5种情况全部通过。见`CONTRACT_COMPATIBILITY.json`；成功0、preview0、blocked2、failed1、编码中取消130。取消在首个实际segment编码进度后送出，确认无成功artifact/export、锁释放；未终止其他进程。
4. 最终真实研究样片 `real-research-e071063a44`：request、内部Timeline、result、输出Timeline、每条JSONL全部过统一模型；17.066667秒、512帧、双流start_time=0、尾时差<0.1秒、全解码。三段原片皆无音轨，source_map记录silence，未伪造观众声/击球声。
5. 来源相位专项：0.5秒延迟音轨（测试输入pulse=1.5秒/flash=1秒）经过0.5x后，flash=2秒、pulse=2.963秒；源延迟基本保留，剩余atempo瞬态偏差约37ms。测量见`DELAYED_AUDIO_MEASUREMENTS.json`。没有再分别归零音视频流。

## 音画同步的实际限制

用白闪与1kHz短音的1ms RMS检测，初始源起点差0ms；修正版0.5x输出音频领先约38ms（低门槛5%为41ms）。双流起始PTS和尾时长一致仍不等于瞬态零偏差。未把这一测试扩展成所有素材/速度/真实听感通过；人工观看与击球声复核pending。项目未给零偏移门槛，保留真实数字，后续可对目标速度评估其他时间伸缩器。来源与命令及hash在`SYNC_MEASUREMENTS.json`。

## 失败和修复

- Git共享元数据写入初次沙箱失败；明确授权提升后创建work/render，无全局safe.directory改动。
- 容量扫描遇到其他模块WSL symlink WinError1920；改lstat统计，不跟随外部目标。
- 合并相邻片段污染input_segments原边界；测试发现后深复制原始审计记录。
- 初始AAC中间段拼接造成成片video首PTS=21.333ms，source_map却从0；改MOV/PCM中间段和最终一次AAC编码，新增zero_start_pts QA。
- 独立视频/音轨归零会消除源延迟；改公共零点/音频先补头静音，并用0.5秒延迟实测。
- Windows默认GBK读取UTF8环境报告一次失败；所有脚本显式UTF8。
- canonical兼容发现本地crop原定义为像素、fps只收int；已统一到0..1 crop、接收30.0。stdout移除额外error/artifact键，Timeline内部字段移到source_map。
- 非整数总毫秒的进度先round后可能超total 0.000333ms；统一合同校验抓到，改round后clamp，并重新生成最新handoff。较早cddceec7d5/d58af7e950产物与日志保留作失败演化记录，不覆盖。

## 未测/外部限制

NVENC、目标跟随、OTIO往返、VFR真实输入、非Windows字体、旋转或非方像素crop、损坏真实源的编码时取消未全覆盖。已测显式crop和普通contain，真实原片机位为固定后场广播。个人录像未提供，人工确认/完整比赛原时间/画面发布授权均未具备。

完整“网页导入→标注→检索→确认→导出”由主任务与platform集成验收；本模块成功不代替全产品通过。
