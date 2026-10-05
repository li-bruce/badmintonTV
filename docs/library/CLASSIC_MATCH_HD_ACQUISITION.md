# 经典比赛高清批次：至少11场、最低1080p

2026-10-05用户更新：先下载10+个，最少1080p。按至少11个不同完整比赛候选实施，沿用经典采集30,000,000,000B总上限，包含旧批次、新原片、partial、PTS、元数据及派生峰值；不自动删除旧文件。旧批次1,484,666,698B，剩余28,515,333,302B。数量/画质目标优先于旧3–5场计划，旧720p/360p三场不计入新目标。

## 开工断言

| 固定ID关联 / 子项 | 输入与验证 | 预期 | 开工状态 |
|---|---|---|---|
| S0-02.classic-hd-source | 正常公开来源及实际码流元数据 | 至少11个不同完整比赛，包含林丹或李宗伟；网页标题/上传dimension只为线索 | NOT_RUN |
| S0-02.classic-hd-acquire | 有界下载、总容量与原文件核对 | 新旧经典批次累计与下载峰值<=30GB；旧文件不覆写/删除；无登录/付费/下载限制绕过 | NOT_RUN |
| S0-02.classic-hd-media | 实际ffprobe、完整CPU解码、原PTS与SHA | 宽>=1920、高>=1080且逐行扫描；低清、1080i、未知扫描状态不计达标；不以放大插帧伪造原始清晰度 | NOT_RUN |
| S0-04.classic-hd-group | match_id与旧同场版本对照 | 同一比赛多版本不凑场数，不跨训练/测试集合；split=unassigned | NOT_RUN，正式划分仍BLOCKED |
| R-04b.classic-hd-scope | 独立训练子树、来源用途字段 | 双training_only、rights证据独立、0人工真值、review_only，不改原中央快照 | NOT_RUN |

开工实测：data16,290,398,890B；项目保守计费94,147,175,539B（runtime不可遍历，按70GB配额上界）；D可用920,528,027,648B，活动预留0。执行环境复用现有平台Python与FFmpeg9.0.2，不新建Conda、不用GPU。

## 当前来源检查

- 正常Edge里约半决赛页可见“登录免费享高清视频”，当前未登录。已保留该页并请用户正常登录；未索取凭据、未从本机浏览器凭据库提取Cookie。
- 无认证普通API请求1080：2008北京决赛BV1eF411y7oh和2016里约半决赛BV1Dm421K7NG实际仍返回720；2015日本1/8决赛BV1cT411U7wp虽标题/可选说明写1080，实际返回360。没有下载这些降级文件。
- 中羽40场80G合集明确有不少未达1080；旧百度入口仍受此前站点安全策略约束，不另换工具绕过。新浪2012全场标题1080，但正常公开播放器API实际852×480，已排除。
- IA北京决赛704×384、里约羽毛球768×432、伦敦BBC相关比赛日608×336；不计入。现有18个Asset中唯一>=1080是4.404秒双打片段，非目标比赛；本地合格完整场数0。

本轮真实高清下载尚为0，未把候选或代码存在视为达成。后续仅在实际高清源可正常访问后写入新批次；如需双轨合并，先记录源轨SHA/PTS与容量峰值，原片不重新编码。

## 2026-10-05实测来源记录

