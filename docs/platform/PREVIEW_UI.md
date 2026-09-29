# 源时间预览与标注交互

更新日期：2026-09-29；前端范围为原生 JavaScript / HTML / CSS，不安装前端依赖、不操作生产数据库。后台代理、源帧提取及容量控制由平台主任务实现。本文记录实现行为及工程回归；独立浏览器验收结果由[平台状态](../status/platform.md)与对应原始报告记录，本文不据代码存在宣告验收通过。

## 开发前冻结的断言

| 用例 | 输入 / 方法 | 预期结果 | 本文证据范围 |
|---|---|---|---|
| R-02a / S1 | CFR、VFR派生片与浏览器不支持容器；服务端生成带源PTS映射的兼容代理 | 原生播放器读取代理；源帧可按原分辨率回查；30固定点源PTS误差≤一个源帧 | 前端实现已交付；真实媒体结果见独立验收记录 |
| R-02a / S1 | 60→30fps映射；图像映射源帧与覆盖区间分开 | 省略的源帧可核查；连续覆盖区间不会被标成源缺口 | 显式PTS测试夹具工程回归PASS；不替代真实解码 |
| R-02b / S1 | 浏览器逐帧前后、循环、缩略图定位、源时间修订保存 | 事件始终保存源ms；沿用CAS及审阅来源；逐帧使用真实源帧索引 | 工程回归PASS；循环子项由主任务独立18082浏览器复测PASS，其他子项见阶段记录 |
| R-02b / S1 | 固定30点冷/热seek，以performance.now及真实seeked/视频帧回调记录 | 每点记录实际耗时、帧媒体时间、误差或超时；分别报告中位数/P95 | 计时及分组回归PASS；性能值只取实际浏览器记录 |
| R-01a / S4（Web配置范围） | 选择30/60fps、安全区及平台规则，保存/重开/提交渲染 | 配置有独立CAS修订，Timeline输出同步；冲突不入队 | 工程回归PASS；持久化重开及实际job参数由主任务独立浏览器验收 |

用户界面须明确代理的画面分辨率与源帧的原尺寸；放大是像素缩放，不能作为恢复拍面/手腕细节的证据。源时间区间使用半开区间 `[start_ms,end_ms)`。普通代理播放的开始/结束使用连续覆盖边界，击球使用画面对应源PTS；精确源帧选择的三种标点使用该帧的PTS边界。开始/击球向下取整、结束向上取整到合同整数ms，并限制在原片时长内。

## 已实现的交互与API

素材最初直接播放原片，并读取最新代理状态；已有成功代理则加载同源H.264媒体。用户可填写源窗口（最长120秒）、720p/1080p、保留源节奏或最高30fps，显式提交生成任务。任务状态、失败和取消保留在后台任务页，前端通过“刷新预览”加载完成结果。该预览无音轨，页面明确说明。

- `POST /api/v1/assets/{id}/preview`：`{start_ms,end_ms,max_height,max_fps}`；返回job。`GET`同路径返回`status,job_id,preview`。
- `preview.frame_map_url`分页读取所有有界代理帧，每页1000。字段为`proxy_frame_index,proxy_pts_ms,source_frame_index,source_pts_ms,source_pts,coverage_start_ms,coverage_end_ms`；禁止以`frame/fps`换算。
- `preview.source_frames_url`只按需要读取128项，用`at_ms`或`offset_frame`定位。源帧是全片0起始序号，含`source_pts,source_pts_ms,source_end_ms`。逐源帧前后使用序号±1，只选择源帧并定位代理，不自动创建原图提取任务；降帧时代理图像可能保持不变。超出代理窗口仍可选择源帧，但不能冒称已经由该代理播放。
- 显式点击原分辨率核查才请求`POST /api/v1/assets/{id}/source-frame {preview_job_id,source_frame_index}`并轮询job；校验`result.frame`的原片ID/hash/帧号/PTS、图片解码与尺寸后显示对应JPEG artifact。原片帧提取不在Web请求内执行FFmpeg。播放或更换源位置时隐藏旧静帧，避免旧图误充当前核查画面。
- `preview.thumbnail_url`与`thumbs[{source_pts_ms,x,width,height}]`提供sprite条。每项点击按源PTS定位；没有前端第三方网络依赖。
- 循环取当前标注的源开始/结束。映射按显式覆盖段与代理PTS插值，区间出界时停用循环并显示原因。浏览器调度与帧呈现可能有延迟，不能称为硬实时循环。
- 原尺寸图可适合窗口、1:1、2×、4×显示并横纵滚动。帧PTS、时间基、源hash、原尺寸均显示；像素放大不恢复原片没有的细节。

