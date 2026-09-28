# Label Studio 集成设计与验证

2026-09-28。子任务范围：`apps/platform/labelstudio.py`、独立测试及本文；平台负责持久化、原始导出归档和修订 CAS。

## 设计

官方 [TimelineLabels](https://labelstud.io/tags/timelinelabels) 输出帧范围，单帧起止相同；[VideoRectangle](https://labelstud.io/tags/videorectangle) 输出对象关键帧。采用二者组合配置。标签不把网前粗球种映射成展搓/收搓。框轨迹只保留证据与未确认身份，不生成动作事实。

Label Studio 视频播放器按项目固定帧率定位，[官方说明](https://labelstud.io/templates/video_object_detector)提示变帧率素材可能偏移。因此必须提供每个显示帧到原片毫秒/PTS 的明确映射。原始 VFR 应生成 CFR 代理并保留逐帧映射；适配器不会按 frame/fps 粗换。每个项目使用相同且已核验的显示帧率。

`FrameMap` 输入 `{mapping_id,source_duration_ms,frames:[{ls_frame,source_start_ms,source_end_ms,source_pts?,proxy_pts?}]}`，不假设起始帧号。TimelineLabels 双端包含显示帧，转换为原片半开区间。未改变的导出区间保留原事件精确毫秒，用户改动边界后才使用覆盖帧范围。

`build_task(asset,media_url,frame_map,events=[],context={})` 导出任务和预标注；context 可指定 player_id/rally_id/shot_id。`import_annotation(task,annotation,tool_version=...,raw_export_relative_path=...,frame_map=None)` 返回 `{events,expected_revisions,tracks,warnings}`。原始 task/annotation/region ID、工具版本、映射 ID、导出引用、原始标注 SHA256 均进入 provenance。导入结果一律 unreviewed，平台复核后才可确认。

`LabelStudioClient` 仅允许 loopback，密钥由环境变量读取。提供 health/create_project/import_tasks/get_task/create_annotation/update_annotation/export_project。禁止自动重定向与代理，错误不回显请求内容或 token。

## 安装与容量预留

- 来源：官方 [安装文档](https://labelstud.io/guide/install.html)、PyPI `label-studio==1.23.1`；代码许可 Apache-2.0，数据/视频许可独立。
- Python：现有 Windows Python 3.12.11 仅用于创建独立 venv，不修改全局包。
- 独立环境 `D:/video/runtime/platform/labelstudio/env`；tmp/cache 均在该 owner 目录内。
- LS runtime 安装峰值预留 3,000,000,000 bytes；平台其他子任务预留 1GB，总预留 4GB < runtime/platform 10GB。
- LS DB/导出 `D:/video/platform/labelstudio` 预留 200,000,000 bytes。
- 安装前 D 盘约 968GB 可用；目录初始为空。主任务后续统一登记容量账本，未借用公共余量。
- 运行端口计划 `127.0.0.1:18081`；不使用 GPU。

## 实际验证（2026-09-28）

已安装 Label Studio 1.23.1 / SDK 2.1.2，Python 3.12.11；环境与缓存最终实测 994,339,440 bytes。安装报告含发行包 URL/哈希：`D:/video/runtime/platform/labelstudio/install-report.json`，依赖锁`requirements.lock.txt`。服务实际监听 `127.0.0.1:18081`，重启后启动器PID43212、服务子进程PID56520（仅代表本次运行）。日志/DB位于上述platform目录；随机凭据保存在同目录 `local-credentials.json`，不提交Git，不在平台API返回token。platform/labelstudio目录含DB、媒体副本及全部报告共2,181,159 bytes（回写验收前统计）。

真实样本：library的 `asset-057d2d6dd52eb892719b36aa1f017ac6272e19502dd93efbc0ca9f97f35b6fe0` / `data/raw/finebadmintonbenchmark/video_000001.mp4`；642,017 bytes，139帧、30fps CFR实测、time_base=1/15360，Asset.duration_ms=4634。标注服务导入为642KB副本（计platform数据），原片未改。数据集画面公开使用权尚未明确，只作本地研究/接口验证。

真实操作：

1. REST创建project1（组合配置被1.23.1接受）→导入真实视频task1→创建annotation1，预标记通用shot区间[1000,1600)，无身份、细手法推断。
2. Edge浏览器登录本机服务，真实视频播放画面加载成功；选择seed region，终帧48改60，界面显示起帧31、终帧60、Duration30。
3. 在第31帧绘制近端球员`player_unconfirmed`框，跳到41帧并移动框形成第二个关键帧，点击Update，界面提示`Annotation updated successfully`。
4. GET项目export取得真实JSON，`import_annotation`输出1个Event和1个track，Event经过统一Pydantic合同验证，区间[1000,2000)，保持unknown/未审核，expected_revision=1、revision=2。
5. 只终止并重启本任务Label Studio服务进程，REST重读task1/annotation1，确认区间31–60、2框关键帧全部保留，健康ready。`verification-restart.json`记录结果。

6. 通过运行中平台18080的`POST /api/v1/events`登记原seed revision1（reviewer=`agent-label-studio-verification`，provenance.reviewer_type=`agent`，unreviewed），`POST /api/v1/annotation/label-studio/task`保存平台权威seed/map，再`POST /api/v1/annotation/label-studio/import`回写真实导出。HTTP200：Event为revision2、[1000,2000)、unreviewed，1条track入库。
7. 原样再次调用import：HTTP200、events为空、track1；`GET /api/v1/events/ls-verification-interval/revisions`仍仅2版，幂等通过。验收调用传`reviewer_type:agent`；初次运行API尚未提供该顶层字段，reviewer名称及seed provenance明确记录agent，主平台后续统一升级审计字段。该标注不属于人类确认真值。
8. 主平台更新审计字段并重启后，读取revision2原内容，保持unreviewed，通过`expected_revision:2`显式新增revision3，顶层`reviewer_type=agent`。前两版保留不改。再次导入相同annotation返回events=[]，修订历史仍为3版，审计补记不破坏幂等。报告`D:/video/platform/labelstudio/verification-platform-agent-audit.json`保存补记内容及前后历史。

原始/回写交接文件：`D:/video/platform/labelstudio/verification-export-ui.json`、`verification-converted.json`、`verification-state.json`、`verification-ffprobe.json`、`verification-platform-seed.json`、`verification-platform-import.json`、`verification-platform-idempotency.json`。Event ID `ls-verification-interval`。平台归档原始JSON：`platform/annotations/labelstudio-ce88bc9e3694456d9341fa1cee2a88210c45e11cc85532e8a72196535eeedf13.json`。URL `http://127.0.0.1:18081/projects/1/data?tab=1&task=1`。

帧约定核验：UI第一帧`1 of 139`显示0秒；第31帧显示1秒；区间31–60显示30帧，确定本次TimelineLabels双端包含。但VideoRectangle导出frame31附带time=1.033333，frame41附带time=1.366666；因此忽略LS的`time`回算，只使用显式PTS映射（31→1000ms，41→1333ms）。这是实际版本差异，不假设所有未来LS版本沿用同一编号。

单元测试：`D:/video/runtime/platform/env/Scripts/python.exe -m pytest tests/platform/test_labelstudio.py -q`，10项，覆盖变帧率、首末/单帧、精确往返、修订、unknown、身份、路径、重复代理帧、源时间缺口和删除警告。使用合成字典验证转换边界，不作为动作识别准确率证据。

## 启动与限制

在独立进程环境设置 `LABEL_STUDIO_BASE_DATA_DIR=D:/video/platform/labelstudio`，`LABEL_STUDIO_USERNAME/PASSWORD/USER_TOKEN`从本机凭据文件读入，`TEMP/TMP=D:/video/runtime/platform/labelstudio/tmp`。运行 `D:/video/runtime/platform/labelstudio/env/Scripts/label-studio.exe start --no-browser --internal-host 127.0.0.1 --port 18081 --enable-legacy-api-token`。服务凭据仅用于本机实例；Python Web端仅需`BTV_LABEL_STUDIO_TOKEN`环境变量。

当前client使用实例已启用的legacy Token认证；未实现Personal Access Token刷新流程。导入后的visibility/player/动作可信度须在平台复核；从LS删去seed会给warning，不能默默删除平台人工事件。外部task.data不得成为权威资产/PTS来源，平台应以自己保存的task映射替换后再转换。个人录像、VFR真实代理、跨镜头跟踪未测。
