# 连板历史回补 dry-run 对账报告(2026-09-30)

> 结论先行:回补范围 = FAPI 边界全量(20210901~20260929,1230 交易日,**取数零失败零 gap**)。
> 重叠段(20260612~20260929,76 天)排除 ST 后一致率 **98.68%**(仅 1 天不等:20260717),
> 含 ST 对照一致率 85.53% —— 排除 ST 口径被数据验证。
> **FAPI 涨停池翻页取满(2026-09-30 复审 F1):7 个普涨截断日(涨停 >200)已按全量翻页修正最高连板**,
> 其中 20240930 由单页 5 → 12、20241008 由单页 6 → 13(各差 7 个板),翻页取满是最高连板口径的关键。
> **a_sentiment 影响(只补缺口实时口径):今日值基本不变(+0.29 分、无 freeze 翻转),近 60 交易日 58/60 天有微幅变化(最大 2.20),历史段(2021-2025)变化显著(全段 47% 日期变、34 天 is_freeze 翻转——翻转清单翻页前后逐日一致)**。
> 本轮**只做 dry-run,生产库零写入**(md5 逐字节验证);写生产库待用户另行授权。

---

## 1. 背景与根因(三层)

生产库 `daily_metric.a_width_max_lianban` 仅 20260612 起(现 77 天,云上库实测),历史缺值根因:

1. **`app/collector/width_history.py` 用 mootdx 回填 7 项宽度指标,唯独漏最高连板** —— mootdx 历史段每天仅 ~85 只样本股,推不出全市场最高连板。
2. **`app/backfill.py:44` skip 判据用 `_have("a_width_zt_count")`** —— zt_count 被全段回填后所有历史日 skip,连板从没补过。
3. **东财涨停池历史只滚动保留近 2-3 周** —— 一年前已清空,20260612 即起点。

**唯一可行历史源 = 同花顺官方 API(FAPI)涨停池**,实测 20210901 起逐交易日可用,字段 `continue_day_cnt` 等价东财「连板数」(映射见 `app/collector/fapi_fallback.py` `_zt_df`)。

## 2. 口径:ST 排除(最关键)

- **FAPI 涨停池含 ST 股,东财涨停池不含 ST**。实测 20260701:FAPI 全量 max=7(top=ST中装)vs 东财当时=3,全是 ST 撑的。
- 判定规则 = **名称字符串宽松包含子串 `"ST"`**(覆盖 `*ST` / `ST` / `SST` 等形态)。实测该日 FAPI 涨停池 200 行含 ST 52 行(含 ST中装/ST美芝/ST东智),排除后非 ST max=3,与东财一致。
- **排除开关有效性数据**:
  - 排除 ST:重叠段 76 天一致 75 天,**98.68%**。
  - 含 ST(仅对照):重叠段 76 天一致 65 天,**85.53%**,ALL 不等 11 天(20260617/0629/0630/0701/0702/0703/0706/0710/0713/0714/0717),其中 20260701 FAPI=7 vs 现库=3(ST 撑高)。

## 3. 交付脚本:`app/backfill_lianban.py`

逐交易日:`_fetch_zt_all_pages(d)`(FAPI 涨停池**翻页取满** page=1..pagination.pages,size=200) → 排除 ST → `max(连板数)` → 待 upsert。
- **翻页取满(2026-09-30 复审 F1 返工)**:FAPI 拒 size=2000、page=2&size=200 有效;单页 200 行上限在普涨日(涨停 >200)会截断尾部、漏掉更高连板——20240930/20241008 两日实测单页 vs 翻页 max 各少 7 个板。回补必须翻页,`app/collector/fapi_fallback.py` 既有行为(每日采集兜底仍 page=1&size=200)不动,由本脚本内部翻页。
- 参数:`--start`(默认 20210901)/ `--end`(默认昨天最近交易日)/ `--db <path>`(默认 app.db 默认库)/ `--dry-run`(默认,一行不写)/ `--write`(真写库,需用户授权)/ `--with-st`(含 ST 对照)/ `--out <json>`(对账明细落盘)/ `--fill-gaps-only`(默认只补缺口)/ `--overwrite`(覆盖已有非 manual 值,需另拍板)。
- 写库保护:`ON CONFLICT ... DO UPDATE SET ... WHERE daily_metric.source != 'manual'`(照抄 `width_history.upsert_width`,防覆盖手动补录),source=`'fapi'`;只补缺口模式再叠加 `AND daily_metric.value IS NULL`(竞态加固,复审 F7)。
- 重试/节流:照抄 `fapi_daily.py`(RETRY=3, BACKOFF=[5,15,30] 秒);成功请求间随机 sleep 0.3~0.8s 节流。
- **gap 处理**:FAPI 返回空/报错/全部被 ST 排除 → 如实记 gap(不静默当 0/跳过)。本轮实测 **gap=0**。

