# FFmpeg9 NVENC API 与现有驱动不兼容

日期2026-09-29，R-03a first attempt **FAIL（执行结果blocked/backend_unavailable）**。构建支持不能代替真实硬件运行。

FFmpeg `9.0.2-essentials_build-www.gyan.dev` 在已获同平台账本GPU窗口与租约的真实旧general片段上初始化h264_nvenc失败。日志明确：`Required: 13.1 Found: 13.0`，该构建提示最低驱动610.00。未启动任何完整GPU成片编码，也无热轮或GPU质量/速度结论。

证据：`D:/video/render/jobs/job-6ddb2881f44048eda5f306f741a3b035/attempt-1/nvenc-probe.log`，backend.json、stage_timings.json；批次 `render/benchmarks/presets-controlled-nvenc-4e5823beb9ca/`，首轮8.356343秒。backend.requested=nvenc、effective=unavailable，未静默CPU回退。

窗口 `render-benchmark-4e5823beb9ca`，租约 `gpu-lease-8d6672d608344b84817e2430d2432d6f`，worker已核验计算停止并释放；窗口在09:02:44 UTC提前revoke，active_window/lease均null。已明确归还models，不占GPU等待下载。

处理方案：不升级/修改全局驱动；在runtime/render配额内独立核验可兼容FFmpeg8/7构建，保留现有9和失败文件。若成功取得兼容构建，CPU和NVENC都使用它重新测量，不能跨构建直接比速度。当前旧构建硬件路径缺口仍开放，兼容尝试结果随后追加。
