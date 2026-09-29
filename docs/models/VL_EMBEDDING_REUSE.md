# Qwen3-VL-Embedding-2B 有界复用适配设计

2026-09-29；对应固定用例 **R-05a、R-03b**，用途继承覆盖 R-04b 的模型衍生物边界。主任务负责权重/环境/GPU；本子任务不安装、不下载大权重、不启动 GPU、不切分支。

## 开发前断言

| ID | 输入/操作 | 预期结果 | 当前实际结果/状态 |
|---|---|---|---|
| R-05a | 隔离 WSL，固定官方 2B 权重，真实 4–6 秒窗与中文查询；batch 1 | 每个文本/视频产生有限 2048 维归一化向量；排序可回查原片/PTS；缺依赖/哈希错误/视觉失败均阻断 | 真实有界特征运行 PASS：实际为同一 6 秒原片的两个 3 秒窗、3 中+3 英查询；原计划 4–6 秒单窗尚未覆盖。失败及成功均见[真实实验](../experiments/models-vl-real-001.md) |
| R-03b | 对同窗独立记录 hash/cold/decode/pre/model/post | CPU PyAV 解码与 GPU 前向区分；同步后计时；allocated/reserved 分开；不宣称 NVDEC 或实时 | 本次短窗计时记录 PASS：真实 PyAV/GPU 分项及两类显存峰值已保留；不据此宣称稳态 RTF 或实时 |
| R-04b（模型输出边界） | typed/provenance/path 任一为 training_only | 特征、排名和 Artifact.producer 继承最严格用途；不能成为制作候选或视频成片 | 局部 CPU 边界测试 PASS：typed/provenance/逻辑路径/解析路径和模拟成功产物均保留用途；整体 R-04b 仍待真实平台/render 拒绝验收 |
| R-05b | 同真值/划分/审片预算比较 CLIP/规则 | P@K/召回有合法分母与真值 | BLOCKED：无冻结人类真值，本实现仅同输入窗口/采样帧诊断排序 |

## 已核验来源

