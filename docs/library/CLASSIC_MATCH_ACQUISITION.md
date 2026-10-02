# 林丹／李宗伟经典比赛采集

2026-10-03用户授权：搜索中羽论坛等资源并下载到既有D:/video，用于后续训练与识别。首批3–5场，总新增不超过30,000,000,000B，包含临时文件、工具及PTS/收据。基线main `c7e68ce4b0132a487e6de8f37d164ec45e157eda`，分支 `codex/library-classic-matches`。

## 开工断言

| 固定ID关联 / 子项 | 验证输入与方法 | 预期 | 开工状态 |
|---|---|---|---|
| S0-02.classic-source | 中羽原帖及实际视频来源页，检查可用下载入口 | 每份来源/赛名/轮次/发布者/许可及限制可追溯；不绕过登录、付费、下载限制 | NOT_RUN |
| S0-02.classic-acquire | 3–5场来源候选，容量预检与有界流下载 | 实际下载新文件，临时+成品+派生总新增<=30GB，不覆盖既有原片；失败保留真实收据 | NOT_RUN |
| S0-02.classic-media | 成品SHA、ffprobe、完整CPU解码与原PTS | 得到可读技术元数据与source绑定的完整PTS，未通过不发布已验证Asset | NOT_RUN |
| S0-04.classic-group | 对照既有Fine训练目录与新来源 | 同场回放/剪辑/转码关联合并候选；unknown不伪装已确认比赛组；split=unassigned | NOT_RUN，正式划分仍BLOCKED |
| R-04b.classic-scope | 训练子树、Asset用途及来源许可字段 | training_only继承；无动作/身份人工真值，不进入制作链；许可未知不声称研究许可已授予 | NOT_RUN |

本轮不训练模型、不使用GPU，不把下载或技术核验当识别成功。新数据目录计划为 `D:/video/data/training/classic-lin-lee-20261003/`；原片只读引用，生产handoff不变。现有标注目录绑定训练registry/split快照，追加登记前需处理兼容性，不能让旧目录静默失效。

开工实测：data14,805,732,192B；项目保守计费92,658,098,585B（runtime不可遍历，按70GB固定配额上界计）；D剩余922,086,301,696B；活动预留0。library data上限300GB、runtime/library上限5GB、项目总上限700GB。每次大写入前用既有QuotaManager预留；下载实际字节硬限，不由页面标称大小替代。

## 搜索与执行记录

候选完整记录见 [CLASSIC_MATCH_SOURCES.json](CLASSIC_MATCH_SOURCES.json)。中羽40场80G合集要求登录回复；2011阿里分享已失效；旧115礼包功能已下线。百度分享仅保存原帖的公开稳定链接，本次正常浏览器被站点安全策略阻止，不另用工具绕过。BWF/Olympics官方YouTube页本轮要求登录反机器人；CNTV2012旧回放明确返回不可播放。以上均不算已下载，也不使用共享账号、P2P或付费中转。

实际首批改用B站“奥林匹克运动会”发布的三场。公开无认证view/playurl正常返回，rights.download=1、pay=0、no_reprint=1；仅选择接口实际提供的普通单MP4。没有更改客户端身份、获取登录Cookie、解锁高画质或绕过限制。短期CDN签名仅驻内存，静态配置和收据保存稳定source_page_url。源平台允许下载不代表授予训练/商用/再分发许可，均rights.status=unknown、allowed_uses=[]，0人工真值。

| 场次 | 来源 | 公开API时长 | 预期视频字节 | API所选画质 |
|---|---|---:|---:|---|
| 2008北京奥运男单决赛 林丹—李宗伟 | https://www.bilibili.com/video/BV1eF411y7oh/ | 3337.000s | 482,738,928 | 720p |
| 2012伦敦奥运男单决赛 林丹—李宗伟 | https://www.bilibili.com/video/BV1xL411z7eX/ | 5298.700s | 196,694,186 | 360p |
| 2016里约奥运男单半决赛 林丹—李宗伟 | https://www.bilibili.com/video/BV1Dm421K7NG/ | 5439.623s | 791,975,537 | 720p |

合计预计1,471,408,651B。以上是远端元数据，下载/解码结果另记；不得把上传原版dimension或网页标题当所下载文件的规格。2012公开DASH最高480p，本次选择无需混流的360p单文件以保存原PTS；细小羽毛球及细手法可识别性未验证。

本批review_only AssetManifest单独位于batch/handoff，未经人工审核和中央注册导入，不声称已接入标注工作台或已可启动训练。中央registry/splits及旧annotation catalog保持现有快照兼容。与Fine中既有2011/2010/2014候选未按SHA视为同一文件；Fine未知videoplayback的同场关系仍未知，不能拿新三场建立独立train/test承诺。

## 实现与运行

本地实现提交 `089fe6add6ea5799cd76226dad8ba6c41d981650`。只读复用平台Python3.12.11/Pydantic2.13.5、既有render FFmpeg9.0.2；未安装新工具、未用GPU、无常驻服务端口。网络元信息只读与D盘有界写入使用用户已授权下载范围的提升执行；没有自动审批拒绝。

启动（仓库根目录，PowerShell）：

```powershell
& 'D:/video/runtime/platform/env/Scripts/python.exe' -B -m scripts.library.acquire_public_bilibili --config 'configs/library/classic_matches.json' --ffmpeg 'D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe' --ffprobe 'D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe'
```

