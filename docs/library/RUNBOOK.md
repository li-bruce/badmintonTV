# Library 运行与交接

在仓库根目录运行；Python≥3.11、纯标准库，无pip/Conda安装。不启动网络服务、不使用GPU。Windows正式存储根 `D:/video`；原片只读引用。

## 小样

```powershell
$ffbin = 'D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin'
python -m scripts.library.acquire_small_sample --ffprobe "$ffbin/ffprobe.exe" --ffmpeg "$ffbin/ffmpeg.exe"
```

固定上游版本与视频SHA见 `configs/library/small_sample.json`。该脚本先预留50MB，单下载另外预留字节限额与小型记录空间；包含4个视频、2份QA JSON、1份原CSV和许可说明，不下载全集。`--download-only`可先完成下载但不发布未探测Asset。重复运行验证已有文件的hash/来源凭据，复用匹配的探测结果，不重新复制原片。

默认目录：

- `data/raw/finebadmintonbenchmark`：原mp4、单下载凭据。
- `data/annotations`：原QA/CSV和各自license/README。
- `data/probes`：每个视频的probe JSON与完整PTS JSONL。
- `data/handoff/assets.v1.json`：正式Asset清单；平台导入入口，models/render只读。
- `data/handoff/annotations.v1.json`：原标注条数、字段与小样QA关联，明确未做Event转换。
- `data/handoff/downloads.v1.json`：来源URL、大小、SHA、下载状态与探测错误。
- `data/handoff/splits.v1.json`：持久SHA→match与match→split约束。
- `data/handoff/capacity.v1.json`：owner用量、总量保守账目、活动预留与物理可用空间。

四段的原场比赛映射未核实，统一unknown/unassigned隔离，不能从不同video_uid推断独立比赛；原始QA不是本项目细动作真值。字幕/计分牌后续只能用于提出待确认球员候选。展示研究视频与具备公开发布许可是两件分别记录的事，见独立问题文件。

## 可复用CLI

```powershell
python -m packages.library quota
python -m packages.library download <https-url> raw/source/sample.mp4 --max-bytes 5000000 --sha256 <publisher-sha256>
python -m packages.library probe data/raw/source/sample.mp4 --ffprobe <ffprobe.exe> --ffmpeg <ffmpeg.exe>
python -m packages.library manifest <asset-array-wrapper.json> handoff/imported-assets.v1.json
python -m unittest discover -s tests/library -v
```

manifest输出只允许data/handoff下JSON文件；禁止覆盖原片、PTS或直接覆盖split登记文件。当前handoff再生成会保留 `data/handoff/audit/` 内的前后hash审计；原片不覆盖。小样CLI固定已核验来源/上限，通用新来源使用download命令另行登记。

共同合同双向检查（此library工作树未复制平台合同源码）：

```powershell
D:/video/runtime/platform/env/Scripts/python.exe -B -m scripts.library.check_contracts --contracts-root C:/Users/USER/Desktop/Program/badmintonTV
```

已用平台原始提交6a3e3deb（main集成为8900958）验证4真实Asset通过Pydantic AssetManifest，以及1个canonical Asset结构fixture通过library校验。fixture的verify_file=False，只验证合同，不将不存在的合成媒体当已下载内容。

下载的 `relative_path` 相对data owner，Asset路径相对共享根，两者不能混淆。CLI参数数组调用，不拼接用户shell。尚不提供平台长Job操作适配；此轮交换端口是受校验的manifest。复用函数：`QuotaManager.reserve`、`download`、`probe_video`、`build_asset`、`write_manifest`；扩展采集任务时先预留解压/派生最大值，当前没有不受限自动解压功能。

## 中断与恢复

HTTP错误、实际字节超限、SHA不符、Range/validator异常全部保留失败记录和part，不自动删除来源文件。正常异常释放本次预留并保留part实占用；进程硬退出会保留lock与reservation，不能把超时当完成。管理员确认该PID已停止后才能显式 `quota.release(reservation_id, reason=...)` 并解除对应lock；无自动按时间清理。部分下载恢复要求源URL、max_bytes、预期hash及响应validator一致；校验失败的part不自动拼接，需人工核实后选择新目标或记录清理动作。

Windows/WSL只能由一个操作系统写本owner账本；模型进程只读原片。对其他owner的不可遍历WSL目录使用整块分配额度上界，不借用50GB安全余量。详情见 `docs/issues/library-windows-wsl-capacity.md`。

## 环境来源

当前解释器：已存在 `C:/Users/USER/miniforge3/python.exe` Python3.12.11，只调用标准库、不更改base。ffmpeg/ffprobe由render任务安装并核验，library只读复用9.0.2 essentials；来源/构建/许可和SHA由render环境清单维护。无新技能、MCP或插件安装；来源研究使用已有web工具及经审批的标准库公开HTTP读取。runtime/library新增环境占用0，额度上限5GB。

## 追加双打小样