- [官方 HF 模型卡](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B)：文本/图像/视频统一嵌入，2B，2048 维，多语言含中文；不能把通用模型能力当羽球细手法成绩。
- HF 固定 revision：`9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda`。通过官方 metadata 精确核对 18 个文件合计 **4,271,068,726 bytes**。
- `model.safetensors`：**4,255,140,312 bytes**，SHA256 `c73fa9caeddeb3ff831d46c085a7a5708343248ca777e90f2d486964464509c1`。
- `tokenizer.json`：11,423,705 bytes，SHA256 `def76fb086971c7867b829c23a26261e38d9d74e02139253b38aeb9df8b4b50a`。
- [官方 HF 小模块](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B/blob/9f2f7e710d6d81056aa5c0a4f04764fec6bb7bda/scripts/qwen3_vl_embedding.py)：13,258 bytes，SHA256 `8ffa74a1a6bb759610c57865ea416fd4daf9936cb787520e1112a3e1d547f36a`。只执行固定校验过、已逐行审阅的本地副本，不自动加载远端代码。
- [GitHub 固定代码](https://github.com/QwenLM/Qwen3-VL-Embedding/tree/393e2978d27852b0d0230d6994f37f9c15bed73c)：commit `393e2978d27852b0d0230d6994f37f9c15bed73c`，当前模块路径是 `src/models/qwen3_vl_embedding.py`，与 HF 随权重的旧 `scripts/` 路径不同；本适配器固定 HF 副本，不混用两版。
- 模型卡及[代码 LICENSE](https://github.com/QwenLM/Qwen3-VL-Embedding/blob/393e2978d27852b0d0230d6994f37f9c15bed73c/LICENSE)标为 Apache-2.0；原视频许可和用途仍单独继承 Asset。

模型卡要求 torch 2.8.0、transformers≥4.57.0、qwen-vl-utils≥0.0.14；当前 GitHub pyproject 要求 torch 2.8.*、torchvision≥0.23.0、transformers≥4.57.3、Python≥3.11。本轮固定 torch2.8.0+cu128 / torchvision0.23.0+cu128 / transformers4.57.3 / qwen-vl-utils0.0.14 独立环境，不能覆盖已有 torch2.7.1 / transformers4.51.3 环境。不运行官方全套 setup，它会安装无关研究依赖并配置另一个包源。

## 官方 API 审阅结论

模块暴露 `Qwen3VLForEmbedding`、`Qwen3VLForEmbeddingOutput`、`Qwen3VLEmbedder`。嵌入模型包装内置 `transformers.Qwen3VLModel`；不是文本生成，也不能仅依据 config 的 `Qwen3VLForConditionalGeneration` 字样猜用 AutoModel。

模块 import 依赖 torch、numpy、Pillow、transformers 的 qwen3_vl/缓存/ModelOutput 类型、`qwen_vl_utils.vision_process.process_vision_info`。先用 `Qwen3VLConfig.from_pretrained(local_files_only=True, trust_remote_code=False)` 加载本地配置实例，再传入 `Qwen3VLForEmbedding.from_pretrained(config=config, local_files_only=True, trust_remote_code=False, use_safetensors=True, attn_implementation='sdpa')`，不调用官方 convenience 构造器。固定源码用 `compile(..., dont_inherit=True)` 保持其独立模块注解语义；首次失败及修复见下文。

原因：官方 `Qwen3VLEmbedder.__init__` 写有 `trust_remote_code=True`，其 `_preprocess_inputs` 还会捕获视觉错误并改成 NULL 文本继续。两者不符合本任务要求。本适配器自行有界解码/预处理；错误直接记录并阻断，不返回缺视频证据的“成功向量”。FlashAttention2 不作为依赖，不声称已测试。

官方 embedder 以最后一个有效 token hidden state 池化、L2 归一化；本实现将池化向量转 float32 再归一化。[transformers4.57.3 processor](https://github.com/huggingface/transformers/blob/v4.57.3/src/transformers/models/qwen3_vl/processing_qwen3_vl.py)在视频 prompt 内放时间戳，默认从 frame_index/fps 推算时间，不适合未经声明的 VFR：适配器保留 PyAV 原 PTS/time_base，以真实源时间覆盖该实例的 `_calculate_timestamps`，按官方两帧 temporal merge 的首末时间平均；模型文本时间显示到 0.1 秒，精确 PTS 另存。已抽帧输入关闭二次采样和二次缩放。metadata 的 fps 是本次采样数/窗口秒数，仅用于满足 processor 接口；时间函数不用此值推断源时间，frames_indices 只表示已提供的帧序号。若 processor 重排帧序号则报错。

## 接口与数据流

`execute(request, root, output_path, progress) -> {artifacts, events: []}`，只由主任务在统一执行器内显式分发。每次持有 models 的容量预留，结果原子且不覆盖；脚本只包装已有 `python -m packages.models run` 的请求协议，不单独建立 GPU 调度入口。

参数：`model_id=qwen3-vl-embedding-2b`；worker 可注入 `model_version=0.1.0`；`windows=[{asset_id,start_ms,end_ms}]`，最多 4 个；`queries=[{query_id,text,language}]`，最多 8 条、每条最多 512 字符，language 为 zh/en，至少一条中文。`num_frames=6`，仅允许 2/4/6/8；`max_pixels=262144`（每帧硬上限、最小 4096）；`compare_clip=true` 可对照已有 CLIP，默认 false。每窗硬上限 30 秒；最初计划单窗 4–6 秒，实际首轮为同一 6 秒原片的 0–3 秒及 3–6 秒两窗。输入不接受媒体 URL、shell、下载选项、动态模型路径或远端代码开关。

流程：Asset/用途/窗口验证 → 源文件 hash → CPU PyAV 精确 PTS 采样 → 有界 RGB/32像素网格缩放 → Qwen batch1 视频/中文/可选英文嵌入 → 归一化与有限性检查 → 同窗 cosine 排名 → 可选 CLIP 同样抽样帧及文本对照 → 特征/计时/失败报告。Qwen 与 CLIP 分开加载，原始媒体只读，不复制全片。

CLIP 仍为逐帧均值，无时序；其原始 OpenAI 模型的中文支持与 Qwen 的官方多语言声明不同，中文只作诊断，英文可作对照。不同模型的相似度不可当概率直接比较；只有各自候选排序。不会构造 Event、player identity、细技术确认或 P@K。

## 运行与证据

2026-09-29 Windows Python3.12.11：`python -m unittest tests.models.test_vl_embedding_reuse -v`，首轮 23/23、`c609b53` 修复后 26/26 CPU 边界测试 PASS；`python scripts/models/run_vl_embedding_reuse.py --help` PASS。测试验证哈希钉住、嵌套源码路径、异常用途字段、VFR 帧序、像素/时间/帧数上限、失败保留、no-overwrite、配置注解语义及显式本地 config 传递；mock 模型/帧只用于控制边界测试，不能当真实识别成功。第一次测试因浮点精确相等断言失败，已改为有容差比较，适配器没有改写真实时间值。

既有 `vl-env` 的恢复安装 run `runtime/models/vl-resume-runs/20260929T105054Z-3c3fa8e2` 已 complete，`pip check` 无冲突。44 个本次安装包的来源/归档 hash、CPU 导入与容量证据见 [安装记录](../../environments/models-vl-installed-20260929.json) 和 [freeze](../../environments/models-vl-installed-20260929.freeze.txt)；CPU 探针未初始化 CUDA。安装后 models runtime 为 19,164,852,807 B，shared（含既有 native base/pkgs）为 7,169,319,439 B，加其余 runtime 20 GB 预留后为 46,334,172,246 B，分别通过 35/15/70 GB 预算。

首次真实作业 `job-a258df27cc5d4598896dd1d6495c955a / attempt-1` 在 cold_load 失败：适配器的 future annotations 被动态 compile 继承，官方 `config` 注解变成字符串，Transformers 4.57.3 据此设置了字符串 `config_class`。原 failure/result 保留；修复 `c609b53` 仅隔离编译标志并显式传入本地 config，未更换固定上游源码、权重或输入。

同权重、同窗口和查询的新作业 **`job-604bf54336ae449a88e004622efd6d1f / attempt-1` succeeded**，Qwen 与 CLIP 比较均成功。真实 `video_001951` 两窗各取 6 帧；2 个视频与 6 条查询（3 中、3 英）各得有限 2048 维 Qwen 向量，CLIP 使用同样帧和查询产生 512 维向量。报告 elapsed **73.481262 s**，包括权重校验 **12.101369 s**、Qwen cold load **31.977933 s**、CPU 解码、框架开销及 CLIP 比较，**不含产物发布 I/O**；它不是稳态 RTF。Qwen 峰值 allocated **4,421,021,184 B**、reserved **4,519,362,560 B**，不是进程总显存。主线程已释放 GPU/queue，未继续启动实验。详细路径、原始 PTS、失败与成功证据见[真实实验记录](../experiments/models-vl-real-001.md)。

主任务通过平台登记 `qwen3-vl-embedding-2b`、版本 `0.1.0`、capability `video_embedding`，并在统一 `inference.execute` 入口分发。CPU 控制面不导入 torch。真实作业继续由既有 worker 的 GPU 租约/watchdog 管理；本 wrapper 不获取租约，不能绕过平台另启并行 GPU 任务。

在完整 v1 request 的 `parameters` 中使用如下结构；示例 asset_id 必须替换为请求 `assets` 中真实、已核验的完整 Asset。查询是开发者诊断输入，不是视频真值。

```json
{
  "model_id": "qwen3-vl-embedding-2b",
  "model_version": "0.1.0",
  "windows": [{"asset_id": "REPLACE_WITH_VERIFIED_ASSET_ID", "start_ms": 20000, "end_ms": 26000}],
  "queries": [
    {"query_id": "zh-smash", "text": "羽毛球运动员起跳杀球", "language": "zh"},
    {"query_id": "zh-serve", "text": "羽毛球运动员站在场地上发球", "language": "zh"},
    {"query_id": "en-smash", "text": "A badminton player jumps and smashes the shuttlecock", "language": "en"}
  ],
  "num_frames": 6,
  "max_pixels": 262144,
  "compare_clip": true
}
```

用于重现 worker 内协议的命令（由主任务在已持有 GPU 实验排期时执行；工作目录为仓库根）：

```bash
source environments/models-vl.env.sh
"$BTV_MODELS_ENV/bin/python" scripts/models/run_vl_embedding_reuse.py \
  --request /mnt/d/video/models/handoff/vl-reuse-NNN-request.json \
  --result /mnt/d/video/models/handoff/vl-reuse-NNN-result.json
```

请求的 `output_dir` 必须是尚不存在或空的 `models/handoff/vl-reuse-NNN`；每次改 NNN，不覆盖旧结果。模型一次持有 `storage.reserve(root,100000000)`；仅写有限 JSON，不导出帧或复制原片。固定权重目录为 `models/weights/qwen3-vl-embedding-2b`，18 文件和 `weights-manifest.json`；清单 source/revision/每项 source_url 必须与上文固定来源吻合，每个文件的 SHA256 以及官方 Git/LFS digest 均检查。模型源码还独立验证 SHA256 后执行原始字节，避免 stale pyc。任何缺失依赖/哈希失配均明确阻断，不触发安装或隐式下载。

输出 `features.json` 含中文/可选英文查询、2048 维 query/video 向量、窗口原片/hash/PTS/用途及各模型独立 cosine 排名；`report.json` 含 source/weight verification、cold load、decode、frame preprocess、processor preprocess、GPU model、postprocess 时间、包版本、GPU allocated/reserved 峰值和无真值声明。GPU 时间前后同步；allocator 峰值不等于进程总显存。cold 指加载权重/processor，整体 elapsed 另外包含核验和解码。CLIP 比较失败单独保留原始本地异常，Qwen 成功向量仍可查看，不能声称比较成功。

一般执行失败写 `failure.json`，记录阶段、异常类型、错误 code 和有界 traceback，并向统一协议返回失败/阻断。已知凭据环境变量值及 HF token 会脱敏；不把媒体写入错误报告。用途 `general | training_only` 与研究许可各自独立，任一输入 training_only 时特征/report/Artifact.producer 整体 training_only；窗口亦有自身用途。当前兼容 guard 在本模块内，待共享 helper 合入可替换，不扩展为制作导出许可。

本次真实结果位于 `models/jobs/job-604bf54336ae449a88e004622efd6d1f/attempt-1/`，首次失败位于独立 job，均未覆盖。该成功证明有界特征与比较链路可运行；准确率、P@K/召回、细手法识别质量及完整阶段验收没有因此完成，`accuracy/precision_at_k` 仍为 null，无冻结人类真值。
