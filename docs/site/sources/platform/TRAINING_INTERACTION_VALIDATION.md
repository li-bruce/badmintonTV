# A-11～A-14 平台验收：拖拽、多维标签与图像区域

2026-10-03（北京时间）。开发前断言见 [设计](TRAINING_INTERACTION_DESIGN.md)；合同 `a0fc1db`，功能 `c97f39f`，真实快速投放修复 `8ba5cc2`。仅操作私有 `127.0.0.1:18082` agent 服务；main 的 human 18080 未写入。本文不宣布模型精度、专家细标签或全产品阶段通过。

## 固定用例结果

| ID / 范围 | 验证方法与输入 | 预期 | 实际结果 | 状态 / 证据 / 后续 |
|---|---|---|---|---|
| A-11 平台时间轴 | 真实 CUA 原生标签拖入空轨道和已有动作块；整段平移及左右端点拖动；越界释放；Alt+方向键；真实浏览器CAS | 原片整数毫秒、克隆校验、非法不改写、待审保存、冲突保留草稿 | 首区间61996–62996；第二区间65249–66249，经整段拖为66246–67246、起点65878、终点67636，再键盘到67637。拖终点至回合外被拒绝，保持65878–67636。并发后浏览器67638草稿保留、服务器仍67637/bundle6 | PASS（平台断言）。取消/捕获丢失/过期上下文由前端事件回归覆盖，未把夹具称为真实半途手势。确认框后旧tab恢复另列失败，不作为成功证据 |
| A-12 标签与主体 | 冻结词表全156叶/8维度/37目录；真实展搓新建、步法点击回退、对手展搓拖入、重复投放 | 目录不落库、多轴独立、label/role/解析人物去重，基础信息手填，不自动确认 | 同一动作保留展搓/本人、后退小跳/本人、展搓/对手3判断；相同标签主体再投显示保留原判断。两个手动匿名人物与两个队伍，均未知身份；所有候选unknown、待审 | PASS。全156个叶/8域遍历和37目录拒绝为真实项目词表+单元测试；不是逐个手工拖156次 |
| A-13 图像区域 | 真实1280×720视频；1366×768视口下矩形两角拖画、整框移动、角点缩放；四点多边形/Enter完成/顶点拖动；取消新草稿；黑边拖画；临时区域删除；两次浏览器save/reload | 坐标扣除黑边、只绑定原时刻/记录/角色/人物；非法不保留；保存复原；不跟踪 | 矩形/对手/远端、多边形/本人/近端均绑定61996ms；矩形移11×4 CSSpx后再缩放，多边形末顶点移−7×8 CSSpx，归一化结果见冻结快照。黑边报告不能圈选且0新增；临时矩形从1删到0。bundle4重载两图形原样恢复 | PASS。仅浏览器时间定位、image_normalized；未声称米制标定或精确源帧。独立根18084另有Escape用例，本表不借用为本tab实测 |
| A-14 平台合同/API/快照 | 旧实际snapshot原字典/旧canonical hash；新实际ROI快照审计JSON；18个新增API边界；跨模块CPU回归 | 不给旧snapshot加默认字段，ROI按原字典保真，agent不能伪human，正式训练门禁保持 | 旧hash不变；新快照2个ROI与bundle逐字典相同，audit下载520054B并等于冻结对象；0eligible/5excluded、trainable=false、正式training下载409；API伪human/非法几何/来源绑定/CAS/重启冻结回归通过 | 平台子项PASS。models/render实际消费由owner/root独立验收，本文不将CPU回归当作真实消费完成 |

## 真实资产、项目与持久化结果

- 复用只读来源 `asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913`，1280×720、源PTS32651项、duration1306040ms。原片231500744B，没有复制或重下载。
- 私有项目 `training-project-51fbe6f69df7457f9e02d203292f62da`，名称“拖拽与圈选验证 · Agent 2026-10-03”。最终project8/bundle6；2人物、5记录（回合、独立死球、2动作区间、1态势点）。角色只是手动演示绑定，不证明镜头内实际人物身份。
- 带区域记录 `record-91ac140b-3995-44ad-ab6d-2d4648dfca66`，61996–62996ms，3项unknown判断；矩形 `region-7fe4a515-3dfe-408a-9892-ae88502ad65d`，多边形 `region-cd46144b-3a59-4b1a-94d1-a70878c45146`。两区域均agent/browser_time/61996ms。
- 被拖动记录 `record-83490d63-ca9f-4428-b0da-1cbb8b5807cb`，最终65878–67637ms。CAS验证后服务器逐records/people与冲突前保存对象全等。
- 快照 `training-snapshot-a4533d2de09143aeae9d3dfe76e1b2ea`，canonical SHA256 `f0a57ada2b902edde5128a78719e69c98dd86f98e933ebd7aec70255b96c53a9`。最终快照通过私有API生成；本轮浏览器快照按钮由根18084独立验证，不能称本tab按钮实测。
- 旧实际 `D:/video/platform/integration-20261002/snapshot-before-restart.json` canonical SHA仍为 `d2deb51291cbb8ad5ac100e7a95d60afb6670e8c3762f05304daee77410a67dd`，原字节SHA `5f471b166151172accb35764be2993945c991707ff9a6d49ce02a162d1e2e460`，未重写。

