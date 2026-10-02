# Qwen3-0.6B 中文 QuerySpec 条件保真诊断

日期：2026-09-28。状态：两轮真实本地 GPU 推理均完成，产品条件保真验收未通过。没有训练、没有视频输入、没有追加 GPU 实验。实验目录 001 与 002 均保留原始结果；本报告只读整理。

## 结论与解释边界

原始提示词在 24 条探针上严格通过 **0/24**；根据首轮错误补充三个完整输出示例后通过 **2/24**。第二轮仅“吊球”和“后退”通过 JSON、schema、动作标签与关系语义的全部检查，不能据此宣布中文解析器可用。

这些是开发者编写的有限语法诊断，数据集标记为 `developer_authored_diagnostic`、`is_user_corpus=false`、`is_video_ground_truth=false`。两轮使用同一组 24 条探针。第二轮提示词是在查看首轮失败后调整的，因此结果属于开发集上的提示词调试，不是独立留出测试。三个示例的完整输入没有出现在计分探针里，这不消除查看开发集后调参的限制。

数字只衡量固定词表、提示词和 greedy 配置下的条件保真；不是模型最佳表现上限，不是用户查询准确率，也不是视频动作精度、检索召回或 A/B/C 路线效果。`video_accuracy`、`retrieval_accuracy`、`general_language_accuracy` 均为 `null`。

## 输入、实现与环境

- 数据：`configs/models/query-probes.json`，`dataset_id=developer-query-diagnostic-v1`。24 条包含单拍 5、步法 4、组合 4、先后/邻近 7、unknown 4。每条条件由开发者显式填写，执行前再与 `parse_rule` 一致性核对。
- 脚本：`scripts/models/query_benchmark.py`；模型只加载一次，逐条生成。每条原文、参考条件、原始生成、错误码、token 数、耗时和显存均独立保存，最后汇总。
- 加载：本地已校验的 `models/weights/qwen3-0.6b`；`local_files_only=true`、`trust_remote_code=false`、`use_safetensors=true`，离线环境禁止隐式下载。
- 生成：CUDA、`torch.bfloat16`、`enable_thinking=false`、`do_sample=false`、`max_new_tokens=768`、seed 0。未实施训练或微调，也未启用结构约束解码。
- 检查：原始生成必须直接构成完整 JSON，再通过 `validate_query` 和 `validate_semantics`；不剥离 Markdown 围栏、不修写机器标签、不补步骤/关系，不在失败后静默替换为规则结果。成功后的 ID/text 元数据按既有合同回填，不参与视频真值判断。
- 第二轮显式指定 `configs/models/query-fewshot-prompt.txt`，追加“挑球”“后退然后发球”“弓步同时放网”三个完整正确 QuerySpec。该文件有来源与哈希记录，探针重复检查通过。
- **默认行为未改**：统一模型 CLI 的本地 Qwen 仍使用 `QUERY_SYSTEM_PROMPT`；benchmark 不指定 `--prompt-file` 时也仍使用原基线。第二轮是显式选择的实验配置。

