# acc_nav 补数执行前两前提查证(2026-10-03)

> researcher 独立产出,针对用户 2026-10-03 拍板「做」后的**执行前两前提查证**(只读+写报告,不执行补数/不写云上/不传 R2)。
> 依据:本分支查证 + 调研报告 `docs/ops/accnav-backfill-0923-0924-20261003.md` + 独立复核报告 `docs/ops/accnav-backfill-review-20261003.md` + 审计 `docs/ops/fund-nav-accnav-clobber-audit-20261002.md`。
> 全部结论带可复核证据(云上路径/命令输出/文件:行号)。

## 0. 一句话结论

**① 补数必须写主库 `/home/ubuntu/code/trade-data/data/public_fund.db`(REPO 树),并同步到 signal/staticdata 两副本(漏任一=「补一半」);`export_fund_nav.py` 在云上实际读主库(REPO=trade-data 时 DB_PATH=主库,已云上实测)。② 缺失不止四天:9-17/21/23/24 是损坏(参考 21959/21956/21977/22754),9-15/16/18/22/28/29/30 七天是「本来就 0 但接口现已可取」,建议顺带补(全量 11 天);9-28~30 核实为「有行但 acc_nav 为空」(非整表无数据)且都是交易日,建议补。③ 10-09 周五 01:43 stage0-nav timer 真实存在、下次触发 10-09 01:43,UPSERT 修复已在云上(L1140),补数在 10-09 前完成即无二次踩踏;补数窗口避开 16:30/17:50/22:00。**

---

## 1. 前提一:三库同步链路(复核报告 P1 缺口,已查实)

### 1.1 三库拓扑(云上实测,谁是谁的源)

云上 `/home/ubuntu/code` 下三棵树,数据树为唯一源:

```
┌─────────────────────────────────────────────────────────────┐
│ REPO 主树(非 git)                                            │
│ /home/ubuntu/code/trade-data                                 │
│   data/public_fund.db           ←── 主库(唯一源)             │
│   app/scripts/config/docs/web/.venv/a-stock-data             │
│        → symlink 指向 /home/ubuntu/code/trade-data-signal     │
│   data/ 与 static-site/ 为实体目录                            │
└─────────────────────────┬───────────────────────────────────┘
                          │ 采集(daily/full/quarterly/stage0-nav)
                          │ 与 export_fund_nav.py 全部读主库
                          │
        deploy.sh L557-561│                        deploy.sh L1013 触发
  rsync REPO/data/ → GIT_REPO/data/ (写库后自动同步)   staticdata_backup_async.sh L140:
                          │                        rsync REPO/data/*.db → STATICDATA/db/
                          ▼
┌──────────────────────┐  ┌──────────────────────────────────┐
│ GIT_REPO 代码树(git) │  │ STATICDATA 灾备第2层(git)          │
│ /home/ubuntu/code/   │  │ /home/ubuntu/code/                 │
│  trade-data-signal/  │  │  trade-data-signal-staticdata/     │
│  data/public_fund.db │  │  db/public_fund.db                 │
│  (副本, 同 md5)       │  │  (副本, 同 md5)                    │
└──────────────────────┘  └──────────────────────────────────┘
```

证据(云上只读,复核报告 §1.4 也独立跑过):
- `ls -la /home/ubuntu/code/trade-data/`:`app/scripts/config/docs/web/.venv/a-stock-data` 全部 `-> /home/ubuntu/code/trade-data-signal/...` symlink;`data/` 是实体目录。
- 三库文件大小全 `2670219264`、mtime 全 `Oct 2 16:01`(ls -la 实测)。
- 三库 md5 逐字一致 `53df2a5d7face1d83c348deebc090cc8`(复核报告 §1.4 独立实测)。
- 副本方向全部 REPO→副本,无反向:deploy.sh L557-561 `rsync "$REPO/data/" "$GIT_REPO/data/"`;staticdata_backup_async.sh L140 `rsync -a "$REPO/data/"*.db "$STATICDATA_REPO/db/"`。
- 10-02 16:01 三库同 mtime = 某轮 deploy/备份把「损坏态主库」同步到了副本(审计 §10.1 证 signal 库 10-01 完整快照已被覆盖销毁)。

