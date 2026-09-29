# FFmpeg 8.0.1 兼容环境（2026-09-29）

用途：主任务的真实 NVENC probe 报告 FFmpeg 9.0.2 需要 API13.1，而当前驱动提供API13.0。保持驱动和原9.0.2安装不变，独立准备较早官方构建。此子任务只验证CPU，**没有调用GPU**；R-03a的硬件兼容性和真实对照须由主任务通过共享GPU租约另验。

安装后的独立硬件验证已完成：同构建CPU/NVENC各8个真实渲染job技术PASS，GPU窗口与租约已释放。见`ROUND_2026-09-29_RESULTS.md`；仓库环境JSON另增`post_install_hardware_validation`链接证据，不覆盖下述原始CPU安装检查。当前NVENC实际可用不代表默认FFmpeg9也已兼容，也不代表整条处理链都运行于GPU。

## 官方来源与完整性

- [Gyan 官方 GitHub 8.0.1 发行](https://github.com/GyanD/codexffmpeg/releases/tag/8.0.1)，对应[FFmpeg 源码 894da5ca7d](https://github.com/FFmpeg/FFmpeg/commit/894da5ca7d)，发布日期2025-11-20。
- [essentials ZIP](https://github.com/GyanD/codexffmpeg/releases/download/8.0.1/ffmpeg-8.0.1-essentials_build.zip)：106,259,850 bytes。[官方资产列表](https://github.com/GyanD/codexffmpeg/releases/expanded_assets/8.0.1)和GitHub API asset `318696612` 的SHA-256均为 `e2aaeaa0fdbc397d4794828086424d4aaa2102cef1fb6874f6ffd29c0b88b673`；实际完整下载再次校验一致。
- 包内README实际依赖行：`ffnvcodec n13.0.19.0-2-g876af32`。该README SHA-256：`a0e976df3cf1d781264c41db8ee3421978c1278be92ed00edbc96337529670be`。
- [FFmpeg nv-codec-headers 13.0.19.0 官方README](https://raw.githubusercontent.com/FFmpeg/nv-codec-headers/n13.0.19.0/README)声明对应SDK13.0.19，Windows最低驱动570.0。当前591.86满足这项静态依赖声明；这**不替代实际NVENC执行成功证据**。
- 构建为GPLv3，完整原包许可/文档保留，二进制不提交Git。没有更改公共Conda、系统PATH、驱动或原9.0.2环境。

## 路径与实测

环境报告：`environments/render-runtime-compat.json`。FFmpeg及ffprobe绝对路径在 `checks.ffmpeg` / `checks.ffprobe`：

```text
D:\video\runtime\render\compat-8.0.1-20260929T091434Z-72fe981b\ffmpeg-8.0.1-essentials_build\bin\ffmpeg.exe
D:\video\runtime\render\compat-8.0.1-20260929T091434Z-72fe981b\ffmpeg-8.0.1-essentials_build\bin\ffprobe.exe
```

外部原始环境报告在同一 `compat-8.0.1-20260929T091434Z-72fe981b/environment.json`，保留安装时原件。仓库JSON的原始字段与其一致，另附 `record_scope` / `audit` 说明。`status: ready`、`gpu_used: false`、`gpu_probe: not_run` 仅描述本次安装器及CPU验证，不描述之后主任务持租约执行的基准。实际执行`libx264 -threads 2`的1秒合成烟测，H.264 yuv420p / AAC48k stereo / 360×640；`subtitles`与系统Microsoft YaHei字体可用；ffprobe验证、完整解码均PASS。代理`view_image`查看生成的`chinese-test.png`，中文完整、无缺字方框；人工观看仍pending。合成CPU烟测不能作为真实动作或R-03a硬件验收。

## 安装与容量记录

```powershell
& D:/video/runtime/platform/env/Scripts/python.exe scripts/render/prepare_compat_runtime.py --install --download-workers 8
```

安装器复用 `prepare_runtime.py` 的容量统计、安全ZIP解压和CPU验证，不修改其9.0.2固定配置。峰值预留870,000,000 bytes，含下载200MB、解压650MB、QA20MB；runtime/render配额5GB，共享700GB，物理空间另留256MB。安装期间使用同一个 `.prepare-runtime.lock` 独占owner，不并行两个安装器。

首次授权进程启动返回TurnAborted，无写入。第二次串行下载过慢，按主任务授权验证锁中PID26160及命令行后精确停止；保留12,582,912-byte部分ZIP和`cancelled-for-range-retry.json`，未覆盖/删除。其目录是 `runtime/render/compat-8.0.1-20260929T090900Z-38df180f`。该部分ZIP未完成完整性核验、未解压，不是可执行环境；记录状态为主动 `cancelled`，不能记为8.0.1的CPU/GPU兼容失败。

独立的真实失败是先前FFmpeg9的NVENC初始化：`D:/video/render/jobs/job-6ddb2881f44048eda5f306f741a3b035/attempt-1/nvenc-probe.log` 明确记录 `Required: 13.1 Found: 13.0` 及最低驱动610.00；同目录 `backend.json` 为requested=nvenc、effective=unavailable、无CPU回退。详见[失败记录](../issues/render-nvenc-driver-api-mismatch.md)。FFmpeg9安装及失败job保留，8.0.1后续基准须单独记录，不覆盖此失败。

随后8路请求**同一个官方资产**，逐路检查HTTP206、精确Content-Range/Content-Length、实际字节数，写单个预分配ZIP的互不重叠区间，没有分块合并双份。重定向只允许固定GitHub发行路径及该仓库的`release-assets.githubusercontent.com`交付路径；HTTPS、无用户信息。九项纯URL允许/拒绝检查PASS。旧部分下载加新完整ZIP共118,842,762 bytes，小于200MB实际下载上限。最终完整SHA验证后才解压，实际解压310,354,584 bytes；超过API13.0的README依赖会立即停止且不调用GPU。

安装结束时（2026-09-29 09:15 UTC）的容量快照为runtime/render 873,307,783 bytes（随后增加几KB报告），包含原9.0.2、新8.0.1及保留partial；共享17,264,882,696 bytes，D盘剩余950,858,764,288 bytes。`reservation-completed.json` 于09:15:37 UTC记录本次目录416,679,776 bytes、reserved_bytes=0。以上是历史快照，不作为基准运行后的实时容量。没有复制library原片。

09:33 UTC的报告核对只读取小型JSON、README、LICENSE和失败日志，并查看文件大小元数据：原始环境JSON一致；8段Range记录连续覆盖106,259,850 bytes；完整ZIP及保留partial的实际文件大小与记录一致；许可和编译依赖行一致。未重新执行FFmpeg、GPU或大文件哈希，也未扫描目录容量，避免干扰当时进行的NVENC基准。此报告仅说明可重复运行的兼容候选和CPU验证，硬件对照结果由后续R-03a记录补充。

## GPU归还后的容量快照

主任务确认GPU结束并归还models后，2026-09-29 **09:37:10–09:37:15 UTC**（北京时间17:37）执行一次只读文件元数据遍历。89,420个文件条目，无读取错误、无扫描中消失文件；不跟随9个已列出的WSL/reparse目录链接，避免重复计数。精确子目录明细在JSON的 `audit.final_capacity_scan.directories_bytes`。

| 目录 | 可见逻辑文件bytes |
| --- | ---: |
| `D:/video/data` | 5,179,148,376 |
| `D:/video/models` | 4,546,771,618 |
| `D:/video/platform` | 196,602,848 |
| `D:/video/render` | 639,633,036 |
| `D:/video/runtime` | 11,824,513,927 |
| `runtime/models`（包含在runtime） | 8,658,113,200 |
| `runtime/platform`（包含在runtime） | 1,048,280,806 |
| `runtime/render`（包含在runtime） | 873,315,597 |
| `runtime/shared`（包含在runtime） | 1,244,804,324 |
| `runtime/render`下旧9.0.2目录（包含在render runtime） | 444,051,922 |
| `runtime/render`下完整8.0.1目录（包含在render runtime） | 416,679,912 |
| `runtime/render`下取消/保留partial目录（包含在render runtime） | 12,583,763 |
| `D:/video`全局可见总量 | **22,386,669,805** |
| D盘物理剩余 | **945,599,983,616** |

render低于40GB，runtime/render低于5GB，全局可见量低于700GB；runtime/render加其他owner固定额度645GB也低于700GB。固定额度单独用于逻辑上限，不重复加到实占，也不作为物理活动预留。外部WSL原生环境仍受对应固定额度约束，本表不把不可见路径虚报为已测量。

这是**非原子快照**：CPU质量检查当时仍在render owner锁内写入，主任务预计该工作约新增400MB，部分已包含在上表；render与物理free均可能继续变化。此后不重复全局扫描，质量完成后由主任务补render目录差值。扫描未修改/删除任何媒体，原始安装容量字段保留历史值，最终快照另存audit。
