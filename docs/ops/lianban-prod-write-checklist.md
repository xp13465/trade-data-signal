# 连板历史回补·生产写库执行清单(只补缺口)

> 状态:本清单仅文档,不执行。写库最终由用户单独授权后在云上执行。
> 脚本:`app/backfill_lianban.py`(feat 分支,需先合入 main 并同步云上后可用)。
> dry-run 全量对账与「只补缺口」数字见 `docs/research/lianban-backfill-dryrun-20260930.md`。
> 复审返工:F3(备份改 SQLite backup API)/F4(可执行校验)/F5(统一 76 + 钉 --end)/F6(回滚补完)/F8(单事务独占)/F9(校验 mode=ro)。

## 0. 目标库与运行环境(云上实测 2026-09-30)

- 生产主库(每日采集写,含 a_width_max_lianban 现有 77 天):`/home/ubuntu/code/trade-data/data/sentiment.db`
  - 现况:a_width_max_lianban 77 行(20260612~20260930,source=akshare/intraday),全库 230995 行
  - ⚠️ **口径**:回补区间 `--end 20260929`(近一个交易日)内重叠 = **76 天**(20260612~20260929);20260930 今天在 end 外,写库时不涉及。执行后总行数 = 1154(缺口 20210901~20260611) + 77(现有全段) = **1231**。
- 运行 python:`/home/ubuntu/code/trade-data/.venv/bin/python`
- 代码仓:`/home/ubuntu/code/trade-data-signal`(app/ 为 symlink 直指主树),cwd 须在 `trade-data/` 以读主库
- ⚠️ `/home/ubuntu/code/trade-data-signal/data/sentiment.db` 是旧镜像(76 行/230894 行),**不是写库目标**,勿误写

## 二. 前置确认(一条不满足即停,绝不跳过)

1. 本次涉及的核心功能「a_sentiment 含实际连板数」为新增补充,**不重算历史 a_sentiment(用户已拍板,回测侧自算)**——本清单只落 `a_width_max_lianban` 值,不回算下游
2. 写库只走**只补缺口**语义:目标库已有非空值→跳过(不管 source);`source='manual'` 双层保护(Python 判定 + SQL `WHERE source!='manual'`,fill-gaps 模式再叠加 `AND value IS NULL` 竞态加固)
3. feat 分支 commit 已合入 main 并同步云上(生产写库前必须在云上能 `import app.backfill_lianban`)
4. **执行时段避开**:交易日盘中 09:30-15:30、盘后 15:35/16:00/17:50/20:35/22:00 定时任务窗口、update_all 17:50 主采集期。建议**安全窗口 23:00 后或周末休市**(§14)。执行**预计 20-40 分钟**(逐日翻页取全量,~1230 交易日 × 节流)

## 三、备份(先行,强制;F3 改 SQLite backup API,不用裸 cp)

> 为什么:主库是 WAL 模式,`cp` 可能拷到未 checkpoint 的半写页;SQLite 在线 backup API(`src.backup(dst)`)拿一致性快照,实测副本行数与源完全一致(230995)。

```bash
# 1) 记录基线 md5(执行前后对照,证明除非新增缺口行外零变化)
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 \
  "md5sum /home/ubuntu/code/trade-data/data/sentiment.db"

# 2) 在线热备(backup API,带时间戳)+ 副本完整性校验
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 'bash -s' <<'EOF'
/home/ubuntu/code/trade-data/.venv/bin/python - <<'PY'
import sqlite3, datetime, os
ts  = datetime.datetime.now().strftime('%Y%m%d%H%M')
src = '/home/ubuntu/code/trade-data/data/sentiment.db'
dst = src + '.bak-lianban-' + ts
s = sqlite3.connect(src); d = sqlite3.connect(dst)
s.backup(d); d.close(); s.close()
ok = sqlite3.connect(dst).execute('PRAGMA integrity_check').fetchone()[0]
n  = sqlite3.connect(dst).execute('SELECT COUNT(*) FROM daily_metric').fetchone()[0]
print('backup ->', dst, 'integrity=', ok, 'rows=', n)
assert ok == 'ok' and n == 230995, 'backup FAIL'
print('BACKUP OK')
PY
EOF

# 3) 备份后重新核 baseline md5 未变(backup API 只读源,不写主库)
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 \
  "md5sum /home/ubuntu/code/trade-data/data/sentiment.db"
```

