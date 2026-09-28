# 跨任务数据合同 v1.0

所有传输采用 UTF-8 JSON/JSONL，顶层 `schema_version: "1.0"`。本文件是第一轮的共同接口。平台任务优先将其实现为 `packages/contracts` 中可验证的类型/schema，并单独提交contracts与canonical请求/结果fixtures；主任务先集成此提交，将SHA告知其余任务。其他任务可先用字典和本地校验器，随后必须用同一组fixtures进行兼容检查，不能只记录差异后各自结束。

## 通用规则

- 所有媒体时间均为**原视频开始起算的整数毫秒**，区间 `[start_ms,end_ms)`；要求 `0 <= start_ms < end_ms <= duration_ms`。帧号是附加信息，保留 time_base 和 PTS 映射用于精确回查。
- ID 为不透明字符串；asset_id 稳定，导入时以 sha256 去重。relative_path 是相对共享存储根的POSIX路径，如 `data/raw/match01.mp4`；禁止绝对路径、`..`、路径穿越和根外符号链接。
- 稳定机器键与中文显示名分离。未知字段用 null/unknown，不能伪装0或negative。模型 confidence 未校准可为空。
- Artifact 必須含 `artifact_id, kind, relative_path, sha256, size_bytes, created_at, producer`。只在完整写入并校验后发布。
- 并发标注更新须携带 expected_revision；冲突返回409。自动预测与人工版本并存。

## Asset 与素材清单

每个 manifest 是 `{"schema_version":"1.0","assets":[...]}`；支持 JSONL 单条 Asset 作为批量交换形式，文件扩展名区分。Asset 字段：

| 字段 | 类型/规则 |
|---|---|
| schema_version, asset_id, relative_path, sha256 | 字符串；hash为原文件SHA-256 |
| size_bytes, duration_ms, width, height | 非负整数；待下载资产不得假填探测值，应保留为 source candidate，下载后再发布Asset |
| fps_num, fps_den, time_base | 有理帧率/流时间基；VFR需另有PTS索引引用 |
| title, match_id | 字符串；match_id贯穿同场回放/剪辑，不能因换文件而换组 |
| source_type | broadcast / personal / dataset / synthetic |
| source_url, source_page, acquired_at | 来源和ISO8601时间；本地个人素材URL可null |
| camera_type, discipline | rear/side/overhead/handheld/mixed/unknown；singles/doubles/unknown |
| players | `[{player_id,display_name,identity_status}]`，身份可unconfirmed |
| rights | `{status,license_url,evidence,allowed_uses}`；status=unknown/research_only/permitted/owned；分别保留画面与标注的证据，不能由仓库许可推断画面许可 |
| split | unassigned/train/validation/test；按match_id整体固定 |
| probe, provenance | 扩展字典：探测器版本、原始URL/数据集版本、hash等 |

下载前 source candidate 使用独立清单，含 URL、预估峰值bytes、用途、许可调查、download_status 与失败原因；不把下载候选当已经存在的 Asset。

## Event 与人工真值

`{"schema_version":"1.0","events":[...]}`；每条：

```json
{
  "schema_version": "1.0",
  "event_id": "event-example-01",
  "asset_id": "asset-example",
  "match_id": "match-example",
  "rally_id": "rally-example-01",
  "shot_id": "shot-example-01",
  "player_id": "player-a",
  "track_id": "shot-example-01:near",
  "kind": "stroke",
  "start_ms": 4000,
  "end_ms": 4700,
  "contact_ms": 4350,
  "labels": {"stroke": "net_shot", "hand_technique": "unknown"},
  "visibility": "insufficient",
  "confidence": null,
  "review_status": "unreviewed",
  "revision": 1,
  "provenance": {"source": "manual", "model_id": null, "model_version": null, "run_id": null},
  "evidence": [{"type": "source_interval", "asset_id": "asset-example", "start_ms": 4000, "end_ms": 4700}],
  "unknown_reason": "球拍触球细节不可见"
}
```

此例只是合同示例，不是实际标注。kind=shot/rally/stroke/movement；review_status=unreviewed/confirmed/rejected；visibility=clear/partial/insufficient。labels 各字段允许unknown；置信度不代替可见性。provenance.source=manual/model/rule/import。人工修订记录审阅者、时间和前一版本，不能让新模型结果覆盖已审核条目。

标签起点：`hand_technique=net_zhan_cuo/net_shou_cuo/unknown`，`footwork=backward_small_hop_start/unknown`。只是产品内稳定标识，正反手细分和动作判据须由标注说明定义；不能把ShuttleSet的net shot直接映射成展搓或收搓。

## QuerySpec 与候选

`QuerySpec={schema_version,query_id,text,player_id,scope,steps,relations,include_uncertain}`。

