# Fine-Badminton 训练视频小范围画面检查

2026-09-29，读取已发布 typed 训练 manifest，按 `probe.probed_at` 顺序分两批完成 10 个资产的中间帧检查。首批只处理获准的 5 个资产；主任务完成 10/10 全片 CPU 解码与完整 PTS 发布后，按通知补齐其余 5 个，首批图像与收据不变。

本次输入只来自 `data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json`。每个源视频 SHA 在生成前后核对；完整 PTS 索引核对 SHA、大小、连续行数与严格递增时间戳。取 `frame_count // 2` 行的实际整数 PTS，使用 CPU FFmpeg 9.0.2 单线程、`-hwaccel none`，先在目标前一秒 seek，再用 `select=eq(pts\,<整数PTS>)` 选帧，`showinfo` 复核整数 PTS 和 time_base，缩放至 640 px 宽。

未使用 CSV 帧索引。以下是逐张 `view_image` 的画面观察，不判断击球类别、人员身份或动作/事件边界；单张近景不表示视频缺少球场画面，也不能代替专家标注。

## 逐资产实际观察

表内资产短码为源 SHA 前 24 位；同名 `.middle.json` 收据保留完整 `source_asset_id`、源 SHA、PTS 索引 SHA/行号/时间、输出 SHA、完整 argv 和两处 `usage_scope=training_only`。

| 源资产短码 | PTS 行号（1 起）/帧索引（0 起） | 源时间（秒） | JPEG bytes | 单张画面可见性 |
|---|---:|---:|---:|---|
| `b210dc39a219d5ec5bb87ef9` | 16326 / 16325 | 653 | 46,337 | 球场主体、球网、边线和双方运动员可见；有比分、台标及水印叠字。 |
| `e3209edc70f0ede17378609a` | 63601 / 63600 | 2544 | 26,024 | 转播人物背侧近景与场边背景可见；没有完整球场，无法用该张检查球场几何。 |
| `33a3ba4819650ec444ea3b56` | 39735 / 39734 | 1589.36 | 29,889 | 高位后方球场画面，球网、场线及双方运动员可见；有比分叠字。 |
| `2b8095bfdc3d9e7b89242667` | 31201 / 31200 | 1248 | 31,187 | 转播人物近景、球拍与场边广告可见；没有完整球场。 |
| `d3b2f63cc237ebb3f22944e1` | 47431 / 47430 | 1582.581 | 18,657 | 转播人物上身近景及台标可见，背景较暗；没有可核查的完整球场。 |
| `8ac4dfb7b7cb045bb975c058` | 36632 / 36631 | 1465.24 | 48,278 | 斜侧方球场主体、球网和场线可见，场内有清洁人员及拖把、场边有人；该张未显示连续比赛动作。 |
| `8b9cac6f911b60cf3240f842` | 71112 / 71111 | 2844.44 | 36,019 | 场边两人人物近景及局部球网、场线可见；没有完整球场。 |
| `3857ef3cdd5e52b2badb5c0f` | 65211 / 65210 | 2608.4 | 22,835 | 转播人物上身近景、台标和直播叠字可见；没有完整球场。 |
| `a70c12f0c1ecbc21ff27ad21` | 59101 / 59100 | 2364 | 51,164 | 人物全身中景、局部场线、网边和场边座椅可见；镜头不足以检查完整球场几何。 |
| `80d9c5be022baef9ce57773c` | 60008 / 60007 | 2396.86 | 59,151 | 后方高位比赛画面，球场主体、球网、场线及双方运动员可见；有比分和赛事叠字。 |

10 张全部生成且逐张 `view_image` 查看；其中 4 张可观察球场主体（包含 1 张清洁场地画面），其余 6 张为人物/场边近景或中景。未根据脸、衣服或比分姓名确认身份。所有图像继续属于 `training_only`，不发布到制作素材库。

## 路径、容量与复跑

唯一图片/收据输出目录：

`D:/video/data/training/fine-badminton-2026-zenodo-20292976-v1.0/quality-control/`

文件名为 `<源SHA前24位>.middle.jpg` 和 `<源SHA前24位>.middle.json`。最终 10 张 JPEG 加 10 个收据实际 **397,365 B**，单张最大 **59,151 B**（首批为 165,998 B，本次新增 231,367 B）。`QuotaManager` 每批预留 10,000,000 B；QC 目录本身也限制为 10,000,000 B，并在写入前包含原子发布临时双份余量。FFmpeg 仅输出到 pipe，最多读 500,001 B，超过 500,000 B 时不会写 JPEG；收据每份不超过 16,384 B。

图片及收据均使用独占 `.part` 和不可覆盖 hardlink 发布，源文件只读。图片已发布但收据尚未写入时若中断，下次会拒绝孤立输出并保留现场，不自动覆盖。批次锁和预留正常释放；共用既有配额账本是唯一 QC 目录外的存储记账变动。媒体图片不进入 Git。

实际命令（两批均退出 0，首批约 4.74 s；补齐批约 8.78 s）：

```powershell
C:/Users/USER/miniforge3/python.exe -B -m scripts.library.audit_training_stills --ffmpeg D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe --max-new 5
```

实际重复校验（退出 0，约 0.43 s）：

```powershell
C:/Users/USER/miniforge3/python.exe -B -m scripts.library.audit_training_stills --ffmpeg D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe --max-new 0
```

首批重复校验全部报告 `still_reused`，没有重写或新增图片。补齐批报告 5 个 `still_reused` 和 5 个 `still_created`；运行前后逐文件核对首批 5 张 JPEG 与 5 个收据的 SHA-256 和 mtime_ns，全部相同。最终只读复核全部 10 张 JPEG 的 SHA/字节数及两处 `training_only` 与收据一致，目录恰有 20 个文件，无遗留批次锁或 `.part`。不重新编码既有图像来挑选更理想的球场画面。

独立只读审阅未发现本轮预算、路径、覆写或 PTS 绑定方面的具体 P1/P2。此项是 R-04a 的有限画面证据，不替代整场解码、标注语义或训练效果验收；本轮没有判断击球、身份、标注边界，也没有新增 CSV 关联。
