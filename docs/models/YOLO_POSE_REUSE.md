# YOLO11n-pose + ByteTrack 有界输入对照

状态：主协调已在隔离环境完成真实90帧 YOLO+ByteTrack 运行；本子任务只读对照旧模型同PTS输出，详见 [真实输入对照实验](../experiments/models-yolo-input-comparison-001.md)。31/32帧场内候选不足未改善，54帧几何跳变减轻；统一诊断守卫为旧87/90、YOLO81/90，不能称整体改善。适配器现有16项 CPU守卫测试、对照脚本3项 CPU测试通过；均不是识别准确率。未生成BST确认输入，校准仍为agent proposal。

目的：在同一真实单打短窗上比较姿态检测与匿名关联，保留失败，判断是否能改善后续输入。BST 仍保持严格缺失守卫；不为满足它的形状补零、删除失败帧、插值人体/羽球或自动确认轨迹。

## 固定来源与许可

| 项目 | 固定值及来源 |
|---|---|
| 包 | [ultralytics 8.3.203](https://pypi.org/project/ultralytics/8.3.203/)，Python≥3.8；不跟随 latest |
| 源码 | 官方 tag `v8.3.203` 经 [tag 元数据](https://api.github.com/repos/ultralytics/ultralytics/git/tags/f8fb9b1c2c51162ad3753e81f41ef9192e720444) 对应 commit `6450d5c38fb4ef069e1c450930bf6bd9fc3fc59c` |
| wheel | `ultralytics-8.3.203-py3-none-any.whl`，1,072,183 B，SHA256 `7103994cfb14f8779fa0a6b7e7908708137309645a3723dbe2ceb73ea7afc63c`；[官方 PyPI 文件元数据](https://pypi.org/pypi/ultralytics/8.3.203/json) |
| 权重 | [官方 release yolo11n-pose.pt](https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n-pose.pt)，6,255,593 B；GitHub release API 未给发布者 digest；统一 writer 下载后 SHA256 `869e83fcdffdc7371fa4e34cd8e51c838cc729571d1635e5141e3075e9319dc0`，已固定在适配器 |
| 许可 | [官方 LICENSE](https://github.com/ultralytics/ultralytics/blob/6450d5c38fb4ef069e1c450930bf6bd9fc3fc59c/LICENSE) 为 AGPL-3.0；官方另提供 Enterprise 许可。本地研究对照不代表完成闭源发布许可判断，也不改变源视频权利 |

本地 manifest：`D:/video/models/weights/yolo11n-pose/reuse-manifest.json`。顶层 `schema_version/model_id/package_version/license`；`package`、`checkpoint` 各是 `relative_path/size_bytes/sha256/source_url` 文件条目。wheel 留在 `models/upstream/ultralytics/8.3.203/`，权重留在 `models/weights/yolo11n-pose/`；均不入 Git。

适配器以自身固定 SHA/字节数检查 wheel 与 checkpoint，不能由请求或自签 manifest 授权新 pickle；核验已安装版本为 8.3.203，并对照固定 wheel 校验包内全部 `.py/.yaml`。官方模型以 pickled Module 发布，因此仅对固定字节缓冲调用 `torch.load(...,weights_only=False)`，把同一份已校验 bytes 交给反序列化；随后使用官方 `PosePredictor`。这不是通用任意 `.pt` 导入入口。

## 隔离依赖与预算

建议主协调使用 `/mnt/d/video/runtime/models/yolo-env`，从项目旧 models 环境创建 `venv --system-site-packages`，共享 torch 2.7.1、torchvision 0.22.1、NumPy 2.4.6、PyAV 15、Pillow；不升级框架、不更改旧环境。运行时不硬编码环境路径，解释器由 worker 配置决定。

[固定版本 pyproject](https://github.com/ultralytics/ultralytics/blob/6450d5c38fb4ef069e1c450930bf6bd9fc3fc59c/pyproject.toml) 声明 NumPy、matplotlib、opencv-python、Pillow、PyYAML、requests、SciPy、torch、torchvision、psutil、polars、ultralytics-thop；[ByteTrack matching](https://github.com/ultralytics/ultralytics/blob/6450d5c38fb4ef069e1c450930bf6bd9fc3fc59c/ultralytics/trackers/utils/matching.py) 另需要 lap≥0.5.12。

| 缺项固定建议 | 一手元数据/约束 |
|---|---|
| `scipy==1.16.3` | [PyPI](https://pypi.org/project/scipy/1.16.3/)：Python≥3.11，NumPy≥1.25.2,<2.6，兼容现有2.4.6范围 |
| `matplotlib==3.10.7` | [PyPI](https://pypi.org/project/matplotlib/3.10.7/)：Python≥3.10；另需 contourpy/cycler/fonttools/kiwisolver/packaging/pyparsing/python-dateutil，writer逐项核查 |
| `polars==1.34.0` | [PyPI](https://pypi.org/project/polars/1.34.0/)：还需 `polars-runtime-32==1.34.0`；`--no-deps`不会带上 runtime |
| `ultralytics-thop==2.0.17` | [PyPI](https://pypi.org/project/ultralytics-thop/2.0.17/)：依赖 NumPy、torch |
| `lap==0.5.12` | [PyPI](https://pypi.org/project/lap/0.5.12/)：NumPy≥1.21.6；使用平台 wheel，避免本地编译 |
| `opencv-python==4.11.0.86` | 主协调确认 libGL 存在后可仅在子环境安装以满足包元数据；保留父环境 headless，不在同一个目录写两份 cv2 |

安装由统一 writer 使用固定 wheel、no-deps、no-cache、only-binary 并检查实际依赖；不默认安装训练/导出/解决方案 extras。600MB 是新增包、临时文件及缓存的**保守预留估计**，不是实测占用。权重+主包约7.4MB；短窗运行另自行 `reserve(root,100000000)`。GPU 预算先估≤1GB供排期，实际 allocated/reserved 以真实报告为准。以上不能挤占 VL 的24GB预留或使 runtime 超过35GB。

Runtime 载入前设置 `YOLO_AUTOINSTALL=false`、`YOLO_OFFLINE=true`、`YOLO_VERBOSE=false`，把 `YOLO_CONFIG_DIR/TMPDIR/MPLCONFIGDIR` 指向 `models/cache/yolo/`。预先检查依赖；缺项 blocked，不允许上游自动安装。输入是 PyAV 解码的内存 BGR 帧和固定本地 checkpoint，不传 URL 给 Ultralytics。

## 接口及证据含义

`packages/models/yolo_pose_reuse.py::execute(request, root, output_path, progress)`；标准 worker 请求，模型 `yolo11n-pose-bytetrack@0.1.0`，operation `analyze/pose/tracking`。

参数：`model_id`、可选且只能为字符串 `model_version="0.1.0"`、`start_ms/end_ms`、`device="cuda"|"cpu"`（默认cuda）、`imgsz=640`、必需 `camera_segment={id,start_ms,end_ms,status,method,evidence}`。camera status 仅接受 `agent_reviewed/human_confirmed`，不自动升级；声明连续镜头必须覆盖窗口。它是审核来源声明，不是自动切镜检测。

约束：单 Asset；窗口≤3秒且预计/实解码均≤100帧，原图≤4K。逐原帧连续解码，保留源 `pts/time_base/stream_start_pts/source_ms/source_frame_index`。现要求恰好覆盖 CFR 帧号 `ceil(start_ms*fps/1000)..ceil(end_ms*fps/1000)-1`，缺首、缺尾、重复、内部缺口、VFR映射不符及越限均 blocked。无抽帧、无换算成伪帧率、无丢弃失败帧。每次请求新建 tracker，不跨请求/镜头拼接身份。此次实际90帧结果在修复前产生，随后独立核对首尾/步进/数量完整，未重写其原产物。

官方 `PosePredictor` 用640输入、conf=.1、IoU=.7、max_det=30，保留它返回的全部检测与17个关键点 `[x,y,confidence]`、bbox、检测分数；这里的 raw 指上游解码/后处理后返回值，不是未后处理 head logits。低关键点分数标 unknown，不改原坐标/分数。帧达到检测上限时记录 `possible_detector_cap_hit`，不能据此宣称完整覆盖。

ByteTrack 使用官方 [默认阈值](https://github.com/ultralytics/ultralytics/blob/6450d5c38fb4ef069e1c450930bf6bd9fc3fc59c/ultralytics/cfg/trackers/bytetrack.yaml) 和 [关联实现](https://github.com/ultralytics/ultralytics/blob/6450d5c38fb4ef069e1c450930bf6bd9fc3fc59c/ultralytics/trackers/byte_tracker.py)。该版内部按高/低置信度分组后重新生成局部 idx；本适配器保留分组前索引，并仅在创建 STrack 时把 idx恢复为原始检测索引。关联代价、Kalman状态及实际 track_id 均由官方算法生成，不做重编号伪装、ReID或按场地上下直接编造身份。

输出 `features.json`：逐帧 `detections` 包含匿名 `track_id`（`segment:anonymous-N`）、原始数值 ID、identity_status，未激活/未匹配为 null；空检测帧保留为 `unknown`，并记录此前见过但当前缺失的 track IDs。既不补人体，也不输出 Kalman 预测当作已观测姿态。检测到的裁判/场边人员仍保留，不能直接称全部为场上选手。场地过滤与人工QA是后续独立步骤。

输出 `report.json`：源 Asset全字段/权利/sha256/usage_scope、固定包/权重来源、配置、模型冷加载、源解码和转换、逐帧 pose wall时间、官方preprocess/inference/postprocess时间、ByteTrack时间、峰值 allocated/reserved 显存。新增版本另计 D2H/list转换、检测序列化、features JSON写入、execute elapsed 与未归因部分；明确计时边界为 execute入口至features写完，排除最终report写入、Artifact哈希及worker结果IPC。禁用上游 synthetic warmup；首真实帧包括冷启动成本。`steady_state_rtf=null`，不把3秒窗口外推成实测整小时。旧90帧report没有这些新增时间项，不能将其旧分项相加称完整端到端耗时。

所有结果为 `experimental`、`unreviewed_model_output`，`accuracy/recall=null`、`fine_labels=unknown`、`reid=false`、`events=[]`；继承 training_only限制。ID关联不代表人名、跨遮挡可靠性或动作识别。当前不会自动转为 BST 确认输入。

## 本阶段验证

| 断言 | 实际结果 | 状态/下一步 |
|---|---|---|
| CPU输入/索引/输出守卫 | `python -m unittest tests.models.test_yolo_pose_reuse tests.models.test_pose_input_comparison -v`：16+3通过；含高低分组索引、null track、不补空帧、精确首尾PTS范围、完整worker请求、固定文件pin、training_only、计时边界、同PTS对照和null metrics | PASS，仅实现验证 |
| R-07b 真实位置/轨迹输入路线 | owner真实90帧已运行，本子任务同PTS数值分析；仍有缺失/额外候选及模型ID缺口 | BLOCKED，仅部分路线已运行；需源帧人工QA、有效完整下游窗口，不替代完整验收 |
| R-07c 实时链路 | 没有摄入节拍/稳定时延实测 | NOT_RUN；短窗pose forward不能替代整链实时验收 |
| S2-03 / S2-04 模型能力与细标签 | 无完整真值，无腕指/脚步细分类器 | NOT_RUN / unknown；不报precision/recall |

后续真实对照至少核对：同PTS两个模型的场上人数/关键点、31/32漏检、54关联异常、遮挡前后ID变化、裁判误检与远端脚踝。羽球65/66缺失不由新人体模型修复；即使人体输入改善，BST仍可能因独立缺球阻断。
