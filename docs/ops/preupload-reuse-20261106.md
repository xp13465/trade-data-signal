# 覆盖前备份：同日相同内容复用（2026-11-06）

本次只优化 `_backup_overwritten_keys` 的同日重试。源对象仍是 A、本地准备上传 B，
而当天 A 的备份已完成时，重试可复用该备份，省去再次 GET A、PUT A。
这不代表 #365 已完成，也不代表每夜 282MB 中转或总耗时减半：跨日期第一次备份照旧。
没有生产部署、真实 R2 验证或生产恢复结论。

## 判据与回退

沿用现有备份 HEAD，只增加 `with_len=True`，不新增请求。新复用分支要求：

- 源对象与当前备份的 HEAD 都返回 200。
- 两端 ETag 都是小写 32 位十六进制，或一对双引号包裹的同样形式；规范解引号后相等。
- 两端长度都有效且相等：只接受非负 Python `int`（不含 `bool`），或 ASCII 数字字符串。

布尔值、负数、缺失值、浮点数（包括 NaN/infinity）、带符号、小数、空白及畸形字符串，
都不能授权新复用。Multipart、weak ETag、畸形引号、未知摘要也回到原有中转流程。
未知条件不删除备份、不把对象存在当内容证明、不把 multipart ETag 当整包 MD5。
原中转对某些畸形源长度仍可能抛异常；本次没有改变其整段异常处理。

Cloudflare 说明，multipart 完成对象的 ETag 由分片摘要组合并带分片数量后缀，
区别于单 PUT；因此不能直接与整包 MD5 比较。
见 [R2 Upload objects / ETags](https://developers.cloudflare.com/r2/objects/upload-objects/)。
非 multipart 对象默认包含 MD5 checksum，HTTP ETag 可有规范双引号。
见 [R2 Workers API reference / Checksums、httpEtag](https://developers.cloudflare.com/r2/api/workers/workers-api-reference/)。
这里沿用仓库现有 S3 单 PUT ETag/MD5 合同，没有将 Workers 的 checksum 属性冒充 S3 HEAD 字段。

## 与 #176、manifest、续传的关系

#176 原判据逐字保留：当天备份存在，且源 ETag 与本次本地指纹一致，即跳过。
其意图是待传内容与源相同时“覆盖无损失”，不是“备份对象等于当前源”的证明；
已有备份可能保留更旧的版本。A 档指纹是原始字节 MD5，B/C 档可能是规范化 JSON 指纹，
不能将所有本地指纹都宣称为 wire MD5。新分支只比较远端源与备份，不依赖本地指纹。
当天备份缺失时，即使源与本地相同，仍创建备份。

本路径没有旧备份内容 manifest 或持久 proof。`r2_export_proof` 验证新导出产物，
state/checkpoint 记录新主上传的完成情况，都不能当作旧备份证明。
本次不新增或消费这些 proof；缺失、损坏的旧 proof 不能授权跳过。
每轮重新 HEAD；源或备份对象的摘要/长度变化、对象消失，均不能命中新复用分支。
HEAD 后的并发变更仍可能发生，不提供快照隔离。

已有 `_incremental_upload` 先按 checkpoint 剔除已完成的主上传文件，再执行覆盖前备份。
当旧源 A 的备份完成而主上传 B 失败时，state 保留旧值、marker 残留，下一轮仍可进入备份，
本次优化使该路径复用 A。主上传没有成功记录时，不因旧备份存在就标记主上传成功。

## 保持的恢复与失败合同

源 HEAD/GET 仍使用 `BUCKET`、原 key；目标仍使用 `BACKUP_BUCKET`、
`pre-upload/<本机日期 YYYYMMDD>/<原 key>`。默认源为老账号 `signal-data`，
备份为新账号 `signal-backup2`，实际路由继续由 `_route_bucket` 决定。
不跨 bucket、account、日期、key 搜索或复用对象；保留期与 prune 不变。
同一天多次内容变化仍覆盖同一个备份 key，保留的是当时的旧版本，不是完整版本历史。

返回值仍为 `(copied, skipped, failed, samples)`。复用计入 `skipped`；
结构化完成日志、失败计数、样本上限、8 线程、整批备份后主上传的顺序均保留。
减量提示明确区分“同内容备份可复用”与“覆盖无损失”。

既有失败行为没有收紧：源 HEAD 非 200 直接返回；捕获到的逐 key 失败计数；
整段 `Exception` 由调用方记 `failed=-1` 后继续主上传，预算 `SystemExit(124)` 不在该兜底内。
因此不能宣称“备份失败一定阻止覆盖”或事故已经关闭。

现有 multipart 源或目标的 P6 只验长度，不能证明完整内容相等。
测试给出具体反例：备份被写成同长度错误字节，仍可能报告 `copied=1`。
本次保持该既有合同，并禁止用这种长度证明授权新复用。

中转及复用针对 HTTP 原始字节，不压缩、解压或重编码；gzip 测试验证取回字节相等，
并可解回旧内容。现有链没有完整保存源 `Content-Encoding` 等 metadata，
本次不承诺 metadata 还原，也没有把内存恢复当成生产恢复。

## 离线验证

新增 `scripts/tests/test_codex_preupload_reuse_20261106.py` 使用相对路径读取真实源码，
仅 AST 编译指定函数，不导入 uploader 顶层，不加载 `.env`。
测试先验证 socket/DNS/HTTP/subprocess/notify 陷阱，再显式安装按 bucket/key 隔离的内存传输。

新增 59 个用例和原有 #237 的 12 个用例定向执行通过。覆盖同日 A→B 重试、严格长度/ETag、
错 hash/大小/日期/bucket/key、multipart、HEAD/GET/PUT/P6 失败、#176 原语义、gzip 恢复、
实际增量入口失败后保留 state/marker 并重试，以及既有失败不阻断与 multipart 长度证明上限。
主上传入口与底层 multipart 传输显式打桩，没有真实 HTTP、R2、通知、SSH 或业务 CLI。

新增测试可单独运行：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -B -m pytest --noconftest -q \
  -p no:cacheprovider scripts/tests/test_codex_preupload_reuse_20261106.py
```

本轮旧 #237 测试直接使用仓库测试文件，`upload_r2` 绑定为从仓库实际文件 AST 编译的函数模块，
通过 `--noconftest` 隔离现有 `.env` 垫片。其桩已经支持 `with_len`，旧测试和断言未改。
新测试另用“关闭新复用分支 / 当前分支 / 再关闭”的行为负控验证 GET/PUT 为 2/1/2，
三者恢复旧字节一致；该负控没有硬编码旧提交，也不冒充历史源码。
本地证据另外把已审 patch 真反向应用到 `/tmp` 副本，并核对撤回字节等于原基线。

环境未安装 Ruff/Flake8；本轮仅做指定 Python 文件的标准库编译/缩进检查，
统一专用 lint 与全量测试留给父侧。本轮未运行全量 `scripts/tests` 或 FAPI 内存测试，
已知 NOT_ALL_GREEN 不变。未 commit、push、部署、修改角色或任务状态索引。
