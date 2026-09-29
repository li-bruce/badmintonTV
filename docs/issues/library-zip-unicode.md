# Fine-Badminton ZIP Unicode Path 兼容修复

## 问题与真实输入

2026-09-29，主任务在已完成下载并通过官方 MD5 的 Fine-Badminton.zip 中发现：两个 `[4K50FPS] BEST MS MATCH！Lin Dan vs Lee Chong Wei _ 2011 World Championships` 成员使用 legacy 名字节、`flag_bits=0` 和 Info-ZIP Unicode Path 扩展 `0x7075`。本机 Python 3.12.11 的 `ZipInfo.orig_filename` 是 CP437 解码后的 `úí`，而 `filename` 经合法扩展得到全角 `！`。旧提取器将任何 `orig_filename != filename` 视为有害归一化，因此拒绝了合法 CSV，并保留失败收据，没有写入 partial。

原包位置：`D:/video/data/training/fine-badminton-2026-zenodo-20292976-v1.0/source/Fine-Badminton.zip`。主任务提供的已验证标识：6,455,837,331 B，官方 MD5 `cb3fcaca0ae9b08c564ac2a19ae4e7a0`，本地 SHA256 `a3518f52d66dd6c5d2b01ce1347de8e589516ccc24a72aae818fea64e0b04439`。本修复只读名字和目录元数据，没有重新散列或提取真实载荷，也没有向 D 盘写入。

## R-04a 本次工程断言

- 只支持单一 `0x7075`，版本必须为 1，CRC32 必须绑定该头部的原始名字节，Unicode 名必须为非空、严格有效 UTF-8。
- 原名字和 Unicode 名分别检查 NUL、反斜杠、绝对路径、驱动器/流、空路径段、`.`、`..` 和长度限制；不猜测 legacy 编码，不执行 Unicode NFC/NFKC 或路径归一化。
- 在 `ZipFile` 构造前检查中央目录及本地文件头。两者原名字节和 UTF-8 标志必须一致；本地头如果含 Unicode Path，其合法 canonical 名必须和中央目录一致。允许格式所容许的中央目录有 Unicode Path、本地头没有该扩展。
- canonical 名全目录唯一。调用者必须选择 canonical 名，不能把 CP437 原名作为第二个隐含别名；标准库打开成员时原有 local/central 原名校验继续保留。
- ZIP64、STORED/DEFLATED 白名单、CRC、实际字节上限、源 ZIP 前后 SHA、配额和不覆盖输出规则保持不变。

## API 与恢复

`inspect_zip()` 的 `name` 现在明确表示经过校验的 canonical Unicode 名；新增 `raw_name` 保存头部按 UTF-8 标志或 CP437 解码的原名，`unicode_path_extra` 表明有经过 CRC 绑定的 Unicode Path 映射。普通 ASCII/UTF-8 名字的 `name` 保持原值。`extract_member()` 签名不变，选取 `item["name"]`，收据 `member` 同时保留上述字段。

训练脚本继续使用 `name` 计算短文件名，因此两个正确 Unicode 名得到新的短路径。此前失败的 CP437 CSV 收据应原样保留，不自动删除/覆盖；此前成功的三个 ASCII 成员沿用原路径和收据，经原有 SHA 核验复用。

## 实际验证

| 验证 | 输入/方法 | 预期及实际 | 结果 |
|---|---|---|---|
| 本地完整回归 | `python -B -m unittest discover -s tests/library -p test_archive.py -v`；临时目录小 ZIP | 原 32 项和新增 10 项全部通过，42/42，1.958 s，无跳过 | PASS |
| Unicode 合法输入 | 精确 legacy 字节 + 合法中央/本地 Unicode Path；中央单独扩展；普通 UTF-8/NFD | canonical 提取、CRC/hash 成功，原 ZIP 不变；没有无请求的名字归一化 | PASS |
| Unicode 边界 | 错 CRC/版本、无效 UTF-8/空/截断、重复扩展、NUL/穿越/反斜杠、原名洗白、本地/中央冲突、重复 canonical 名、原名别名调用 | 在读取载荷前拒绝；结构性问题在 `ZipFile` 构造前拒绝 | PASS |
| 真实包只读元数据 | `inspect_zip()`；mock `ZipFile.open` 为抛错，禁止打开真实载荷 | 24 项（22 文件 + 2 目录），总展开 6,467,329,596 B；两个 Unicode 映射正确，本地/中央检查通过；源 ZIP size/mtime 未变 | PASS |
| 真实恢复提取/探测 | 由主任务按原配额、双 SHA 和不可覆盖规则恢复 | 本次修复任务未运行真实提取，不代替完整数据验收 | NOT_RUN |

本地回归只证明解析与存储边界；R-04a 全部要求仍由主任务的实际完整解压、哈希、媒体与标注核验决定。

## 后续真实恢复（library 主执行，2026-09-29）

修复提交 `e8331d318c70938bd6b8d307ba2e3fe1edce056b` 后，完整恢复命令退出 0：22/22 成员提取且 SHA/CRC/字节上限验证通过，包含 10 MP4、10 CSV、README、LICENSE。原三个成功成员通过哈希后复用，原 Unicode 失败收据保留。成功收据首次 09:43:01.483967 UTC、最后 09:53:18.307969 UTC；该 616.824 秒跨度包含修复暂停。恢复新写 19 项的收据时间跨度为 153.333 秒，不能视为纯解压计时。每成员前后源 ZIP SHA 检查均保持 `a3518f52d66dd6c5d2b01ce1347de8e589516ccc24a72aae818fea64e0b04439`。

`extracted-sources.v1.json` 的 `complete=true`，展开原件 6,467,329,596 B；加原 ZIP 共 12,923,166,927 B。提取成功不等于媒体探测或标注语义已全部通过，后两项独立记录于 `docs/library/FINE_BADMINTON_2026_DATA_REPORT.md`。
