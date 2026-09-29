# 制作素材用途隔离

日期：2026-09-29；对应固定用例 R-04b（S0、S4），工程回归 G-01。本轮先实现合同及共用边界；完整 R-04b 仍需平台和独立 render 在真实数据入口执行，不能仅凭合同测试判为产品 PASS。

## 冻结断言与设计

给定 Asset、导入前只有 relative_path 的 partial metadata，或产品内派生物，制作前检查必须遵循以下断言：

1. 新增 `Asset.usage_scope=general|training_only`，旧清单缺字段按 general 读取。它独立于 rights 和 split。
2. typed 字段、provenance.usage_scope、逻辑或解析物理路径的 `data/training/`、可信 registry 的 ID/hash/path、可解析的来源链，任一命中 training_only 都拒绝制作；research_preview 也拒绝。
3. registry 只读固定的 `data/training/handoff/training-registry.v1.json`，仅 library 写入。它包含 schema_version=1.0、assets 数组，条目最小字段为 asset_id/sha256/relative_path/usage_scope=training_only，可附 provenance；不要求完整 Asset 探测字段。
4. 完全没有 data/training 目录且 registry 缺失时，兼容检查已有用途标识、路径和提供的来源链；data/training 已存在但 registry 未发布时，全局 TRAINING_REGISTRY_PENDING 阻塞制作。library 可原子发布有效空 registry 表示暂无已验证资产。存在但损坏、不可读或异常的 registry 必须阻塞，不得按“未发现训练数据”放行。每次公开检查重新读取并计算 registry SHA256；不依赖 mtime、文件大小缓存旧结果。
5. 产品内派生物保留直接来源 asset_id/sha256 和用途；ID/hash 关系矛盾或来源环路拒绝。无法解析的来源关系保留提示，不虚构来源用途；外部任意转码移除元数据后，本工具不能保证识别它。

检查分为 metadata/path/registry/source-chain 四层，不同步读取整段媒体计算 SHA256。**调用方必须先核验实际字节 hash，或在后台探测得出真实 hash 后再次调用**，不能只信任 Web 声明的 sha256。partial 导入预检不是最终准入。路径解析应在实际打开原片之前重做；返回的 Path/检查结果不代替文件系统防竞态措施。

## API

已公开：`UsageScopeGuard(storage_root).check(asset, source_assets=()) -> UsageDecision`；`assert_production_allowed(assets, storage_root, source_assets=(), research_preview=False)`；`inherit_usage_scope(derived, source, storage_root, source_assets=()) -> dict`。支持 Asset 和包含平台附加字段的 dict；partial 至少 relative_path。

UsageDecision 含 allowed、usage_scope、reasons 与本次 registry_sha256。UsageScopeError 带 code/asset_id/reasons。稳定错误码：TRAINING_ONLY（可在浏览时过滤此项）；TRAINING_REGISTRY_PENDING、TRAINING_REGISTRY_INVALID、TRAINING_REGISTRY_UNAVAILABLE（全局阻塞）；USAGE_METADATA_INVALID、USAGE_PATH_INVALID、USAGE_SOURCE_CONFLICT（资产验证失败，不得静默过滤）。

不提供 Web 指定 registry 路径的参数，也不提供 registry 写接口。生命周期内复用 Guard 不会缓存某次放行；每次检查重新加载 registry。

```python
from packages.contracts import assert_production_allowed, inherit_usage_scope, UsageScopeError

# 导入预检接受 partial；后台得出 verified_asset 的实际 SHA256 后必须再调用。
assert_production_allowed({"relative_path": "data/raw/input.mp4"}, storage_root)
assert_production_allowed([verified_asset], storage_root, source_assets=stored_sources)
# 创建产品内代理 metadata 时保留直接来源，不覆盖已有不一致的来源关系。
proxy = inherit_usage_scope(proxy_metadata, verified_asset, storage_root, source_assets=stored_sources)
# 研究预览不会绕过训练用途限制。
assert_production_allowed(selected_assets, storage_root, research_preview=True)
```

同 SHA 多路径（同 ID 同 hash 的别名也包括在内）合法，所有别名都受限制；重复 ID 的 hash 冲突、同路径的 hash 冲突拒绝整个 registry。`TrainingRegistry` / `TrainingRegistryEntry` 是公开的最小清单类型，随 `python -m packages.contracts --output ...` 导出独立 JSON Schema。

## 验证记录

目标：上述 5 条断言全部有正反向可复现合同回归；真实职业素材隔离由 library/platform/render 联调另行验收。

输入：临时原生文件系统中的明确合成 metadata、registry 和符号链接/junction，无媒体下载、无模型推理。

命令：`D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/contracts -q`。

预期：训练用途冲突、别名物理路径、registry ID/hash/path 与递归来源链均阻断；普通旧清单兼容；损坏 registry 阻断；同大小同 mtime 更新不能沿用旧放行。

实际结果：合同回归 **111 PASS，0 FAIL，0 SKIP**（2026-09-29）。覆盖类型兼容、partial 预检、每个训练标识及冲突、研究预览、逻辑/物理路径、实际 Windows junction、最小 registry、缺失/损坏/权限错误、完整数组验证、多路径别名、同大小同 mtime 更新、递归来源/冲突/环路、派生用途继承及 caller hash 核验边界。环境为既有 `D:/video/runtime/platform/env`，不下载媒体或新依赖。

R-04b 的**合同层子断言 PASS**，证据是 `tests/contracts/test_usage_scope.py` 与当前测试输出；完整 R-04b 仍为 **NOT_RUN**，下一步由平台制作库/选片/时间线/worker 与独立 render 对真实训练清单逐入口验证，不能把此处 111 项软件回归替代完整产品验收。
