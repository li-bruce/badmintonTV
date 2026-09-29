# 原分辨率单帧提取的长片成本

日期：2026-09-29。关联R-02a/R-02b；状态：前端任务放大问题已修复，后台线性读取/解码成本保留，长片性能未测。

`packages/runtime/media_proxy.py`的`exact_frame`先执行源身份校验，再由FFmpeg从输入开头用`select=eq(n,source_frame_index)`取指定序号。单次成本包括整片源校验及到目标帧的解码；不能用四秒素材的响应速度推断一小时比赛也可即时核查。本次不声称已跑长片基准，不改变真实PTS或放宽源hash验证。

旧UI每次前后源帧自动创建exact_frame任务，切换后仅不显示过期结果，没有取消后台任务。这会使连续按键放大上述成本。现已采取：

- 普通逐源帧仅选中源序号并定位代理，原图核查为显式操作。
- 单一有效核查generation，串行入队/取消；旧POST的job_id迟到也先取消，取消失败阻止新任务累积。running取消ACK不等于进程已结束，实际终止由worker确认。
- 最多16项会话成功缓存，身份含源ID/hash/帧及preview attempt；仅复用真正成功、经校验的JPEG产物。
- UI说明后台校验、从头解码和可能耗时，超过120秒停止本次等待并请求取消。

工程验证：`tests/platform/preview_ui.test.cjs`总计32 PASS，新9项覆盖零自动提帧、成功缓存与隔离/上限、坏结果拒绝、迟到响应/切源取消、取消ACK顺序、失败不堆积及旧失败不能淘汰新缓存。测试使用模拟事件/API；未重跑原240点媒体计时。

真实浏览器闭环于2026-09-29 10:11 UTC完成：独立18082上三次普通step后exact任务仍为原2个；显式#61任务`job-3232068ebb15432aacf59d96585d50c4`切帧后在attempt0取消；显式#62任务`job-76ab9527c53146868463ebc1bc0052b3`由单次CPU worker完成。切离再返回#62核查时，页面显示“复用本会话已校验结果”，exact总数保持4（原2、取消1、成功1），无queued/running任务。见[队列回执](../platform/browser-exact-request-proof.json)、[实际DOM](../platform/browser-exact-request-dom.json)和[截图](D:/video/platform/research-20260929/browser-ui-evidence/browser-exact-cache.png)。这验证短片上的创建/取消/复用行为，不是长片吞吐或running取消的进程退出实测。

后续如优化后台关键帧寻址或源校验复用，需独立设计索引身份、VFR/非零PTS精度、文件变更失效和进程取消边界，并用真实长片测量源校验/解码分项耗时。本次没有实现或宣告这些优化完成。
