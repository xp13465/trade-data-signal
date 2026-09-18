# 凯利 ETF 冻结分时点漂移根治(2026-09-18)

用户 2026-09-18 拍板「要根治」。B 级逻辑改动,只改两处脚本,不碰前端/数据产物。

## 根因

冻结表 `data/signal_kelly_etf_freeze.json`(key=`date|index_id|signal` → top1 ETF + track_score/track_tier/frozen_at)的冻结值 = 回测脚本「首次碰到该信号时点」用「当时 best_etf」就地补冻,**不锁定信号日**。

- 生产每天盘后跑回测 → 当天新信号当天冻结(正确)。
- 本机 dev sync 拉新 DB 后,本机冻结表停在旧日期,回测首次碰到 9-14~9-17 历史信号 → 用「本机今天(9-18)的 board_etf_map」重新冻结 → **冻结分漂移**。
- 实证:hs300 的 9-16 信号,云上冻结 track_score=**81.5**(9-16 当天冻,frozen_at=2026-09-16 16:34),本机 sync 后被重冻成 **78.7**(frozen_at=2026-09-18 08:06,9-18 map)。

## 根治方案(双保险)

### 改动① 回测脚本锁定时点 `scripts/signal_kelly_backtest.py`

`_resolve_etf(date, iid, sig, best_etf, freeze, latest_signal_date=None)`:

- 未冻结分支 + best_etf 有该指数时,新增判定:
  - `date < latest_signal_date`(YYYYMMDD 字符串字典序比较即数值序)→ 历史信号,缺失冻结值 → **拒绝补冻**,记入全局 `_FROZEN_MISSING_EVENTS`,返回 `(None, False)`。
  - 仅 `date == latest_signal_date`(当天盘后新信号)→ 走现有就地补冻逻辑。
- **实现顺序注意**(与直觉相反的部分):latest 判定必须在 `be = best_etf.get(iid)` **之后**。原因是 best_etf 里本就没有的指数(如 `sw_801030`/`csi_000813` 这些 track_score=None 被 `_build_best_etf` 过滤的新指数),其历史信号过去在云上也从未冻结(本来就无 ETF 可冻),若判定放最前会把这类信号**误记异常告警**。只有「有 ETF 可补冻但该信号日已过」才是真正的防御对象。
- 三个调用点传 latest_signal_date:
  - 全量档 needed_etfs 收集(L1583):传 `latest_signal_date = _etf_daily_today_ready()[1]`(etf_daily 全表 MAX(date))。**不能传 today_str**——today_str 在价格加载后才有值,而 needed_etfs 收集在价格加载前(顺序矛盾);etf_daily MAX 与其语义等价且提前可得。
  - 全量档分类循环(`_classify_buy_rows` L1355):`_classify_buy_rows` 新增 `latest_signal_date` 参数,compute 调用处传入。
  - 盘中档(`compute_intraday` L1739):传 `signal_date_str`(=T 日)。**绝不能用盘中 today_str**——盘中 today_str 是注入 T+1 真实开盘后的 next_date,会让所有 T 日信号 date < latest 被误判为"历史信号"拒绝(盘中档整个崩掉/空输出)。
- 回测结尾保存冻结表后,`_FROZEN_MISSING_EVENTS` 非空 → `notify.py --severe` 告警(文案含「冻结表缺失 N 个历史信号事件,拒绝补冻已跳过,请核查生产冻结流程」,dedup 1h 防轰炸)。

### 改动② dev sync 同步云上冻结表 `scripts/sync_dev_from_r2.sh`

- 新增 step2.1:rsync 云上权威冻结表 `/home/ubuntu/code/trade-data/data/signal_kelly_etf_freeze.json` → 本机双写 `trade-data/data/` + `trade/data/`。
- 顺序对齐:mmdownload-db → **rsync 冻结表(新增)** → build_board_etf_map → export → verify-r2。
- ⚠️ 冻结表不在 R2(s3 全 404 已实测),只能 rsync,不走 download-db。
- rsync 失败不阻断(降级为"回测触发拒绝补冻告警"兜底)。

## 验收记录

| # | 验收口径 | 证据 |
|---|---|---|
| 1 | py_compile 过;dry-run 三路径 | `python3 -m py_compile` PASS;`/tmp/test_resolve_etf.py` 全 PASS(①历史未冻→不补冻+记异常 ②当天未冻→补冻 ③已冻→返回冻结值 ④latest=None 兼容旧行为) |
| 2 | sync 后本机冻结表 md5==云上;9-16 hs300=81.5 | rsync 后本机两处 md5 均 = `0ac632a2`(==云上);9-16 hs300 track_score=81.5 code=515330 frozen_at=2026-09-16 16:34 |
| 3 | sync 后回测无告警、口径对齐 | 全量回测 rc=0,拒绝补冻告警**0 个**;回测后冻结表 md5 仍 = 云上,键集合零差异、同键值零差异(新固化=0,无漂移) |
| 4 | 不碰只读侧 | 只改 `scripts/signal_kelly_backtest.py` + `scripts/sync_dev_from_r2.sh`;`app/queries.py` `_align_home_top1_to_backtest` / `static-site/app.js` `_topEtfByScore` / `nextday_plan_generator.py` 均未动;不 bump 版本串 |

## 附加发现(排查中验证而非新问题)

对 `_iid_in_excluded_category` 不做改动(冻结读取侧剪枝保持原样)。排查确认:
- `signal_kelly_backtest_bond.py` 用独立临时 freeze,不写主冻结表 → 无需改。
- `nextday_plan_generator.py` 只读冻结表 → 无需改。
- `sw_801030`/`csi_000813` 等 track_score=None 被 best_etf 过滤的新指数,其历史信号在云上本来就未冻结(云上冻结表 0 条),正式非防御对象 → 判定顺序放 be 之后,不误告警。

## 复现路径

```bash
# 改动①自测
/Users/linhuichen/code/trade-data/.venv/bin/python /tmp/test_resolve_etf.py
/Users/linhuichen/code/trade-data/.venv/bin/python /tmp/test_intraday_sim.py

# 改动②完整跑(本机 dev sync,EXPORT_SKIP_R2=1 不上传)
bash scripts/sync_dev_from_r2.sh

# 全量回测验证无告警 + 冻结不漂移
cd /Users/linhuichen/code/trade-data && .venv/bin/python /Users/linhuichen/code/trade/scripts/signal_kelly_backtest.py --output /tmp/kelly_test_output.json
```

## 相关约束遵循

- §23.2 修 bug 三铁律:同类错误面已 grep(`freeze[key]`/`_save_etf_freeze`/写冻结表各处);自测覆盖主档+盘中档;根因修(回测脚本补冻逻辑)+ 配套数据同步(dev sync),非逐文件打补丁。
- §23.3 举一反三:冻结表写入逻辑确认仅 `_resolve_etf` 一处;`bond` 独立 freeze 确认不动;只读侧(queries.py/app.js/nextday_plan)确认不碰。
- §5.4 测试基准:current baseline(v1.1.7),本改动只修机制不改默认组合/算法,不发版本。
- §8/§24:本次只改后端脚本+sync 脚本,不动前端源码,不 bump 版本串;agent 只 commit+push feat,不 push main。