## 四. 云上 dry-run 复核(写库前必跑一次,防生产环境 FAPI 数据漂移)

> 目的:在目标主库上重跑「只补缺口」dry-run,核对 planned_write / skipped_existing / skipped_manual / gap 与本地一致,再放行。缺口段为 2021-2026 历史固定,FAPI 应返回稳定,重点盯近 30 日与 gap 数。
> ⚠️ **钉 `--end 20260929`**:默认 end=昨天会随执行日漂移、重叠跳过数随之变化;复核与执行都显式钉 end,数字口径固定。
> ⚠️ F9:脚本 `backfill_lianban` 连库用普通连接(读为主,会 touch sidecar `-wal/-shm`,文件内容 0 字节不写数据);此 dry-run 非纯只读——**连库即建空 sidecar,跑完顺手清掉**(见末尾命令)。数据本身一行不动,靠「执行前后行数 + md5 排除新增行」验证。

```bash
cd /home/ubuntu/code/trade-data
/home/ubuntu/code/trade-data/.venv/bin/python -m app.backfill_lianban \
  --start 20210901 --end 20260929 --db /home/ubuntu/code/trade-data/data/sentiment.db \
  --out /tmp/lianban_prod_dryrun.json
cat /tmp/lianban_prod_dryrun.json | python3 -c '
import json,sys; d=json.load(sys.stdin)
print("planned_write=",d["planned_write"],"skipped_existing=",d["skipped_existing"],
      "skipped_manual=",d["skipped_manual"],"gap=",len(d["gaps"]),
      "overlap=",d["overlap_total"],"overlap_written=",d["overlap_written"])
'
```

期望(与本地 dry-run 同源):`planned_write=1154 | skipped_existing=76 | skipped_manual=0 | gap=0 | overlap=76 | overlap_written=0`。
(若近期 FAPI 已更新涨停池,近几日可能跳过/新增,以云上 dry-run 复核数字为准,但与本地报告对账后放行。)

## 五、执行(只补缺口,默认即非 overwrite;F8 单事务独占)

> ⚠️ F8:执行是**单事务**(脚本逐日 `_upsert` 攒到最后一次 `conn.commit()`),天然原子——**中途 Ctrl-C / SIGKILL = 0 行落库**,已写行因未 commit 全部回滚,库保持执行前原样。可放心在 23:00 后跑;真被杀重启脚本即可(重复写幂等,fill-gaps 跳过高危为零)。

> ⚠️ P2-7(2026-10-02)生产护栏:脚本对 `--write` 且目标解析为生产主库路径(含未指定 --db 默认、本机 DB_PATH、云上主库 `/home/ubuntu/code/trade-data/data/sentiment.db` 常量)强制二次确认——必须加 `--confirm-prod` 或环境变量 `LIANBAN_CONFIRM_PROD=1`,否则 rc=3 拦截。dry-run 不拦。因此下面写库命令须带 `--confirm-prod`。

```bash
cd /home/ubuntu/code/trade-data
/home/ubuntu/code/trade-data/.venv/bin/python -m app.backfill_lianban \
  --start 20210901 --end 20260929 --db /home/ubuntu/code/trade-data/data/sentiment.db --write --confirm-prod \
  2>&1 | tee /home/ubuntu/code/trade-data/data/logs/lianban_backfill_run.log
```

期望(与本地 dry-run 同源):`计划写入 1154 天 | 因已有值跳过 76 天 | 因 manual 跳过 0 天 | gap 0`。
(若近期 FAPI 已更新涨停池,近几日可能跳过/新增,以云上 dry-run 复核数字为准。)

## 六、校验(F4 可执行校验 + F9 全部 mode=ro)

> F9:校验连接一律 `mode=ro`(只读,不写库不产生 sidecar),防校验本身污染。以下 python 片段统一用 `file:<path>?mode=ro` 打开。