| 来源 | 正常访问所得结果 | 高清计数 |
|---|---|---:|
| https://www.bilibili.com/video/BV1eF411y7oh/ | qn=80正常API实际返回quality64/mp4720，482,738,928B | 0 |
| https://www.bilibili.com/video/BV1Dm421K7NG/ | qn=80正常API实际返回quality64/mp4720，791,975,537B；Edge页面明确登录享高清 | 0 |
| https://www.bilibili.com/video/BV1cT411U7wp/ | 标题1080p，48:21；qn=80实际返回quality16，141,130,486B；support_formats描述80不能替代实际返回 | 0 |
| https://k.sina.com.cn/article_2020948351_m7875397f03300drd3.html | 2012伦敦决赛，标题1080P；引用的正常播放器API仅852×480，5,390,210ms、441,025,368B，无媒体下载 | 0 |
| https://sports.cntv.cn/20110314/100790.shtml | 2011全英决赛56:00；videoCenterId=3b893bac29fa404f663378aac7cfdff1；公开视频信息ack=yes/play=1，HLS主清单唯一流480×360，未读分片 | 0 |
| https://quanzi.tiyushe.com/article/view.html?id=9887&share_uid=0 | 39场目录列2015中国、2016亚锦/里约、2017马来西亚四份SNG1080i；仅公开百度入口，未访问受限域，实际流/大小未知 | 0 |
| https://bbs.badmintoncn.com/forum.php?mod=viewthread&tid=3676429 | 40场80G目录自承部分达不到1080P，实际下载区需要登录回复；未发帖 | 0 |
| https://archive.org/details/2008_Beijing_Olympics | 男单决赛元数据704×384，413,673,115B | 0 |
| https://archive.org/details/2016_Rio_Olympics_Net_Sports | 羽毛球原MKV元数据768×432 | 0 |
| https://archive.org/details/2012_London_Olympics_BBC_Coverage | 相关比赛日原AVI608×336 | 0 |
| https://cvssp.org/acasva/Downloads.html | 下载页明确不提供原视频 | 0 |
| https://www.infront.sport/sports-media-rights/portfolio/badminton/bwf-major-championships-world-tour | BWF版权档案拥有历年SD/HD及full archive；具体1080p文件需正规账号/授权，未登录/联系 | 0 |
| https://www.olympics.com/en/video/men-s-singles-final-badminton-london-2012-replays | 正常匿名页面HTTP200、时长1:36:55；页面引用的HLS master正常匿名读取HTTP403后停止，未读分片，分辨率/扫描方式/DRM/可下载性均未确认 | 0 |

这些是来源排除证据，不是已下载成果。没有下载低清文件充数，没有安装新软件或改变浏览器设置。代码尚未扩展，旧工具sources上限5且不强制最低画质；在正式启动高清批次前须添加数量、实际逐行画质与跨批30GB预算门槛。没有高清源时不先做未能实际验证的DASH混流功能。

## 本轮实际验收与交接

| 子项 | 实际结果 | 状态 | 未达标原因 / 下一步 |
|---|---|---|---|
| S0-02.classic-hd-source | 已核查上述正常入口；确认可正常下载且合格的高清整场0/11 | BLOCKED | 实际流低于要求或正常访问受限；等待用户在已保留的Edge页面正常登录，再核查可用画质，或取得其他可访问的合格源 |
| S0-02.classic-hd-acquire | 新高清媒体写入0，原三场保留；没有启动高清批次下载 | NOT_RUN | 缺少合格源；不能以容量充足代替真实有界下载验收 |
| S0-02.classic-hd-media | 没有新文件可供探测、完整解码、SHA及PTS核验 | NOT_RUN | 后续每个实际文件均须逐项通过后才计入11场 |
| S0-04.classic-hd-group | 没有发布新Asset或划分集合 | NOT_RUN | 正式比赛独立分组仍BLOCKED，需在实际素材到齐后核对 |
| R-04b.classic-hd-scope | 没有新高清批次清单；原中央快照未作写入 | NOT_RUN | 尚无新产物，不能复用上一批PASS宣称本批已验收 |

用户目标尚未完成。本轮仅修改library来源/问题/状态文档，未修改执行代码，未启动训练、服务或GPU任务，未重跑无关工程测试；运行代码基线仍为 `089fe6add6ea5799cd76226dad8ba6c41d981650`。当前旧下载入口不满足本轮门槛，故没有提供可直接启动高清批次的命令。取得正常可用高清源后，先完成数量/质量/共同预算门槛并验证，再下载和验收；正常登录不预先保证凑齐11场。