### 3.1 翻页取满实证(2026-09-30 复审 F1;涨停池 >200 行的 7 个截断日)

单页 size=200 的涨停池在普涨日(涨停 >200)会被截断——最高连板可能落在第 2+ 页尾部。按 `pagination.pages` 翻页取满后,1230 个交易日中共 **7 天**涨停池 >200 行,最高连板修正如下(全部为增量段):

| date | 单页 max | 翻页 max | 池总行数(排除ST后) | 差 |
|---|---|---|---|---|
| 20220429 | (单页截断) | **6** | 208 | 漏算尾部 |
| 20240208 | (单页截断) | **6** | 491 | 漏算尾部 |
| 20240219 | (单页截断) | **7** | 235 | 漏算尾部 |
| 20240417 | (单页截断) | **4** | 226 | 漏算尾部 |
| 20240930 | 5 | **12** | 664 | **-7 板** |
| 20241008 | 6 | **13** | 711 | **-7 板** |
| 20241028 | (单页截断) | **12** | 242 | 漏算尾部 |

> 对账佐证:20240930 当日真实为双成药业 12 连板(002693)、20241008 为 13 连板(东财公告/资讯可查),翻页值与原单页值差距 7 个板=翻页到第 2-4 页才拿到的高连板股被截掉。若沿用单页口径,回补的历史段最高连板数值系统性偏低,20240930/20241008 两日直接差 7。**回补必须翻页取满**。重叠段(20260612+)无 >200 行截断日,故重叠一致率 98.68% 结论不变。

## 4. dry-run 全量对账(20210901~20260929)

| 项 | 值 |
|---|---|
| 交易日 | 1230 |
| 成功 | 1230 |
| gap | 0(取数全成功) |
| 重叠段(现有值∩区间) | 76 天 |
| 重叠一致 | 75 天 |
| **重叠一致率** | **98.68%**(预期 ≥98%) |
| 增量段 | 1154 天(20210901~20260611) |

### 4.1 ALL 不等日(重叠段,仅 1 天)

| date | 现库值 | FAPI 值(排除 ST) | 说明 |
|---|---|---|---|
| 20260717 | 5.0 | 4.0 | 现库 source=akshare;当日 FAPI 涨停池仅 34 行(非 ST max=4=艾艾精工),疑似 FAPI 该日涨停池覆盖不全或东财侧含 5 连板股而 FAPI 缺(东财历史已不可查)。单日差异,如实保留。 |

### 4.2 纯增量段(20210901~20260611)按年聚合

| 年 | 交易日 | 成功 | gap | max 连板分布(min/max/众数) |
|---|---|---|---|---|
| 2021 | 81 | 81 | 0 | 2 / 17 / 6 |
| 2022 | 242 | 242 | 0 | 2 / 17 / 5 |
| 2023 | 242 | 242 | 0 | 2 / 14 / 4 |
| 2024 | 242 | 242 | 0 | 2 / 14 / 4 |
| 2025 | 243 | 243 | 0 | 3 / 15 / 5 |
| 2026(至0605) | 104 | 104 | 0 | 2 / 18 / 4 |

按月聚合明细见 `--out` JSON(`/tmp/lianban_dryrun/full_dryrun.json` `monthly` 数组,61 个月;含每月交易日/成功/gap/max 连板分布直方图/分位数)。

### 4.3 gap 清单

**0 天**。全量 1230 交易日 FAPI 均取数成功(排除 ST 后均至少有 1 只非 ST 涨停股可取 max 连板)。

### 4.4 只补缺口模式(dry-run,2026-09-30 用户拍板「现有 76 天一根汗毛不动」)

运行:`--start 20210901 --end 20260929 --db <prod副本>`(默认只补缺口,非 overwrite)。输出 `fillgaps_dryrun.json`。增量段值一律为**翻页取满**口径(§3.1,7 截断日已修正)。

| 项 | 值 |
|---|---|
| 交易日 | 1230 |
| 计划写入(缺口) | **1154 天**(=用户预期,全部为增量段 20210901~20260611) |
| 因已有值跳过 | 76 天(现有 20260612~20260929,全 source=akshare/intraday 非 manual) |
| 因 manual 跳过 | 0(现库无 manual 行) |
| gap | 0 |
| 重叠段写入 | 0 天(overlap_written=0,76 天全部跳过) |
| 重叠段对账 mismatch | 0(跳过日不计入,不再误报不等) |

