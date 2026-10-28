"""fund_daily_nav 涨跌幅 / 前值的单一计算·补齐实现(2026-10-28 根治)。

背景(根因报告 `docs/ops/fund-nav-pct-rootfix-20261028.md`)
  · 采集器 `fetch_daily_nav()` 的「当日未发布 → 回退写前一交易日」路径**按设计不写**
    `prev_unit_nav` / `nav_change_pct`(public_fund.py 回退分支:次新列不存在 ⇒ prev=None,
    `use_pct=False` ⇒ pct=None);源端当日没给「日增长率」时也直接落 NULL。
  · 两条路径都**没有「用库内前一交易日那条 unit_nav 派生 pct」的兜底** ⇒ 2026-10 攒下
    49,295 行 `nav_change_pct IS NULL`(10-16 单日 24,103 行,且该日 prev 整日全空)。

规则(口径 = 「基准行必须是前一交易日」,2026-10-28 审查裁定)
  · **基准日 = `app/calendar.last_trading_day(目标日 - 1)`**,即目标日的**前一交易日**。
    **禁止用自然日差 1** —— 周末/节假日跨天但交易日相邻(2026-10 有 726 行)是**正确**的日
    涨幅,用自然日会误杀。
  · prev = 该基金在**基准日那一行**的 `unit_nav`(基准行缺失/为空 ⇒ 不可算,保持 NULL)。
    **不再**退化为「库里更早任意一条」:东财对周更基金(000053/009437/009467)周更日
    JZZZL 为空、006111 在 10-15 无净值时 10-16 的 JZZZL 也为空 —— 源端自己都拒绝跨多日算;
    实测跨日比值与源值只对得上 10-24%(gap=1 时 100%)。跨多日累计涨幅**不许**写进「日增长率」。
  · pct = `(unit_nav / prev - 1) * 100`;`prev` 为空或为 0 ⇒ None(不可算,绝不编数);
  · 该基金在库里**首条记录** ⇒ 保持 NULL(语义正确);
  · `pct` 已有值 ⇒ **一律不动**(只补空,不重算、不覆盖源端口径)。
  · 采集端「源端给了 prev 列值」那条路:列值**必须自带其日期**且等于基准日才采信
    (`fill_row_prev_pct(..., prev_unit_date=...)`);否则按跨多日处理 —— 不拿它算 pct,
    改用库内基准行的值(prev 与 pct 分母同一口径);库内也没有基准行则 pct 留 NULL、源值保留。

性能(2026-10-28 必修 2)
  · 取 prev **一律走 `PrevNavCache`**:按「基准日」一次性预取该日全部基金 `(fund_code, unit_nav)`
    (一条 `WHERE date=?`,走 `(date, fund_code)` 主键),派生只在内存查表。
  · 旧的逐行 `ORDER BY date DESC LIMIT 1` 无 `(fund_code,date)` 复合索引 ⇒ 每行一次 TEMP B-TREE
    全史排序,16:20 槽(900s 上限,实测 843-861s)每次回退日多耗 11-25s,余量只剩 39-57s。
  · `prev_nav_from_db` 保留为**单行点查**(`date=? AND fund_code=?`,只用于对账/单行场景),
    与 `PrevNavCache` 走同一口径(同一 `prev_trading_date` 判据),两条取数路径结果必须逐位一致。

口径提示(诚实标注,不属缺陷)
  · 派生 pct 是**原始比值**;源端「日增长率」在**分红日**是调整口径(把分红额并入涨幅),
    二者在分红日会有微差 —— 与 `scripts/backfill_fund_nav_null_days_251.py` 同一既有结论。
  · 跨日不补(gap≥2)导致的部分 NULL 是**正确行为**,不是漏补。
  · `unit_nav IS NULL` 的基金(QDII/FOF/定开当月不发布,1,942 只)不可派生。
"""
from __future__ import annotations

import datetime as dt
from functools import lru_cache

from ..calendar import calendar_available, last_trading_day


def calc_pct(unit_nav, prev_nav):
    """(unit_nav/prev_nav-1)*100;任一侧为 None 或 prev_nav 为 0 时不可算,返 None。"""
    if unit_nav is None or prev_nav is None:
        return None
    if float(prev_nav) == 0:
        return None
    return (float(unit_nav) / float(prev_nav) - 1.0) * 100.0