有界流每次只访问正常公开API提供的单文件，配置max_bytes分别600MB/300MB/1GB；每项再核对远端精确size，失败不发布成功资产。批次累计上限30GB涵盖part、PTS和审计；序列CPU探测另预留132MB（PTS128MB+元数据4MB）。既有数据收据内容变更记录old/newSHA审计，视频和PTS不覆写。

全库工程回归223/223 PASS、0 skip、28.146s，详见 [测试收据](CLASSIC_MATCH_TESTS.json)。覆盖下载拒绝/付费即停止、超限不成功、签名URL不落盘、失败probe不出成功资产、成功记录后中断可恢复manifest，以及旧manifest对应记录缺失/损坏时保留旧清单。这些是工程夹具结果，真实视频验收另记。真实首轮已加载的脚本在最后旧清单恢复保护补丁前启动；新批次路径不受该补丁影响，后续复跑使用完整已测试版本。

## 实际交付与验收

首批3场下载全部成功，原片共 **1,471,408,651B**，总时长 **3:54:34.640**；包含完整PTS、收据、审核清单和6张QA样帧的整个批次 **1,484,666,698B（约1.485GB）**。实际文件和独立复核证据见 [CLASSIC_MATCH_RESULTS.json](CLASSIC_MATCH_RESULTS.json)。没有下载部分文件残留，也没有活动预留或批次锁。

| 文件（相对于D:/video/data/training/classic-lin-lee-20261003/） | 实际规格 | 视频时长 | 完整帧数 | SHA-256 |
|---|---|---|---:|---|
| raw/2008-beijing-final-lin-lee.mp4 | 1280×720，25fps | 55:36.720 | 83,418 | 5be9e7b28fe122c3f15892ddda026f7c505380f3ace59b85f47e0a590fdc8c01 |
| raw/2012-london-final-lin-lee.mp4 | 640×360，25fps | 1:28:18.560 | 132,464 | e0a3253b69ce5722f188cce17f1cc1728b96988bf2f7be41c27b7735497b719c |
| raw/2016-rio-semifinal-lin-lee.mp4 | 1280×720，25fps | 1:30:39.360 | 135,984 | edd640486b313868957b75ea3a80b0bc3450711595cd23c2dabeefb425a1df3f |

三份均通过FFmpeg9.0.2全视频流CPU解码；总351,866帧的原始整数PTS已保存，独立重数行数、检查单调递增、重算视频及PTS SHA并通过AssetManifest合同验证。技术时长来自视频stream.duration，与播放器包含音频/容器尾部的时长略有差异，未截短或转码原视频。全部原片保持所下载字节。

6张样帧已看图：2008/2012中点是主球场转播视角；其他样帧包括热身、入场、俯拍或运动员近景。该抽查仅证明局部画面可读，不证明全片每个回合连续、全场球场可见、球员身份或动作真值。2012为实际360p，识别小球和细手法的适用性仍未测。

| 固定ID关联 / 子项 | 实际结果与证据 | 结论 / 未达标项 |
|---|---|---|
| S0-02.classic-source | 三份稳定官方发布页、下载标志和来源元信息已存source-catalog与Asset provenance；14条候选及失败原因为独立搜索记录 | PASS；视频训练/商用/再分发授权仍未知 |
| S0-02.classic-acquire | 三份真实原片共1.471GB；批次1.485GB；无part、无锁、活动预留0；每份实际bytes等于公开API size | PASS |
| S0-02.classic-media | 3/3完整CPU解码、3/3视频/PTS SHA复核、351,866行原PTS重数、typed manifest通过 | PASS；模型识别NOT_RUN |
| S0-04.classic-group | 新三场仅按来源命名；既有Fine未知视频仍可能同场；全体unassigned，没有制造独立训练/测试分组 | 本轮保守隔离PASS；正式比赛组/划分BLOCKED，需人工审核 |
| R-04b.classic-scope | 顶层与provenance双training_only、rights unknown、allowed_uses=[]、0人工真值；review_only批次清单 | 本地标记PASS；中央登记/工作台导入NOT_RUN |

主要入口（均在D:/video）：

- `data/training/classic-lin-lee-20261003/raw/`：三份原片。
- `data/training/classic-lin-lee-20261003/handoff/assets.v1.json`：三份Asset的待审核清单。
- `data/training/classic-lin-lee-20261003/handoff/verification.v1.json`：独立校验及样帧观察；SHA `96836ad15e5fc1d0d7bb4c4ba68b16339ed6cef33ef3ed13219131e2b812f261`。
- `probes/`保存完整PTS，`qa/`保存6张抽帧，`source-catalog.v1.json`保存可复核的来源计划。

最终容量：data **16,290,398,890B**；项目保守计费 **94,144,360,854B**（runtime仍按70GB固定额度上界，不是实际用量）；D可用 **920,509,063,168B**，活动预留0。新增总量与batch实测完全一致，低于30GB用户上限及300GB data/700GB项目配额。

中央training-registry SHA `63eb86de88e6c760be8ff3464318d8fd55a923e7bfa1d1c177dc2bdd643e52aa`、training-splits SHA `4c8ac9e928775e0f1025c64655fa24d9a9557f73cf03efda9aa3cc890109c4ef`、旧annotation-catalog SHA `3fc6adf81e6f5229e4b4e4ae7de215be89bc415838d5e5aea64fb28ec85bea32` 全部保持不变。未宣称新数据已接入工作台或进入训练。

本轮用户下载目标已完成。后续训练/识别前的来源用途、细手法画质、独立分组和人工真值前提见 [访问与用途问题](../issues/library-classic-source-access.md)。本轮没有训练、预测或自动生成真值。
