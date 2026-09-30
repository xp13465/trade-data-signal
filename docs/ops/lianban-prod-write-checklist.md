# 连板历史回补·生产写库执行清单(只补缺口)

> 状态:本清单仅文档,不执行。写库最终由用户单独授权后在云上执行。
> 脚本:`app/backfill_lianban.py`(feat 分支,需先合入 main 并同步云上后可用)。
> dry-run 全量对账与「只补缺口」数字见 `docs/research/lianban-backfill-dryrun-20260930.md`。

## 0. 目标库与运行环境(云上实测 2026-09-30)

- 生产主库(每日采集写,含 a_width_max_lianban 现有 77 天):`/home/ubuntu/code/trade-data/data/sentiment.db`
  - 现况:a_width_max_lianban 77 行(20260612~20260930,source=akshare/intraday),全库 230995 行
- 运行 python:`/home/ubuntu/code/trade-data/.venv/bin/python`
- 代码仓:`/home/ubuntu/code/trade-data-signal`(app/ 为 symlink 直指主树),cwd 须在 `trade-data/` 以读主库
- ⚠️ `/home/ubuntu/code/trade-data-signal/data/sentiment.db` 是旧镜像(76 行/230894 行),**不是写库目标**,勿误写

## 二. 前置确认(一条不满足即停,绝不跳过)

1. 本次涉及的核心功能「a_sentiment 含实际连板数」为新增补充,**不重算历史 a_sentiment(用户已拍板,回测侧自算)**——本清单只落 `a_width_max_lianban` 值,不回算下游
2. 写库只走**只补缺口**语义:目标库已有非空值→跳过(不管 source);`source='manual'` 双层保护(Python 判定 + SQL `WHERE source!='manual'`)
3. feat 分支 commit(`f3937e194` 脚本 + 文档)已合入 main 并同步云上(生产写库前必须在云上能 `import app.backfill_lianban`)
4. **执行时段避开**:交易日盘中 09:30-15:30、盘后 15:35/16:00/17:50/20:35/22:00 定时任务窗口、update_all 17:50 主采集期。建议安全窗口 23:00 后或周末休市

## 三、备份(先行,强制)

```bash
# 记录基线 md5(执行前后对照,证明除非新增缺口行外零变化)
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 "md5sum /home/ubuntu/code/trade-data/data/sentiment.db"

# 冷备一份(带时间戳)
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 \
  "cp /home/ubuntu/code/trade-data/data/sentiment.db /home/ubuntu/code/trade-data/data/sentiment.db.bak-lianban-\$(date +%Y%m%d%H%M) \
   && md5sum /home/ubuntu/code/trade-data/data/sentiment.db.bak-lianban-\$(date +%Y%m%d%H%M) \
   && ls -lh /home/ubuntu/code/trade-data/data/sentiment.db.bak-lianban-*"
```

## 四. 云上 dry-run 复核(写库前必跑一次,防生产环境 FAPI 数据漂移)

> 目的:在目标主库上重跑「只补缺口」dry-run,核对 planned_write / skipped_existing / skipped_manual / gap 与本地(见报告 §只补缺口)一致,再放行。由于缺口段为 2021-2026 历史固定,FAPI 应返回稳定,重点盯近 30 日与 gap 数。

```bash
cd /home/ubuntu/code/trade-data
/home/ubuntu/code/trade-data/.venv/bin/python -m app.backfill_lianban \
  --start 20210901 --db /home/ubuntu/code/trade-data/data/sentiment.db \
  --out /tmp/lianban_prod_dryrun.json
cat /tmp/lianban_prod_dryrun.json | python3 -c '
import json,sys; d=json.load(sys.stdin)
print("planned_write=",d["planned_write"],"skipped_existing=",d["skipped_existing"],
      "skipped_manual=",d["skipped_manual"],"gap=",len(d["gaps"]),
      "overlap=",d["overlap_total"],"overlap_written=",d["overlap_written"])
'
```

> 注:脚本参数为 `--start/--end/--db/--dry-run/--write/--with-st/--overwrite/--fill-gaps-only/--out`。dry-run 为默认模式,`--write` 才真写库。

## 五、执行(只补缺口,默认即非 overwrite)

```bash
cd /home/ubuntu/code/trade-data
/home/ubuntu/code/trade-data/.venv/bin/python -m app.backfill_lianban \
  --start 20210901 --db /home/ubuntu/code/trade-data/data/sentiment.db --write \
  2>&1 | tee /home/ubuntu/code/trade-data/data/logs/lianban_backfill_run.log
```

期望(与本地 dry-run 同源):`计划写入 1154 天 | 因已有值跳过 77 天 | 因 manual 跳过 0 天 | gap 0`。
(若近期 FAPI 已更新涨停池,近几日可能跳过/新增,以云上 dry-run 复核数字为准。)

## 六、校验

1. 行数:a_width_max_lianban 从 77 → 应 ≈ 77+1154=1231 天(以 20260629 为最近交易日计;若天然含 20260930 则 +1)
```bash
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 \
  "/home/ubuntu/code/trade-data/.venv/bin/python -c \"import sqlite3;c=sqlite3.connect('/home/ubuntu/code/trade-data/data/sentiment.db');print('lianban_days=',c.execute(\\\"SELECT count(*) FROM daily_metric WHERE metric_id='a_width_max_lianban'\\\").fetchone()[0]);print('range=',c.execute(\\\"SELECT MIN(date),MAX(date) FROM daily_metric WHERE metric_id='a_width_max_lianban'\\\").fetchone());print('manual_rows=',c.execute(\\\"SELECT count(*) FROM daily_metric WHERE metric_id='a_width_max_lianban' AND source='manual'\\\").fetchone()[0])\""
```
2. source 分布:应含新增 `fapi` 源行;既有 akshare/intraday 77 天**值不变**(md5 基线见下)
3. 边界核对:20260611 有值(fapi 新增)、20260612 现有值(akshare/intraday)插值逐位与执行前一致(抽样 SQL 对比)
4. md5 已变(因新增行),但**排除新增行后**基线段 hash 与执行前一致——用备份版本做差异位核对(见回滚)

## 七、回滚

```bash
# 恢复到执行前备份(会丢弃本次新增,现有 77 天恢复原值)
ssh -i ~/tdsignal.pem -o ConnectTimeout=15 ubuntu@122.51.111.173 \
  "cp /home/ubuntu/code/trade-data/data/sentiment.db.bak-lianban-<执行前时间戳> /home/ubuntu/code/trade-data/data/sentiment.db \
   && md5sum /home/ubuntu/code/trade-data/data/sentiment.db"

# 恢复后核对 baseline md5(与『三、备份』第一步基线一致)
```

> 若只在近段写错且无需整体回滚,可`--end` 只回补/只删特定日期,但默认一律用整库备份回滚最稳。

## 附. 与本分支交付的关系

- 脚本:`app/backfill_lianban.py`(feat,commit f3937e194;文档本清单 + dry-run 报告同分支)
- 关键纪律:agent 不直接 push main、不跑本清单(文档只给命令)、不 deploy/不 bump;本清单唯一目的是用户授权后由云上执行
- 合 main 前特例:脚本文档属「只读生产源 + 输出独立 + 不 bump/deploy/push 数据」的未排功能隔离形态,写库前必须用户再授权