**两条防线证明**:
1. 只补缺口跳过:现有 76 天于 fill-gaps-only 下全部 `skipped_existing`,不产生覆盖(手动打印/SQL 双层保护)。
2. `--end 20260611` 天然避开:本地验证 `_existing_map(20210901..20260611)` 返回 0 条,现有 `a_width_max_lianban` 最小日期 = 20260612 > 20260611 → 该回补区间全部位于现有段之前,零重叠、零触碰。即便用默认 end 到昨日(20260929),现有 76 天也因防线 1 全跳过。

**逐行零触碰证明**(key=metric+date,重放计划写到副本库后对比):
- 副本写入 1154 条后对比原库:`added_rows=1154`(全部为 `a_width_max_lianban`),`removed_rows=0`,`changed_rows=0`。
- **现有 a_width_max_lianban 77 天(20260612~20260930)逐位零变化(changed=0)**;全 230995 行中除新增 1154 行外,所有其它 metric 无任何新增/删/改。
- 证明「只补缺口」写库 = 仅新增缺口行,现有数据一根汗毛不动。脚本:`docs/scripts/verify_lianban_fillgaps_zerotouch.py`,重放 SQL 与 `app.backfill_lianban._upsert` 一致(manual `WHERE source!='manual'` 兜底)。

## 5. a_sentiment 影响实测(回补前 vs 回补后各算一遍)

> 方法:在临时副本上,`sent_before.db`(原样)vs `sent_after.db`(注入 1230 天回补值)各跑一次 `app.compute.sentiment.compute()+store()`(120 交易日滚动百分位,权重表 `sentiment.py:10-17`),对比 `score_daily.a_sentiment` 逐日 value / is_freeze。对比日期共 2602 天(库内 a_sentiment 全历史)。

### 5.1 今日值(20260930)

| | before | after | delta |
|---|---|---|---|
| a_sentiment | 42.92 | 43.21 | **+0.29** |
| is_freeze | 0 | 0 | 不变 |

### 5.2 影响口径:两个口径,真实写库只看「只补缺口」

> ⚠️ **口径关键(2026-09-30 复审返工补充)**:影响实测注入 `computed` 全量 1230 天 = **全量替换口径**(把重叠段 20260717 现库 5 也覆盖成 FAPI 4)。但真实写库是**只补缺口**,重叠段 76 天一根汗毛不动(`skipped_existing=76`,20260717 不会被覆盖)。下表两口径并列,**真实写库影响 = 只补缺口列**。

| 项 | 全量替换口径(旧报告/对照) | **只补缺口口径(真实写库)** |
|---|---|---|
| 近 60 日 changed | 58/60 天 | **58/60 天** |
| 近 60 日 max 变化 | 5.48(20260717,全量替换覆盖出的假象) | **2.20** |
| 全段 changed | 1220 天(旧单页估算)/ 1219 天(翻页修正) | **1219 天(47.0%)** |
| is_freeze 翻转 | 34 天 | **34 天**(清单完全相同) |

> 上表可见:近 60 日 max 从 5.48 → 2.20,差异正是**被全量替换口径误计的 20260717 覆盖**(现库 5→FAPI 4)。真实只补缺口写库不碰它,所以真实近端影响更小。

### 5.2a 近 60 交易日(只补缺口口径,真实写库)

- **变了 58/60 天**(仅 2 天未变)。
- 最大变化(绝对值)= **2.20**;变化分布 min=-2.20, max=+0.90, mean≈-0.14。
- **近 60 交易日内无 is_freeze 翻转**。

### 5.3 全段(2602 天,只补缺口口径)

- **变了 1219 天(46.9%)**;delta min=-15.60, max=+17.91, mean=-0.22。
- 绝对值最大前 10(节选):20240906 +17.91、20231023 +16.64、20220125 +16.18、20230428 -15.60、20250911 -15.04、20250811 -14.94、20240426 -14.17、20240429 -14.07、20260429 -13.96、20260615 -13.93。

> 注:全段 changed 由旧单页版估算 **1220 → 1219 天**,差异来源是 **F1 翻页修正确实改值**——翻页后 7 个截断日 max 上调,经 120 日滚动百分位窗传播,恰好使某 1 个历史日的 delta 归零(边界漂移)。只补缺口口径与翻页全量替换口径同为此数(1219),说明「重叠段不覆盖」对全段 changed 无额外影响(重叠段仅 20260717 一天值不同)。

### 5.4 is_freeze 翻转:34 天(全部在 2021-2025 历史段,近 60 交易日内 0 天;两口径清单完全一致)

