# Label Studio 1.23.1 视频框导出time与界面帧定位差一帧

状态：已复现，适配器通过显式PTS映射绕开；不是模型识别问题。2026-09-28。

环境：Windows独立Label Studio 1.23.1，Edge。真实139帧、30fps CFR小样 `asset-057d2d6dd52eb892719b36aa1f017ac6272e19502dd93efbc0ca9f97f35b6fe0`，project1/task1/annotation1。

界面第1帧显示0秒，第31帧显示`00:01:00`；TimelineLabels 31–60显示Duration30。对第31/41帧新增或移动VideoRectangle框，真实JSON导出包含 `{frame:31,time:1.0333333333}` / `{frame:41,time:1.3666666667}`。源视频PTS对应1000ms/1333ms。官方VideoRectangle模板也展示frame/time，但不能将其表述推作所有版本的可靠时间转换契约。

证据：`D:/video/platform/labelstudio/verification-export-ui.json`、`verification-ffprobe.json`，测试设计与逐步操作见[集成说明](../platform/LABEL_STUDIO.md)。未修改第三方安装包，没有伪造导出。

已采用：所有回写仅使用显式`ls_frame→source_start_ms/source_end_ms`映射；VideoRectangle原始time仍保留以利审计，但不作为原片时间证据。TimelineLabels双端包含显示帧，平台转为半开毫秒区间。FrameMap不内置1基假设，由每个显示媒体/代理提供编号表。

剩余：真实VFR代理和未来Label Studio版本须重新核验首末帧及端点语义；目前不宣称已对这些组合验收。原片不存在完整可靠PTS或代理映射时应拒绝自动回写，不以frame/fps估计冒充精确源时间。