### 1.2 `export_fund_nav.py` 读的是哪一个库 —— 主库(云上实测)

- 云上文件路径:`/home/ubuntu/code/trade-data-signal/scripts/export_fund_nav.py`(git 树内;REPO 树 scripts 是 symlink 指向它,见 export_fund_nav.py L75-80)。
- 源码:export_fund_nav.py L77 `ROOT = Path(__file__).absolute().parent.parent`(**不 resolve symlink**,L75-76 注释「不用 .resolve():scripts 在两树间 hardlink/symlink,resolve() 会绕回 trade 致输出路径错树」)→ L78 `sys.path.insert(0, str(ROOT))` → L80 `from app.collector.public_fund import DB_PATH, STATIC_DATA_DIR`。
- `public_fund.py` L71 `_ROOT = Path(__file__).absolute().parent.parent.parent`、L74 `_DATA_DIR = _ROOT / "data"`、L75 `DB_PATH = _DATA_DIR / "public_fund.db"`。
- **关键**:`__file__` 不 resolve symlink → 云上 timer(全部 `WorkingDirectory=/home/ubuntu/code/trade-data`、`REPO=/home/ubuntu/code/trade-data`)跑 `"$PY" "$REPO/scripts/export_fund_nav.py"` 时,`__file__` = `/home/ubuntu/code/trade-data/scripts/export_fund_nav.py` → `ROOT=/home/ubuntu/code/trade-data` → import 的 `public_fund.__file__` 仍带 trade-data 前缀 → `DB_PATH=/home/ubuntu/code/trade-data/data/public_fund.db` = **主库**。
- 云上只读实测(模拟 timer 环境):
  ```
  cd /home/ubuntu/code/trade-data && .venv/bin/python -c "
  import sys; sys.path.insert(0,'/home/ubuntu/code/trade-data')
  import app.collector.public_fund as pf; print(pf.DB_PATH)"
  → /home/ubuntu/code/trade-data/data/public_fund.db
  ```
- 佐证:export_fund_nav.py docstring L41-42「输入依赖: $REPO/data/public_fund.db」「从 trade-data 跑读实时库写 trade-data/static-site/data/」;deploy.sh L302「显式 REPO=$REPO 读主库(单仓下 REPO 即主库)」。
- 结论:**export_fund_nav.py 读主库 `/home/ubuntu/code/trade-data/data/public_fund.db`**,不是 signal 库、不是 staticdata 库。

### 1.3 写一个库,其余库怎么同步

- **deploy.sh L557-561**(1.7 段):`rsync -a --exclude=logs/ --exclude=notify_dedup.json --exclude=alert_state.json --exclude=alerts/ --exclude=warning_*/ --exclude=backups/ --exclude=<4 个 seed 文件> "$REPO/data/" "$GIT_REPO/data/"` → 每次 deploy 把主库 data/ 全量同步到 signal 树(public_fund.db 未被 exclude,会同步)。
- **deploy.sh L1013-1034**:deploy 末尾 `systemd-run ... staticdata_backup_async.sh`(异步);该脚本 step1 L140 `rsync -a "$REPO/data/"*.db "$STATICDATA_REPO/db/"` → 主库 db 同步到 staticdata/db/。
- **update_all.sh L118**(产物方向,与 DB 无关):`rsync -a --delete "$REPO/static-site/data/nav_bucket/" "$GIT_REPO/static-site/data/nav_bucket/"`。
- 触发链:update_all.sh L149 `bash "$REPO/scripts/deploy.sh" all` → deploy 段1 export+R2+rsync、段2 git。
- 因此:**写主库后,副本自动同步的唯一途径 = 跑一次 deploy**(或其 1.7 rsync 段 + staticdata_backup_async step1)。补数执行链若只 UPDATE 主库不触发 deploy,**signal/staticdata 两副本保持损坏态直到下一次定时 deploy**,期间任何从副本库读取/恢复的环节读到坏数据 = 「补一半」。

### 1.4 结论:补数必须写哪几个库

