# #333 批1 FOF/QDII 净值独立采集器 方案(§5.7 三件套)

> 立项:用户 2026-11-01 拍板,走方案 A(独立采集器走历史 API,止漏核心)。批1 只做止漏,不碰批2/批3(份额类清理/定开识别/历史回填)。
> 调研根因全文:/tmp/agent-progress-research-333.md。

## 一、可修正的依据(§5.7①,带行号/实测)
1. **根因代码锚点**:`app/collector/public_fund.py:873 fetch_daily_nav()` 用 `ak.fund_open_fund_daily_em`(东财每日快照,只最新 2 日列)+ 只写 `target_date` 单日(`:941 rows.append((today_str, ...))`)+ 次新列只喂 `prev_unit_nav`(`:919-925`)+ 无回填(`:957-969` COALESCE 只保留非空)。FOF/QDII T+1/T+2 跨日发布,16:20/17:00 采集时当日 `unit_nav` 列为空→写 NULL,次日 target_date 滚到 T+1,FOF 的 T 日净值落进次新列只成 T+1 行的 `prev_unit_nav`,永不作为 T 日 `unit_nav` 落行(`:905-906` 注释即此)。
2. **上游有值实测**:curl lsjz API(`https://api.fund.eastmoney.com/f10/lsjz?fundCode=005827&pageIndex=1&pageSize=5&startDate=2026-10-20&endDate=2026-10-31`,带 Referer)返回 FOF 005827 的 2026-10-26~10-30 每日 DWJZ/JZZZL 全有值(实测 2026-11-01 23:07)。
3. **影响面实测**:云上 `data/public_fund.db` 查 `fund_basic.fund_type`:`FOF-*` 共 1421 只(稳健 805+均衡 378+进取 238)、`QDII-*` 共 375 只;调研 20 只样本中 13 只上游有值我方整月 NULL(11 FOF)。
4. **时点空档实测**:云上 `systemctl list-timers` —— 21:00 `trade-backfill-evening`(backfill_metrics.sh,grep 确认只碰指数+sentiment.db metrics,**不碰 public_fund.db**)、21:20 `trade-futures-backfill`;public_fund.db 写入任务只有 16:20/17:00 `trade-public-fund-daily` 与 03:00 `trade-public-fund-quarterly`。**21:10 空档**(21:00 任务写 sentiment.db 不撞同库,21:20 任务写期货数据不撞同库)。

## 二、实现预期(§5.7②,可观测 X→Y)
- 批1 上线(21:10 timer)次日,`fund_daily_nav` 中 FOF/QDII(类型 LIKE 'FOF%'/'QDII%')在最近 2 个交易日的 `unit_nav` 非空率从 ~0% → ≥90%(上游发布率,调研 20 只样本 13/20 有值=65%,但 FOF 占绝对多数且 FOF 上游几乎全有,预期 ≥90%)。
- 股票型/债券型等非 FOF/QDII 的 `fund_daily_nav` 行**零变更**(git diff 确认 `fetch_daily_nav` 主体未动 + 采集器只选 FOF/QDII)。
- 已有非空 `unit_nav` 不被覆盖(SQL 用 `COALESCE(fund_daily_nav.unit_nav, excluded.unit_nav)` 只补 NULL)。

## 三、证据用例(§5.7③,实现前写定,可独立复现)
- **E1(API 通)**:`curl -s --max-time 15 -H "Referer: https://fundf10.eastmoney.com/" "https://api.fund.eastmoney.com/f10/lsjz?fundCode=005827&pageIndex=1&pageSize=5&startDate=2026-10-20&endDate=2026-10-31"` 返回 `Data.LSJZList` 非空,含 FSRQ/DWJZ/LJJZ/JZZZL。
- **E2(只补 NULL)**:沙箱 sqlite 建表,先插一行 `(20261030, '005827', unit_nav=1.0)`,跑采集器 mock 返回 DWJZ=1.3725,断言该行 `unit_nav` 仍=1.0(不被覆盖);另插一行 `(20261029, '005827', unit_nav=NULL)`,断言被补成 1.3632。
- **E3(判别力反证)**:去掉「只补 NULL」守卫(改成 INSERT OR REPLACE)→ E2 第一行被覆盖成 1.3725 → 测试 FAIL(证明守卫生效)。
- **E4(真实小样)**:临时 sqlite,挑 3 只真实 FOF(005827/017579/018302)实跑采集器,断言落行 `unit_nav` 非空且日期格式 YYYYMMDD(禁碰生产 public_fund.db)。
- **E5(单只失败不中断)**:mock 一只 fund_code 触发网络异常,断言其余 fund 仍落行 + 失败被记录。
- **E6(不改股票型)**:`git diff app/collector/public_fund.py` 确认 `fetch_daily_nav` 函数体无改动(只新增独立脚本)。

