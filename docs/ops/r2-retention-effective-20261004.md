# R2 `signal-backup` backup/ 保留期「矛盾」真相:代码已上云但从未执行(2026-10-04)

> **一句话结论**:R2 `signal-backup` 桶 `backup/` 现存对象 20260904~20261003(27 日期 × 2 DB = 54 对象)并非「30 天保留出问题」,而是 **14 天保留的代码已上云、但一次都还没跑过**——实际生效保留期:10-04 当日仍为 **30 天**;**2026-10-04 21:00 定时首跑之后才切到 14 天**(首跑后 `backup/` 由 2691.6 MB → 约 1361.5 MB,省约 1330.2 MB)。
> 本报告为 2026-10-04 researcher 根因调研的正式落档;所有证据均经云上实测或本地逐字节比对,非推断项已在 §诚实标注 明确区分。

## ① 背景:表面「矛盾」长什么样

- `backup/` 前缀现存对象日期 = **20260904~20261003**,跨 29 个自然日(business 日 27 个)。
- 而代码声称保留 **14 天**(`743c0043c`,2026-10-03 用户拍板方案 B 实施)。
- 表面矛盾:09-20 之前的对象按理早该被 `_prune_r2_backup` 删除,为何还在?

## ② 真相:不是矛盾,是「代码已上云、但那版代码一次都没跑过」

| # | 证据 | 实测值 | 结论归属 |
|---|---|---|---|
| E1 | 云上 `/home/ubuntu/code/trade-data/scripts` 是 **symlink** → 真实文件 `/home/ubuntu/code/trade-data-signal/scripts/upload_r2.py`,md5 = `0dfeace0e0c7597b8ff45ce92eb6ca6f` | 与本地 main(含 14 天改动)该文件 **md5 逐字节一致** | 实测锤死:14 天改动的代码确实在云上 |
| E2 | 云上 git HEAD = `c7d840891`;`743c0043c` 在云上 HEAD 祖先链上 | 14 天改动(`743c0043c`)已在云上同步 | 实测锤死 |
| E3 | 云上该文件 mtime = **2026-10-03 23:42:37** | = merge 后立即 `git pull` 的时间 | 实测锤死:代码今天凌晨才落云 |
| E4 | `trade-backup-db.timer` **上次执行 = 2026-10-03 21:00:01** | 早于代码落云(23:42) ⇒ **10-03 那次定时跑的是旧代码,新版一次未执行** | 逻辑锤死(定时器执行时点 vs 文件 mtime 先后不兼容) |
| E5 | 云上 9 条可用日志(最早 20260913)全量 `grep "分层清理共"` | 每天恰命中 1 行、全部同一文案含「`backup/ 30天`」;`删除失败|✗|Traceback` **0 命中**;退出码 0 | 铁证:**10-03 运行时仍是旧代码(30 天文案),且从未失败** |
| E6 | `backup/` 54 对象 = **27 日期 × 恰好 2 个/天** | 与「每天 2 份 DB 备份 × 30 天窗口」完全吻合,无提前删除痕迹 | 实测锤死:30 天窗口确实在维持 |

**推论(唯一兼容全部证据的解释)**:10-03 21:00 定时执行时 = 旧代码(30 天);10-03 23:42 新代码(14 天)落云;此后下一次定时 = **10-04 21:00** 才首跑新代码。⇒ **生效时点 = 2026-10-04 21:00 首跑;之前 `backup/` 保持 30 天窗口合法。**

## ③ 三层现状与口径核对(backup / weekly / monthly)

| 层级 | 实测现状 | 代码口径 | 核对结论 |
|---|---|---|---|
| `backup/` 日 DB 备份 | 54 对象(27 日期 × 2),20260904~20261003,2691.6 MB | 30 天 → 14 天(**10-04 21:00 起生效,见 §②**) | 现状=旧代码 30 天窗口的合法维持,无异常 |
| `weekly/` | 8 对象(日期 0907/0914/0921/0928),386.7 MB | 28 天裁剪 | 与代码口径一致,无异常 |
| `monthly/` | 8 对象,289.1 MB | 365 天裁剪 | 与代码口径一致,无异常 |

- **写入侧排除(无第二写入者)**:`backup/` 唯一写入点 = `upload_r2.py:2147`;全仓唯一调用方 = `backup_db.sh:93`;实测 54 对象 = 27 日期 × 恰好 2 个/天,与单写入者(每日 2 份)完全吻合。

## ④ 容量实算(14 天 prune 首跑后)

- `backup/` 当前(2026-10-04):**54 对象 = 2691.6 MB**。
- 首跑(10-04 21:00)按 14 天 cutoff 语义(保留最近 14 个 business 日期、删 09-20 及更早):删 **28 对象(14 个日期),省 1330.2 MB**;剩 26 对象(13 个日期)= **约 1361.5 MB**。
- 长周期恢复能力不受影响:`weekly/`(8 对象)与 `monthly/`(8 对象)仍在保留窗口内(§③)。

