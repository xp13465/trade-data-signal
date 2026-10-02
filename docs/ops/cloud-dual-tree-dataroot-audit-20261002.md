# 云上双树 data/ 写读分离根因审计(2026-10-02)

> 调研 agent 只读审计,不实施。结论均带可复现证据(命令+关键输出+file:line)。实测/推断/未查三档诚实标注。
> 关联后台:止血 agent「云上止血重出fund_nav」正在并行修复(本报告撰写时 R2 线上已更新到 20260930)。

## 0. 一句话结论

云上存在**两棵独立 data/ 树**:REPO=`/home/ubuntu/code/trade-data`(数据树,不 git init)与 GIT_REPO=`/home/ubuntu/code/trade-data-signal`(git 树)。**全部 35+ systemd service 统一从 REPO 运行、读写 REPO/data/**(env 注入),GIT_REPO/data/ 只是 deploy rsync 的**镜像**(rsync 桥在 deploy.sh L547,位于 check 闸门 L323 之后)。

本轮 public_fund.db 分叉 + deploy 连环 FAIL 的**直接根因不是写读分离**,而是:
1. **9-25(中秋)非交易日**,9-28/29/30 三个交易日数据源(fund_open_fund_daily_em)**连续三天未发布净值**,daily 采集写入 24137/24135/24152 行但 `unit_nav/acc_nav` 全 NULL(仅 name 有值)→ 主库有效净值停在 9-24 → nav_bucket 产物停在 9-24。
2. **10-02 01:43 stage0-nav 二轮回填(1825 天)**,用 `INSERT OR REPLACE` 把 9-28/29/30 的 `unit_nav` 补上(所以 check 看到"DB 领先产物 6 天")。
3. 但 stage0 写入 `acc_nav` 恒为 NULL(fetch_nav_history L1132 `rows.append((d, code, None, nav, None, None, nav_pct))`),**REPLACE 覆盖了 daily 采集的 acc_nav 有值行**——全库 9 月 acc_nav 从 signal 快照的 **88696 行**暴跌到主库现在的 **173 行**(数据回退,独立 bug)。
4. deploy check `DB(9-30) vs 产物(9-24)` FAIL → 终止于 check,rsync 桥未跑 → GIT_REPO 库停在 10-01 16:01 快照。

## 1. 树结构与成因(Q1)

### 1.1 两树独立(实测)
- REPO `/home/ubuntu/code/trade-data`:`ls | wc -l`=53 个 data/ 文件,`du -sh`=6.3G
- GIT_REPO `/home/ubuntu/code/trade-data-signal`:56 个,6.1G
- 63 个共有文件 inode 全不同(0 hardlink),19 个只在一棵树(此前审计)。
- `public_fund.db` 两树 size 差 6,393,856 字节。

### 1.2 成因
- **架构设计**:REPO=数据树(不 git init,存大 DB),GIT_REPO=git 树(rsync 镜像后 git commit/push 上线静态资源)。deploy.sh 两段式(#149,L38-44):段1 export+check+R2+rsync(不持锁),段2 `--git-phase` 持锁 git。
- **rsync 桥**位置:deploy.sh L547-553 `rsync -a --exclude=... "$REPO/data/" "$GIT_REPO/data/"`,位于 check(L323)之后 → check FAIL 则桥不跑。
- **脚本路径逻辑故意不 resolve symlink**:`export_fund_nav.py` L75-77 注释"不用 .resolve(): scripts 在两树间 hardlink/symlink, resolve() 会绕回 trade 致输出路径错树"。`public_fund.py` L71-77 `_ROOT = Path(__file__).absolute().parent.parent.parent`(不 resolve)。

### 1.3 何时形成
- service 文件批量创建 mtime 9-16 05:11(大部分),public-fund-daily 9-21 21:32。9-16 起 main 树每天比 signal 多约 2000 行(fund_daily_nav)即两树分叉起点——此前同一归档段审计已确认。

## 2. 写/读归属完整表格(Q2,实测)

**机制**:`/etc/systemd/system/trade-*.service` 全部注入 `WorkingDirectory=/home/ubuntu/code/trade-data` + `Environment=REPO=/home/ubuntu/code/trade-data` + `Environment=GIT_REPO=/home/ubuntu/code/trade-data-signal`。脚本内默认 `REPO="${REPO:-/Users/linhuichen/code/trade-data}"`(mac 路径),云上由 env 覆盖。

| 定时任务 | 时点 | 从哪棵树跑(ExecStart) | 写 REPO/data | 读 REPO/data | 备注 |
|---|---|---|---|---|---|
| trade-update-all | 17:50 | REPO `scripts/update_all.sh` | export 产物+rsync GIT | export_fund_nav/check | 主入口 |
| trade-public-fund-daily | 16:30/17:00 | REPO `public_fund_daily.sh` | fund_daily_nav 等 | check_data_integrity | 采集器 |
| trade-pf-score-daily | 16:00 | REPO `pf_score_daily.sh` | fund_score | 读 fund_daily_nav | L41 直接 import public_fund |
| trade-pf-stage0-nav | 周五 01:43 | REPO `stage0_nav.sh` | **REPLACE 覆盖 fund_daily_nav** | — | 本轮事故源之一 |
| trade-public-fund-full | 22:00 | REPO `public_fund_full.sh` | fund_basic 等 | — | |
| trade-public-fund-quarterly | 03:00/04:00 | REPO | 季报表 | — | |
| trade-public-fund-estimation | 10:00/11:00 | REPO | fund_value_estimation | — | |
| trade-etf-national-team | 20:07/21:30 | REPO | etf_national_team.db | — | |
| trade-fapi-daily | 18:10 | REPO | stock_daily.db(fapi) | — | |
| trade-intraday-snapshot | 09:25/09:35 | REPO | intraday 表 | — | |
| trade-s06-snapshot | 交易日 20:35 | REPO | S06 快照 | — | |
| trade-overfit-monitor | 交易日 21:40 | REPO | overfit 产物 | — | |
| trade-check-data-gap | 交易日 22:35 | REPO | — | check_data_gap | |
| trade-daily-brief | 20:40 | REPO | — | — | 邮件 |
| trade-brief-push | 20:45 | REPO | — | — | 推送 |
| trade-daily-summary-supplement | 20:30 | REPO | — | — | 邮件 |
| trade-backup-db | 21:00 | REPO `backup_db.sh` | 备份 | 读全部 DB | |
| trade-backfill-evening | 16:35/21:00 | REPO | 回填 | | |
| trade-futures-backfill / lhb / rzhb / turnover | 多档 | REPO | 对应表 | | |
| trade-etf-track-index / lof-track-index | 周 03:30/04:00 | REPO | 映射 | | |
| trade-fetch-news | 每30min | REPO | news | | |
| trade-gold-night | 02:40 | REPO | | | |
| trade-us-stock-morning | 05:00 | REPO | | | |
| trade-nextday-gap-check / nextday-plan | 09:26/22:30 | REPO | | | |
| trade-schedule-monitor | 每15min | REPO | | | |
| trade-self-heal | 每15min | REPO | | | |
| trade-ab-direction-anchor | 21:15 | REPO | | | |
| trade-kelly-intraday-rerun | 09:40 | REPO | | | |
| trade-lab-auto | 19:00 | REPO | | | |

**结论:写/读全部落 REPO(trade-data)树,GIT_REPO 只是 rsync 镜像 + git。不存在"某 service 从 GIT_REPO 写数据"的分离。**

## 3. public_fund.db 具体链路(Q3)

- **写**:`trade-public-fund-daily.service` → REPO `public_fund_daily.sh` → REPO `.venv/bin/python -m app.collector.public_fund daily` → `fetch_daily_nav()`(L870)→ `INSERT OR REPLACE INTO fund_daily_nav(...)`(L911)。DB_PATH=REPO/data/public_fund.db(L71-77)。
- **读(产物侧)**:`trade-update-all` → REPO `scripts/export_fund_nav.py`(L107)→ `from app.collector.public_fund import DB_PATH`(L80)→ SQL(L174-176)`SELECT date, unit_nav, acc_nav FROM fund_daily_nav WHERE fund_code=? AND unit_nav IS NOT NULL ORDER BY date ASC` → 写 REPO/static-site/data/nav_bucket/(桶化,256 桶,2026-09-23 起)。
- **读(闸门侧)**:`check_data_integrity.py` `_find_public_fund_db()`(L1172)→ `_db_candidates` 优先 env REPO/GIT_REPO(L810-826)→ **优先读 REPO 库**,采样 SQL(L1411)。`_dir_note`(L1381-1400)"DB 领先产物 N 天"。
- **GIT_REPO 库**:仅 deploy rsync 桥(L547)从 REPO 镜像,无任何 service 直接读写。
- **可复现取证命令**:
  ```bash
  # 写入方(采集)
  grep -n "fund_daily_nav 写入" /home/ubuntu/code/trade-data/data/logs/public_fund_daily_20260928_1700.log
  #   [E] fund_daily_nav 写入 24137 行 @20260928
  # 读取方(export)
  sed -n '75,80p' /home/ubuntu/code/trade-data-signal/scripts/export_fund_nav.py   # 不用 resolve
  sed -n '170,176p' /home/ubuntu/code/trade-data-signal/scripts/export_fund_nav.py # SELECT ... unit_nav IS NOT NULL
  # 闸门读取源(db 候选)
  sed -n '810,826p' /home/ubuntu/code/trade-data-signal/scripts/check_data_integrity.py
  ```

## 4. 影响面穷举(Q4,实测)

除 public_fund.db 外,其余 DB/JSON **两树内容基本一致**(rsync 同步正常,写读分离无缺口),例外是:

| 产物 | main 树 | signal 树 | 差异 | 性质 |
|---|---|---|---|---|
| public_fund.db | size 较大 6.39MB 差 | 停 10-01 16:01 快照 | unit_nav 9-30(回填)vs 9-24;acc_nav 全清 | **核心缺口+数据回退** |
| sentiment.db | daily_metric 最新 20261002(5 rows) | 最新 20261001(7 rows) | signal 落后 1 天 | 轻微陈旧(rsync 未覆盖 10-02) |
| etf_national_team.db | etf_daily 1484685 max=20260930 | 同 | **两树内容一致** | 无缺口 |
| stock_daily.db | mootdx 20260928/baostock/fapi 20260930 | 同 | **两树内容一致** | 无缺口 |
| signal_stats.json | size 差 6 字节 | — | 小内容差 | 轻微 |
| nav_bucket/(桶化产物) | 256 桶,2026-09-23 起 | git 不 track(0 文件) | — | R2 上传即发布,与 git 树无关 |

**判定判据**:inode/mtime/rowid 对齐。sentiment.db 落后是因为 10-02 当天采集写主库后,rsync 桥在 check FAIL 处未跑——与 public_fund 同因,但 sentiment 无产物闸门消费,故无实际用户侧缺口。

**stage0 acc_nav 数据回退(独立 bug,最严重影响面)**:
- signal 快照(10-01 16:01,stage0 二轮前):9 月 `acc_nav 有值 88696 / 总 530646`
- 主库(10-02 stage0 二轮后):9 月 `acc_nav 有值 173 / 547123`
- 逐日:9-17/21/23/24 有 21959/21956/21977/22754 行 acc_nav(signal 快照),主库现在只有个位数;9-18/22/28/29/30 为 0。
- 根因:`fetch_nav_history()`(L1076)每行 `(d, code, None, nav, None, None, nav_pct)`(fund_name/acc_nav/prev 全 None),`INSERT OR REPLACE`(L1132)整行替换 → **覆盖 daily 的 acc_nav 值**。
- 前端影响:app.js 画净值线只用 unit_nav(映射伪 OHLC [date,v,v,v,v]),acc_nav"可 null"(app.js 校验注释);export_fund_nav payload 保留 acc_nav 字段但前端不展示 → **用户可见影响低,但数据层损坏(历史累计净值丢失),且 stage0 每次周五跑都会继续清 acc_nav**。

## 5. 生产数据缺口(Q5,实测)

- 线上用户侧:基金弹窗「净值走势」9-28/29/30 三天缺失(产物停 9-24)。**9-25 中秋休市,本身无净值,不算缺口**。
- 10-02 17:50 deploy check FAIL "DB 领先产物 6 天(DB 9-30 vs 产物 9-24)" → deploy 终止 → **GIT_REPO/data/public_fund.db 停在 10-01 16:01**(rsync 快照,与主库 10-01 16:01 mtime 一致)。
- 10-02 21:42-21:44 止血 agent 重出 export_fund_nav(256 桶刷新到 9-30);本报告撰写时(22:14)**R2 线上 00/01/02 桶最新已到 20260930**(curl 验证)→ 线上缺口已由止血 agent 修复。
- 剩余问题:重出产物使用**被 stage0 污染的主库**(9-28/29/30 unit_nav 有值但 acc_nav 全 None)→ 线上 9-28/29/30 只有单位净值、无累计净值。用户画线用 unit_nav 不受影响。

## 6. 本机同类问题(Q6,实测)

本机 `~/code/trade/` 与 `~/code/trade-data/` 同样双树,但**本机两库内容一致**:
- trade/data/public_fund.db 最新有值 20260910,总行 22,162,244
- trade-data/data/public_fund.db 最新有值 20260910,总行 22,162,244
- size 差 122,880 字节(inode 不同,mtime 不同),但内容查询一致。
- 本机 nav_bucket 两树均不存在(产物在云上生成)。
- **结论:本机双树仅是开发镜像,数据一致,无写读分离问题**(本机定时任务已废弃,生产在云上,memory `local-dev-cloud-prod-split`)。

## 7. 修复方向(Q7,只给方向+成本/风险,不实施)

按优先级:

1. **[P0] stage0-nav 禁止清空 acc_nav(数据回退根治)**:
   - 改 `fetch_nav_history()` L1132:`INSERT OR REPLACE` → `INSERT ... ON CONFLICT(date, fund_code) DO UPDATE SET unit_nav=excluded.unit_nav, nav_change_pct=excluded.nav_change_pct`(只更新有值字段,不触碰 acc_nav/fund_name/prev)。
   - 或 REPLACE 前先取旧 acc_nav 合并。成本:一处 SQL 改动。风险:stage0 只拉"单位净值走势",本身无 acc_nav 来源——**需要决定累计净值从哪补**(数据源 fund_open_fund_info_em 另拉"累计净值走势",或保留 daily 值)。

2. **[P1] nav_bucket 产物刷新链路暴露期检查(9-24 停更 6 天未被发现)**:
   - export_fund_nav 产物 date 连续 N 天不推进应触发告警(现仅有 check_data_integrity 在 deploy 时拦,但 deploy 因其他原因不跑时无告警)。
   - 成本:check 脚本加一个"产物日期 vs 日历"告警。

3. **[P1] 数据源连续多日无净值自动降级/告警**:
   - 9-28/29/30 daily 写入全 NULL 行但 exit=0、无告警。`fetch_daily_nav()` 应对 `unit_nav 全部 None` 视为异常(至少日志 + 告警)。

4. **[P2] rsync 桥位置**:check(L323)与 rsync data/ 桥(L547)同属段1,check FAIL 会阻止 data 镜像同步——可评估"数据镜像 rsync 独立于 deploy 闸门"(如先同步数据、闸门只管线上产物发布),避免 GIT_REPO 数据长期陈旧。成本中等,涉及 deploy 流水线结构。

5. **[P2] 双树架构文档化 + 一致性机检**:两树 data/ 共有文件 inode 全不同是正常设计(镜像非硬链),但需明确"谁写谁读",避免后续误判。可在 deploy 加"GIT_REPO 数据 mtime 落后 REPO>1 天即告警"。

## 8. 诚实标注

- **实测**:两树目录/DB/inode/size/service 归属/日志时间线/stage0 SQL/前端 acc_nav 消费方式/R2 线上日期/本机双库内容一致——全部实测。
- **推断**:①"9-28/29/30 数据源未发布净值"的**外部原因**(天天基金接口连续三天空列)未追查社区/厂商,只确认了"写入行 unit_nav 全 NULL"这一事实;②9-16 分叉起点 = service 创建日,属因果性推断(行数差异与时间吻合)。
- **未查**:①signal_stats.json 6 字节差异具体字段;②stage0 首次(9-18)运行对 4-8 月 acc_nav 的破坏程度(signal 快照 4-8 月 acc_nav 有值 0,与首轮 stage0 时间吻合,推断同为覆盖所致);③远端 git history 中 nav_bucket 桶文件未 track(0 文件)属正常设计还是异常(git ls-files 结果,上游 commit 未查)。

## 9. 复现锚点速查

```bash
# 两树 db 内容对比(signal 快照 vs 主库)
/home/ubuntu/code/trade-data-signal/.venv/bin/python - <<'PYEOF'
import sqlite3
for tag,p in [('signal','/home/ubuntu/code/trade-data-signal/data/public_fund.db'),('main','/home/ubuntu/code/trade-data/data/public_fund.db')]:
    c=sqlite3.connect(p)
    r=c.execute("SELECT SUM(CASE WHEN acc_nav IS NOT NULL THEN 1 ELSE 0 END), COUNT(*) FROM fund_daily_nav WHERE date>='20260901'").fetchone()
    print(tag, '9月acc_nav有值', r[0], '/', r[1])
    c.close()
PYEOF

# 9-28/29/30 采集写全 NULL 行
grep -E "fund_daily_nav 写入" /home/ubuntu/code/trade-data/data/logs/public_fund_daily_2026092{8,9}_1700.log /home/ubuntu/code/trade-data/data/logs/public_fund_daily_20260930_1700.log

# stage0 写入 acc_nav=None 的 SQL
sed -n '1125,1135p' /home/ubuntu/code/trade-data-signal/app/collector/public_fund.py
#   rows.append((d, code, None, nav, None, None, nav_pct))  <- acc_nav 恒 None
#   "INSERT OR REPLACE INTO fund_daily_nav"                  <- REPLACE 覆盖 daily 行

# check 闸门 FAIL 证据
grep "fund_nav: DB" /home/ubuntu/code/trade-data/data/logs/deploy_20261002_1750*.log | head -3
```
