# 浏览器视频标注工具：选型与本轮复用

核查日期：2026-10-02。目标是让用户快速标触球、回合、手法/步法和双方态势，并形成可训练的数据集。参考项目不等于已经集成；本轮主界面仍由badmintonTV提供。

## 选择结论

采用现有平台的独立训练工作区；复用原片校验、PTS映射、修订和快照机制，保留已安装Label Studio作为复杂区间/框标注副工具。借鉴VIA、Vidat和网球工具的快捷操作，不再启动另一套重型标注后台。常用操作在一个页面完成，用户不需要编辑JSON。

| 工具 / 一手来源 | 可复用能力 | 需要补的内容 | 许可与本轮决定 |
|---|---|---|---|
| [Label Studio](https://github.com/HumanSignal/label-studio) | TimelineLabels单帧/帧段；VideoRectangle框轨迹；已有REST/JSON回写 | training_only受控入口、多维标签配置、回源PTS、审核语义 | Apache-2.0；本地已有1.23.1，继续复用，兼容适配不等于所有新训练字段已打通 |
| [VIA 3](https://robots.ox.ac.uk/~vgg/software/via/index.html) | 轻量纯前端视频区间、属性和静帧空间标注；JSON/CSV | 触球点事件、修订、持久化、权限/用途及源PTS | BSD-2-Clause；借鉴轻量交互，备选adapter，未嵌入其源码 |
| [CVAT](https://github.com/cvat-ai/cvat) | 帧标签、骨架、单点轨迹插值、密集点/框纠正 | 独立部署及格式转换；区间语义不是最直接的交互 | MIT；密集轨迹标注规模增加后再考虑；本轮不安装其数据库/缓存/worker组合 |
| [Vidat](https://github.com/anucvml/vidat) | 浏览器动作区间、自定义骨架、JSON/HTTP提交、WebCodecs路线 | 多维动作字段、构建链、真实帧率/PTS；默认10fps抽帧不适合直接精标触球 | MIT；前端参考，本轮不直接迁移整站 |
| [Tennis action_annotator](https://github.com/Da-233/tennis-vision-analysis/blob/main/src/utils/action_annotator.py) | Flask页面、Q/E区间、数字类别、改删和自动保存 | 触球独立字段、多标签、球场点、隔离；默认复制/转码和全网卡监听不符合本项目要求 | 仓库MIT；仅借鉴操作方式，不原样部署 |

## 两个容易混淆的功能

[Label Studio KeyPointLabels](https://labelstud.io/tags/keypointlabels)是图像工具；可对绑定原PTS的静帧作点标，但不能据此称社区版已有视频关键点轨迹。新[VideoVectorLabels](https://labelstud.io/tags/videovectorlabels)标为Enterprise/Starter Cloud功能，不能写成本地社区版可用。

CVAT的[帧Tags](https://docs.cvat.ai/docs/manual/advanced/annotation-with-tags/)可以记录触球，但[导出格式](https://docs.cvat.ai/docs/dataset_management/formats/)覆盖不同；仅导出视频轨迹XML可能丢失分类Tags。任何接入必须做包含触球/区间/人物/unknown的往返测试。

VIA/Vidat提供浏览器交互组件，不自动解决原片身份、变帧率、比赛划分和训练/制作用途隔离。当前页面上的小数秒也不天然代表帧精确，要有真实PTS映射支持。

## 本轮落到工作台的设计

1. 视频与回合队列、大播放器、属性侧栏，常用标签中文可选。
2. 触球mark、回合起止、动作区间分别存在，可从时间线跳回原片。
3. 本人、对手、搭档与队伍可选择；姓名不明也可以用比赛内匿名身份。
4. 球种、手法、步法、球路和状态分开标，unknown有明确原因。
5. 原片只读引用，保存有修订/冲突提示，快照冻结内容，不复制视频。
6. 坐标如为图像点击必须标明归一图像坐标；只有经过校准才称场地坐标。

真实操作速度仍需用户试标后测量。agent浏览器验证只证明操作和持久化可用，不能替代教练判断或声称已经降低多少标注成本。本轮工程断言见[实施计划](IMPLEMENTATION_ROUND_2026-10-02.md)。

## 依赖记录

本次选型未安装上述新标注产品，也未复制其代码。已有Label Studio安装/来源及历史真实回写见[本地记录](platform/LABEL_STUDIO.md)。新工作台使用现有FastAPI/Jinja2/浏览器API；新增依赖若发生，以模块锁文件和handoff为准。

框架说明网页使用构建时Markdown解析器[Marked](https://marked.js.org/)，本机已有隔离的桌面工具runtime版本17.0.5，MIT；不加载浏览器CDN。解析器仅用于静态文档构建，不加入平台/模型运行环境；构建脚本禁用文档原始HTML并限制链接协议。输出网页可以离线阅读，Markdown仍是内容源。
