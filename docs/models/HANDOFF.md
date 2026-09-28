# 模型模块交接

任务01a0e88b-416f-7ca2-bfec-c09ec1462866，分支work/models。当前为协议可验证初版；环境与真实ML实测结果随后补充，不以代码存在冒充模型已验证。

## 平台入口

在已集成仓库根目录：

```powershell
python -m packages.models catalog
python -m packages.models run --request REQUEST.json --result NEW_RESULT.json
```

WSL模型环境：

```bash
source environments/models.env.sh
/mnt/d/video/runtime/models/env/bin/python -m packages.models run --request /mnt/d/video/models/handoff/requests/real-pose-001.json --result /mnt/d/video/models/handoff/real-pose-001/attempt-01/result.json
```

管理员launcher用参数数组调用，Windows路径由launcher转换，绝不把请求拼进shell。模型不读写平台SQLite。请求须含schema_version/job_id/attempt_id/operation/assets/parameters/output_dir。assets是完整Asset数组；parameters.model_id必填；output_dir以models/开头。新attempt应使用新目录/result路径，既有结果不覆盖。

操作：query_parse、pose、video_embedding、movement_classification；analyze仅作为共享fixture兼容别名，依model_id解析非查询能力。平台queue可叫model，但CLI不能传operation=model。退出码0成功/1失败/2blocked/130cancelled。强杀未产result时由worker记录WORKER_INTERRUPTED并确认旧进程终止才释放GPU；解析数据、SHA256、stderr都不是成功凭据，检查result+exit+attempt。

## 模型清单与结果

`configs/models/catalog.json` 是供导入的初始状态快照；catalog实时检查本进程依赖、受控权重清单/文件大小，不凭snapshot判定就绪。模型实际加载前复核完整文件SHA256。

| model_id | 能力/结果 | 首版限制 |
|---|---|---|
| query-rule-v1 | QuerySpec artifact，stdlib | 有限中文词表，不支持的修饰/否定/任选/未确认姓名明确失败；不推断player_id |
| query-endpoint-v1 | 兼容端点解析 | 管理员BTV_LLM_CONFIG路径；只发固定prompt+查询；默认loopback，远程需显式HTTPS；未配blocked |
| qwen3-0.6b | 本地小模型解析 | 原始模型输出须schema与规则语义双检；失配blocked，无静默fallback |
| torchvision-keypointrcnn | COCO17原片坐标+PTS特征 | 每帧detection ID，track_id/player_id=null；没有跨帧跟踪或手法分类 |
| clip-frame-mean | 512维短窗抽帧均值向量 | 无时序顺序、中文检索未验证，不能据此识别细搓球 |
| skeleton-temporal-v1 | unavailable | TRAINING_DATA_REQUIRED；只有骨骼特征函数，未训练分类器 |

姿态与CLIP结果events为空，这是没有动作证据的真实状态。所有产物含源asset/time/hash、模型版本/job/attempt与未验证事项。推理max30秒、max120采样帧、80M保留像素、10k解码帧/帧间60秒截止；单次原生解码阻塞还需worker超时兜底。只在platform GPU租约下运行；当前模块初始化实验持有GPU排期。

兼容端点管理员JSON只有base_url/model/api_key_env/timeout/allow_remote；不接受HTTP响应重定向，不继承系统代理，key只放Authorization，不返回原始服务端错误。未部署实际LLM端点，loopback测试是传输测试。

## 已验证与数据边界

- 主任务共享合同8900958（platform原6a3e3d）：canonical model-request、所有结果fixtures、六清单、四真实Asset、QuerySpec交叉验证通过。
- Windows90tests：88过、2个symlink权限跳过；WSL同90tests全过，包含symlink与真实loopback HTTP。
- 真实四片来源D:/video/data/handoff/assets.v1.json已读取并生成请求；match_id unknown/split unassigned，只能预训练推理，不能正式训练/评测。
- 协议/算子/真实推理/准确率四者分开报告。缺细标签、专家命名锚点与跨场真值，详见docs/issues/models-fine-label-ground-truth.md。

复核命令：

```powershell
$env:BTV_CONTRACT_FIXTURES_DIR='C:/Users/USER/Desktop/Program/badmintonTV/packages/contracts/fixtures'
python -m unittest discover -s tests/models -v
D:/video/runtime/platform/env/Scripts/python.exe scripts/models/check_contracts.py --contracts-repo C:/Users/USER/Desktop/Program/badmintonTV
```

## 环境和存储

WSL共享base=/home/ubuntu/miniforge3（conda25.9.1已有）；新models prefix=/mnt/d/video/runtime/models/env。公共包缓存=/mnt/d/video/runtime/shared/pkgs。无需其他任务安装公共Conda。脚本environments/models.env.sh固定HF/Torch/tmp/pip路径，禁自动线上拉权重；bootstrap.sh与锁文件提供复现依据。没有模型网络服务端口。

model权重/特征等<=180GB；models runtime<=35GB；公共base+cache<=15GB（原生base+旧pkgs保守约5.925GB计入，其他用户env单独记录不修改）；其他runtime20GB保留。没有删除用户数据。下载中断partial保留有记录，下载流实际字节受限；models写者原子排他预留，其他owner按固定全额配额保守计数。
