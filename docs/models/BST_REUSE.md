# BST 复用审查（2026-09-29）

状态：**调研和严格适配器已实现，29项 CPU 夹具测试通过；真实推理 NOT_RUN**。主任务已下载并核验固定权重，本适配器独立读取清单、重算源码/权重哈希通过；未运行模型。本文件不宣称精度通过或人工校准完成。下方公开访问记录保留最初只读调研时点，最新本地清单和输入接口见末节。对应本轮 R-07b、R-07c，以及原 S2-03 / S2-04；正式验收以 [实施轮断言](../IMPLEMENTATION_ROUND_2026-09-29.md) 和 [阶段总表](../STAGE_ACCEPTANCE.md) 为准。

## 能否复用现有真实输入

**有条件可以组成一个单打离线粗球种实验；现有稀疏 pose 文件不能直接代表作者完整输入链路。** 需要在同一源视频、同一连续镜头与逐帧 PTS 上，准备真实两人 COCO17 姿态/框、真实羽球轨迹、可审查的场上两人分配、有效球场校准和击球窗口。已有 pose 可用作格式与人工 QA 的起点；连续源帧缺口、裁判误检、检测编号变化均须处理并记录。作者采用 MMPose；换成本项目现有姿态模型是输入分布变化，不是作者结果复现。

模型输出只作为 `experimental` 粗球种候选，不得转成展搓、收搓或后退小跳的已确认真值。未有独立完整真值时 `accuracy=null`、`recall=null`；一次输出 25 个有限 logits 只证明前向执行。

## 固定来源、许可与公开权重

