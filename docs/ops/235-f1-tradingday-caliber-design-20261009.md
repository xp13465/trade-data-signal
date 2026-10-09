# #235 F1:数据新鲜度校验「自然日 → 交易日」口径设计(只读调研)

- 日期: 2026-10-09 | 角色: 调研 agent(只读,未跑任何业务脚本、未外发)
- 对象: `scripts/check_data_integrity.py`(`_days_ago` 全部调用点) + `app/calendar.py`(复用) + `scripts/deploy.sh`(拦截点)
- 任务: #235 方案 B 的详细设计——把「数据过期几天」的判据从自然日改为交易日口径,根治长假后首日批量误报(deploy 自锁)
- 所有行号均为本次实读钉死;所有数字均有实测/日志来源,来源逐一标注

## 1. 结论摘要

1. **改 8 点 / 不改 2 点 / 保留 1 处既有降级**:`_days_ago` 共 1 定义 + 9 直接调用(全仓穷举,无间接包装),另加 1 处 mtime 版自然日(L739)一并改 → 合计 8 处替换为交易日口径 helper;2 处保留自然日(overview L267、fund_score L507,均为「每日驱动含假期」链,实证见 §6);`nextday_plan` 的「日历不可用宽限 7 自然日」降级(L1986)保留不动。
2. **核心公式**(纯日期粒度,无时刻依赖):

   ```
   lag = len(trading_days_between(date, today)) - (1 if is_trading_day(date) else 0); 再 clamp ≥ 0
   ```

   语义 = 「区间 (date, today] 内的交易日个数」(date 是交易日时不含自身)。稳态自洽:盘后校验当日数据 → 0;盘前校验昨日盘后数据 → 1;假期中/长假后首日校验假前最后交易日数据 → 0/1,全部不误报。
