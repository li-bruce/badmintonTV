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

可选归档API：`packages.library.archive.inspect_zip(path)`只读有界中央目录（最多10,000项/16MiB）；`extract_member(archive, member_name, relative_path, quota=..., max_bytes=..., expected_archive_sha256=...)`只流式提取一个明确普通文件。原ZIP必须位于data owner并保留；禁路径穿越、链接/加密/重复成员，不覆盖目标；`.extract.part/.extract.json/.lock`保留失败与锁信息。首次实现不支持ZIP64中央目录、多卷或尾随数据，不提供无界extractall。本轮没有真实ZIP取回/解压，不能把本地ZIP测试算真实素材成功。