| 库 | 路径 | 必须写? | 为什么 |
|---|---|---|---|
| 主库(REPO) | `/home/ubuntu/code/trade-data/data/public_fund.db` | **是(第一必须)** | export_fund_nav.py 读它(§1.2 实测);采集写它;产物正确性只依赖它 |
| GIT_REPO 副本 | `/home/ubuntu/code/trade-data-signal/data/public_fund.db` | **是(同步)** | 不写=副本保持损坏;deploy 会自动同步但需等下一轮,建议写主库后手动触发 deploy 或直接 rsync |
| STATICDATA 副本 | `/home/ubuntu/code/trade-data-signal-staticdata/db/public_fund.db` | **是(同步)** | 同上;灾备第2层,留坏数据=恢复会丢 |

**漏任一 = 「补一半」定义**:
- 漏主库 → export 读损坏态,产物(nav_bucket)仍坏 = 完全没补。
- 只写主库不触发同步 → 线上产物正确,但 signal/staticdata 两副本坏;任何读副本的环节(后续从 GIT_REPO 跑 export、从 staticdata 恢复/发布)不一致(§22 数据一致性铁律)。
- 最小充分动作:UPDATE 主库 → 跑一次 `deploy.sh`(自动带 1.7 rsync + staticdata_backup)或手动两路 rsync。

---

## 2. 前提二:完整缺失日期清单(9-15 至 10-03,云上主库只读 SQL)

### 2.1 逐日表(主库 `/home/ubuntu/code/trade-data/data/public_fund.db`)

命令:`SELECT date, COUNT(*), SUM(unit_nav IS NOT NULL), SUM(acc_nav IS NOT NULL) FROM fund_daily_nav WHERE date BETWEEN 20260915 AND 20261003 GROUP BY date ORDER BY date`

| date | total | unit_nav 有值 | acc_nav 有值 | 判定 |
|---|---|---|---|---|
| 9-15 | 26086 | 25267 | **0** | 本来就 0(非损坏,R2 快照 acc=None) |
| 9-16 | 26079 | 25262 | **0** | 本来就 0 |
| 9-17 | 26070 | 25278 | **21** | **损坏**(参考 21959,被清 -21938) |
| 9-18 | 26165 | 26087 | **0** | 本来就 0(接口现在可取) |
| 9-21 | 26125 | 25292 | **23** | **损坏**(参考 21956,被清 -21933) |
| 9-22 | 26139 | 25299 | **0** | 本来就 0(接口现在可取) |
| 9-23 | 26135 | 25320 | **25** | **损坏**(参考 21977,被清 -21952) |
| 9-24 | 26219 | 26164 | **54** | **损坏**(参考 22754,被清 -22700) |
| 9-28 | 26178 | 25313 | **0** | 有行但 acc_nav 空(数据源当时未发布) |
| 9-29 | 25827 | 24355 | **0** | 同上 |
| 9-30 | 25816 | 24353 | **0** | 同上(接口现已可取) |
| 10-01~10-03 | — | — | — | DB 无行(国庆休市+周末,正常) |

- `SELECT MAX(date) FROM fund_daily_nav` = `20260930`(10 月数据尚未采集;10-01~07 国庆休市,10-08 才开盘)。
- 参考值来源:审计 `fund-nav-accnav-clobber-audit-20261002.md` §1.3(signal 10-01 快照损坏前完整态):9-17=21959/9-21=21956/9-23=21977/9-24=22754;9-18/9-22 本来就是 0。
- 三库(signal/staticdata)逐日结果与主库**逐位一致**(复核报告 §1.4 独立 SQL 三库都跑过)。

### 2.2 9-28~30 专项核实(任务点名)

- 是「**有行但 acc_nav 为空**」,不是「整表无数据」:9-28 total=26178/unit=25313/acc=0;9-29 total=25827/unit=24355/acc=0;9-30 total=25816/unit=24353/acc=0。
- 云上日历(`app.calendar.is_trading_day`):**9-28/29/30 都是交易日(True)**;10-01/02/05/06/07 非交易日(国庆)。
- 审计判定「数据源当时未发布净值,本就非损坏」;但 10-03 天天基金接口实测已返回这三天值(000001 9-30=3.795,调研报告 §1)→ **数据源后来发布了,可补**。
- **结论:9-28/29/30 建议补**(交易日、接口可取、成本≈0),不因「非交易日」豁免。

