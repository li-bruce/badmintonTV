# 预览寻帧目标帧 rVFC 回调等待约一秒：原因未确定

2026-09-29；关联 R-02b / S1。状态：**OPEN**。四种输入、冷媒体重载和重复访问共 8 组中，实际寻帧完成 total 中位数为 **990.55–996.80ms**，P95 为 **997.30–1001.60ms**；seeked 事件则明显更早。240 次测量完成且全部在一个源帧误差内，但这不能证明流畅审片目标达成。当前未改变验收门槛，也未把约一秒等待认定为可接受。

## 证据与复现条件

原始数据：[preview-seek-all-cold-warm.json](../platform/preview-seek-all-cold-warm.json)，SHA256 `3af74369e55f8ec8ebfb2f81bb2c3470edf650ef0cea02610810291fed69cde5`。只读统计，未改原始样本。2026-09-29 UTC 09:09:50–09:28:11，独立平台浏览器验证服务 18082，每组 30 个固定源时间点。

| 输入 | preview job | cold total 中位数/P95 ms | repeat total 中位数/P95 ms |
|---|---|---:|---:|
| 旧真实 CFR | job-8b17d44989c24272bbe108d88e5e3dc1 | 996.15 / 998.90 | 995.70 / 1001.60 |
| 明确派生 VFR | job-69b5c992e05e42bbafa91a67a0b5df6c | 996.30 / 999.10 | 996.80 / 1000.20 |
| 明确派生 FFV1 | job-2fdc852324a643e08f66262e63b4bc0b | 995.65 / 999.30 | 995.35 / 1000.80 |
| 明确派生 60→30 | job-3851a50c5be148a3b4892ec5a9be09bc | 995.75 / 999.00 | 990.55 / 997.30 |

cold 每点重建媒体加载、独特 URL、服务端 `no-store`；**没有清 OS 文件缓存**。repeat 复用媒体元素、不重载，浏览器与 OS 缓存未清；HTTP 缓存复用未保证。cold total 包含重载，repeat total 仅寻帧及目标帧观测，不能直接相减推断 IO 收益。真实输入及明确派生方法见 [MEDIA_PROXY.md](../platform/MEDIA_PROXY.md)，没有用派生 VFR 冒充原生摄录。

页面通过 `seekSource` 的全源 PTS 索引选择目标，`seekMedia` 等待 seeked 及 `requestVideoFrameCallback` 回调报告符合预期的代理帧；两者都到达后完成。每组固定 30 点，保留 `elapsed_ms/seeked_ms/presented_ms/observed_media_ms` 与源帧误差。P95 使用 nearest-rank 的第 29 个样本。完整八组分项表见[研究验收记录](../platform/RESEARCH_VALIDATION.md#浏览器-240-点寻帧原始统计)。

## 已确定与未确定

- seeked 中位数为 **6.65–33.80ms**，P95 **14.60–84.00ms**；presented 中位数为 **952.95–996.70ms**。cold 重载本身中位数 **39.90–42.05ms**。这些是不同计时段的分布统计，不能直接相减视作逐点分解。慢项出现在等待目标帧 callback 的观测路径，尚不能从回调时间单独断言解码、HTTP、调度、页面代码或浏览器任一层为根因。
- 所有样本支持 requestVideoFrameCallback，且 `status=ok/frame_observed=true`。`presented_ms` 在回调到达时以 `performance.now()` 计算，属于回调等待时长，不是实际屏幕呈现耗时。没有保存 metadata.presentationTime、expectedDisplayTime、processingDuration，无法据此归因于解码或 compositor，也没有物理显示器响应的外部测量。不会以快速 seeked 事件替代目标帧观测，制造低延迟结论。
- 全部点 `document_visibility=visible`。CFR repeat 第 27–30 点的 viewport 可见面积为 0，其余 **236 点为 1**。去掉这四点，该组 total 中位数/P95 仍为 **996.25/1001.60ms**；其他完全可见组也约一秒。因此“全部离屏造成慢”与数据不符；也尚未证明可见性完全不影响浏览器行为。
- 源帧带符号误差：**212 点为 0，28 点为 -1**，后者仅 60→30 两组各 14 点，约 -16.6667ms。全部 `abs(source_error_frames)≤1`。先前仅取 `max()` 导致“全零”误述，已按绝对误差与范围更正。显示前一源帧与降帧 coverage 相符，精确源图另由原分辨率接口回查；不把 coverage 当成显示了全部原帧。
- 另有实际区间循环“寻帧超时”、count=0。改为 pause→seek+rVFC→play 后，平台任务实际复跑 DOM 记录 23 次、截图 22 次（先后抓取）、last_source_ms=1000、notice 为空，见[循环证据](../platform/browser-loop-proof.json)。修复后循环路径通过；它与本文件 240 点计时是不同操作路径，**没有重新测出更低的八组时延**，也未证明二者根因相同。

## 后续验证与关闭条件

保留相同源文件、代理、30 点和原始记录，以可见播放器复跑；每次注明浏览器版本、页面构建、窗口可见性与缓存处理。增加逐请求的 currentTime 设置、seeking/seeked、每次 rVFC metadata、回调排队和完成时间，关联对应网络请求及解码观测，先定位等待发生在哪一层。对窗口失焦/离屏、已有目标帧、快速后续操作等单独控制，不靠推测更改映射或放宽超时。

循环修复已有单一区间的真实回环次数和源时间检查，后续性能复跑仍须保留该回归；逐帧、标记保存、60→30 原帧回查继续保持现有准确性断言。若需要流畅性的具体时延阈值，应由平台任务在下一轮测试前明确登记，不能用当前约一秒分布倒推合格门槛。

本问题在有可复现的原因定位、修复前后同条件分项测量，以及平台任务确认的性能与循环验收前保持 OPEN。尚未做跨浏览器对照、清 OS 缓存的全系统冷启动、长整场负载或物理屏幕响应测量；这些未测项不写成已完成。