官方模型卡建议非 thinking 采样使用 temperature 0.7、top_p 0.8、top_k 20、min_p 0；本实验未采用这一采样配置，而固定 greedy 以便比较可重复配置。不能把当前结果解释成所有解码策略的上限。[官方模型卡](https://huggingface.co/Qwen/Qwen3-0.6B#best-practices)

| 组件 | 两轮记录值 |
|---|---|
| 系统/设备 | WSL Linux；NVIDIA GeForce RTX 5090；compute capability 12.0 |
| Python | 3.11.16 |
| torch / CUDA build | 2.7.1+cu128 / 12.8 |
| transformers / tokenizers | 4.51.3 / 0.21.4 |
| safetensors / huggingface-hub / accelerate | 0.5.3 / 0.36.2 / 1.6.0 |
| 权重来源 | `https://huggingface.co/Qwen/Qwen3-0.6B` |
| 固定 revision | `c1899de289a04d12100db370d81485cdf75e47ca` |
| 权重 manifest 相对路径 | `models/weights/qwen3-0.6b/weights-manifest.json` |
| 权重 manifest SHA256 | `2478d998ff4d782a1801f833d5f59220ed7f8cf4ce7f2d0b9e0ad5addbd21903` |
| model.safetensors SHA256 | `f47f71177f32bcd101b7573ec9171e6a57f4f4d31148d38e382306f42996874b` |

`run-metadata.json` 保存全部七个权重/配置文件的 URL、字节数和 SHA256。各文件均指向同一固定 revision，加载前核验本地文件哈希。固定版本来源页为 [Qwen 模型卡](https://huggingface.co/Qwen/Qwen3-0.6B/blob/c1899de289a04d12100db370d81485cdf75e47ca/README.md)。

| 可追溯项 | 001 原基线 | 002 fewshot-v1 |
|---|---|---|
| prompt SHA256 | `7591e515dbec4ba176ed6ba30445b2d2e6252d10cdf9646e21b9dd56ed3b13ba` | `e9db2da9ab521d7aea0ab2492c99c69662173e79aa66116920be7db18f315e34` |
| probes SHA256 | `4281358eeae264198ff90c0a1424a437fb19bed3e6b585c95b67b3f11923d0a0` | 同左 |
| query.py SHA256 | `1e26add14747a137d8025d0cc737fac9a5e86d2c88ca3033f2b58ec00aecbd31` | 同左 |
| benchmark.py SHA256 | `235f93851168d1adc95013ec39a0eeb25da5f6f15fded442a9523efd39617ba6` | `fc164529efdc9a8c05d8264a138059e9476c7e0999e0690eb6f63d4607c2f235` |

脚本哈希不同是因为第二轮增加了显式 prompt 文件入口和来源记录；默认提示词和严格检查逻辑未改。原始提示词全文均保存在各轮 metadata 中。

## 实测结果

| 指标 | 001 原基线 | 002 fewshot-v1 |
|---|---:|---:|
| 执行状态 | completed_with_failures | completed_with_failures |
| 实际推理条数 / blocked | 24 / 0 | 24 / 0 |
| 严格通过 | 0/24（0%） | 2/24（8.33%） |
| JSON 解析失败 | 24 | 20 |
| schema 失败 | 0* | 1 |
| schema 合法、语义失配 | 0* | 1 |
| schema 合法总数 | 0 | 3 |
| 达到 768 token 上限 | 0 | 0 |
| 输入 token 范围 | 1045–1056 | 1668–1679 |
| 生成 token 总数 | 4281 | 2617 |
| 生成耗时 | 85.636106 s | 52.541517 s |
| 生成速度 | 49.990596 token/s | 49.808231 token/s |
| 单条总耗时中位数 | 3.480364 s | 1.663119 s |
| 模型加载耗时 | 22.003169 s | 22.389461 s |
| 总 wall time | 132.304909 s | 99.927184 s |
| peak allocated | 1,383,128,064 bytes（1.383128 GB） | 1,450,786,816 bytes（1.450787 GB） |
| peak reserved | 1,428,160,512 bytes（1.428161 GB） | 1,480,589,312 bytes（1.480589 GB） |

\* 失败码是按检查顺序记录的第一个失败原因。001 在 JSON 阶段全部被拒绝，因此其 schema/语义失败计数为零不意味着内部标签或关系正确。

GB 使用十进制。显存来自当前 PyTorch 进程分配器，包括其模型与推理分配；不是整张显卡的总占用，也不包含其他进程。总 wall time 包括权重校验、模型加载、生成和结果发布。第二轮输出 token 更少、总生成时间更短，但 token/s 基本相同，不能描述成模型获得了更高推理吞吐。

| 类别 | 探针数 | 001 通过 | 002 通过 |
|---|---:|---:|---:|
| 单拍 | 5 | 0 | 1（“吊球”） |
| 步法 | 4 | 0 | 1（“后退”） |
| 组合 | 4 | 0 | 0 |
| 先后/邻近 | 7 | 0 | 0 |
| unknown | 4 | 0 | 0 |

第二轮成功记录为 `single-05.json`（`stroke=drop`）和 `footwork-01.json`（`movement=backward`），均单步骤、`relations=[]`、`include_uncertain=false`。它们不是 few-shot 示例，也不是视频中的已识别动作。

## 实际失败样例

以下直接核对已保存的 `raw_generation`；只作错误分析，没有修改原始结果或重新计分。

1. **001 / single-01.json，“杀球”**：输出包在 Markdown JSON 围栏中；内部仍把 `labels.stroke` 写成中文“杀球”，创建 `from_step=to_step=1` 的自连关系，`relation=stroke` 不在允许枚举中，并擅自开启 `include_uncertain=true`。所以问题不只是围栏格式。
2. **001 / single-04.json，“网前击球”**：内部粗标签虽为 `net_shot`，却创建 `to_step=null`、`relation=stroke` 的关系，并将 same_player/same_rally 改为 false、include_uncertain 改为 true。单动作查询本不应产生关系。
3. **002 / single-01.json，“杀球”**：内部可见机器标签 `smash`、空 relations、include_uncertain=false；仍带 JSON 围栏，因此按原合同严格失败，未将“看似可修复”算成通过。
4. **002 / sequence-04.json，三步组合**：除围栏外，第二步写成 `stroke=jump`，遗漏 `smash` 与 `footwork=jump` 的正确合取；第三步遗漏 `movement=forward`，并把两个应有的 before 关系全部删为 `relations=[]`。移除围栏也不能恢复原查询含义。
5. **002 / combination-04.json，“后退同时杀球”**：把后退写进 `footwork=backward`，而参考为 `movement=backward`；遗漏 overlaps 关系，仍输出围栏。
6. **002 / unknown-01.json，“手法未知”**：原始输出是合法 QuerySpec，`hand_technique=unknown` 也正确，但擅自将 `include_uncertain=false` 改成 true，被 `endpoint_semantic_mismatch` 阻断。未知标签与主动扩大不确定候选范围是不同条件。
7. **002 / unknown-04.json，“移动方向未知”**：生成可解析 JSON，但缺少顶层 `include_uncertain` 且 `steps=[]`；应保留的 `movement=unknown` 条件消失。实际先因顶层字段不完整触发 `invalid_schema`；空 steps 本身也不符合查询至少一个明确条件的要求。

001 全部 24 条原文以围栏开头；002 的 20 条 `invalid_generated_json` 也全部带围栏。其余两条失败为上述 schema/语义问题。没有 token 上限截断或 OOM 记录。当前已证明该环境可以完成前向生成；具体阻碍是输出合同和条件保真，不应笼统归为“模型未安装”或“GPU 不兼容”。

## 原始结果与复现

全部记录位于共享存储，仅只读引用；没有向 Git 复制模型或结果大文件。

- Windows：`D:/video/models/handoff/query-diagnostic-001/` 与 `D:/video/models/handoff/query-diagnostic-002/`。
- WSL：`/mnt/d/video/models/handoff/query-diagnostic-001/` 与 `/mnt/d/video/models/handoff/query-diagnostic-002/`。
- 每轮 `report.json` 是汇总，`run-metadata.json` 是完整配置/来源；24 个 probe JSON 含原始生成。001 UTC 时段 `2026-09-28T15:43:52Z` 至 `15:46:04Z`，002 为 `15:50:57Z` 至 `15:52:37Z`。
- 每轮一次预留 100,000,000 bytes；持久 JSON 实际占用分别 64,032 与 63,986 bytes。原子发布、不覆盖已有输出。两轮均保留失败；002 调度进程返回 exit 1。

在 WSL Ubuntu、仓库根目录、已安装的隔离环境下，获得 models GPU 时段后使用**新的**目录名。以下仅为复现说明，本报告撰写时没有执行：

```bash
export BTV_STORAGE_ROOT=/mnt/d/video
/mnt/d/video/runtime/models/env/bin/python scripts/models/query_benchmark.py \
  --output-dir models/handoff/query-diagnostic-baseline-repro-001

/mnt/d/video/runtime/models/env/bin/python scripts/models/query_benchmark.py \
  --output-dir models/handoff/query-diagnostic-fewshot-repro-001 \
  --prompt-file configs/models/query-fewshot-prompt.txt
```

当前脚本默认基线的提示词和生成配置与 001 相同；由于增加了 override/metadata 功能，重跑脚本文件哈希会与 001 不同。比较时核对实际 prompt、probes、query.py、权重 revision 和环境，不声称跨版本/GPU bitwise 相同。旧目录存在时程序拒绝覆盖。

## 产品决定与后续验证

当前 Qwen3-0.6B 本地配置保持实验性质，不能替代严格规则/人工条件编辑入口。失败由合同/语义验证阻断，不能自动用其生成结果执行检索。对应独立问题见 [models-qwen-query-fidelity.md](../issues/models-qwen-query-fidelity.md)。

下一步应先冻结独立的真实用户查询与人工期望条件、单列未支持语义，再比较结构约束解码或更大解析模型。结构约束可能消除格式/字段错误，不能保证动作标签、关系顺序、同球员/同回合与 unknown 语义正确，仍需保留条件保真检查。修改提示词用开发集；最终留出集不参与提示词选择。此轮没有继续 GPU 搜参或训练。