| 项目 | 2026-09-29 核验结果 |
|---|---|
| 官方仓库 | [Va6lue/BST-Badminton-Stroke-type-Transformer](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer) |
| 固定提交 | `fb9b310bf4c8a8e3d89c75e61bc06a7ac3de62df`，提交时间 `2026-06-06T03:49:44Z`，GitHub API 返回 tree 未截断 |
| 代码许可 | [固定提交 LICENSE](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/blob/fb9b310bf4c8a8e3d89c75e61bc06a7ac3de62df/LICENSE)：MIT，Copyright 2025 Jing-Yuan Chang |
| 权重入口 | README 的 ShuttleSet [公开 Drive 目录](https://drive.google.com/drive/folders/1D4172WZDJWPvpJdpaHDhy_cA-s8F-zR5) |
| 选定依据 | 官方 [bst_infer.py](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/blob/fb9b310bf4c8a8e3d89c75e61bc06a7ac3de62df/stroke_classification/main_on_shuttleset/bst_infer.py) 的示例组合，不是本项目用测试集挑出的最佳权重 |
| 精确文件名 | `bst_CG_AP_JnB_bone_between_2_hits_with_max_limits_seq_100_merged_2.pt` |
| 公开文件 ID | `1snqpEEww-GG6xFUBzkuctYAPHcBP360B`；[文件页](https://drive.google.com/file/d/1snqpEEww-GG6xFUBzkuctYAPHcBP360B/view)匿名 GET 返回 200 |
| 页面状态 | 普通目录滚动找到目标，界面显示约 `7.2 MB`、修改日期 `2025-08-02`；文件共享说明为知道链接即可查看、无需登录 |
| 二进制入口 | 文件页提供的 [官方下载链接](https://drive.usercontent.google.com/download?id=1snqpEEww-GG6xFUBzkuctYAPHcBP360B&export=download) |
| 无内容 HEAD | 200；`Content-Type=application/octet-stream`；`Content-Length=7514133`；Content-Disposition 的文件名与目标相同 |
| 权重校验和 | 本次未下载，因此本地 `sha256=null`。响应无 `ETag` / `Content-MD5`，所查公开页未提供 SHA256；不得把文件 ID 或 Git 提交当权重 hash |
| 权重、数据与媒体许可 | 已核验 MIT 代码许可；尚未取得独立权重许可说明。代码许可不自动确认训练数据/原视频的再分发或商用权利，需分别登记 |

目录最初匿名 HTML 只列出前 50 项，不能把未显示的文件推断为不存在；随后通过正常浏览器目录读取目标。浏览器已有登录状态，未主动登录、改权限或下载；再以匿名 HTTP 文件页和 HEAD 独立核对公开访问。未遇限流/验证码，不使用绕过机制。没有下载权重或数据、执行远程代码、安装依赖、运行 GPU。

源码只读校验记录（用于后续复核文件是否同版；不是权重 hash）：

| 固定提交下源码 | SHA256 |
|---|---|
| `stroke_classification/model/bst.py` | `4313f9f411a90da24bfeead81f88b83894363bfd5248a75132a8c60ec3905b74` |
| `stroke_classification/model/tempose.py` | `0f3274bb4c0ec1b3f4a068b066993b7f1c0d58349bb580b55d0e0919e3821bc6` |
| `stroke_classification/preparing_data/prepare_train_on_shuttleset.py` | `e75127c188eaa4ae29cab7836c26f40c71f54b338ae439c2b92897fcf6517287` |
| `stroke_classification/preparing_data/prepare_train_on_shuttleset_merged.py` | `b62048822c2ca6face0f1d5bb2be55f673cd2a1be44f337956ca0d920b63c096` |
| `stroke_classification/preparing_data/shuttleset_dataset.py` | `5d5e0f4442ce4e59b093ef1df0b2da123f26f679e31d0f7be462416858f87f38` |

读取工具：官方 GitHub / raw 源文件的小型限额 HTTP 读取、公开 Drive HTML 与 HEAD；普通目录浏览使用已安装 `computer-use` 26.924.22138 技能及 `unified-computer-use` 浏览器工具，来源 `openai-bundled/computer-use`，本轮无安装。浏览器仅用于发现公开文件名/ID，不保存用户账号或浏览数据。

## 模型和标签含义

[BST_CG_AP 源码](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/blob/fb9b310bf4c8a8e3d89c75e61bc06a7ac3de62df/stroke_classification/model/bst.py)融合关节/骨向量、场地位置与羽球图像轨迹，包含 TCN、时间 Transformer、人与球的 cross-attention、交互 Transformer、clean gate 和 aim-player 分支。作者源码注释给出 CG/AP 约 **1.85M** 参数；本次未实例化计数。不要把小分类头参数量当作姿态、球检测及预处理的整链资源量。

示例配置：`model_name=BST_CG_AP`、`seq_len=100`、`in_channels=2`、`n_classes=25`、`pose_style=JnB_bone`。两人输入经关节及骨向量展平为 `[batch,100,2,72]`；`pos=[batch,100,2,2]`；`shuttle=[batch,100,2]`；有效长度为 `[batch]`。72 来自 `(17 COCO joints + 19 bones) × 2`，不是输入关节置信度。`J_only` 是另一种维度/权重组合，不可与 JnB 权重混用。

源码的两个人槽位与球槽位参与交互，`n_people>2` 明确未实现。**不能把双打四人裁成两个最高分检测冒充支持双打。** Top/Bottom 是场地侧别，不是实名身份，也不意味着跨换边长期 track。

合并标签由 [shuttleset_dataset.py](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/blob/fb9b310bf4c8a8e3d89c75e61bc06a7ac3de62df/stroke_classification/preparing_data/shuttleset_dataset.py)规定：**12 球种 × 上/下场 + 1 未知球種 = 总计 25 类**。12 类依次为：放小球、擋小球、殺球、挑球、長球、平球、切球、推球、撲球、勾球、發短球、發長球。标签索引应直接锁定作者序列，不能翻译后重排。模型第 0 类“未知球種”是训练标签；本项目“证据不足/看不清/未审核”的 `unknown` 是证据状态，二者分开存储。球种名不能映射为已确认腕指/拍面细手法。

## 必须遵守的作者输入处理

以下规则来自固定版本 [ShuttleSet 预处理](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/blob/fb9b310bf4c8a8e3d89c75e61bc06a7ac3de62df/stroke_classification/preparing_data/prepare_train_on_shuttleset.py)。复用时须做逐项数值对照；本表不是已经通过的适配器测试。

| 输入 | 源码规则与适配要求 |
|---|---|
| 姿态与 bbox | COCO17 图像像素坐标、每人 bbox `[x1,y1,x2,y2]`；推荐调用 `joints_normalized_by_v_height=False`、`joints_center_align=True`，函数默认值本身不是推荐调用值 |
| `normalize_joints` | 坐标减 bbox 左上角、除 bbox 对角线长度，再减归一化 bbox 中心；不能换成全视频归一化或髋中心缩放。原零坐标先按作者条件保留零，中心对齐后还会减中心；缺失语义须原样对照，不能把 score 当坐标 |
| 场地位置 | 原图坐标先映射到作者 1280×720 参考，再使用相应 H；COCO 左右脚踝各自投影后求中点，再按投影球场边界 L/R/U/D 归一化。`H(mean(pixel ankles))` 通常不等于 `mean(H(ankles))` |
| 场上两人 | 作者按场地范围筛人，只接受恰好 2 人并按归一化 y 排成 Top、Bottom。没有提供长期身份跟踪；本项目须额外输出选择依据及可审查分配 |
| 羽球 | TrackNet X/Y 除**原视频**宽/高，保持图像坐标；不套用球场 H。每条观测与 pose 共用源帧/PTS，不拿近似行号静默对齐 |
| 失败帧 | 作者人在场内检测数异常时两人的关节/位置置零，并同步将该帧羽球置零。复用要保留原始观测、失败 mask 和原因；不能以全零/随机三路输入替代真实观测后声称跑通 |
| 时长整理 | `make_seq_len_same` 对过长序列使用作者 stride 规则对三路同步抽样；不足部分尾部补零并传有效长度。补齐实际短片与捏造缺失模态不同；禁止为满足100帧重复稀疏 pose 假装原帧率 |

骨向量按作者 19 个 COCO 连接和端点差生成，再与17关节拼接；采用其逐坐标非零掩码。框退化、脚踝缺失、时间长度不一致或 H 无效应阻塞/显式 unknown，不能默默用备用常数把 tensor 形状凑齐。

若 H 是直接从原图四点估计，则需与作者参考坐标链作数学等价转换；不可先由原图 H 投影，再误乘 1280×720 缩放。手工校准要存源尺寸、四点名称与顺序、目标点、H、适用镜头和审查者，确保近远场方向一致。

窗口也属于输入协议。[gen_my_dataset.py](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/blob/fb9b310bf4c8a8e3d89c75e61bc06a7ac3de62df/ShuttleSet/gen_my_dataset.py)的 `between_2_hits_with_max_limits` 使用当前击球的前一次与后一次击球边界：前界缺失时退至当前前约0.5秒，后界缺失时为后约0.5秒；有下一拍时后界加约0.25秒；最大界限约为前1.5秒与后1.75秒。具体以 `fps` 的 floor 除法与源帧索引为准。没有审查过的击球时刻时，可运行标明偏差的探索窗口，但不能称为完全复现该 checkpoint 的数据生成条件。

## 对位置复用的实施建议（尚未实现）

1. 先选一个无剪切的真实单打短窗，记录 `asset_id`、原片 hash、源尺寸、全部 source PTS、窗口/击球点来源及输入使用范围。源资产 `training_only` 必须传到模型产物，不能进入制作集锦链路。
2. 在实际源帧上输出 COCO17、bbox、检测分数。先用 court ROI 排除裁判；再以几何关联和连续性形成候选 track。把候选关联、冲突/重置/遮挡记录输出供复核；未审核时保持 `track_status=unreviewed`，检测数组 index 不是 track ID。
3. 四点由可见球场线生成候选，供人确认。记录 `calibration_status`、创建方式 `agent_proposed` 或 `human_confirmed`，只有真实人工动作才填后者；相机移动/切镜后重新校准或使 H 失效。不能由四个数存在推断校准已确认。
4. 左右脚可见性不足时位置 `unknown`；只有单脚则不能伪造两脚平均。跳跃时踝点未必处于地平面，应保留脚落地假设与误差来源。场地位置/速度可观察，不等于后退小跳、战术意图或击球点真值。
5. 取同一时间轴真实 TrackNet 结果，`observed` 与 `imputed` 分开。原作者 TrackNet 使用 attention 版本；换用本轮 rectification 版是显式替换条件，不能称全部依赖与原文相同。
6. 冻结输入协议、缺失率/有效帧门槛及重采样索引后，才调度隔离 WSL 中受限的单窗口真实前向。校准与 track 未审核的试跑仍可标 `experimental`，但不能通过要求确认轨迹/场地映射的断言。

## 因果性、运行与后续验收

[tempose.py](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/blob/fb9b310bf4c8a8e3d89c75e61bc06a7ac3de62df/stroke_classification/model/tempose.py)中的 TCN 采用两侧 padding；BST 时间注意力使用有效长度 mask，未采用逐时刻的因果 mask。加上上述下一拍窗口，当前模型属于离线窗口分析。**即使之后实测 RTF<1，也不能据此将 R-07c 判为 PASS。** 因果版本需另定义可用信息、改模型/训练与测试，不能只截掉窗口标签。

源码依赖包括 PyTorch、`positional-encodings`、`torchinfo`；数据准备路径另依赖 NumPy/Pandas/OpenCV/MMPose 等。先审查最小推理导入链、固定版本并在既有 models WSL 隔离环境中安排，不能为小头默认安装整个姿态框架或修改全局环境。正式下载前由 owner 重测 D 盘容量与 models 配额，至少为 7,514,133 字节权重、临时写入及运行产物预留，下载后计算 SHA256、字节数，原子落盘并登记来源/许可；遇登录或下载限制停止。加载采用匹配架构、严格 state_dict 校验与安全权重加载选项。

| 固定用例/检查 | 要验证的输入与断言 | 本次实际结果 / 状态 | 解除条件或下一步 |
|---|---|---|---|
| R-07b / 输入路径 | 同源真实 pose + PTS + 两人分配 + 可追溯校准 → 位置/轨迹可回查 | 仅源码/权重入口审查；**NOT_RUN** | 先生成并复核连续输入与 H，再单窗推理及可视化 QA |
| R-07c / 因果实时 | 不使用未来帧；稳态 RTF≤1；端到端延迟、丢帧有实测 | BST 当前架构与窗口使用未来信息；**BLOCKED** | 当前路线只记离线吞吐；另找/训练因果模型 |
| S2-03 / 自动事件 | 真实粗球种输出、时间定位、失败例可复查 | **NOT_RUN**；未下载/加载该权重 | 对齐标签/预处理后生成真实预测与观测证据，不改已确认标注 |
| S2-04、R-06a / 细标签 | 展搓/收搓/后退小跳有专家定义与独立真值 | BST 没有这些输出标签；**BLOCKED** | 保留 unknown，单独建立细标签数据/模型 |
| S0-04、S3-04、R-05b / 效果评测 | 整场无泄漏划分、同输入/同人类真值后报告指标 | **BLOCKED**；本次不生成模型成绩 | confirmed 比赛来源/正式 split、独立标注、完整真值后评测 |

下一次真实实验必须分别报告解码、三路特征、预处理、模型前向、后处理、冷启动/稳态计时，以及 allocated/reserved 显存和失败帧。100帧小头耗时不能代表完整视频链路，更不能把短窗冷启动线性外推写成实测一小时处理时间。

## 2026-09-29 严格适配实现追加

已新增 `packages/models/bst_reuse.py`、`tests/models/test_bst_reuse.py`、`scripts/models/run_bst_reuse.py`；不改注册表/公共调度，由主任务集成。标准 `execute(request, root, output_path, progress)` 返回预测/报告两个 Artifact，`events=[]`，不自动写 confirmed 事件。命令 `python scripts/models/run_bst_reuse.py --request <request.json> --result <result.json>` 走现有 worker 协议，GPU 租约仍由调度负责；默认 CPU。

模型 ID 为 `bst-cg-ap-reuse`，operation 支持 `analyze`、`movement_classification`、`stroke_classification`。parameters 仅允许 `model_id`、可选 `model_version`（若提供必须为字符串 `0.1.0`）、`device`（cpu/cuda）、`features`（`relative_path/size_bytes/sha256` 文件条目）。features 指向 models 目录下最多12MB的 JSON，原源文件仍为 request 的唯一 Asset。先检查 features/源 Asset 哈希、所有输入和源片真实解码 PTS，再加载模型，缺少条件抛具体 `ModelBlocked`。

主任务提供的本地权重 SHA256 为 `997f43e52b20cb47517132c71d3e147d7d717a2d9651cfbe7651a5003bd66809`、`7514133` 字节。默认清单 `models/weights/bst/reuse-manifest.json`，可由管理员环境变量 `BTV_BST_MANIFEST` 指向 models 内其他路径；源码 SHA 固定在适配器中，清单不能授权任意新增 Python。执行源码只需 `bst.py` 和 `tempose.py`，不导入上游训练脚本。依赖分项检查 `torch`、`positional_encodings.torch_encodings`、`torchinfo`、`torch.utils.flop_counter`；真实源 PTS 校验另需 PyAV。缺哪个模块，blocked 消息直接给出模块名。权重加载使用 `weights_only=True` 与 `strict=True`，不以随机初始化前向充当结果。

执行源码同时固定字节数：`bst.py=33050`、`tempose.py=24519`。manifest 声明与固定 SHA/字节数均须一致；真正执行前再次有界读取源码，用固定常量核验，并把核验过的同一份 bytes 直接交给 `compile/exec`，消除校验后再次读路径执行的替换间隙。

小依赖建议由模型环境统一 writer 安装固定版本：[positional-encodings 6.0.3](https://pypi.org/project/positional-encodings/6.0.3/)（Python≥3.7，wheel SHA256 `714135704d54f42adc77585d54747e9d42580e03746ca90441e869ba7b3fc324`，PyPI显示7.5kB）及 [torchinfo 1.8.0](https://pypi.org/project/torchinfo/1.8.0/)（Python≥3.7，wheel SHA256 `2e911c2918603f945c26ff21a3a838d12709223dc4ccf243407bce8b6e897b46`，PyPI显示23.4kB）。两者均为上游两份源码的模块级 import，不能因 summary 只供调试就略掉 torchinfo。`torch.utils.flop_counter` 来自已装 PyTorch 本体。[positional-encodings 6.0.4](https://pypi.org/project/positional-encodings/6.0.4/) 要求 Python≥3.12，不应在旧 Python 环境无版本安装。本适配器的 feature 数学准备和 CPU 守卫测试只需 stdlib；上述是实际模型加载依赖，此处未执行安装。

**输入 pack 的冻结字段（第一版）**：

| 字段 | 要求 |
|---|---|
| 根 | `schema_version="1.0"`、`format="bst-source-features-v1"`、`asset_id`、`source_sha256`、`usage_scope`、整数 `source_start_pts`（PyAV stream.start_time，无值时0） |
| `camera_segment` | `{id,start_ms,end_ms}`，一个连续镜头完整覆盖该窗口 |
| `track_assignment` | `{status,method,evidence,track_ids:[top_track,bottom_track]}`，两条不同稳定ID |
| `shot_boundaries` | `{status,method,evidence,current_frame,previous_frame,next_frame}`，均为原 Asset 的零基 CFR 帧号；邻拍 null 只允许附 `previous_missing_reason="rally_start"` 或 `next_missing_reason="rally_end"` |
| `calibration` | `{id,status,method,evidence,camera_segment_id,coordinate_space:"source_pixels_to_unit_court",source_width,source_height,valid_start_ms,valid_end_ms,source_points,court_points,homography}` |
| 四点 | source_points 对应远左、远右、近右、近左；court_points 精确为 `[[0,0],[1,0],[1,1],[0,1]]`；H 直接作用于原图坐标，逐点校验误差≤1e-5。此 H 相当于把作者参考尺寸缩放与边界归一化合并进同一个矩阵 |
| `provenance` | `pose` 和 `shuttle` 各含原特征产物的 `model_id`、`artifact_sha256`；原产物保留在D盘。pack 自身通过完整 SHA/字节数核验 |
| `frames[]` | 逐源帧 `{source_frame_index,pts,time_base,source_ms,width,height,players,shuttle}`；长度必须恰好覆盖由邻拍生成的作者窗口，无缺帧、重复帧、稀疏样本改号 |
| `players[]` | 恰好2人、顺序与 track_ids 一致；每人 `{track_id,box_xyxy,keypoints_xyv,ankles_status:"observed"}`。COCO17 `[x,y,v]` 为原图坐标，v只作为有观测标志，不当模型校准置信度 |
| 每帧 `shuttle` | `{pts,time_base,status:"observed",x,y,available_at_source_ms}`；与 pose 的 pts/time_base 精确相同；x/y原图像素，不能提供归一化值或origin缺失占位 |
| 可选 `selection` | 选择该真实完整窗口的方法、候选范围、因缺失排除哪些窗口等，原样保留在预测产物；不能由一个完整窗口宣称全片覆盖 |

三个 review 对象的 status 只接受 `agent_reviewed` 或 `human_confirmed`，且均需 method/evidence；adapter 不会把 agent 改为 human。输入 producer/审核字段是来源声明，不等于程序能独立确认审核者诚实或人体关键点正确；原片和可视化审查仍不可省略。

严格版只接受源帧率10–120的单打CFR，最长5秒/600帧，PyAV实际解码核对全部 PTS。每帧两个17点完整、脚踝可见、人在场内、球点observed；missing/imputed/unknown 一律具体 blocked。短缺失容忍暂未实现。可选符合条件的真实完整击球窗口进行实验，但不能把任意无缺失小片段伪装为前后拍窗口。三路按作者stride共同抽样，只有实际有效窗口后的尾部padding为零，传入真实valid_length。无 synthetic warmup，不运行随机/全零模型输入。

CPU验证命令：`python -m unittest tests.models.test_bst_reuse -v`，33/33 PASS（全为标明 synthetic 的数学/守卫夹具，不是视频识别成绩）。覆盖缺校准/时间范围、四点/H不符、多人/换号、稀疏PTS/实际源PTS不完整、缺球/补轨/脚踝、非有限数、前后拍、作者stride/尾padding、固定源码哈希/字节数/执行buffer、完整 worker 请求及严格 model_version、训练用途继承与无真值指标为null；wrapper `--help` 通过。本地实际 manifest 全部文件重算哈希通过，此项不加载 PyTorch，也不是模型运行。R-07b / S2-03 仍 NOT_RUN，R-07c 因未来帧不计通过。