## ⑤ 对 `743c0043c` 的表述订正

- 既有文档/索引(如 `docs/ops/r2-backup-bucket-capacity-20261002.md` §⑩、pending 索引 #170)表述「R2 保留期 30→14 天已上线(`743c0043c` 在 main ✓)」——**准确但易误读**:
  - **改动有效且已上云** ✓(证据 E1/E2:md5 逐字节一致、HEAD 祖先链含 `743c0043c`)。
  - 但**实际效果尚未发生** ✗(证据 E3/E4/E5:10-03 21:00 定时跑的是旧代码;新版迄今零执行)。
  - 正确表述:**「14 天生效时点 = 2026-10-04 21:00 首跑」**;10-04 当日实测窗口仍为 30 天,属预期过渡态,非故障。

## ⑥ 关于 lifecycle 30 天规则的定位(冗余兜底)

- API 复核 `GetBucketLifecycleConfiguration` = **403 AccessDenied**(当前 S3 凭证无此权限,与 `upload_r2.py:2102-2103` docstring 记载一致),无法 API 直证。
- 仅采信用户 2026-10-04 dashboard 观察:R2 `signal-backup` Lifecycle rules 确实有 `backup/` 30 天规则。
- **定性:lifecycle 是冗余兜底,不是当前 30 天窗口的解释**——实际删除者是代码 `_prune_r2_backup`(每天真删 2 个,日志 E5 铁证);lifecycle 因窗口(30 天)严于代码(PASS 期是 30 天、现在 14 天)而长期不触发,仅当代码清理故障时兜底。
- 兜底与代码当前口径不同步的问题已登记 pending 索引 **#171,待用户拍板**(主控倾向不改:无容量收益 + 松一档的兜底网在自动化故障时更安全)。

## ⑦ 诚实标注:实测锤死 vs 推断

**实测锤死(§② E1-E6)**:
- 代码上云且 md5 与本地 main 逐字节一致(E1/E2);落云时刻 10-03 23:42(E3);10-03 21:00 定时跑的是旧代码(E4 时点不兼容 + E5 日志文案 + 零失败);30 天窗口由旧代码合法维持(E6 对象数吻合)。

**推断(执行尚未发生,务必标注)**:
- 「今晚(10-04 21:00)将删 09-20 及更早、删 28 对象省 1330.2 MB」= **按代码 cutoff 语义推导**,首跑尚未发生;首跑后实际 cutoff 以运行时为准(若首跑晚于 10-04 21:00,cutoff 顺延,过期对象更多,§容量实算对应下调)。
- lifecycle 规则「长期不触发」= 按「lifecycle 30 天 > 代码 14 天」比较推断,正确性依赖 §⑥ 用户 dashboard 观察(API 无法复核)。

## ⑧ 复核用命令(主控回放)

```bash
# E1 本地代码 md5(应 0dfeace0…)
md5 /Users/linhuichen/code/trade/scripts/upload_r2.py

# E2 云上 git HEAD + 祖先链(应按 c7d840891、含 743c0043c)
ssh -i <云上key> ubuntu@<云上IP> 'cd /home/ubuntu/code/trade-data-signal && git log --oneline -3 && git merge-base --is-ancestor 743c0043c HEAD && echo yes'

# E3 云上落云时刻(应 2026-10-03 23:42:37)
ssh -i <云上key> ubuntu@<云上IP> 'stat -c "%y" /home/ubuntu/code/trade-data-signal/scripts/upload_r2.py'

# E4 定时器 LAST/NEXT(上次执行应 ≤ 2026-10-03 21:00:01,早于代码落云)
ssh -i <云上key> ubuntu@<云上IP> 'systemctl list-timers trade-backup-db.timer'

# E5 云上日志(9 条可用日志全量 grep「分层清理共」应全部同文案含 backup/ 30天;失败计数 0)
ssh -i <云上key> ubuntu@<云上IP> 'grep -H "分层清理共" <日志路径>/upload* | tail -9 && grep -c "删除失败\|✗\|Traceback" <日志路径>/upload* || echo 0'

# E6 对象数核对(应 54 对象 = 27 日期 × 2)
/Users/linhuichen/code/trade/.venv/bin/python docs/scripts/r2_bucket_stats.py --bucket signal-backup --prefix backup/

# lifecycle 兜底(API 403 预期;仅用户 dashboard 可查)
/Users/linhuichen/code/trade/.venv/bin/python docs/scripts/r2_bucket_stats.py --bucket signal-backup --lifecycle 2>&1 | tail -2
```

## 关联

- 桶容量总览与瘦身方案:`docs/ops/r2-backup-bucket-capacity-20261002.md`(§⑩ 方案 B 执行记录;本报告为其「实际生效时点」补充)
- 待拍板项:`docs/pending-features-index.md` **#171**(lifecycle 是否同步改 14 天)
- 本问题侧关键 commit:`743c0043c`(代码保留 30→14)