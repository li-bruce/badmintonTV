# Platform 验证记录

日期：2026-09-29（北京时间）。真实资料与结构测试分开记录。

## 自动化

`D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/platform tests/contracts -q`：236 passed、2 skipped。跳过项是runtime测试账号不能创建symlink与需显式选择的WSL实机测试；后者已另外实机运行1 passed。contracts及storage真实Windows junction越界测试已通过。Starlette针对httpx测试客户端发弃用提示，当前功能测试通过。

覆盖：统一合同与attempt/退出码；实际SHA欺骗拒绝；路径逃逸；event修订409/批量事务回滚/来源为model的人类确认保护；human/agent审计；同球员同回合对手插拍；unknown候选不视为已命中；否定/混合查询拒绝；候选明确确认；传递重叠合并；LLM密钥遮盖；跨来源写入拒绝；任务领取竞争、租约中断、心跳、重试、取消完整子进程树、产物hash、资源容量、缺失模型blocked。

## 真实原片与浏览器链路

资料：library handoff `D:/video/data/handoff/assets.v1.json` 的4个FineBadmintonBenchmark Asset，原片只读。公开画面权利unknown，source match分组未确认，不能随机切训练/测试。没有私人录像、专家细技术真值。

1. 18080服务导入4条Asset，视频Range预览成功。独立worker另完成真实hash/ffprobe/缩略图，原PTS保留；详见RUNTIME。
2. Edge实际点击素材→预览第一段→填写[0,4000)镜头区间→选择Agent审阅来源→保存。标签仅scene=rally_clip、stroke/hand_technique=unknown，球员未确认；不是展搓/收搓真值。
3. 网前击球中文规则解析实际显示QuerySpec。随后通过可编辑条件查询scene=rally_clip，获得3段真实候选；逐个点确认选用，审阅来源agent。
4. 点击生成时间线，保存中文总标题/片段标题、第二段speed=0.75；保留contain；点击“提交竖屏导出”，默认research_preview=true。
5. 页面实际创建`job-3ebf04b748644087b1328283382df830`，worker独立调用render CLI，attempt-1 succeeded。request/result在`D:/video/platform/jobs/<job>/attempt-1/`，4个产物在`D:/video/render/jobs/<job>/attempt-1/`。
6. 成片`export.mp4`为14.833333s、445帧、1080×1920、H264/AAC、938753 bytes。QA所有技术项通过，4产物hash另行核验均符；原片无音轨，输出静音AAC。6秒成片帧已视觉核对：完整球场、球员、中文慢放标题和“待人工确认·本地研究样片”。
7. 平台进程真实重启，4素材、浏览器保存的event、LS修订历史仍可读；时间线/任务使用同一SQLite恢复。没有把重启当成任务成功。

报告：`D:/video/platform/handoff/platform-real-flow.json`、`platform-restart-check.json`、`events.v1.json`、`assets-imported.v1.json`、`browser-export-frame.jpg`。这些为运行产物，不入Git。手工确认技术标签=false，公开发布资格unknown。

## Label Studio 与模型适配

Label Studio 1.23.1真实API→Edge编辑TimelineLabels和VideoRectangle→导出→PTS转换→平台CAS revision2，随后显式补记agent审计revision3。重复原annotation不新增版本；LS与平台各自重启后保留。工具框导出的time曾实测偏移一帧，所以一律使用frame→PTS权威映射。详见LABEL_STUDIO和独立issue。

导入6个ModelManifest，页面按实际执行环境显示ready/experimental/unavailable及参数。CPU query-rule-v1经持久队列和统一模型CLI执行：`job-2142e445c48249f8ac66dc24efb1fa92` attempt1因models下载独占写锁失败，被模块报output_exists；未删锁。协调models空闲窗口后显式retry，attempt2 succeeded，旧日志保留。models已修复锁竞争返回OWNER_BUSY。Qwen卡已更新为WSL experimental，开发提示诊断仅2/24通过，不用作默认可靠解析。UI不加载torch。

## 真实平台 GPU 与大文件回归

Edge模型下拉框选择COCO17、输入原片asset-5ad7e41...及0–6000ms/4fps/max_frames24，点击提交创建`job-3dc9ece15e914eecb9616ac306ece6b8` attempt-1。Windows worker经管理员精确模型argv启动受控WSL Python；SQLite仍仅Windows访问。页面观察到queued→running/decode→succeeded/completed。

源片6秒、24帧；RTX5090 / torch2.7.1+cu128；含加载解码28.702605725秒，allocated489201152/reserved792723456bytes。此冷短片结果不可当成全比赛稳态吞吐；平台旧素材快照camera/discipline为unknown，未声称完成分层验证。features620202bytes、report849bytes，两个SHA独立核验。events=[]、accuracy/recall=null、manual_review_required=true。结果在`models/jobs/<job>/attempt-1/`；request/result/done在`platform/jobs/<job>/attempt-1/`。done确认compute_stopped=true、exit0；GPU租约released，窗口提前revoke后available=false/active_window=null/lease=null，正式归还models排期。

Windows进程死亡→Linux守护清理另用真实WSL CPU进程树验证通过；没有以CPU fixture声称GPU中断实测。完整证据 `D:/video/platform/handoff/platform-wsl-pose-real-flow.json`。

probe大文件回归使用原6秒视频的本地无损FFV1派生`platform/qa/probe-large-real-source-20260929.mkv`，50,049,933bytes，仅用于修复验证，不算新的独立比赛。`job-d1e09c26b26e449193b209871a9e7d5b`真实hash/ffprobe/缩略图成功后API apply HTTP200，直接使用worker_sha256_verified入库，无Web重复大文件hash或新的verify任务。原片只读，派生文件保留记录。

## 剩余限制

- GPU窗口/租约/WSL启动已实作且单次pose通过；不代表四模块全部实验统一调度。仍须先与models协调，默认无窗口不可启动。
- 没有真实LLM端点/密钥，本轮连接失败/密钥屏蔽与规则兜底已测，真实LLM语义效果未测。
- 本轮真实片段全无音轨，混合格式、音画同步/慢放音频技术矩阵由render模块报告；不得用本次静音素材声称真实人声同步已测。
- 未提供个人录像或专家确认细标签，自动识别成绩未验收；Agent选片与人类技术确认明确分开。
- library网络下载尚无平台job adapter，仅manifest/原片引用；回放自动识别去重未实现。