- **True→False(原冰点被移除):29 天**—— 20210929、20211012、20211021、20211224、20220125、20220211、20220304、20220329、20220524、20221019、20221125、20221216、20221228、20221229、20230111、20230208、20230224、20230727、20230825、20230914、20231222、20240715、20240814、20240822、20240827、20240906、20240913、20250515、20251121。
- **False→True(新增冰点):5 天**—— 20221220、20240521、20240717、20240723、20250403。

> 翻转清单权威 = `/tmp/lianban_dryrun/sent_impact.json` `freeze_flips`(含 before/after 值);近 60 交易日窗口(20260701~20260930)内翻转 **0 天**。
> 翻页修正后重跑:flips 清单与旧单页版**逐日一致**(34 天无增减),说明 7 截断日 max 上调虽放大个别历史日 a_sentiment,但不改变任何一天的冰点翻转判定。

### 5.5 对线上展示的影响面(§23.3 举一反三)

is_freeze 消费点:
- `app/queries.py:1514-1518` 首页「近期冰点」(近 120 日 LIMIT 9)与 `:1538-1543`「情绪日历」(近 90 日)。
- **翻转 34 天全在 2021-2025,最近一条 20251121**,不在近 90/120 日窗口 → **首页冰点日历/情绪日历展示不受影响**。
- 但 a_sentiment **数值本身**(只补缺口口径近 60 日最大变化 2.20)会随回补后的重算变化 → 前端情绪分曲线(export `score_daily` → `sentiment-*.json`)会变。若未来用回补后数据重算并上线,需知此影响。
- **3y/5y/all 情绪曲线末值(20260930)**:今日值 before=42.92 → after=43.21,**末值 +0.29**;曲线中段(近 60 日)58/60 天微幅变化(最大 ±2.2 分)。若只补缺口写库后重算上线,三条曲线末值统一 +0.29、历史段(2021-2025)冰点日历少 29 个红点、多 5 个新增冰点。
- 其他 a_sentiment 消费:`app/scheduler.py`(每日重算)、`cross.py/fear_greed.py/market_summary.py`(下游评分)、`static-site/export.py`(导出)。

## 6. 零写入验证(必做)

对同一临时副本跑 dry-run 前后:
- `md5` 逐字节:**e59d1d33fc75ba385d7ff8aa12093fb6 → 相同(完全一致)**。
- `SELECT count(*), count(DISTINCT metric_id)`:**230995 | 205 → 相同**。
- 注:SQLite WAL 模式连接会产生空的 `-shm`/`-wal` 辅助文件,不影响主库内容(md5 证明主库零写入)。

## 7. 口径自查(§21/§22 一致性)

- 排除 ST 开关真实生效(4.1/4.2 的 98.68% vs 85.53% 对照)。
- 与既有 `width_history.py` / `backfill.py` 的 DB 连接、schema、upsert、source 命名风格一致(非自创)。
- FAPI 边界 20210901 为调研实测起点(FAPI 更早数据未验证,按用户拍板「补到 FAPI 边界全量」)。

## 8. 已知限制 / 风险(诚实标注)

1. **FAPI 涨停池分页 size=200**:已根治(2026-09-30 复审 F1)——回补脚本按 `pagination.pages` 翻页取满,7 个普涨截断日最高连板已修正(见 §3.1)。`app/collector/fapi_fallback.py` 每日采集兜底仍 page=1&size=200(既有行为冻结),若日度采集也需防截断另议。
2. **20260717 单日差异**(现库 5 vs FAPI 4):东财历史不可查,无法最终归因;疑 FAPI 该日覆盖不全。如实保留,不静默改现库。
3. **is_freeze 历史翻转**:回补后若全量重算 a_sentiment 并上线,历史段冰点日历将变化(34 天翻转),属 §23.7 冻结范畴,需用户对「是否用回补数据重算历史 a_sentiment」单独拍板。
4. **回补值自身不写生产库**:本轮 dry-run 产出 `full_dryrun.json` 的 `computed` 数组含全部 (date, value);真写库命令为 `python -m app.backfill_lianban --write --start 20210901 --end <昨天>`,须用户再次授权。

## 9. 顺手修正的过时文档

`docs/research/icepoint-shanghai-trader-20260930.md` §3.4 原写「用 mootdx 自算连板补历史」—— 实测 mootdx 历史段仅 85 只样本股,路径不可行;已改为指向 FAPI 正解 + 本报告。只改该处一处,依据=实测结论。

## 10. 复现段

