# 研究成果实施轮：2026-09-29

用户授权实施上一轮视频工具/模型研究，下载新找到的完整职业数据用于模型开发，尝试动作、位置、球轨迹与战术方向的现成模型。沿用四模块分工、独立 Git 分支、700 十进制 GB 和 owner 配额；主任务负责接口与集成。

## 冻结的数据用途与接口

1. `Asset.usage_scope` 兼容扩展为 `general | training_only`，默认 `general` 以读取旧清单。用途与 `rights`、`split` 分开：training_only 包含训练、验证、测试和内部模型诊断，不意味着所有比赛属于 train。按整场确定 split 前保持 unassigned。
2. 新职业数据固定在 `data/training/<dataset-version>/`，专用 handoff 位于 `data/training/handoff/`。不得追加制作素材库 `data/handoff/assets*.json`，不得自动导入制作库。原文件只读共享，模型输出仍在 models。
3. typed `usage_scope=training_only`、兼容 `provenance.usage_scope=training_only`、规范路径位于 `data/training/`，任一命中从严处理，检查逻辑路径和解析后的物理路径。衍生物保留用途与源资产/hash关系。制作库导入、候选到时间线、保存时间线、worker 执行与独立 render CLI 均拒绝此数据；`research_preview=true` 不豁免。模型诊断的关键点/轨迹可视化属于实验产物，不能进入成片工作流。
4. platform 首先交付合同字段和共用用途判定 helper 的独立提交；其余模块同步该提交。下载可先进行，但 handoff 发布需通过新合同。
5. 预览代理保留源 hash、源 PTS 和代理到源映射；标注始终落在源时间。源帧率不等于代理帧率，720p 代理不构成手腕/拍面可见性证据。显示图像对应帧与区间覆盖范围须区分，降帧不能造成区间回写缺口。

可信用途登记固定为 `data/training/handoff/training-registry.v1.json`，由 library 独占原子写入。UTF-8 JSON 顶层 `schema_version="1.0"` 和 `assets` 数组，每项至少 `asset_id,sha256,relative_path,usage_scope="training_only"`，可附 provenance；不是完整 Asset。先登记再发布训练 manifest。制作端只读，损坏不能回退为放行；用途不能降级。产品内派生物继承源 asset_id/hash 与用途。此约束不声称能识别在产品外任意转码且删除全部来源信息的文件。

## 实施职责

| 模块 | 本轮实现 | 实际验证 |
|---|---|---|
| platform | 用途合同/制作库隔离；兼容播放代理、源时间映射、逐帧/循环/缩略图交互；原分辨率核查 | CFR/VFR/不支持容器、修订往返、寻帧计时、容量与取消、浏览器操作 |
| library | 作者2026 Fine-Badminton完整公开包，许可/哈希/安全解压/探测/标注语义与整场分组；模型handoff | 实测场数/时长/CSV、作者校验和、训练用途隔离 |
| models | TrackNetV3球轨迹、Qwen3-VL-Embedding-2B视频向量；姿态/位置/时序技术路线；明确战术边界 | 真实视频有界运行、实际输出、分项时延/显存；因果约束与稳态RTF单列 |
| render | 30/60fps导出档、安全区；训练素材拒绝；CPU/NVENC和适用NVDEC对照 | 相同真实时间线、ffprobe/解码/映射、大小/速度/质量；无平台上传 |

models 持有 GPU 排期，render 的短硬件基准须协调同一窗口/租约，不能与模型加载或推理抢占。无GPU时先开发/下载/CPU测试，不停止用户进程。

## 新增固定验收用例

正式补充用例，不改变原25项产品用例门槛。模块报告给输入、命令、预期/实际、证据与下一步。

| ID / 阶段 | 目标断言与验证方法 | 初始状态 |
|---|---|---|
| R-01a / S4 | 同一真实时间线输出1080×1920 H.264 yuv420p AAC48k的30/60fps；ffprobe、全解码、长度/映射一致；安全区不裁比赛画面 | NOT_RUN |
| R-02a / S1 | CFR、真实VFR或明确标注的VFR派生测试片、不支持格式均有有界代理；30固定点源PTS误差≤一个源帧；可回查原分辨率 | NOT_RUN |
| R-02b / S1 | 浏览器逐帧/循环/缩略图与源时间修订保存成功；记录30点冷/热寻帧中位数和P95 | NOT_RUN |
| R-03a / S2、S4 | CPU/NVENC同输入验证尺寸/帧数/源时间；分项时延、大小、质量指标和视觉检查；设备不可用如实失败/阻塞 | NOT_RUN |
| R-03b / S2 | 分开记录解码、预处理、模型、后处理和冷启动；尝试NVDEC时验证实际设备路径与PTS；未测不称加速 | NOT_RUN |
| R-04a / S0 | 完整公开ZIP大小和MD5/SHA256校验、安全解压；实际比赛/时长/标注数与作者描述逐项核对差异 | NOT_RUN |
| R-04b / S0、S4 | 专用训练manifest供模型读取，制作库导入/选片/直接渲染/研究预览拒绝，覆盖用途冲突和保留路径 | NOT_RUN |
| R-05a / S3 | 2B视频嵌入在隔离WSL对真实片段及中文查询产生有限向量/排序；记录版本/hash/显存/时间，不报无真值准确率 | NOT_RUN |
| R-05b / S3、S5 | CLIP/规则同划分、同人工真值和审片预算比较P@K/召回 | BLOCKED：缺真值 |
| R-06a / S0、S5 | 三细标签有专家认可可观察定义及独立真值后再训练/报告支持范围 | BLOCKED：缺专家真值 |
| R-07a / S2 | TrackNetV3官方权重在真实连续视频输出源PTS球位置/缺失；观测与补轨分开，报告失败/耗时 | NOT_RUN |
| R-07b / S2 | 位置/姿态路线输出可回查轨迹或明确未跟踪；场地坐标有校准来源/适用镜头；track ID不当姓名 | NOT_RUN |
| R-07c / S2 | 给定窗口/分辨率/帧率下因果处理稳态RTF≤1，记录端到端延迟/丢帧；使用未来帧的离线模型不计通过 | NOT_RUN |
| R-07d / S2 | 战术技术路线与可运行组件分开；推测有观测依据/不确定性；缺模型/真值保持experimental/unavailable | NOT_RUN |
| R-07e / S2 | 最近的公开粗动作checkpoint以真实姿态/位置/轨迹输入运行，遵循作者归一化与类别；输出不等于细手法真值，缺必要输入不能用随机值替代通过 | NOT_RUN |

下载前重测容量，包含压缩包、解压、临时副本、权重/环境；6.5GB标称包不等于峰值。先可复现小窗再整场批处理，不盲目训练缺乏细标签真值的类别。