## 四、采集器设计
- **新文件**:`scripts/collect_fof_nav.py`(独立入口,不改 public_fund.py 主逻辑)。
- **DB 复用**:`from app.collector.public_fund import get_conn, init_db, _acquire_lock`(§6.5 第 2 层复用,不重写连接/schema)。
- **选基**:`SELECT fund_code, fund_name FROM fund_basic WHERE fund_type LIKE 'FOF%' OR fund_type LIKE 'QDII%'`。
- **API**:lsjz `GET https://api.fund.eastmoney.com/f10/lsjz`,参数 `fundCode/pageIndex=1/pageSize=20/startDate/endDate`(近 7 自然日,覆盖 T-1/T-2+周末),header `Referer: https://fundf10.eastmoney.com/`(实测必须,否则可能空)。用 `urllib.request`(标准库,§6.5 第 4 层,不引入新依赖)。
- **解析**:FSRQ `2026-10-30` → `20261030`;DWJZ→unit_nav;LJJZ→acc_nav;JZZZL→nav_change_pct;前一条的 DWJZ→当前条 prev_unit_nav。
- **写入 SQL**(只补 NULL,原子事务,每只一 commit):
  ```sql
  INSERT INTO fund_daily_nav(date,fund_code,fund_name,unit_nav,acc_nav,prev_unit_nav,nav_change_pct)
  VALUES(?,?,?,?,?,?,?)
  ON CONFLICT(date,fund_code) DO UPDATE SET
    fund_name=COALESCE(fund_daily_nav.fund_name, excluded.fund_name),
    unit_nav=COALESCE(fund_daily_nav.unit_nav, excluded.unit_nav),
    acc_nav=COALESCE(fund_daily_nav.acc_nav, excluded.acc_nav),
    prev_unit_nav=COALESCE(fund_daily_nav.prev_unit_nav, excluded.prev_unit_nav),
    nav_change_pct=COALESCE(fund_daily_nav.nav_change_pct, excluded.nav_change_pct)
  ```
  (COALESCE(库值, 新值)=库值非空保留库值,只补 NULL;与 fetch_daily_nav 同口径)
- **失败兜底**:单只 try/except 记日志 continue;限速 0.3s/只(防 WAF,参考 intraday 多源教训);urllib timeout 15s。
- **断点续跑**:幂等(只补 NULL,重跑不覆盖,天然续跑)。
- **原子写**:每只一个 transaction(commit 后再下一只);DB WAL 模式(get_conn 已设)。
- **锁**:acquire `public_fund.lock`(非阻塞,撞锁跳过,防与 daily/quarterly 并发写同库)。

## 五、时点与部署
- **timer 时点**:21:10(交易日;21:00 backfill-evening 写 sentiment.db 不撞,21:20 futures 写期货不撞,public_fund.db 写入只 16:20/17:00+03:00)。
- **systemd unit 四副本纪律(L54/L55)**:本批只产**代码 + 生成源 doc(本文件)+ unit 模板**;云上真实 unit 部署待批1 验证后由主控派部署任务(不直播主 unit)。timer OnCalendar=`*-*-* 21:10:00`(仅交易日,脚本内 `is_trading_day` 闸门)。
- **预算**:内层 `run_to 600`(1162+ 只 ×0.3s ≈ 350s + 请求 15s 单只上限,最坏 ~500s);外层 systemd `TimeoutStartSec=900`(梯度 400s)。

## 六、批2/批3 待办(不在本批)
- 批2:份额类清理(QDII 后端/港币/美元现钞映射主份额);定开/封闭识别(封闭期 lsjz 空,从 fund_basic 状态剔除)。
- 批3:历史回填(补 2026-10 整月 + 更早缺失);prev_unit_nav 跨日 gap 派生(fund_pct 联动)。