旧事件的`expected_revision`、审阅者及`reviewer_type`保存路径未改变；候选/时间线回看改为先映射源时间后定位代理，Label Studio快照导入导出保持原有字段。

### 原图核查的取消与有界复用

原图提取目前会校验整片源文件，并从头解码到指定源序号；长片或靠后位置可能耗时。此前每次前后源帧都自动提原图，过期请求只隐藏结果，会形成不必要的后台任务。现普通逐帧只导航，原图由用户显式请求，页面说明其成本；本次没有修改后台索引、关键帧寻址或源校验，成本限制见[问题记录](../issues/platform-exact-frame-long-video-cost.md)。

原图核查只有一个当前generation。更换素材、源位置、预览attempt、开始播放或发起新核查都会撤销旧generation，对已知queued/running job调用cancel API。创建与取消串行：旧POST尚未返回job_id时，新创建等待；旧job_id迟到后先取消，再允许最新意图创建。取消失败会保留可重试记录、显示原因并阻止新任务堆积。running任务的cancel响应只确认取消请求已登记，实际进程退出由worker处理，不宣称立即终止。核查等待超过120秒也请求取消，并提示在任务页查看。

会话缓存最多16项，按最近使用淘汰；仅缓存后台succeeded且经过ID/hash/真实PTS/图片解码和尺寸校验的成功产物。key包含源asset_id、sha256、全片source_frame_index、preview job_id和`index_relative_path`中的attempt目录；缺attempt身份时不缓存。重复核查加载该产物，不新建exact_frame job，页面标记“复用本会话已校验结果”；产物加载失败会淘汰缓存，下次显式核查重新创建任务。旧generation的失败不能删除新generation已验证的同帧缓存。缓存不生成预测帧、不修改原片，也不放宽后台未缓存请求的源身份校验。

### 图像源帧与区间覆盖：source #61

`source_frame_index`始终是全片0起始真实源序号。代理画面来源由`source_frame_index/source_pts_ms`描述；该代理帧承担的源时间范围由`coverage_start_ms/coverage_end_ms`描述。这两组字段不可互换。

下表是`preview_ui.test.cjs`中的显式PTS测试夹具，不是真实视频实测：60fps源片降为30fps代理，代理首张图来自源#60，下一张来自源#62；源#61仍存在。

| 对象 | 图像对应源时间 | 覆盖/源帧时间区间 |
|---|---|---|
| 代理#0 / 源#60 | 1000ms，源PTS 90000 | `[1000,1033.333333)`ms连续覆盖 |
| 精确选择源#61 | 1016.666667ms，源PTS 91500 | `[1016.666667,1033.333333)`ms真实源帧 |
| 代理#1 / 源#62 | 1033.333333ms，源PTS 93000 | `[1033.333333,1066.666667)`ms连续覆盖 |

选中#61时，代理可能仍显示#60，界面须保留“选中源帧”与“代理画面来源”的区别；原分辨率核查请求的序号是61。对这一精确选择设标点会得到开始1016、结束1034、击球1016ms；未精确选择时，代理#0的区间标点使用整个覆盖段，击球取其图像PTS。代理省略了图像，不代表源片时间有缺口；确实缺失的覆盖段会明确拒绝定位，不使用FPS估算补洞。

