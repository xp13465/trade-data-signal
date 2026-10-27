"""index_daily.pct_change 的单一计算/保护实现(2026-10-29 根治)。

背景(根因:`app/collector/fetchers.py` 两个采集分支 + `runner.upsert_index_rows`)
  · pct_change **全部由我们自己算**(新浪全球指数接口连涨跌幅列都没有,thsc 源也不给),
    算法是「本次返回 df 的上一行 close」。df **第一行没有上一行** ⇒ pct=None。
  · upsert 是全字段覆盖 ⇒ 这个「计算副产物 None」把库里原本正确的好值抹掉。
  · 两个源的窗口首行每天前移(thsc 起拉日=date-400 天;新浪全球指数服务端只给 1000 行)
    ⇒ 每天抹掉一个新的日期,形成「283 行、每天 20 条左右、日期逐日推进」。

本模块提供两处**单一实现**(禁止再在别处复制第二份比较/计算逻辑,§23.2③):
  ① `fill_first_pct` / `fill_row_pct` —— 写库前补「首行缺 prev」的 pct:
     用同 index_id、date 更早、close 非空的最近一条 close 作 prev;
     prev 不存在(该序列真正的第一行)⇒ 保持 NULL(语义正确,不编数)。
  ② `PCT_CHANGE_PRESERVE_SQL` —— ON CONFLICT DO UPDATE 里 pct_change 的赋值表达式:
     价没变(close 完全相同)且新值为空 ⇒ 保留旧值(防伪改写);close 真变 ⇒ 照常覆盖
     (不挡真修正)。**禁止用裸 COALESCE**:那会把「close 真变 NULL 的真缺行」也保住旧
     pct,造出「有涨跌幅没收盘价」的自相矛盾行。
"""
from __future__ import annotations

# ON CONFLICT DO UPDATE 里 pct_change 的赋值片段(全仓所有 index_daily upsert 共用)。
# 语义:只保护「close 完全相同 + 新 pct 为空」这一窄条件。
# close 为 NULL 时 SQL 三值逻辑里 `NULL = 任何值` 不成立 ⇒ 走 ELSE,真缺行照常写 NULL。
PCT_CHANGE_PRESERVE_SQL = (
    "pct_change = CASE WHEN excluded.close = index_daily.close "
    "AND excluded.pct_change IS NULL "
    "THEN index_daily.pct_change "
    "ELSE excluded.pct_change END"
)


def _calc_pct(close, prev_close):
    """(close/prev_close-1)*100;prev 为 0/None 时不可算,返 None。"""
    if close is None or prev_close is None:
        return None
    if float(prev_close) == 0:
        return None
    return (float(close) / float(prev_close) - 1.0) * 100.0


def prev_close_from_db(conn, index_id, date):
    """库里同 index_id、date 更早、close 非空的最近一条 close(逐行查,不整表拉内存)。"""
    row = conn.execute(
        "SELECT close FROM index_daily WHERE index_id=? AND date<? AND close IS NOT NULL "
        "ORDER BY date DESC LIMIT 1",
        (index_id, date),
    ).fetchone()
    if row is None:
        return None
    return row[0]


def fill_row_pct(date, index_id, close, pct, conn):
    """单行写入用: pct 为空且 close 非空 ⇒ 用库里更早的最近一条 close 补。"""
    if pct is not None or close is None:
        return pct
    return _calc_pct(close, prev_close_from_db(conn, index_id, date))


def fill_first_pct(rows, conn, index_id=None):
    """补 index_daily 写入行里缺失的 pct_change(单一实现)。

    rows: [(date, index_id, open, high, low, close, pct_change, amount), ...]
    conn: sqlite 连接(只对「缺 pct 且 close 非空」的行查前一条 close)
    index_id: 只处理该 index_id;缺省 None = 按行内 index_id 分组全处理

    规则: 按 date 升序,prev = 同一 index_id、date 更早、close 非空最近一条 close
    (同批更早行优先,没有才查库);prev 不存在 ⇒ 保持 NULL。
    返回**新列表**(不原地改调用方传进来的元组)。
    """
    out = [tuple(r) for r in rows]
    groups: dict[str, list[int]] = {}
    for pos, r in enumerate(out):
        if index_id is not None and r[1] != index_id:
            continue
        groups.setdefault(r[1], []).append(pos)
    for iid, positions in groups.items():
        positions.sort(key=lambda p: out[p][0])
        prev_close = None  # 同批内上一行的 close(按日期升序推)
        for p in positions:
            date, _, _, _, _, close, pct = out[p][:7]
            if pct is None and close is not None:
                base = prev_close if prev_close is not None else prev_close_from_db(conn, iid, date)
                new_pct = _calc_pct(close, base)
                if new_pct is not None:
                    out[p] = out[p][:6] + (new_pct,) + out[p][7:]
            if close is not None:
                prev_close = close
    return out