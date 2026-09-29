# R-04b：真实训练 Asset 的直接渲染拒绝

2026-09-29 17:59北京时间，使用代码提交`0f0c7f9887a365fcb41d50b51168f70e61cf00a9`，对library刚发布的真实训练Asset运行四个独立CLI负例。四例均 **PASS：exit 2 / blocked / TRAINING_ONLY**。没有生成该训练视频的成片、预览、图像或媒体探测结果。

## 固定资产与快照

- Asset ID：`asset-b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913`。
- 相对路径：`data/training/fine-badminton-2026-zenodo-20292976-v1.0/extracted/876ddac3abe9141b8ce7f2fe.mp4`。
- 声明SHA256：`b210dc39a219d5ec5bb87ef980f5bce0d3ed1ebf1234d21d5342b24273a1f913`；文件实际存在，stat为231,500,744 bytes，与manifest一致。
- Asset typed及provenance的`usage_scope`均为`training_only`，split为unassigned，权利为research_only；`Asset.model_validate`及四份`JobRequest.model_validate`通过。
- library manifest：`data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json`。本次读取4项，快照SHA256为`6a30244ce17b6fec560af822be71e336e52a3641e444600595cc73cc80d3403c`。
- 固定可信registry：`data/training/handoff/training-registry.v1.json`，快照SHA256为`3a0b9bf2c4677c43639929c402afcb81dbd497b3dd22b1ca193db60533aea9c4`。指定ID唯一匹配，SHA/path/用途均一致。

manifest仍在增加条目、排序可能变化，因此按library交付的**固定ID**选取，不使用动态列表首项。原片完整hash、PTS、全解码来自library的已验证Asset；本次只读其元数据与stat，**没有重新读231MB原片或重算媒体SHA**。因此这是实际资产的用途拦截验证，不是第二次媒体完整性验证，也不是模型识别实验。

## 入口与结果

使用同一资产构造0–1000ms的负例请求，CPU后端指向实际存在的compat8 FFmpeg/ffprobe二进制。只对一次性测试请求改变preview/research_preview/review_status，不修改原manifest、registry或生产库。

| CLI模式 | preview | research_preview | 测试review_status | 退出/结果 | 媒体子进程启动尝试 | 渲染job目录 |
|---|---|---|---|---|---:|---|
| standalone | false | false | unreviewed | 2 / TRAINING_ONLY | 0 | 不存在 |
| preview | true | false | unreviewed | 2 / TRAINING_ONLY | 0 | 不存在 |
| research-preview | true | true | unreviewed | 2 / TRAINING_ONLY | 0 | 不存在 |
| confirmed | false | false | confirmed（测试声明） | 2 / TRAINING_ONLY | 0 | 不存在 |

每例仅输出一个error ProgressEvent，artifacts为空。错误同时报告typed、provenance、逻辑训练路径、物理训练路径和可信registry ID/SHA/path七项命中。confirmed仅用于反例，**不是人类确认，更未写回库中**。

为确保负例绝不会误生成媒体，子Python通过`runpy.run_module('packages.render', run_name='__main__')`运行真实CLI入口，并安装Python audit hook：任何`subprocess.Popen`、`os.system`、`os.exec*`或`os.spawn*`都会先记录尝试并抛错。没有mock用途helper、请求归一化、错误或返回结果。四份audit均为空，证明本轮连媒体子进程启动尝试也未发生；这项审计只限本次受控负例，不宣称是普遍的操作系统沙箱。

## 证据、容量与复核

证据目录为`D:/video/render/handoff/training-denial-5f1e29d2eab9/`：

- `validation.json`保存固定Asset摘要、快照SHA、四个实际argv、逐项assert及结果hash。
- `guarded_cli.py`保存实际审计包装代码，可结合各argv复核运行方式。
- 各模式的`*.request.json`、`*.result.json`、`*.audit.json`、`*.stdout.jsonl`、`*.stderr.txt`保存原始结果。重跑必须换job/输出及result路径，不能覆盖这些证据。

短时证据元数据预留为1,000,000 bytes，实际仅 **33,747 bytes**，含四份完整请求元数据；媒体文件未复制。预留覆盖证据目录，不是制作任务的媒体容量预留。完成后释放，`.render.lock`不存在，GPU未使用。独立子agent按同一固定ID只读核对Asset/registry/文件stat及共享helper，也返回TRAINING_ONLY。

这里只补R-04b的render侧真实训练资产证据；制作库导入/选片、下载接口、模型研究入口分别由对应模块验证。未改变现有生产小样，也未据此宣布整个产品验收完成。