证据目录 `D:/video/platform/training-interaction-20261003`：`bundle-before-cas.json`、`concurrent-save.json`、`bundle-after-conflict.json`、`project-final.json`、`snapshot-with-regions.json`、`audit-snapshot.json`、`validation-api.json`。`training-interaction-cas.json`保存浏览器真实DOM冲突文案/hidden=false/67638草稿。过程原生拖动与屏幕截图可在本chat工具记录复核；本轮尚未保存最终浏览器截图文件，不能拿上一轮截图代替。

## 已运行检查

复用Python `D:/video/runtime/platform/env/Scripts/python.exe`、Node `C:/Program Files/nodejs/node.exe`。没有安装包、改全局环境或使用GPU。

| 命令（python -m pytest，CPU） | 实际结果 |
|---|---|
| `tests/contracts tests/platform -q -rs --disable-warnings` | 836 passed / 8 skipped / 781 warnings / 91.28s |
| `tests/library -q -rs --disable-warnings` | 186 passed，另317 subtests passed / 22.44s |
| `tests/models -q -rs --disable-warnings` | 319 passed / 14 skipped，另313 subtests passed / 3.89s |
| `tests/render -q -rs --disable-warnings` | 165 passed / 1 skipped，另409 subtests passed / 7.27s |

主测试合计1506 PASS/23 SKIP，1039 subtests单列，不重复计数。首次把五目录合成一个pytest进程，因contracts/library的同名test_training.py出现收集冲突；随后按仓库现有配置分进程，全部覆盖完成。跳过是平台5项opt-in媒体、2symlink、1opt-in WSL，models4symlink与10项缺NumPy，render1symlink；均未升级为PASS。

新增ROI API 18/18 PASS（9.48s，无skip）包含有效几何save/reload、10类invalid422无副作用、agent来源、CAS409、冻结下载/重新打开库、旧实际snapshot。其合成human种子只在隔离测试实例内，不是实际视频真值。

前端四文件命令：`node --preserve-symlinks --preserve-symlinks-main --test tests/platform/training_ui.test.cjs tests/platform/training_interactions.test.cjs tests/platform/training_regions.test.cjs tests/platform/training_timeline.test.cjs`。功能提交69/69 PASS；8ba5cc2新增2回归后时间线20/20 PASS（92.1ms）；最终四文件合并 **71/71 PASS，0 skip，350.8ms**。JS语法与git diff检查通过；最终syntax命令最初漏掉两项preserve-symlinks参数，被沙箱lstat用户目录拒绝，按既有参数重跑后通过，没有扩张权限或改实现。

## 失败、修复与未测

1. 快速标签拖到已有窄块首次无drop：真实事件只到dragenter，已用同一受限MIME接受逻辑修复，真实重复去重与对手判断投放通过。详见 [问题记录](../issues/platform-fast-label-drop.md)。点击后的时间线残留提示也已修复，新增生命周期回归旧代码失败/新代码通过。
2. 本轮CAS已真实409且保留草稿。随后“放弃当前编辑并重载”原生confirm导致Edge控制超时；getJsDialog、重新取得tab和同浏览器新tab均超时。服务端仍为bundle6且records/people全等。浏览器确认框原地恢复与最终截图目前BLOCKED，已请用户关闭测试弹窗；不把这个恢复动作计PASS，不触碰用户其它浏览器/进程。临时1366×768视口也待连接恢复后reset。
3. 本轮没有再次重启私有服务器；ROI重启冻结只由隔离API测试覆盖。本轮实际小屏1366×768可见视频、标签盘与源时间线；窄轨道内部可滚动，其余浏览器/触屏设备未测。
4. 没有真人已确认判断、专家细标签定义或可信独立比赛组，不能导出正式训练视图；不降低训练隔离与正式数据门槛。

服务维持 `127.0.0.1:18082` / agent；实际PID73300，launcher49668，2026-10-02 16:40:10UTC启动合同a0fc1db，静态文件已更新到8ba5cc2。DB `D:/video/platform/training-20261002/platform.sqlite3`。启动：`.\start-platform.ps1 -Port 18082 -DatabasePath D:/video/platform/training-20261002/platform.sqlite3 -TrainingReviewer agent`。容量收尾见证据目录的 `capacity-final.json`；没有后台训练/渲染worker。

17:18:16UTC最终测量：本轮证据1640561B（写容量/manifest前）、私有DB目录4606110B；platform208579380B/60GB、runtime/platform1048360620B/10GB，reserved均0，D余量920498995200B。本轮2GB预留已释放；这不是所有模块700GB总审计。

收尾时root回执：独立18084已实际完成时间区间62.051–64.143秒、左右边界/整段平移、三标签、区域增删后仍2ROI/bundle4的保存重载与集成截图；真实ROI模型审计、render/PTS、WSL CPU解码通过。上述是root独立实例的证据，不属于本报告私有项目；整项A-11～A-14由root归并。按其要求，本模块不再扩大测试或恢复Edge，不再要求用户关闭弹窗，旧tab恢复/截图/viewport reset仍保持未验证限制。
