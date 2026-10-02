# R2 mac-backups/2026-10-01/ 取回本机 + md5 对账 PASS + 删 R2(2026-10-02)

> 背景:#151(r2-backup-bucket-capacity-20261002.md)指认该前缀为备份桶超免费额度**唯一元凶**:10.171 GiB / 86 对象,占备份桶 71.1%,无 prune 只增不减。
> 本次执行完整落地:「取回本机 → md5+size 对账 → **86/86 全 PASS** → 逐 key 删 R2(仅此 86 个)→ 删后确认前缀空」。
> 数据全部安全落位本机:~/code/trade-data/data/mac-backups-20261001/(git 仓外,10.171 GiB),恢复路径见 §⑤。

## ① 测速实测(第 1 步,分叉判定)

- 对象:挑 8 个 50-150MB 中等文件(sentiment_*.db,81.7–99.4MB),8 路并发 GET。
- 往返:总 725.5 MB,耗时 224.5s,**聚合 3.23 MB/s**;8/8 成功。
- **分叉判定:聚合 ≥ 3 MB/s → 走全量下载分支**(阈值见任务书;2.0 版任务书阈值 3MB/s)。
- 若 <3MB/s 本应停止且不删 R2 —— 本次未触发该分支。

## ② 全量下载结果(第 2 步)

| 项 | 值 |
|---|---|
| 对象 | **86/86 成功**(测速已下 8 个跳过,新下 78) |
| 总字节(锚点日志求和) | **10,920,869,888 B = 10.171 GiB** |
| 全量耗时 | 869 s |
| 全量聚合吞吐 | **11.15 MB/s**(高于测速段,见 §⑥ 诚实标注) |
| 落点 | `~/code/trade-data/data/mac-backups-20261001/`(86 文件,du 10.171 GiB) |

文件名保持 key basename(`mac-backups/2026-10-01/<name>`,strip 前缀)。下载过程逐 20 个输出进度,无失败项。

## ③ md5 + size 对账(删除唯一前提,第 3 步)

- 锚点:`/tmp/mac_backups_upload_log_20261001.txt`(86 行,为 10-01 上传时逐文件记录的 size + 本地 md5)。
- 方式:本地 86 文件逐文件算 md5,与锚点日志逐行比对 size + md5(日志字段列位:`key|size=N|md5=HASH|status=...`)。
- **结果:PASS 86/86,MISSING 0,MISMATCH 0**。
- 结论行:**对账 86/86 PASS ⇒ 已删 R2**(逐文件全比对,非摘要抽样)。
- 复现:见 §⑦。

## ④ 删除前后对比(第 3.5 步)

| 时点 | 对象数 | 字节 |
|---|---|---|
| 删除前(首次 List) | 86 | 10,920,869,888 (10.171 GiB) |
| 删除后(重新 List) | **0** | 0 |

- 删除方式:对**明确列出的 86 个 key** 逐个 `s3_request("DELETE", key, bucket=BACKUP_BUCKET)`,86/86 全部 status=204。
- **无前缀批量删除逻辑、未触碰 `mac-backups/` 以外任何前缀**(含 backup/ weekly/ monthly/ large-json/ claude-backup/ 均保持原样)。
- 删后重新 List 该前缀确认 = 0 对象,与任务预期一致。

## ⑤ 恢复路径(一行命令,可逆性)

数据已完整在本机,随时可逆:

```bash
# 逆向恢复:把本机这份归档原样放回 R2 同前缀(signal-backup/mac-backups/2026-10-01/)
python3 docs/scripts/restore_mac_backups_r2.py put-restore

# 或直接使用本机文件(86 个 .db 快照,按日期可直接取用)
ls ~/code/trade-data/data/mac-backups-20261001/
```

文件为每日 sentiment / etf_national_team DB 快照;若后续需要回滚某日数据,直接用对应 `.db` 即可,无需依赖 R2。

## ⑥ 诚实标注(异常 / 差异)

1. **与 10-01 历史慢速实测差异**:10-01 家清时记录「本机→R2 下行极慢,>25min/150MB(≈0.1 MB/s)」;本次实测聚合 3.23 MB/s(测速段)、11.15 MB/s(全量段),均远快于该记录。推测 10-01 为临时网络状况/单连接限速,非恒态;本次多连接并发未复现瓶颈。此差异不改变本次「已取回+对账 PASS+已删」结论(删除前提是本地对账,与速度无关)。
2. **测速段单连接不均**:8 文件完成时间 73s/83s/112s/115s/125s/127s/189s/225s,前段快后段慢,疑连接抖动,不影响正确性。
3. **全量速率高于测速段**(11.15 > 3.23 MB/s):可能因测速段 8 个大文件同步起步瞬时拥塞、全量段大小文件混合节奏更平滑,不做强结论。
4. **对账客观性**:md5 为逐文件全量计算,与锚点日志逐行比对,非抽样。

## ⑦ 复现(脚本 + 命令)

脚本:`docs/scripts/restore_mac_backups_r2.py`(复用 `scripts/upload_r2.py` 的 s3_request/SigV4,不新写凭证明文)。

```bash
python3 docs/scripts/restore_mac_backups_r2.py list          # List 前缀对象(验证对象数/字节)
python3 docs/scripts/restore_mac_backups_r2.py speedtest     # 8 并发测速(决定全量 or 停)
python3 docs/scripts/restore_mac_backups_r2.py download      # 8 并发全量下载(本地已有且 size 匹配自动跳过)
python3 docs/scripts/restore_mac_backups_r2.py verify        # md5+size 对账锚点日志(删除前置)
python3 docs/scripts/restore_mac_backups_r2.py delete        # 仅 86/86 PASS 才删(内置 verify 前置,非 PASS abort)
python3 docs/scripts/restore_mac_backups_r2.py put-restore   # 恢复:本地传回 R2 同前缀
```

安全设计:delete 子命令强制执行 verify,对账未全 PASS 直接 abort;删除对象由锚点日志生成的明确 key 列表限定,杜绝前缀通配误删。密钥经 upload_r2 的 load_env() 从 .env 读取,本脚本不接触凭证明文。