3. **新 helper `_lag_trading_days(date_str) -> int | None`**(插入 `_days_ago` 之后,保持原契约:解析失败返回 None),内含两道护栏:①日历未覆盖 today 时**回退自然日**(防跨年日历未刷新时静默放松);②任何异常回退自然日(fail-safe 保守)。
4. **10-08 02:06 实拦 6 项已实证钉死**(§2):alert/notifications/ad_line/a_stock/accum_nav_map_fresh/s06_state,全部 date=20260930 自然日 8 天 → FAIL;交易日口径下全部 lag=1 → OK(§4.3 数值表实测)。
5. **最大风险 = 交易日历覆盖断层**(不是 bug 是护栏缺口):`data/trade_dates.txt` 现尾部止于 20261231,若 2027 年前未刷新,`is_trading_day` 对 2027 年日期恒 False → lag 恒 0 → 校验静默放松。helper 的「`is_trading_day(last_trading_day(today))` 为 False 即回退自然日」判据专门挡这个(§4.2/§9.1)。
6. **次风险 = 真过期检出延迟变长**:交易日口径把 WARN 首现推到滞后第 4 个交易日、FAIL 推到第 8 个交易日(旧口径自然日 4/8 天)。真停更时发现变晚约 1~1.5 周,缓解见 §9.2(deploy 链每日运行 + WARN 可见 + 断链检查已有)。
7. **附注(#236 关联,不在本实施规格内)**:alert.json 的 R2 上传唯一通道在 check 之后(自锁),10-08 全天 ≥15 轮 deploy 被拦。本设计修掉 6 项误报后 alert 自锁的触发面大幅减小,但**结构性自锁仍在**(#236 专项)——可选增强:照 s06 ①b 先例(L2164-2187)给 alert 增补「本地 vs R2 差异只 WARN」,**必须 WARN 不能 FAIL**(同防死锁理由)。

## 2. 「02:06 拦了哪 6 项」实证(实读日志,非任务书转述)

### 2.1 日志原文 6 条

来源:`/tmp/deploy_20261008_0206.log`(本机副本,602 行;云上原件 `/home/ubuntu/code/trade-data/data/logs/deploy_20261008_0206.log`):

```
L553   ✓ overview: date=20261007 (滞后 1 天)          ← 每日驱动链,假期照常推进(不改的实证)
L557   ✗ alert: alert.json date=20260930 滞后 8 天 > 7 天
L558   ✗ notifications: notifications.json date=20260930 滞后 8 天 > 7 天
L560   ✓ fund_score: date=20261007, count=2000 (滞后 1 天)  ← 每日驱动链,同上
L561   ✗ ad_line: ad_line.json 最后日期=20260930 滞后 8 天 > 7 天
L562   ✗ a_stock: a_amount 最后日期=20260930 滞后 8 天 > 7 天
L566   ✓ signal_accum_nav_lag: 信号日 20261001 vs accum_nav 日 20260930 滞后 0 交易日  ← 交易日口径先例,正常
L568   ✗ accum_nav_map_fresh: accum_nav_map.json 最新 nav 日期=20260930 滞后 8 天 > 7 天(净资产曲线/强平日真价停更)
L571   ⚠ trade_sim_indices: trade_sim_indices.json mtime 滞后 7 天 > 3 天
L580   ✗ s06_state: 线上 S06 快照 coverage_end=20260930 滞后 8 天 > 7 天
L595   === 汇总: 34 ok / 2 warn / 6 fail ===
L596   ✗ 数据产物校验失败(退出码 1)，终止部署（4 类事故拦截）
L602   [notify][dedup] 更新 key=deploy_check_data_integrity_fail last_alerted=now
```

6 项对应代码位置:alert→L428、notifications→L456、ad_line→L541、a_stock→L573、accum_nav_map_fresh→L996、s06_state→L2210(R2 路径)。

### 2.2 时间线(三档对照,全部来自日志实读)

| 时点 | 6 项状态 | 汇总 | 说明 |
|---|---|---|---|
| 10-07 21:05 档 | 6 项 ⚠ 滞后 7 天(不拦) | 34 ok / 8 warn / 0 fail | 自然日 7 天 >3 触发 WARN、不 >7;文档 L50 |
| 10-08 02:06 档 | 6 项 ✗ 滞后 8 天(拦) | 34 ok / 2 warn / 6 fail | 跨入第 8 天,纯阈值边界;拦截在**任何写线上步骤之前**(日志止于 L597-602 notify+dedup,无 rsync/R2/git 行) |
| 10-08 21:00 backfill 后 | 5 项自愈,仅 alert 1 项 fail | 39 ok / 2 warn / 1 fail | `/tmp/bf1008_full.log` L996-1014:notifications/ad_line/accum_nav_map/trade_sim 均 date=20261008 滞后 0 天自愈;s06 coverage_end=20261008 ✓;唯一残留 alert(自锁,#236) |

s06 的档间行为差异(§3 逐点核对用):10-07 自然日 7 天仍 ≤7 → 本地门槛 `local_fresh=True` → 走 ① 本地互证 + ①b R2 比对 → PASS;10-08 自然日 8 天 >7 → `local_fresh=False` → 降级走 ② R2 路径 → R2 coverage_end=20260930 8 天 → FAIL。**同一条链一天之差由 allow/deny 翻转,纯口径问题**。

### 2.3 诚实标注(时间线出入与未测项)

- 任务书称「今天(2026-10-09)02:06 拦了 6 项」;实据为 **2026-10-08** 02:06(6 项与描述完全吻合)。10-09 02:06 档云上日志**未测**(本机 ssh 无法连通云上,两次尝试失败后按约束停止);按 10-08 21:32 状态推断:10-09 凌晨若跑,最多剩 alert 1 项(其余已自愈)。
- 10-08 拦截发生在 deploy 段 1 的 check 处(L323-324,"数据产物校验失败…终止部署"),**拦截在任何线上写之前**,线上零污染(用户看到的是 09-30 完好数据,属假期正确状态)。

## 3. `_days_ago` 调用点穷举(9 直接 + 1 mtime 版)与逐点定性

### 3.1 穷举方法与「间接包装」排查

- `grep -n "_days_ago" scripts/check_data_integrity.py` → 1 定义(L156)+ 9 调用(L267/428/456/507/541/573/996/2141/2210)。
- 全仓 `grep -rn "_days_ago" --include="*.py" --include="*.sh"` → 仅本文件;无其他文件的 import/包装/重导出。
- 唯一外部引用: `scripts/test_188_s06_sync_blindspot.py` L356 调 `ci.check_s06_state_snapshot(dd)`(测试 D 段,只测 ①b R2 比对;其构造的 `coverage_end=today` 在改口径后 lag=0,兼容,见 §7.4)。
- 另 1 处同类但非 `_days_ago` 的自然日:`check_trade_sim_indices` 的 mtime 版 L739 `days = (datetime.now() - mtime_dt).days`(语义相同,一并纳入)。
- `_days_ago` 本体(L156-162)实读契约: `def _days_ago(date_str: str) -> int | None`,try/except `(ValueError, AttributeError)` → **解析失败返回 None**(不抛异常);调用点统一以 `if days is None:` 分支处理。新 helper 保持此契约不变。

### 3.2 定性总表

| # | 行号 | 校验项 | 数据链节奏(证据) | 建议 | 理由 |
|---|---|---|---|---|---|
| 1 | L267 | overview | **每日驱动含假期**(10-08 日志 date=20261007) | **不改** | 假期照常推进,无日历空档;改反而歪 |
| 2 | L428 | alert | 交易日驱动(date=最新 sh K 线日,export_alert.py L196) | **改** | 假期不更新属正常节奏(§2) |
| 3 | L456 | notifications | 交易日驱动(date=_today_str(),export_notifications.py L108) | **改** | 同上;阈值 >1 语义=容忍 1 交易日(盘前时点) |
| 4 | L507 | fund_score | **每日驱动含假期**(10-08 日志 date=20261007) | **不改** | 公募评分链逐日跑,报告期类 |
| 5 | L541 | ad_line | 交易日驱动(daily_metric 交易日数据) | **改** | 同上 |
| 6 | L573 | a_stock | 交易日驱动(a_amount 日行情) | **改** | 同上 |
| 7 | L739 | trade_sim_indices(mtime) | 交易日驱动(update_lab.sh L36/L81-89 交易日 gate) | **改** | 假期文件不动属正常;10-08 时 7 天 WARN 即此因 |
| 8 | L996 | accum_nav_map_fresh | 交易日驱动(nav=交易日真价;deploy 段1 每日生成但数据源停于 09-30) | **改** | docstring L985-986 自称"自然日+周末/节假日自然滞后不误报"是**错误认知**,与 10-08 实拦矛盾 |
| 9 | L2141 | s06 本地门槛 | 交易日驱动(s06_snapshot.sh L75-79 gate) | **改** | 与 L2210 必须同口径改,否则本地门槛/线上校验分裂(§2.2 一天翻转实证) |
| 10 | L2210 | s06 R2 新鲜度 | 同上 | **改** | 同上;WARN 阈值 +1(跨日容忍)保留 |

### 3.3 逐点细节(现行为 → 建议 → 风险)

1. **L267 overview(不改)**:L266-275,`date_str = data.get("date")`(overview.json,来源 score_date=last_trading_day() 回退 a_sentiment max)。自然日判定 WARN>3/FAIL>7。10-08 日志 date=20261007 滞后 1 天——**假期内也推进**,自然日天性正确。改交易日会引入"假期中 date=假期日→?"的无谓歧义。**风险:无**(维持现状)。
2. **L428 alert(改)**:L427 注释"alert 是盘后日频,允许滞后 1 天"。判定 FAIL>7、WARN>STALE_DAYS_WARN+1(=4)。改后语义:>4 交易日 WARN(url 级)、>7 交易日 FAIL。**风险:检出延迟**(§9.2);另注意 alert 生成的 date 锚=最新 sh K 线日,若 K 线采集停更,交易日口径仍能检出(日期不变→lag 涨)。
3. **L456 notifications(改)**:判定 FAIL>7、WARN>1。改后:>1 交易日 WARN(隔 1 个交易日没更新=生成链可疑)。10-08 21:00 自愈实证 date=20261008 滞后 0 天。**风险:无特殊**。
4. **L507 fund_score(不改)**:L508-519,date=MAX(score_date) from fund_score 表(export_fund_score.py L135-146),公募评分链逐日驱动含假期(10-08 日志 date=20261007 滞后 1 天)。**风险:无**。
5. **L541 ad_line(改)**:date=最后一条 daily_metric(交易日数据)。判定同 alert 模式(FAIL>7/WARN>3)。**风险:无特殊**。
6. **L573 a_stock(改)**:`days = _days_ago(last_date)`(a_amount.data[-1].date);判定 `days is not None and days > ...`,保留 None 处理。**风险:无特殊**。
7. **L739 trade_sim_indices(改)**:mtime 版 L736-747。改法: `days = _lag_trading_days(mtime_dt.strftime("%Y%m%d"))`,None 防御回退自然日(见 §7.2)。10-08 02:06 时为 WARN(7 天),改后 lag=1→OK。**风险:mtime 时区依赖**(§9.4)。
8. **L996 accum_nav_map_fresh(改)**:L996 `days = _days_ago(last_dt)`(max 日期)。**同日必须修正 docstring L985-986**(错误认知与实现矛盾)。10-08 02:06 FAIL 的第二高嫌疑(6 项之一),21:00 自愈实证(date=20261008)。**风险:无特殊**。
9. **L2141 s06 本地门槛(改)**:L2140-2144,`days = _days_ago(cov_end)` → `local_fresh = days <= STALE_DAYS_FAIL`。**该 days 不直接 FAIL,只决定分支**(新鲜→①本地互证+①b;不新鲜→②降级 R2 路径)。改后长假后首日 lag=1 → 走 ① 本地互证(正确:该验"将上传的快照");真过期(≥8 交易日)→ 仍走 ② 降级由 L2214 FAIL。**风险:与 L2210 必须同时改**(单改一处会造成分支/阈值分裂)。
10. **L2210 s06 R2 新鲜度(改)**:L2213-2216,FAIL>7、WARN>STALE_DAYS_WARN+1(=4)。L2206-2208 注释表明设计意图已是"交易日兜底(check_s06_freshness)"。**风险:无特殊**。

## 4. 复用件:`app/calendar.py` 三函数语义 + helper 设计

### 4.1 三函数实读语义(app/calendar.py)

| 函数 | 行 | 语义(实读) | 边界 |
|---|---|---|---|
| `is_trading_day(d=None)` | L66-75 | d=None→今天;传 str(自动去 `-`)或 date;查 `data/trade_dates.txt` 集合(源=akshare `tool_trade_date_hist_sina`,L17-28 首次落盘缓存);**日历为空时降级 weekday<5** | 日历存在但日期超出覆盖范围 → 返回 False(与"假期"不可区分!→ helper 护栏处理) |
| `last_trading_day(d=None, max_lookback=15)` | L78-87 | 返回 `<= d` 最近交易日 `"YYYYMMDD"`(str);含当天;前找 15 天找不到 → **兜底返回输入 d 自身**(即使不是交易日) | 覆盖正常时返回值必是交易日(可用作覆盖判据,见 4.2) |
| `trading_days_between(start, end)` | L90-100 | 返回 `[start, end]` **闭区间**交易日 list[str];start>end → 空列表 | 类型 str/date 均可(`_to_yyyymmdd` 归一) |

数据文件:`data/trade_dates.txt`(79172 字节,本机存在;内容含 20261008/09/12…,尾部止于 20261231 → 跨年覆盖风险 §9.1)。

### 4.2 新 helper 方案(建议插入 `_days_ago` 之后,L162 后)

```python
def _lag_trading_days(date_str: str) -> int | None:
    """解析 YYYYMMDD,返回交易日口径的「滞后交易日数」(最近交易日数据=0)。

    口径: 区间 (date, today] 内的交易日个数(date 是交易日时不含自身;非交易日按其后交易日计)。
    周末/假期自然空档不计滞后(根治长假误报);日历不可用/未覆盖 today 时回退自然日口径
    (宁可保守,不静默放松)。解析失败返回 None(与原 _days_ago 契约一致)。
    """
    try:
        d = datetime.strptime(date_str.strip(), "%Y%m%d")
    except (ValueError, AttributeError):
        return None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 先例同款 L901-902
        from app.calendar import is_trading_day, last_trading_day, trading_days_between
        today = datetime.now().date()
        if not is_trading_day(last_trading_day(today)):
            # 日历未覆盖 today / 不可定位交易日 → 回退自然日,防跨年未刷新时静默放松
            return (datetime.now() - d).days
        ds, ts = d.strftime("%Y%m%d"), today.strftime("%Y%m%d")
        n = len(trading_days_between(ds, ts))
        return max(n - (1 if is_trading_day(ds) else 0), 0)
    except Exception:
        return (datetime.now() - d).days  # fail-safe: 日历不可用退自然日(旧行为)
```

覆盖护栏判据推演(`is_trading_day(last_trading_day(today))`):
- 覆盖正常+今天交易日:last_trading_day(today)=today,is_td=True → 用交易日口径 ✓
- 覆盖正常+今天假期:前推找到最近交易日,is_td=True ✓
- **日历未覆盖 today**(today 超 20261231):前找 15 天全 False → 返回 today 自身 → is_td(today)=False → **回退自然日** ✓
- 日历文件缺失/为空:is_trading_day 降级 weekday<5,last_trading_day 亦降级 → is_td(工作日)=True → 交易日口径=weekday 启发式(可接受)✓
- 极端:连续 >15 天无交易日(现实不存在) → 误回退自然日=旧行为,保守可接受。

### 4.3 实测数值表(today 视角,本机运行 app/calendar 真实日历,15 组)

| date | today | between(个) | 新 lag | 旧(自然日) | 场景 |
|---|---|---|---|---|---|
| 20260930 | 20261008 | 2 | **1** | 8 | **长假后首日,6 项误报场景 → 改后 OK** |
| 20260930 | 20260930 | 1 | 0 | 0 | 数据=今日 |
| 20261008 | 20261008 | 1 | 0 | 0 | 稳态盘后 |
| 20261008 | 20261009 | 2 | 1 | 1 | 盘前查昨日盘后数据 |
| 20260930 | 20261009 | 3 | 2 | 9 | 首日后仍未更新 |
| 20260930 | 20261012 | 4 | 3 | 12 | (周一) |
| 20260930 | 20261013 | 5 | **4** | 13 | **WARN 首现档(>3)** |
| 20261009 | 20261013 | 3 | 2 | 4 | 相对滞后 |
| 20260930 | 20261014 | 6 | 5 | 14 | alert/s06 WARN 首现档(>4) |
| 20260930 | 20261016 | 8 | 7 | 16 | 边界:7 天仍 WARN |
| 20260930 | 20261019 | 9 | **8** | 19 | **FAIL 首现档(>7)** |
| 20261019 | 20261008 | 0 | 0(旧 -11) | — | 未来日期 clamp 0(旧口径负数也不报,等价) |
| 20261007(假期) | 20261008 | 1 | 1 | 1 | 假期日期按其后交易日计 |
| 20261005(假期) | 20261008 | 1 | 1 | 3 | 同上(旧口径 3 天已近 WARN) |
| 20260930 | 20261010(周六) | 3 | 2 | 10 | 周末 today 不误报 |

补充实读:`is_trading_day(20261008)=True`、`is_trading_day(20261009)=True`;`last_trading_day(20261008)=20261008`、`last_trading_day(20261005)=20260930`。
注:事故文档 L11 表述"交易日差=0"指 09-30 收盘后至 10-08 凌晨无已收盘交易日;本公式为纯日期粒度(含当日=1),两口径对误报判定完全等价,本公式无时刻依赖更稳。

## 5. 先例复用分析(3 个 + 1 个增强参照)

1. **`signal_accum_nav_lag`(L899-907)` 可复用的模式**(不能直接照搬):`sys.path.insert` + `trading_days_between` + `max(..., 0)` + try/except fail-secure(其 except 直接 `_fail`,因它是断链级检查);方向不同(它是"信号日领先 nav 日"的差值,本设计是"date 距今滞后")——公式形态不同,但"借用 app.calendar + clamp + 异常保守"三要素直接沿用。10-08 日志 L566"滞后 0 交易日"证明其长假后行为正确。
2. **`nextday_plan`(L1966-1987)**:allowed 集合(最近交易日/上一交易日/下一交易日/today)+ 日历异常时降级"7 自然日宽限"。**降级回退思想与 helper 一致**;其"allowed 集合"模式不适用本设计(本设计是连续 lag,不是集合匹配)。
3. **s06 ①b(L2164-2187)"只 WARN 不 FAIL"防自锁先例**:该先例明文记录"本函数在 deploy.sh L324 先于 R2 上传执行, FAIL 会 abort deploy → R2 永不上传 → 死锁"。**本设计遵循同一原理**:8 处替换均为"同位置同阈值、仅换口径",不新增任何 FAIL 语义;唯一的可选增强(alert R2 比对)也必须 WARN(§9.3)。
4. **(增强参照)check_s06_freshness.py**:独立的交易日兜底链(以 index ohlc 数据锚标尺),本设计不动它;它印证了"s06 日常新鲜度应由交易日逻辑兜底"的设计意图(见 L2206-2208 注释)。

## 6. 「不改」清单(反例核对)与理由

| 项 | 行号 | 理由(证据) |
|---|---|---|
| overview.json 新鲜度 | L267 | 每日驱动含假期:10-08 02:06 日志 date=20261007 滞后 1 天(假期日照常推进,自然日无空档) |
| fund_score.json 新鲜度 | L507 | 同上:同日 date=20261007 滞后 1 天(公募评分链逐日驱动) |
| nextday_plan 日历降级分支 | L1986 | 既有设计:日历不可用→7 自然日宽限;属"降级路径"本身,保留 |
| check_s06_freshness.py | — | 已是交易日逻辑,不在本次 `_days_ago` 范畴 |

## 7. 实施规格(逐文件逐行号)

### 7.1 新增 helper
`scripts/check_data_integrity.py`:在 L162(`_days_ago` 结束)之后插入 §4.2 的 `_lag_trading_days`(约 20 行)。文件头已有 `sys`/`Path` import(先例 L901-902 同款用法),无新依赖。

### 7.2 替换表(8 处)

| # | 行号 | 现文本 | 改为 |
|---|---|---|---|
| 1 | L428 | `days = _days_ago(date_str)` | `days = _lag_trading_days(date_str)` |
| 2 | L456 | `days = _days_ago(date_str)` | `days = _lag_trading_days(date_str)` |
| 3 | L541 | `days = _days_ago(date_str)` | `days = _lag_trading_days(date_str)` |
| 4 | L573 | `days = _days_ago(last_date)` | `days = _lag_trading_days(last_date)` |
| 5 | L739 | `days = (datetime.now() - mtime_dt).days` | `days = _lag_trading_days(mtime_dt.strftime("%Y%m%d"))` + 下一行 `if days is None: days = (datetime.now() - mtime_dt).days`(防御式,strftime 恒合法) |
| 6 | L996 | `days = _days_ago(last_dt)` | `days = _lag_trading_days(last_dt)` |
| 7 | L2141 | `days = _days_ago(cov_end)` | `days = _lag_trading_days(cov_end)` |
| 8 | L2210 | `days = _days_ago(cov_end)` | `days = _lag_trading_days(cov_end)` |

判定阈值、消息结构、None 分支**全部不动**(仅换口径来源)。

### 7.3 文案修正(可选但建议,防"交易日口径说天"误导)

- 各 FAIL/WARN 消息"滞后 {days} 天"→"滞后 {days} 交易日":alert L432/434/436、notifications L460/462/464、ad_line L545/547/549、a_stock L575/577、trade_sim L743/746/747、accum_nav_map L1000/1002/1003、s06 R2 L2214/2216。参照先例文案 L914"滞后 0 交易日"。
- `accum_nav_map_fresh` docstring L985-986 **必须修正**(现文与实现矛盾):"口径与 check_overview 一致(自然日 + 周末/节假日自然滞后不误报)"→ 改为交易日口径描述(check_overview 不改,勿再写"与 check_overview 一致")。
- overview/fund_score(L271-275/L511-519)不改的 2 点文案保持"天"不动(口径未变)。

### 7.4 测试影响(已核)

- `grep scripts/tests/*.py` 无 "滞后"/"_days_ago" 断言(仅 test_alert_denoise 无关命中)→ 文案改动安全。
- `scripts/test_188_s06_sync_blindspot.py` L356 调 `check_s06_state_snapshot(dd)`:其构造 coverage_end=today → 改后 lag=0 ≤7 → 走 ① 本地互证分支 → 与测试预期一致(测试只 stub `_fetch_r2_json` 测 ①b;today 为交易日时 lag=0,非交易日时 between(today,today) 为空 len=0 → lag=0,两态同)。兼容 ✓。
- `deploy.sh` 只读 check rc(L323-331)→ 无脚本层断言依赖消息文本。

## 8. 双向验收判据 + 判定矩阵

### 8.1 判据 A:长假后首个交易日不误报(核心目标)

- 复现口径:6 项数据 date=09-30、today=10-08 → 全部 lag=1(§4.3 实测)。
- 逐项预期:alert lag=1(≤4 OK)、notifications lag=1(≤1 OK)、ad_line lag=1(≤3 OK)、a_stock lag=1(≤3 OK)、accum_nav_map lag=1(≤3 OK)、s06 R2 lag=1(≤4 OK)+ s06 本地 lag=1 → `local_fresh=True` 走 ① 互证。
- 时点无关性:对上表任一"假期 date + 长假后首日"组合,lag 均 ≤1。

### 8.2 判据 B:真过期仍报(WARN/FAIL 均按交易日计)

判定矩阵(改后):

| 项 | WARN | FAIL |
|---|---|---|
| alert / s06 R2 | lag ≥5(>4) | lag ≥8(>7) |
| notifications | lag ≥2(>1) | lag ≥8 |
| ad_line / a_stock / accum_nav_map / trade_sim | lag ≥4(>3) | lag ≥8 |

- 构造法(验收日无关,可跨日复跑):T0=今天;A=last_trading_day(T0);B=last_trading_day(T0-1d);C=last_trading_day(T0-8d)。断言 `_lag_trading_days(A)==0`、`(B)==1`、`(C)==8`;文件级:把某项 JSON 的 date 改为 C → 该项 FAIL;改为 last_trading_day(T0-5d) → alert/s06 WARN(≥5)、notifications WARN、ad_line/a_stock/accum_nav WARN(≥4)。

### 8.3 判据 C:边界

- date=today → 0;date=未来 → 0(不报);date=假期日 → 按其后交易日计(§4.3);日历缺失/未覆盖 → 回退自然日(可用临时目录+monkeypatch 构造验证,或人工审代码)。

### 8.4 判据 D:回退路径

- 模拟日历未覆盖(把 trade_dates.txt 换成尾部早于 today 的副本)→ `_lag_trading_days` 应返回自然日值(实测法:临时改 `_CACHE_PATH`?只读验收建议直接在测试环境副本上做,不碰生产文件)。

## 9. 风险与护栏

### 9.1 最大风险:交易日历覆盖断层(跨年)
`data/trade_dates.txt` 现尾部=20261231。若 2027 前未刷新(`refresh_trade_dates`,app/calendar.py L31-55,每交易日闭市后调用):`is_trading_day` 对 2027 日期恒 False → 若 naive 实现,lag 恒 0 → **校验静默放松**(比误报更危险的失效方向)。**护栏已内建**(§4.2):`is_trading_day(last_trading_day(today))` 异常判据 → 回退自然日(保守旧行为)。另建议运维侧:给 trade_dates.txt 的 max<today 加一条可见性告警(可选项,独立于本设计)。

### 9.2 次风险:真过期检出延迟变长(量化)
- WARN 首现:滞后第 4 个交易日(旧:自然日 4 天);FAIL 首现:第 8 个交易日(旧:自然日 8 天)。长假场景(如 09-30 后真停更):旧口径 10-04 WARN / 10-08 FAIL;新口径 10-13 WARN / 10-19 FAIL(§4.3 实测锚点)。
- 缓解:①deploy 链每日运行,WARN 级输出持续可见;②已有断链级检查(`signal_accum_nav_lag`)与 `check_s06_freshness` 交易日兜底;③生成链自身失败有 notify(各 export 脚本链路)。
### 9.3 alert 自锁(#236 关联,范围外但必须联动知晓)
alert.json 的 R2 上传唯一通道=deploy.sh L582,在 check(L323-324)之后;check FAIL ⇒ R2 永不上传(结构性死锁,#236 专项)。本设计修掉 6 项误报后,自锁触发面大幅减小但结构仍在。**可选增强**(不在本实施规格):照 s06 ①b(L2164-2187)给 alert 增补"本地 vs R2 差异只 WARN"——**必须 WARN 不能 FAIL**(同防死锁,先例注释明示)。本机 `static-site/data/alert.json` 存在(date=20260918 旧残留),增强可实施。

### 9.4 其它
- mtime(§7.2 #5)与 `datetime.now()` 均依赖运行机时区(云上 = 北京时间,deploy 日志 02:06 与调度一致);本设计未改变该假设,非新增风险。
- 节假日表来源=akshare sina 表(权威);`tool_trade_date_hist_sina` 每年更新次年(实现已有安全刷新 L31-55:拉取失败保留旧缓存)。

### 9.5 未测/限制(诚实标注)
- 10-09 02:06 云上档未验证(ssh 不通,标未测;按 10-08 21:32 状态推断最多剩 alert 1 项)。
- 10-07 21:05 档、10-08 05:00 档数据引自事故定性文档 `docs/ops/deploy-integrity-fail-20261008-0206.md`(L50/L121),未直接读云上原件。
- 线上 curl fund_score.json 曾得到 date=20260828 与日志 20261008 矛盾(疑 CF 缓存),记录为异常,不深究,不影响本设计结论。

## 附:证据文件索引
- 拦截日志: `/tmp/deploy_20261008_0206.log`(本机副本);`/tmp/bf1008_full.log`(10-08 21:00 backfill 链)
- 事故定性: `docs/ops/deploy-integrity-fail-20261008-0206.md`(L11/L44/L50/L121)
- 自锁专项: `docs/ops/deploy-integrity-selflock-20261008.md`
- 核心代码: `scripts/check_data_integrity.py`(改点 §7);`app/calendar.py`(复用件 §4.1)