### 可观察的循环完成结果

`#loop-status`保留源半开区间，显示“已完成循环 N 次”。勾选或关闭循环、改选素材、改变源区间会归零；新建标注及设开始/结束标点也归零。DOM属性`data-loop-count`保存计数，`data-last-loop-source-ms`保存最近成功回跳后观测的源位置，重置时后者为空。

到达结束边界（含播放器自然结束）后，先暂停视频，以免继续播放越过等待中的目标帧；完成回跳seek及目标帧回调，并等`player.play()`成功恢复播放，才增加一次。进入区间前的初次定位不算循环；seek/play失败不增加计数，旧素材或旧区间的异步完成也不计入。这些是可供真实UI验收读取的观测点，不是硬实时或帧精度保证。暂停后回跳的修复已有播放推进竞态模拟回归，主任务真实浏览器复测记录如下。

2026-09-29，R-02b循环子项，独立18082实例：

| 轮次 | 输入/方法 | 预期 | 实际结果与证据 | 状态 |
|---|---|---|---|---|
| 修复前 | 源区间`[1000,1800)`ms，勾选循环，在`#preview-workbench`按Space开始播放 | 到区间末尾回跳，成功恢复播放后计数增加 | 主任务观察到“寻帧超时：浏览器未提交目标代理帧”；循环自动取消，count为0，视频继续至约4秒结束。保留此次失败，不计为通过 | FAIL |
| 修复后 | 完整刷新页面重新加载JS，使用相同源区间，勾选循环，在工作区按Space开始 | 连续完成回跳并产生真实成功计数，通知无错误 | DOM记录count为23、last_source_ms为1000、notice为空；[原始JSON](browser-loop-proof.json)。[截图](D:/video/platform/research-20260929/browser-ui-evidence/browser-loop-proof.png)捕获的是稍早的22次，之后JSON记录增至23次。主任务随后按Space暂停并取消勾选 | PASS |

修复针对播放中seek与目标帧回调的竞态：旧实现未暂停，继续解码可能已越过等待中的目标帧；现先暂停，等seeked与目标帧观测完成再恢复播放。工程测试模拟继续播放会略过目标帧的条件，并验证暂停后连续两次成功计数。上述真实复测验证循环恢复及计数，不据此宣称无调度延迟、严格区间边界精度或整个R-02b全部通过。

## 工程导出设置

时间线编辑区提供30/60fps竖屏预设、安全区四个数字及平台时长规则。选择`portrait_1080p30`或`portrait_1080p60`立即同步工程JSON的`Timeline.output`为1080×1920、30或60fps、`video_codec=h264`、`audio_codec=aac`。默认安全区为`{x:0.06,y:0.10,width:0.82,height:0.78}`，各值为相对输出画幅的比例；宽高须大于0，`x+width<=1`且`y+height<=1`。比赛画面仍默认完整保留，安全区不是裁比赛画面的命令。

`platform_profile`可选`null`（不附加平台时长上限）或`youtube_shorts`（本产品预设最长180000ms）。时长按各段`(out_ms-in_ms)/speed`求和，渲染端继续复核最终帧量化时长；这里描述产品配置，不声称已核对外部平台的最新发布政策。

- 加载时间线时GET `/api/v1/timelines/{id}/render-options`，读取`{schema_version:'1.0',timeline_id,revision,options:{export_preset,safe_area,platform_profile}}`。未持久化设置时revision为0；设置独立存储，不扩展Timeline合同。
- 保存与渲染先校验本地设置，再保存Timeline，随后PUT同一render-options路径，正文为`{expected_revision,options}`。只有两步均成功才可POST render入队；API将保存的设置及其修订写入job快照。
- PUT返回409时保留用户修改与旧修订，提示明确重载。`#render-options-status`提供`data-revision/data-dirty/data-conflict`。点击“重载已保存导出设置（替换本地设置）”才丢弃该本地草稿；不会自动取最新修订重试覆盖。
- 两次保存不是跨对象事务。若Timeline已经保存而设置PUT失败，界面会说明这一状态，且不提交渲染任务。
- 旧工程24/25/50fps默认`export_preset=null`，加载时不悄悄改为30/60。界面提示先明确选择预设，再通过本入口保存或导出。JSON新建工程可从无记录revision 0开始保存；只有明确404按新工程处理，其他读取失败不伪装成默认设置。

