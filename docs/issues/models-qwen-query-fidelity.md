# Qwen3-0.6B 查询输出合同与条件保真未通过

状态：open / fidelity blocked。记录日期：2026-09-28。影响模块：models.query_parse。范围：本地 Qwen3-0.6B 的当前提示词与 greedy 配置；不是全部 LLM 的能力判断，也不是视频识别效果结论。

## 已确认问题

模型、权重校验和 RTX 5090 前向生成已经运行，当前失败来自输出合同与查询语义。两轮都实际执行 24 条开发者诊断，均 `completed_with_failures`：

| 实验 | 严格通过 | 首个失败原因 |
|---|---:|---|
| query-diagnostic-001，原提示词 | 0/24 | 24 个 `invalid_generated_json` |
| query-diagnostic-002，fewshot-v1 | 2/24 | 20 个 `invalid_generated_json`、1 个 `invalid_schema`、1 个 `endpoint_semantic_mismatch` |

第二轮只有“吊球”和“后退”通过；三个 few-shot 输入是“挑球”“后退然后发球”“弓步同时放网”，未出现在计分探针中。第二轮看过首轮错误后调整提示词，所以 2/24 是开发集调试结果，不能作为独立测试成绩或模型最佳表现上限。

明确的失败证据：

- 001 `single-01.json`：JSON 围栏、中文机器标签 `stroke=杀球`、自连关系、非法 `relation=stroke`、擅自开启 include_uncertain。001 `single-04.json` 还出现空目标关系与 same_player/same_rally=false。
- 002 `sequence-04.json`：围栏内仍把起跳杀球写成非法 `stroke=jump`，遗漏标签合取和全部 before 关系。单纯去除围栏不能修复条件。
- 002 `unknown-01.json`：合法 JSON/schema 中 `hand_technique=unknown` 正确，但 `include_uncertain` 被擅自改为 true；严格语义检查已经阻断该扩大条件的结果。
- 002 `unknown-04.json`：JSON 中 `steps=[]`，且缺少必需的 include_uncertain；应保留的 `movement=unknown` 消失，schema 检查拒绝。

原文保存在 `D:/video/models/handoff/query-diagnostic-001/` 与 `D:/video/models/handoff/query-diagnostic-002/`；WSL 对应 `/mnt/d/video/models/handoff/`。每轮 report、run-metadata 和逐项 raw_generation 都保留，未修写、未重新计分。完整版本、哈希、速度、显存、复现命令见 [实验报告](../experiments/models-003-query-diagnostics.md)。

## 配置与资源证据

权重 revision 为 `c1899de289a04d12100db370d81485cdf75e47ca`；Python 3.11.16、torch 2.7.1+cu128、CUDA build 12.8、transformers 4.51.3；bf16 CUDA、非 thinking、greedy、最大 768 新 token、seed 0。没有训练或结构约束解码，两轮均未出现 token 截断或 OOM 记录。

001 生成 4281 token / 85.636106 s，49.990596 token/s；peak allocated/reserved 分别 1,383,128,064 / 1,428,160,512 bytes。002 为 2617 token / 52.541517 s，49.808231 token/s；peak allocated/reserved 为 1,450,786,816 / 1,480,589,312 bytes。显存只描述当前 PyTorch 分配器，不代表整卡占用。

原提示词 SHA256 为 `7591e515dbec4ba176ed6ba30445b2d2e6252d10cdf9646e21b9dd56ed3b13ba`，fewshot-v1 为 `e9db2da9ab521d7aea0ab2492c99c69662173e79aa66116920be7db18f315e34`；两轮探针 SHA256 相同：`4281358eeae264198ff90c0a1424a437fb19bed3e6b585c95b67b3f11923d0a0`。第二轮仅显式选了 prompt override；统一模型 CLI 及不带 override 的 benchmark 默认仍为原基线。

## 产品影响与当前处理

该配置不能标为已验证的自动中文条件解析。JSON 合法也不能保证标签、顺序、同人/同回合、unknown 与 include_uncertain 的含义正确。错误结果若直接送入检索，可能遗漏约束或扩大候选范围。

当前严格校验保留：原始输出直接做 JSON/schema/语义验证，失败明确返回错误；不剥围栏、不补字段、不重写标签、不静默退回规则。底座可以继续使用独立的受限规则解析与人工条件编辑；选择本地 Qwen 时应显示实验状态及具体失败。

## 下一步与关闭条件

1. 先获得真实用户查询，人工填写期望 QuerySpec，冻结独立测试集；保留 unknown、关系方向、同球员/同回合、否定/任选/计数等支持边界，不以本轮 24 条调试探针冒充用户语料。
2. 在开发集比较结构约束解码或更大解析模型，再用冻结集验证。结构约束只解决可表达的格式限制，仍需独立核验标签与条件保真。官方建议的非 thinking 采样配置也与本轮 greedy 不同，当前结果不能解释为最优解码上限。
3. 关闭问题须提供配置/权重/代码版本、冻结查询集、逐条原始输出与完整失配记录，并证明成功输出不遗漏或扩大已支持条件；未支持查询要明确拒绝。具体产品门槛由主任务与真实查询覆盖共同确定，不能用两条简单成功代替。

本次只记录已完成实验，没有继续 GPU 尝试、下载或训练。此问题独立于细动作视频真值缺口；解析器通过也不等于视频中动作存在。