@lru_cache(maxsize=2048)
def prev_trading_date(date) -> "str | None":
    """目标日(date)的**前一交易日** `YYYYMMDD`;日历不可用/日期非法 ⇒ None(保守不派生)。

    · 判据 = `app/calendar.py` 的交易日历(`data/trade_dates.txt` 覆盖 1990-2026),
      **绝不用自然日差 1**(周末/节假日跨天但交易日相邻是正确日涨幅)。
    · 日历为空(既无缓存文件、akshare 也不可用)⇒ 返回 None 而不是退化成周末启发式:
      宁可留 NULL(与修前行为一致),也不拿自然日把跨日累计涨幅写进「日增长率」。
    """
    key = str(date).replace("-", "")
    if len(key) != 8 or not key.isdigit():
        return None
    if not calendar_available():
        return None
    try:
        d = dt.datetime.strptime(key, "%Y%m%d").date()
    except ValueError:
        return None
    return last_trading_day(d - dt.timedelta(days=1))


def is_prev_trading_day(prev_date, date) -> bool:
    """`prev_date` 是否恰好是 `date` 的前一交易日(源端 prev 列值可否采信的**唯一**判据)。"""
    if prev_date is None:
        return False
    p = prev_trading_date(date)
    return p is not None and str(prev_date).replace("-", "") == p


def prev_nav_from_db(conn, fund_code, date):
    """单行点查:`date` 的前一交易日那一行的 `unit_nav`(基准行缺失/为空 ⇒ None)。

    只用于对账/单行场景;批量取数请用 `PrevNavCache`(禁止逐行查库,见模块头「性能」)。
    """
    pdate = prev_trading_date(date)
    if pdate is None:
        return None
    row = conn.execute(
        "SELECT unit_nav FROM fund_daily_nav "
        "WHERE date=? AND fund_code=? AND unit_nav IS NOT NULL",
        (pdate, fund_code),
    ).fetchone()
    if row is None:
        return None
    return row[0]


class PrevNavCache:
    """按「前一交易日」一次性预取 `fund_code -> unit_nav` 的进程内缓存(单一取数实现)。

    每个基准日一条 SQL(走 `(date, fund_code)` 主键),之后的派生全部是内存 dict 查表。
    用 `navs_on()` 取到整日映射后,采集端/回填脚本可按需要再做统计,不必二次查库。
    """

    def __init__(self, conn):
        self._conn = conn
        self._by_prev_date: dict[str, dict[str, float]] = {}

    def navs_on(self, prev_date: str) -> dict[str, float]:
        """该交易日全部基金的 unit_nav 映射(首次访问才查库,之后命中缓存)。"""
        m = self._by_prev_date.get(prev_date)
        if m is None:
            m = {}
            for r in self._conn.execute(
                "SELECT fund_code, unit_nav FROM fund_daily_nav "
                "WHERE date=? AND unit_nav IS NOT NULL", (prev_date,)):
                m[r[0]] = r[1]
            self._by_prev_date[prev_date] = m
        return m

    def prev_nav(self, fund_code, date):
        """目标日 `date` 的前一交易日那一行的 unit_nav;缺失/为 0 ⇒ None。"""
        pdate = prev_trading_date(date)
        if pdate is None:
            return None
        v = self.navs_on(pdate).get(fund_code)
        if v is None or float(v) == 0:
            return None
        return v

    def clear(self):
        self._by_prev_date.clear()


def fill_row_prev_pct(date, fund_code, unit_nav, prev_unit_nav, pct, prev_source,
                      prev_unit_date=None):
    """单行写入用:补 prev / pct,返回 `(prev_unit_nav, nav_change_pct)`。

    优先级(同源更可信,但**必须能证明是前一交易日**):
      ① `prev_unit_nav` 已给 **且** `prev_unit_date == 前一交易日` ⇒ 用它当基准;
      ② 否则用库内**前一交易日**那一行(`prev_source` = `PrevNavCache`),prev 一并取该值
         (保证「prev 列」与「pct 分母」是同一口径,§22 一致性);
      ③ 库内也没有基准行 ⇒ pct 保持 None(跨多日/基准行缺失一律不编数),源端 prev 原样保留
         (不抹源数据)。

    `pct` 已有值 / `unit_nav` 为空 ⇒ 两列原样返回。
    """
    if pct is not None or unit_nav is None:
        return prev_unit_nav, pct
    if prev_unit_nav is not None and is_prev_trading_day(prev_unit_date, date):
        return prev_unit_nav, calc_pct(unit_nav, prev_unit_nav)
    base = prev_source.prev_nav(fund_code, date)
    if base is None:
        return prev_unit_nav, None
    return base, calc_pct(unit_nav, base)


def fill_row_pct(date, fund_code, unit_nav, pct, prev_source, prev_unit_date=None):
    """单行写入用(只要 pct 的场景):走同一实现。"""
    return fill_row_prev_pct(date, fund_code, unit_nav, None, pct, prev_source,
                             prev_unit_date=prev_unit_date)[1]