## 实测入口与证据边界

`#seek-diagnostics`提供30个固定均布窗口点，落到实际源帧PTS后逐点seek。`#seek-benchmark-results`是DOM可读取的真实JSON，导出按钮保存同一数据。每点以`performance.now()`计时，记录`seeked`和`requestVideoFrameCallback`提交目标帧的时刻、实际mediaTime、源帧/PTS偏差；有回调时须同时收到seeked和目标帧，超时如实失败。不支持回调的浏览器会标记`rvfc_supported=false,frame_observed=false`，不据此宣称画面帧精度通过。无实际位置变化的no-op不进入耗时分位数。30点短到落在同一源帧的情况也不会伪造30个不同seek。

首次组`first_access`和复访组`repeat_access`只表达操作顺序。另有`cold_media_load`组：每个点给同一媒体接口增加唯一`_btv_cold_seek`参数，重新加载媒体元素，配合服务端`Cache-Control: no-store`绕开HTTP缓存；总计时包含媒体元数据加载、seek和目标帧呈现。每点单列`media_load_ms`、`seek_elapsed_ms`以及从加载开始计的seeked/呈现时间；30个`fixed_points_ms`与复访组完全相同。复访组保留当前媒体元素并不重载。

这里的“冷”只指媒体元素/HTTP媒体加载，OS文件缓存未清除，不能称为全系统冷缓存。run的`cache_control`和`timing_scope`记录实际条件。页面不能清除OS磁盘缓存；主任务在独立18082验收实例记录这些受控条件下的中位数/P95，此文件不预填性能值。测试辅助不会保存事件或修改数据库。

主任务首次浏览器基线发现seeked常在3–14ms，而目标帧回调出现约1秒延迟；当时播放器滚出了视口，暂以可能的浏览器节流作为待验证解释，保留原始数据。后续测量开始将播放器滚到视口中央，每一run及row都记录`document_visibility`、播放器矩形、视口宽高与可见面积比例；不通过删减/替换原测量来隐藏条件差异。行内仍分开报告seeked与呈现耗时。