```bash
# 1) 从云上只读拉取生产库副本(scp 仅读取,云上零写入)
mkdir -p /tmp/lianban_dryrun
scp -i ~/tdsignal.pem -o BatchMode=yes -o ConnectTimeout=15 \
  ubuntu@122.51.111.173:/home/ubuntu/code/trade-data/data/sentiment.db \
  /tmp/lianban_dryrun/prod_sentiment_copy.db

# 2) 全量 dry-run 对账(翻页取满版,2026-09-30 复审 F1 返工后;需在仓库根,PYTHONPATH 指向 repo 根可 import app)
cd /Users/linhuichen/code/trade   # 或 worktree
/Users/linhuichen/code/trade/.venv/bin/python -m app.backfill_lianban \
  --dry-run --start 20210901 --end 20260929 \
  --db /tmp/lianban_dryrun/prod_sentiment_copy.db \
  --out /tmp/lianban_dryrun/full_dryrun.json
#   → planned_write=1154 / skipped_existing=76 / skipped_manual=0 / gap=0
#   → 7 个截断日(涨停池>200 行)翻页取满后修正值:
#     20220429=6 / 20240208=6 / 20240219=7 / 20240417=4 /
#     20240930=12(单页 5,差 7 板)/ 20241008=13(单页 6,差 7 板)/ 20241028=12

# 3) 重叠段含 ST 对照(验证排除开关)
/Users/linhuichen/code/trade/.venv/bin/python -m app.backfill_lianban \
  --dry-run --start 20260612 --end 20260929 --with-st \
  --db /tmp/lianban_dryrun/prod_sentiment_copy.db

# 4) a_sentiment 影响实测(生成 sent_before.db / sent_after.db / sent_impact.json)
PYTHONPATH=<repo-root> /Users/linhuichen/code/trade/.venv/bin/python \
  docs/scripts/sent_impact_lianban.py \
  --prod /tmp/lianban_dryrun/prod_sentiment_copy.db \
  --rows /tmp/lianban_dryrun/full_dryrun.json \
  --work /tmp/lianban_dryrun

# 5) dry-run 零写入验证
cp /tmp/lianban_dryrun/prod_sentiment_copy.db /tmp/lianban_dryrun/zero_write.db
md5 /tmp/lianban_dryrun/zero_write.db            # 记前
/Users/linhuichen/code/trade/.venv/bin/python -m app.backfill_lianban \
  --dry-run --start 20210901 --end 20210910 --db /tmp/lianban_dryrun/zero_write.db
md5 /tmp/lianban_dryrun/zero_write.db            # 应完全相同

# 6) 只补缺口 dry-run + 逐行零触碰证明(§4.4)
/Users/linhuichen/code/trade/.venv/bin/python -m app.backfill_lianban \
  --start 20210901 --end 20260929 --db /tmp/lianban_dryrun/prod_sentiment_copy.db \
  --out /tmp/lianban_dryrun/fillgaps_dryrun.json        # 默认只补缺口
/Users/linhuichen/code/trade/.venv/bin/python \
  docs/scripts/verify_lianban_fillgaps_zerotouch.py \
  /tmp/lianban_dryrun/fillgaps_dryrun.json \
  /tmp/lianban_dryrun/prod_sentiment_copy.db \
  /tmp/lianban_dryrun/fill_test.db                     # PASS:仅新增1154行,其余零变化
```

复现所需文件:`app/backfill_lianban.py`(本次新增)+ `docs/scripts/sent_impact_lianban.py`(影响实测辅助脚本,本次新增)+ `docs/scripts/verify_lianban_fillgaps_zerotouch.py`(逐行零触碰证明,本次新增)+ `/tmp/lianban_dryrun/full_dryrun.json`、`sent_impact.json`、`fillgaps_dryrun.json`(对账/影响/只补缺明细,跑出的中间产物,不入 git)。

## 11. 后续待办(用户拍板)

1. **是否授权写生产库**:写库走**只补缺默认**(现有 76 天一根汗毛不动),云上执行完整步骤(备份/复核/执行/校验/回滚)见 `docs/ops/lianban-prod-write-checklist.md`——只写文档不执行,一带用户再授权才动。目标库为云上主库 `/home/ubuntu/code/trade-data/data/sentiment.db`(注意非 `trade-data-signal/data/sentiment.db` 旧镜像)。
2. **是否用回补后 lianban 重算历史 a_sentiment**:会改变历史段数值与 34 天 is_freeze 标记(§23.7 冻结范畴),需用户单独决策。
3. ~~FAPI 分页 size=200 截断~~ 已根治:回补脚本按 `pagination.pages` 翻页取满(§3);`app/collector/fapi_fallback.py` 每日采集兜底仍 page=1&size=200(既有行为冻结,§23.7),若日度采集也需防截断另议。