### 2.3 9-15/16/18/22 判定(任务「不要预设只有四天」)

- 三库与审计一致:这 4 天 acc_nav 本来就是 0(审计 §1.5 表「9-1~9-16/9-18/9-22 本来就 0,无损坏」)。
- R2 旧快照 `fund_nav/`(9-22 批,损坏前源)抽样 4 只(000001/110022/005827/163402):9-15/16 acc_nav 全 None、9-18/22 **无此行**(当时接口没给)→ 不是被清,是数据源当时确实没发布。
- **但现在**接口实测已返回 9-15/16/18/22 值(000001 9-15=3.823/9-16=3.869/9-18=3.906/9-22=3.9;110022 同步可取,本查证补测)→ **可顺带补**。
- 结论:这 4 天属于「接口现在可取的非损坏缺口」,是否纳入补数由主控拍板(成本≈0,建议一并补,数据资产更完整)。

### 2.4 建议补的完整日期集合(按实测,非预设四天)

| 类别 | 日期 | 理由 |
|---|---|---|
| **必补(损坏,参考值明确)** | 9-17 / 9-21 / 9-23 / 9-24 | 被 10-02 stage0-nav 二轮 REPLACE 清空(88646→123),参考 21959/21956/21977/22754 |
| **建议顺带补(非损坏,接口已可取)** | 9-15 / 9-16 / 9-18 / 9-22 / 9-28 / 9-29 / 9-30 | 交易日;接口实测可取;9-28~30 非交易日豁免不成立(实测是交易日) |
| 不补 | 9-19/20/25/26/27、10-01~07 | 非交易日,DB 本无行(正常) |

执行时 `--dates 20260917,20260921,20260923,20260924` 为必补;追加 `20260915,20260916,20260918,20260922,20260928,20260929,20260930` 为全量 11 天。预期 acc_nav 有值行数回到参考值 ±(以 fix.db 实量为准)。

---

## 3. 前提三:补数窗口与风险

### 3.1 云上定时任务(只读 `systemctl list-timers --all` + `systemctl cat`)

| timer | OnCalendar | 写 public_fund.db? | 补数影响 |
|---|---|---|---|
| `trade-public-fund-daily` | 16:30 / 17:00 | **是**(fetch_daily_nav INSERT OR REPLACE) | **避开** |
| `trade-update-all` | 17:50 | 是(export_fund_nav 读 + deploy rsync 同步副本) | **避开**(补数撞上会导出半补态/同步半补副本) |
| `trade-public-fund-full` | 22:00 | 是(python -m app.collector.public_fund full) | 避开 |
| `trade-public-fund-quarterly` | 03:00/04:00/07:00 | 是(quarterly) | 避开 |
| `trade-public-fund-estimation` | 10:00/11:00/13:30/14:30 | 是(写 fund_estimation_nav,同库文件) | 避开 |
| `trade-pf-stage0-nav` | **Fri 01:43** | 是(stage0-nav --days 1825,已 UPSERT 化) | 见 3.2 |
| `trade-pf-score-daily` | 16:00 | 只读 DB 写 fund_score(不写 fund_daily_nav) | 无写冲突 |
| `trade-backup-db` | 21:00 | **不碰 public_fund**(只备份 sentiment+etf_national_team,backup_db.sh L77-78) | 无冲突 |
| `trade-s06-snapshot` / `trade-kelly-intraday-rerun` / 盘中系列 | 各时点 | 与 public_fund 无关 | 无冲突 |

### 3.2 10-09 周五 01:43 stage0-nav 核实(任务点名)