`requestVideoFrameCallback`是帧呈现观测而非精确seek保证，依据[Chromium官方说明](https://web.dev/articles/requestvideoframecallback-rvfc)；seek行为参照[HTML标准](https://html.spec.whatwg.org/multipage/media.html#seeking)。实际精确源帧核查使用服务端原分辨率提取的图片。

任务取消、重试及应用结果成功时，顶部通知仅显示操作、job_id和状态，完整响应显示在`#job-detail`；`#notice`高度限制为`min(24vh,160px)`并允许内部滚动和长串换行。错误详情仍可读，不应覆盖整个工作区。CSS效果由主任务浏览器复核。

## 当前验证记录

2026-09-29，Node.js v18.16.0，未安装新环境。命令：

```powershell
Get-Content -Raw apps/platform/static/app.js | node --check
node -e "require('vm').runInThisContext(require('fs').readFileSync('tests/platform/preview_ui.test.cjs','utf8'))"
```

32项前端回归PASS（此前23项，原图任务管理新增9项）：60→30画面与覆盖分离、被代理略去的源帧标点、VFR/非零窗口双向映射、重复源图的独立覆盖、真实缺口拒绝、分位数不含失败/no-op、计时须等实际目标帧与seeked、切换资产拒绝旧分页回写、旧seek意图拒绝、精确源帧标点不被邻近代理图覆盖，以及冷媒体组确实30次唯一URL重载、复访组不重载且使用相同固定点。慢素材A查询在切至B后迟到时，不得改写当前素材，随后保存的event/match/evidence仍属于B。循环测试覆盖成功计数、恢复失败不计、旧区间异步完成不计、自然结束及区间改变归零，以及播放推进会略过目标帧时暂停回跳可连续完成两次。导出测试覆盖旧fps保持、保存顺序与重载、CAS冲突不入队、安全区/含速度时长校验、新工程404分支。任务通知回归使用10KB Job payload，验证取消/重试只显示简短job_id和状态，完整数据保留在详情。

原图新增回归：快速step（含代理窗口外）零exact job；同帧缓存及asset/hash/attempt隔离；16项上限与无attempt不缓存；坏hash/PTS/时间/尺寸/解码结果不缓存；切素材取消queued/running；迟到入队响应仍取消；取消ACK前不新建且只执行最新意图；取消失败阻止堆积；旧轮询失败不淘汰新成功缓存。使用显式测试映射、模拟API和浏览器事件，仅为工程回归，不能代替真实媒体解码、后台进程退出或浏览器交互。此补丁不重跑已有240点媒体测量。

平台主任务随后在真实Edge/独立18082完成取消与缓存闭环：三次普通step没有新增exact job；源#61的queued任务切帧后在attempt0取消；源#62由单次CPU worker成功提取1280×720原图；切离再返回后显示“复用本会话已校验结果”，exact任务总数没有增加。见[队列回执](browser-exact-request-proof.json)、[DOM](browser-exact-request-dom.json)与[截图](D:/video/platform/research-20260929/browser-ui-evidence/browser-exact-cache.png)。后台worker已经退出，无queued/running任务；该短片操作不证明长片快速解码或运行中任务已即时停止。

本文维护者未操控验收浏览器；上述循环真实结果引用主任务独立操作与证据，不在此代填R-02a、R-02b整体状态或性能结论。独立验收状态见[平台状态](../status/platform.md)，后台真实代理验证见[MEDIA_PROXY.md](MEDIA_PROXY.md)。本轮前端开发及文档更新未启动18080、未改生产DB、未占GPU、未新增依赖或大文件。

## 旧probe JSONL的有界分页

新增`apps/platform/frame_index.py`供主任务接入Web路由：

```python
read_source_frame_page(asset, storage_root, *, offset_frame=0, limit=128, at_ms=None)
read_label_studio_frame_map(asset, storage_root)
```

第一接口按真实PTS返回最多1000个全片0起始源帧，`at_ms`选包含该时间的帧为页首（视频末端取最后帧），页内每帧的结束边界取下一真实PTS，最后一帧使用原片时长。保留`source_pts`整数，时间计算使用`Fraction`，不从FPS推断。

旧JSONL没有随机访问索引，因此每页仍需线性扫描验证整文件hash/帧数；内存仅保留目标页与一个lookahead。单行最多64KiB、索引最多64MB（与library旧probe写入限制一致），不调用`read_bytes`/`read_text`，文件读取前后校验身份/大小/修改时间。新代理的SQLite索引走runtime原有分页接口。

第二接口只允许经实际扫描证明≤1000帧的完整旧Label Studio映射；声明数量更大时读文件前拒绝，缺失或谎报数量仍在第1001帧拒绝并提示先生成小段代理映射。短片保持原`mapping_id=pts-{hash前20位}`、1起始LS帧号、整数floor边界和原始PTS字段。

2026-09-29执行`D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/platform/test_frame_index.py -q`：31 PASS；包括10,000行索引有限页的峰值<512KB、lookahead/VFR/EOF、hash/数量不一致、坏PTS/序号、路径逃逸、超长行、LS完整导出上限。不替代真实源视频的验收。