- scope 含 library_ids、asset_ids、match_ids、source_types；player_id可null。
- steps 是 `[{step_id,kind,labels}]`；relations 是 `[{from_step,to_step,relation,max_gap_ms,same_player,same_rally}]`。
- relation=before/overlaps/near；before 以源时间排序，不要求整张事件表相邻，因此允许对手插入击球。
- Candidate 含 candidate_id、asset_id、start_ms/end_ms、player_id、event_ids、matched_conditions、missing_conditions、uncertainty_reasons、rank_score、review_status、evidence。
- rank_score 只用于排序，不能标成准确率。规则查人工真值是第一条可靠基线，LLM/向量均可为空缺功能。

## 模型卡和执行协议

`ModelManifest={schema_version,model_id,version,display_name,capabilities,status,entrypoint,environment,weights,parameters_schema,input_schema,output_schema,supported_labels,supported_camera_types,evaluation_report,license,resource_requirements}`。

- status=not_installed/ready/experimental/unavailable；未安装/依赖不兼容须说明reason。
- weights 每个含relative_path、sha256、license_url。entrypoint是管理员注册的命令模板，用户不可传任意shell命令。
- capabilities 可有 pose,tracking,stroke_detection,movement_classification,video_embedding,query_parse。
- 模块CLI协议：`python -m <module> run --request <request.json> --result <result.json>`；执行参数数组调用，禁止shell拼接。具体module路径在model manifest登记。
- request=`{schema_version,job_id,attempt_id,operation,assets,parameters,output_dir}`；assets固定为Asset数组。output_dir必须是共享根下该owner目录内的POSIX相对路径，例如render/jobs/job-01/attempt-01；执行器根据配置的Windows或WSL存储根解析。
- stdout JSONL=`{schema_version,job_id,seq,event,stage,current,total,unit,message}`，event=progress/artifact/warning/error；stderr日志不得包含secret。
- result=`{schema_version,job_id,attempt_id,status,artifacts,events,error}`，status=succeeded/failed/cancelled/blocked；未就绪应blocked并有error.code。stdout进度不是成功凭据，结果文件和返回码均要检查。退出码约定：0=succeeded、1=failed、2=blocked、130=cancelled；强制终止导致没有result时由worker如实记录取消或WORKER_INTERRUPTED，不能伪造结果。
- `--request`与`--result`是子进程所在操作系统可访问的文件路径；跨Windows/WSL由受控launcher转换，不让模型猜路径。模型不得打开平台SQLite。写回必须匹配当前attempt_id，防止旧重试覆盖新结果。

## Timeline 与渲染协议

```json
{
  "schema_version": "1.0",
  "timeline_id": "timeline-example",
  "title": "网前技术片段",
  "segments": [
    {"segment_id": "clip-01", "asset_id": "asset-example", "in_ms": 2000, "out_ms": 7000,
     "speed": 1.0, "event_ids": ["event-example-01"], "fit": "contain",
     "title": "待人工核验的示例", "audio": "source", "review_status": "confirmed"}
  ],
  "output": {"width": 1080, "height": 1920, "fps": 30, "video_codec": "h264", "audio_codec": "aac"}
}
```

Timeline 是可编辑工程；片段通过Asset映射解析路径，不能直接执行传来的FFmpeg过滤器。speed>0，音频策略source/mute；慢放使用匹配音频变速或显式静音。fit=contain/crop；默认contain保留整个比赛画面，crop必须有明确裁切窗口，运动跟随可作为后续扩展。序列合并/回放去重应保留被合并事件的回查关系。

研究预览兼容扩展：`parameters.research_preview=true` 可处理未人工确认的片段，输出必须带“待人工确认·本地研究样片”标记，QA记录 `human_confirmed_segments=false`。这用于先交付本地可审阅样片，不会将unreviewed事件变为confirmed。片段边界/播放检查、技法真值审核、公开发布权限分别记录；代理审片来源为agent，不能冒充human审核。无该参数时保持确认片段的正式流程。

渲染采用同一CLI请求/result协议，operation=render，parameters仅含timeline及渲染设置，assets数组只放顶层，由执行器内部按asset_id建立映射。render result 的artifacts至少有MP4、timeline JSON、逐段原片/输出时间映射、QA报告；OTIO为可选互操作产物，不替代实际编码。QA记录输出尺寸、时长、音视频流、解码检查和人工观看结论。导出本地研究样片与公开发布资格分别报告。

完整外层请求形状（assets中的对象字段按上表填齐，下面只表示结构，不是可下载/已验证素材）：

```json
{
  "schema_version": "1.0",
  "job_id": "job-01",
  "attempt_id": "attempt-01",
  "operation": "render",
  "assets": [],
  "parameters": {
    "timeline": {
      "schema_version": "1.0", "timeline_id": "timeline-01", "title": "空结构示例",
      "segments": [],
      "output": {"width": 1080, "height": 1920, "fps": 30, "video_codec": "h264", "audio_codec": "aac"}
    }
  },
  "output_dir": "render/jobs/job-01/attempt-01"
}
```

空segments必须作为无可渲染片段失败，不能生成空白视频假称成功。可运行非空示例由platform在contracts fixtures中提供，并由render共同验证。
