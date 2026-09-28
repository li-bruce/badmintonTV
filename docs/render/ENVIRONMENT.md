# Render runtime 环境记录

核验与安装日期：2026-09-28。代码与本记录属于 render；不修改系统 PATH、Windows 驱动、Conda base、公共 Conda 或其他模块环境。无服务和端口，无 GPU 使用。

## 来源与版本

- [FFmpeg 官方下载页](https://ffmpeg.org/download.html)明确列出 [Gyan Windows builds](https://www.gyan.dev/ffmpeg/builds/)；此次固定安装 `9.0.2-essentials_build-www.gyan.dev`，没有追随滚动 latest URL。
- 下载：[固定 essentials ZIP](https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip)，对应[供应方 SHA-256](https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip.sha256)。下载前读取官网校验值，与脚本固定值一致才继续；流式下载后再次校验实际 ZIP。
- SHA-256：`60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba`；ZIP 实际 `114,768,076` bytes，解压 `329,221,735` bytes。
- Gyan 此构建为静态 GPLv3；构建命令有 `--enable-gpl --enable-version3 --enable-libx264 --enable-libass`。FFmpeg 一般许可与具体启用组件的区别见[官方许可说明](https://ffmpeg.org/legal.html)。此次使用外部 CLI，不把二进制提交 Git；后续分发此二进制须另落实相应源码、通知与许可义务。
- 供应方关联的源代码：[FFmpeg commit 946fcce07b](https://github.com/FFmpeg/FFmpeg/commit/946fcce07b)。原包内许可与文档全部保留。
- 安装器仅用已有 `C:\Users\USER\miniforge3\python.exe`，Python 3.12.11 标准库；未向此环境安装包。无新技能或 MCP 插件安装。

## 可调用路径

```text
FFmpeg:  D:\video\runtime\render\install-20260928T151048Z-8cca16ed\ffmpeg-9.0.2-essentials_build\bin\ffmpeg.exe
FFprobe: D:\video\runtime\render\install-20260928T151048Z-8cca16ed\ffmpeg-9.0.2-essentials_build\bin\ffprobe.exe
原始安装报告: D:\video\runtime\render\install-20260928T151048Z-8cca16ed\environment.json
仓库环境报告: environments/render-runtime.json
```

平台/renderer 从环境报告的 `checks.ffmpeg`、`checks.ffprobe` 读取管理员指定二进制路径；不依赖全局 PATH。FFmpeg、ffprobe 各自 SHA-256 亦在该 JSON 中。仓库版另追加代理查看中文帧记录；安装时原始报告保留原样。

## 受控安装与容量

PowerShell 命令，cwd 为仓库根目录：

```powershell
# 只检查，不写入或下载
& C:\Users\USER\miniforge3\python.exe scripts/render/prepare_runtime.py

# 本次实际运行；写入 D 盘须使用已授权的外部目录权限
& C:\Users\USER\miniforge3\python.exe scripts/render/prepare_runtime.py --install --report environments/render-runtime.json
```

安装器唯一运行时写入根是 `D:\video\runtime\render`，总配额 `5,000,000,000` bytes。下载上限 `200,000,000`，解压上限 `650,000,000`，验证与记录预留 `20,000,000`，本次预留峰值 `870,000,000` bytes。检查 ZIP 中声明的解压总量、条目数、路径穿越、Windows 路径、符号链接和重名，逐文件独占创建；实际流量和解压量都有上限。

通过 `.prepare-runtime.lock` 原子独占创建串行化本 owner 内安装；锁内记录 PID 和预留量，结束释放本进程创建的锁。每次使用唯一 attempt 目录，不覆盖/删除已有安装、包或部分文件。`reservation.json` 为起始快照，完成后新增 `reservation-completed.json`；活跃预留以存在的 `.prepare-runtime.lock` 为准。失败保留部分目录及 `failure.json`，不擅自清理。

共享容量检查统计 `D:\video` 已用，并保守再预留其余 owner 的完整 `645GB` 分配上限（涵盖本次无法直接统计的 WSL 原生环境与活跃预留）。这会重复计算其余目录已用量，在机器接近额度时可能保守阻止安装；不会借用50GB安全余量。物理可用空间也同时预留其他 owner 的上限及1GB安全空间。所有 owner 各自遵守固定配额是并发保证的一部分。

本次安装前共享已用 `1,664,079,784` bytes、D 盘可用 `966,360,342,528` bytes。验证后本 owner 约 `444,047,356` bytes（随后仅增加几KB报告），共享约 `2,290,213,041` bytes、D盘可用 `965,735,444,480` bytes。含 ZIP、全部解压文件、合成烟测MP4/PNG/SRT/日志；不复制 library 原片。

重复安装必须指定新的、尚不存在的 `--report` 文件，否则拒绝；成功安装可以直接复用，不必重复下载。脚本要求 Windows / Python 3.12+。起初普通预检遇到公共 Conda 包中的 WSL `libcrypto.so` 链接 WinError 1920，已改为 `lstat` 统计链接本身，不跟随外部链接；重新预检与实际安装均成功。此失败发生在下载和写入前。

## 实测结果

1. `ffmpeg -version`、`-encoders`、`-filters` 验证 `libx264`、原生 `aac`、`subtitles` 可用。
2. 用 lavfi 生成1秒 `360×640 / 30fps / H.264 yuv420p / AAC 48kHz stereo`，CPU `libx264 -threads 2`；字幕为“网前击球 · 中文字幕测试”。输出仅是 runtime 技术烟测，不是业务样片或真实动作识别证据。
3. `ffprobe` 验证 H.264/AAC 双流与 `1.000000` 秒时长；FFmpeg 全程 `-f null -` 解码，无错误。
4. libass 日志实际选择 `MicrosoftYaHei`。字体来自现有 `C:\Windows\Fonts\msyh.ttc`，亦检测到 `simhei.ttf`；未复制/分发字体文件。用 `view_image` 查看首帧，中文完整可读、无缺字方框。此项为代理视觉检查，用户观看验收仍待做。

验证文件均在上述 attempt 目录：`runtime-smoke.mp4`、`runtime-smoke.log`、`chinese-test.srt`、`chinese-test.png`。真实素材、多段时间线、慢放音画同步和1080×1920业务输出由 render 主流程另验，不由此次 runtime 烟测替代。NVENC 构建支持存在，但未启用/实测，不声明已验证硬件编码。