```powershell
C:/Users/USER/miniforge3/python.exe -m scripts.library.acquire_doubles_sample --ffprobe D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe --ffmpeg D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe
D:/video/runtime/platform/env/Scripts/python.exe -B -m scripts.library.check_contracts --contracts-root C:/Users/USER/Desktop/Program/badmintonTV --manifest D:/video/data/handoff/assets.doubles.v1.json
```

脚本只接受已核验Drone_BD单片URL与5,857,600 bytes上限，配套CSV固定28,707 bytes，README固定Git提交且最多100KB。批次预留50MB；幂等运行逐一验证原始收据和SHA，无新下载；独立`assets.doubles.v1.json`、`annotations.doubles.v1.json`、`splits.doubles.v1.json`及`doubles-acquisition.v1.json`都在data/handoff，修改留下审计。保留原四片与旧manifest。孤立的新小样PTS保留并显式报错，人工查明后选新的attempt路径，不盲目覆写。

可选归档API：`packages.library.archive.inspect_zip(path)`只读有界中央目录（最多10,000项/16MiB）；`extract_member(archive, member_name, relative_path, quota=..., max_bytes=..., expected_archive_sha256=...)`只流式提取一个明确普通文件。原ZIP必须位于data owner并保留；禁路径穿越、链接/加密/重复成员，不覆盖目标；`.extract.part/.extract.json/.lock`保留失败与锁信息。2026-09-29新增标准单卷ZIP64支持；多卷、扩展ZIP64扇区、前后附加数据仍拒绝，不提供无界extractall。实际公开ZIP验收单独记录，不把本地ZIP测试算真实素材成功。

选中成员只允许`ZIP_STORED`/`ZIP_DEFLATED`。BZIP2、LZMA及其他格式在打开成员前返回`unsupported_compression`，因为固定read长度不能限制这些路径的内部解压分配。详见[内存边界修复](../issues/library-zip-compression-memory.md)。

## 完整训练包（2026-09-29）

```powershell
C:/Users/USER/miniforge3/python.exe -B -m scripts.library.acquire_training_dataset --phase download
C:/Users/USER/miniforge3/python.exe -B -m scripts.library.acquire_training_dataset --phase extract
D:/video/runtime/platform/env/Scripts/python.exe -B -m scripts.library.acquire_training_dataset --phase probe --contracts-root C:/Users/USER/Desktop/Program/badmintonTV --workers 2 --ffprobe D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe --ffmpeg D:/video/runtime/render/install-20260928T151048Z-8cca16ed/ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe
C:/Users/USER/miniforge3/python.exe -B -m scripts.library.acquire_bfmd_annotations
```

前三步依次执行。第四步须等Fine-Badminton ZIP writer退出且官方MD5/大小校验通过，可与后续CPU探测并行；不要同时启动另一个下载writer。这里只列可执行流程，真实完成状态见`docs/status/library.md`与数据验收报告。

完整包固定Zenodo record20292976/v1.0、6,455,837,331 bytes及作者MD5；下载预留40GB，实际字节受精确上限控制。解压总声明上限20GB，另预留声明总额+1GB，单成员提取仍独立预留；共享配额按叠加的保守预留和实占核算。完整原ZIP只读保留，每个成员提取前后校验整个ZIP SHA。本机Windows长路径未开启，因此解压文件用原成员名SHA前24位与扩展名生成短路径；原始名称和精确映射留在ZIP及`archive-inventory.v1.json`，映射碰撞拒绝。

视频完整提取并校验后先登记到`data/training/handoff/training-registry.v1.json`。探测每视频均CPU全解码及全量PTS扫描，最多2个worker，每视频PTS最多2,000,000帧/128MB；每个成功Asset经新合同校验后增量发布到`data/training/handoff/fine-badminton-2026-zenodo-20292976-v1.0.assets.v1.json`。重跑先验证既有清单及原件，再合并成功项，避免中断后缩减已有资产。split保持unassigned，两处usage_scope均training_only，未知注释时基不能生成Event。

`--contracts-root`仅只读复用main新合同；使用既有platform Python提供Pydantic，不安装依赖，不在合同目录写字节码。实际合同提交SHA在验收中记录。

BFMD配置固定到已核对的121项（115活动JSON、1备份、5根源文件），1,825,439,459 bytes，预留2.5GB。文件ID、路径、大小、类型及URL组合的固定SHA验证选择不变；下载只用正常公开Drive入口，遇标准Download anyway页最多读64KiB并正常提交一次。登录、验证码、403/429、异常确认停止批次，保留已验证成果及未尝试数；动态确认UUID不写入收据。作者脚本仅归档，不执行；无视频，不创建Asset、不转换Event。结果为`data/training/handoff/bfmd.annotations.v1.json`。

BFMD稳定清单在中断或重跑时保留已验证文件，启动前校验旧原件、收据及固定源目录；本轮失败、未尝试和中断状态单列于`data/training/handoff/bfmd.acquisition-progress.v1.json`。批次锁阻止两个重跑覆盖同一旧快照。复核修复后完整library回归155/155通过（15.226秒、0跳过），真实数据完成状态仍须读取实际交接记录。
