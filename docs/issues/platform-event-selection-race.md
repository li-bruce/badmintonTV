# 切换素材后，旧标注列表和保存回执污染当前编辑器

2026-09-29；关联 `R-02b / S1-02` 的源时间标注与修订往返。本项断言：发起于旧素材选择的标注读取、列表操作、保存回执和定位等待，不得更新新选择的标注编辑器；A→B→A 也按不同选择区分。工程回归 **PASS**；本修复未运行浏览器，不替代真实视频与人工标注验收。

## 复现与影响

在 `7e8a9bd` 的原前端，用现有 Node 假 DOM/延迟 API 复现：A 的 `/events?asset_id=A` 未返回时切到 B；B 加载完成后让 A 响应返回。实际 `state.asset=B`，列表却显示 `event-A`。点击该条目后，保存请求组合了 `event_id=event-A / asset_id=B / expected_revision=1`。后端 Store 已禁止修订更换原素材，因此会拒绝此请求；没有声称已经发生落库污染。但页面显示、定位与待保存内容串源，正常编辑被阻断。

同类迟到保存回执也能在切源后重新设置 `state.event`。单纯比较 asset_id 不足以覆盖 A→B→A；必须同时核对选择 epoch。旧按钮发起的 seek 如果等媒体 metadata 后才捕获 epoch，也可能把旧目标时间写到新播放器。

## 修复

- 切源开始立即清理当前 Asset、Event 和列表；新 Asset 确认后在任何 frame-map 等待前建立新标注状态。
- `loadEvents` 绑定 asset_id、epoch 和列表请求序号；旧成功/失败均不能更新当前列表或通知；列表按钮也核对相同上下文及 Event.asset_id。
- `selectAsset` 在等待 `loadEvents` 后再次检查 epoch，避免旧流程以旧时间重新刷新新素材代理。
- 保存使用发起时的 Asset 快照；回执只在同一 asset/epoch/编辑器 generation 下更新页面。旧请求仍可正常完成其原素材保存，不谎称撤销已发出的请求。新的标注草稿或条目选择不会被旧回执覆盖。
- 标注定位进入 `seekMedia` 时即捕获 epoch，媒体元数据等待结束后再次核对，禁止旧定位操作影响新素材。

## 验证

新增六组可控异步顺序测试，覆盖：A事件列表迟到；旧按钮在A→B及A→B→A后失效；旧保存成功/409回执在这两条路径后失效；慢frame-map期间清除旧event并按revision0新建；同一素材新建草稿抵御旧保存回执；旧标注等待metadata后不能定位B。

```powershell
Get-Content -Raw apps/platform/static/app.js | node --check
node -e "require('vm').runInThisContext(require('fs').readFileSync('tests/platform/preview_ui.test.cjs','utf8'))"
```

当前代码 **38/38 PASS，0 skipped，约1.52秒**，语法检查通过。测试使用内存假 DOM/API，无真实 HTTP、浏览器、媒体任务或数据库写入。同一新测试集合在内存绑定到 `7e8a9bd` 原源码时为 **32 PASS / 6 FAIL**，全部新增反例会在原代码失败；未回退工作树文件。

测试开发首轮36 PASS / 1 FAIL是新夹具尚未创建 notice DOM 节点，补齐假DOM后通过；没有放宽行为断言。后续如浏览器重复验证，仍须分别保留工程回归与真实视频证据，不将这些异步夹具当作模型准确率或人工审核真值。