```bash
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 'bash -s' <<'EOF'
/home/ubuntu/code/trade-data/.venv/bin/python - <<'PY'
import sqlite3
DB='/home/ubuntu/code/trade-data/data/sentiment.db'
c = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)

# 1) 行数与区间
print('lianban_days =', c.execute("SELECT COUNT(*) FROM daily_metric WHERE metric_id='a_width_max_lianban'").fetchone()[0])
print('range =', c.execute("SELECT MIN(date),MAX(date) FROM daily_metric WHERE metric_id='a_width_max_lianban'").fetchone())
print('manual_rows =', c.execute("SELECT COUNT(*) FROM daily_metric WHERE metric_id='a_width_max_lianban' AND source='manual'").fetchone()[0])

# 2) source 分布
for r in c.execute("SELECT source, COUNT(*) FROM daily_metric WHERE metric_id='a_width_max_lianban' GROUP BY source ORDER BY source"):
    print('source', r[0], r[1])

# 3) 双向 EXCEPT:缺口段(20210901~20260611)应与全 fapi 新增、无缺口残留
gap = c.execute("""
  SELECT date FROM daily_metric WHERE metric_id='a_width_max_lianban'
    AND date BETWEEN '20210901' AND '20260611' AND value IS NULL
""").fetchall()
print('缺口段空值残留(应0) =', len(gap))
print('缺口段覆盖天数(应1154±) =', c.execute("""
  SELECT COUNT(*) FROM daily_metric WHERE metric_id='a_width_max_lianban'
    AND date BETWEEN '20210901' AND '20260611'
""").fetchone()[0])
c.close()
PY
EOF
```

3. 边界核对:20260611 有值(fapi 新增)、20260612 现有值(akshare/intraday)插值逐位与执行前一致(抽样 SQL 对比)
4. md5 已变(因新增行),但**排除新增行后**基线段 hash 与执行前一致——用备份做差异位核对(见回滚)

## 七、回滚(F6 补完:无写入进程确认 + 清 sidecar + 不需重启)

> 备份是 backup API 一致快照(§三),回滚 = 用备份覆盖主库,一步恢复执行前原样。

```bash
# 0) 确认无写入进程(必查,防覆盖瞬间又被写)
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 \
  "ps aux | grep -E 'backfill_lianban|collect_snapshot|update_all' | grep -v grep | wc -l"
#   期望输出 0

# 1) 恢复到执行前备份(会丢弃本次新增,现有 77 天恢复原值)
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 'bash -s' <<'EOF'
/home/ubuntu/code/trade-data/.venv/bin/python - <<'PY'
import sqlite3, glob, os
BACKUP = sorted(glob.glob('/home/ubuntu/code/trade-data/data/sentiment.db.bak-lianban-*'))[-1]
print('restore from', BACKUP)
src = sqlite3.connect(BACKUP); dst = sqlite3.connect('/home/ubuntu/code/trade-data/data/sentiment.db')
src.backup(dst)   # 一致性恢复,WAL 一并处理
dst.close(); src.close()
ok = sqlite3.connect('/home/ubuntu/code/trade-data/data/sentiment.db').execute('PRAGMA integrity_check').fetchone()[0]
print('integrity =', ok)
assert ok == 'ok'
print('RESTORE OK')
PY
EOF

# 2) 清空回滚后可能残留的 sidecar(backup API 恢复后不应有,但保险清一次;只删 -wal/-shm 不删主库)
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 \
  "rm -f /home/ubuntu/code/trade-data/data/sentiment.db-wal /home/ubuntu/code/trade-data/data/sentiment.db-shm"

# 3) 恢复后核对 baseline md5(与『三、备份』第 1 步基线一致;md5 相同即完全回滚成功)
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 \
  "md5sum /home/ubuntu/code/trade-data/data/sentiment.db"
```

> 不需要重启任何服务:sqlite 每连接独立,回滚后新连接即读新库内容,定时采集下一轮自然落到恢复后的库。
> 若只在近段写错且无需整体回滚,可 `--end` 只回补/只删特定日期,但默认一律用整库备份回滚最稳。

## 附. 与本分支交付的关系

- 脚本:`app/backfill_lianban.py`(feat 分支;文档本清单 + dry-run 报告同分支)
- 关键纪律:agent 不直接 push main、不跑本清单(文档只给命令)、不 deploy/不 bump;本清单唯一目的是用户授权后由云上执行
- 合 main 前特例:脚本文档属「只读生产源 + 输出独立 + 不 bump/deploy/push 数据」的未排功能隔离形态,写库前必须用户再授权
- **不碰 F2**:写库后是否重算历史 a_sentiment,由主控上报用户另行拍板,本清单只落连板值。
