"""fund_daily_nav 涨跌幅 / 前值的单一计算·补齐实现(2026-10-28 根治)。

背景(根因报告 `/tmp/navnull-rootcause-report.md`)
  · 采集器 `fetch_daily_nav()` 的「当日未发布 → 回退写前一交易日」路径**按设计不写**
    `prev_unit_nav` / `nav_change_pct`(public_fund.py 回退分支:次新列不存在 ⇒ prev=None,
    `use_pct=False` ⇒ pct=None);源端当日没给「日增长率」时也直接落 NULL。
  · 两条路径都**没有「用库内更早一条 unit_nav 派生 pct」的兜底** ⇒ 2026-10 攒下
    49,295 行 `nav_change_pct IS NULL`(10-16 单日 24,103 行,且该日 prev 整日全空)。
  · 指数侧已有同形实现 `app/collector/index_pct.py`(定理:同一计算只许一份),本模块照其
    形态落地。**禁止在 public_fund.py / 回填脚本里再复制第二份比较或计算逻辑**(§23.2③)。

规则(与指数侧同构)
  · prev = 同 `fund_code`、`date` **更早**、`unit_nav IS NOT NULL` 的**最近一条** `unit_nav`;
  · pct = `(unit_nav / prev - 1) * 100`;`prev` 为空或为 0 ⇒ None(不可算,绝不编数);
  · 该基金在库里**首条记录**(没有更早的非空 unit)⇒ 保持 NULL(语义正确);
  · `pct` 已有值 ⇒ **一律不动**(只补空,不重算、不覆盖源端口径)。

口径提示(诚实标注,不属缺陷)
  · 派生 pct 是**原始比值**;源端「日增长率」在**分红日**是调整口径(把分红额并入涨幅),
    二者在分红日会有微差 —— 与 `scripts/backfill_fund_nav_null_days_251.py` 同一既有结论。
"""
from __future__ import annotations


def calc_pct(unit_nav, prev_nav):
    """(unit_nav/prev_nav-1)*100;任一侧为 None 或 prev_nav 为 0 时不可算,返 None。"""
    if unit_nav is None or prev_nav is None:
        return None
    if float(prev_nav) == 0:
        return None
    return (float(unit_nav) / float(prev_nav) - 1.0) * 100.0


def prev_nav_from_db(conn, fund_code, date):
    """库里同 fund_code、date 更早、unit_nav 非空的最近一条 unit_nav(逐行查,不整表拉内存)。"""
    row = conn.execute(
        "SELECT unit_nav FROM fund_daily_nav "
        "WHERE fund_code=? AND date<? AND unit_nav IS NOT NULL "
        "ORDER BY date DESC LIMIT 1",
        (fund_code, date),
    ).fetchone()
    if row is None:
        return None
    return row[0]


def fill_row_prev_pct(date, fund_code, unit_nav, prev_unit_nav, pct, conn):
    """单行写入用:补 prev / pct,返回 `(prev_unit_nav, nav_change_pct)`。

    优先级(同源更可信):`prev_unit_nav` 已给(采集回退路径的「次新列」值)⇒ 用它;
    列缺失才回落到库内更早一条。`pct` 已有值 ⇒ 两列原样返回(不重算)。
    `unit_nav` 为空 ⇒ 原样返回(当日没有净值,算不出涨跌幅,也不编 prev)。
    """
    if pct is not None or unit_nav is None:
        return prev_unit_nav, pct
    prev = prev_unit_nav if prev_unit_nav is not None else prev_nav_from_db(conn, fund_code, date)
    return prev, calc_pct(unit_nav, prev)


def fill_row_pct(date, fund_code, unit_nav, pct, conn):
    """单行写入用(只要 pct 的场景):pct 为空且 unit 非空 ⇒ 用库里更早的最近一条派生。"""
    return fill_row_prev_pct(date, fund_code, unit_nav, None, pct, conn)[1]