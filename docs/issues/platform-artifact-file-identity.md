# 产物声明哈希不能代替当前文件身份

日期：2026-09-29。状态：修复及定向工程回归通过；独立实例重启后的真实兼容验证由主任务执行。

原问题：成功任务的general产物声明SHA-A，文件被同长度替换为registry已登记的training_only字节B后，下载用途门禁仍使用声明A，FileResponse随后打开B，可能返回200。预览专用媒体、索引和缩略图入口也必须遵守同一身份边界。

修复：worker在既有实际哈希入口捕获路径及文件句柄身份，成功finish同一事务写入runtime的`artifact_identities`专用表，绑定job、attempt、artifact_id、相对路径、实际SHA及大小；失败/取消不发布证明。任务JSON或Artifact中的自称proof字段不授予信任。preview SQLite使用关闭连接的上下文，退出后才计算产物hash。

下载有证明时只核对身份、当前用途与registry，不重复Web哈希大文件。没有证明的旧产物只允许≤8,000,000字节有界校验；先对实际SHA做用途检查，再核对声明，且只保存哈希时捕获的身份。旧大产物返回409 `ARTIFACT_REVERIFY_REQUIRED`，须后台重新生成/验证。Windows/Python可能把path stat的ctime表示为创建时间、fd stat的ctime表示为变更时间，故两种五元组分别保存/比较，跨API只核对dev/inode/size/mtime，不丢弃ctime。

通用下载及preview media/index/thumb共用校验。下载在真正打开文件时再次复核，后续Range/整文件流读取该句柄并检查读取中的变化，避免route核对后又按路径打开另一份文件。原片媒体保留既有source身份路径；导入缩略图采用同一有界实际哈希及句柄下载边界。

新增`tests/platform/test_artifact_identity.py`有29项PASS：同长度替换为training字节、同inode/大小/mtime原地改写、声明proof伪造、旧小文件一次升级、旧大文件不Web哈希、preview所有入口、route后替换、成功/失败/取消发布边界、双ctime、哈希后不冒取新stat、SQLite关闭、多Range/HEAD/no-store。输入均为临时合成字节，不是视频解码或模型实测证据。最后合跑此文件与`test_preview_api.py`、`test_runtime.py`、`test_api.py`、`test_source_identities.py`、`test_source_identity_api.py`、`test_production_usage.py`：143 PASS、1 SKIP（原环境条件）；最终全套由主任务统一执行。