- **timer 真实存在**:`trade-pf-stage0-nav.timer` OnCalendar=`Fri *-*-* 01:43:00`,`systemctl list-timers --all` 输出 **下次 `Fri 2026-10-09 01:43:00 CST`(LEFT 5 days)**。
- **UPSERT 修复已在云上**:云上 `/home/ubuntu/code/trade-data-signal/app/collector/public_fund.py` L1131-1140 为「UPSERT 而非 INSERT OR REPLACE(2026-10-02 acc_nav 踩踏事故根治)」:`ON CONFLICT(date, fund_code) DO UPDATE SET unit_nav=excluded.unit_nav, nav_change_pct=COALESCE(...)` —— **不再 SET acc_nav/fund_name/prev_unit_nav**,不会再清 acc_nav。
- **结论**:补数在 **10-09 01:43 前完成**即无二次踩踏;即使 10-09 后跑,stage0-nav 也不会再清 acc_nav(只更新 unit_nav+nav_change_pct)。建议仍按排期在 10-09 前完成,更稳。

### 3.3 补数窗口建议

- **推荐窗口**:周末/假期白天(10-03/10-04 周六日、10-05~07 国庆休市均可),或 23:00 后;避开 16:30/17:50/22:00 及盘中 estimation 时点。
- 补数动作序列建议(执行 agent 侧):①备份主库 → ②本机全量拉取生成 /tmp/accnav_fix.db → ③scp + UPDATE 主库(只补 acc_nav IS NULL)→ ④**同步副本**(跑 deploy.sh 或手动 rsync REPO/data→GIT_REPO/data + REPO/data/*.db→staticdata/db/)→ ⑤重出 nav_bucket → ⑥上传 R2 → ⑦三库+线上验证。④ 是复核报告 P1 缺口补上的关键步骤。

---

## 4. 诚实标注(未验证项)

1. **9-15/16/18/22 全市场接口可补性未穷举**:只抽 000001/110022 实测可取;若拍板顺带补这 4 天,拉取脚本全量跑时自然覆盖(与 9-23/24 同链路)。
2. **9-28~30 接口可补性**:调研报告 §1 已实测 000001 9-30=3.795,本查证补测 000001/110022 全 7 天可取;未穷举全市场。
3. **拉取脚本 `repro_backfill_accnav.py` 未实跑**(只验证接口,脚本待实施侧运行)——与调研/复核报告一致。
4. **「写主库后跑 deploy 自动同步副本」未实际触发验证**:deploy.sh 1.7 rsync 段(L557-561)与 staticdata_backup_async step1(L140)均已读代码确认方向(REPO→副本),但本任务只读,未真跑一次 deploy 验证副本同步时效。实施时④同步步骤必须实际做+验证(三库 md5 比对)。
5. 三库 md5 `53df2a5d...` 为复核报告 §1.4 实测,本查证引用未重跑;实施前如需强校验可重跑 `md5sum` 三路径。

## 5. 复现段(命令速查,全部只读)

```bash
# 1) 三库拓扑 + symlink
ls -la /home/ubuntu/code/trade-data/ | grep "\->"
# 2) 三库 md5
md5sum /home/ubuntu/code/trade-data/data/public_fund.db \
        /home/ubuntu/code/trade-data-signal/data/public_fund.db \
        /home/ubuntu/code/trade-data-signal-staticdata/db/public_fund.db
# 3) export_fund_nav 读哪个库(模拟 timer REPO=trade-data)
cd /home/ubuntu/code/trade-data && .venv/bin/python -c "
import sys; sys.path.insert(0,'/home/ubuntu/code/trade-data')
import app.collector.public_fund as pf; print(pf.DB_PATH)"
# 4) 逐日缺失(主库)
python3 -c "
import sqlite3
c=sqlite3.connect('/home/ubuntu/code/trade-data/data/public_fund.db')
for r in c.execute(\"SELECT date, COUNT(*), SUM(unit_nav IS NOT NULL), SUM(acc_nav IS NOT NULL) FROM fund_daily_nav WHERE date BETWEEN 20260915 AND 20261003 GROUP BY date ORDER BY date\"): print(r)"
# 5) stage0-nav timer 下次触发
systemctl list-timers --all | grep stage0-nav
# 6) 云上 UPSERT 修复在不在
grep -n "ON CONFLICT(date, fund_code)" /home/ubuntu/code/trade-data-signal/app/collector/public_fund.py
```
