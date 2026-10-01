# #145 + #146 fapi_fallback.py 存量缺陷修复(2026-10-01)

> 同一文件 `app/collector/fapi_fallback.py`,两个独立缺陷(#145 参数口径混用 / #146 字段缺失未兜底),各自独立改法与不变性证明,分两个 commit。
> 分支:`worktree-agent-a1593f5b599a18d5a`(feat),base = `0b025c7db`(开工时 origin/main 链)。
> commits:`71a6dacbd`(#146)、`d2135800e`(#145)。

## 一、#145 跌停/炸板池老日期取数 code:1002(参数口径混用)

### 定位(文件:行号 + 原代码)
跌停/炸板池**没有独立取数分支**——三池(`limit-up-pool`/`limit-down-pool`/`limit-break-pool`)共用 `fetch_zt_fallback`,`ZT_ENDPOINTS`(L29-33)按 func_name 映射端点后,**同一行**构造 params:

```
app/collector/fapi_fallback.py L107(改前):
    params = {"date_ms": _date_ms(date), "page": 1, "size": 200}
```

date_ms(毫秒时间戳)是涨停池契约;跌停/炸板池契约要求 `date=YYYYMMDD`。三池共用一行 → 跌停/炸板池按历史日期取数时 FAPI 返回 `{code:1002}`(参数不合法),老日期恒取不到。
佐证:`docs/pending-features-index.md` L236(#145 登记)+ L231(#140 独立 reviewer 真实调用复核:「跌停/炸板池老日期 `date_ms` 报 `code=1002`,改 `date=YYYYMMDD` 则通」)。外部接口行为不作闭门实验,以上一轮 reviewer 取证为准。

### 改法 diff
```
    # #145 参数口径按池区分:limit-up-pool 契约用 date_ms(毫秒时间戳),涨停池
    # 当日实时取数保持 date_ms 逐位不变;limit-down-pool/limit-break-pool 契约用
    # date=YYYYMMDD——原先三池共用 date_ms 致跌停/炸板池历史日期取数 FAPI
    # 返回 code:1002(参数不合法),老日期恒取不到。
    if r == "limit-up-pool":
        params = {"date_ms": _date_ms(date), "page": 1, "size": 200}
    else:
        params = {"date": date, "page": 1, "size": 200}
```
同步更新模块 docstring 端点表(L13-15):limit-down-pool / limit-break-pool 标注 `date=YYYYMMDD`(一致性登记点,防后人误读「同结构」)。

### 不变性证明(§23.7,实测对照)
方式:monkeypatch 真实模块 `_api` 捕获 params,同输入跑新版 `fetch_zt_fallback`(脚本 `/tmp/prove145.py`),5 场景全 PASS:
1. 涨停池 `stock_zt_pool_em("20241008")` → params 含 `date_ms=1728316800000` 且**无 date**,连板列 `[2,5]` 逐位不变(手算核对:2024-10-08 00:00+08 = 2024-10-07 16:00 UTC,epoch 1728316800000 ✓)
2. 跌停池 `stock_zt_pool_dtgc_em` → params 含 `date="20241008"` 且**无 date_ms**
3. 炸板池 `stock_zt_pool_zbgc_em` → 同 2
4. 涨停池翻页 3 页取满 450,每页均带 date_ms 无 date
5. 跌停池翻页 3 页取满 450,每页均带 `date="20241008"` 无 date_ms(翻页 `{**params, "page": page}` 参数继承正确)

**结论:改动只影响「老日期查询」路径;涨停池当日实时取数(date_ms + 翻页)逐位不变。**

## 二、#146 跌停/炸板池连板列整列 NaN(字段缺失未兜底)

### 定位(文件:行号 + 原代码)
```
app/collector/fapi_fallback.py L72(改前):
    lianban_col: it.get("continue_day_cnt"),
```
`_zt_df` 从 item 取 `continue_day_cnt` 算「连板数」。但契约文档 `docs/fapi/fapi-integration-plan-20260901.md` L200-202:仅 `limit-up-pool` item 有 `continue_day_cnt`;`limit-down-pool` item 字段 = pagination.total/first/last_limit_time/turnover_ratio_pct,`limit-break-pool` item 字段 = pagination.total/items ——**两池均无该字段** → 连板列整列 NaN。
当前调用链两池走 `count_rows`(只取 len,fetchers.py L616)/`ratio_count`(只取 len,L705-715),连板 max 只对涨停池兜底 → 不炸;**潜伏风险**:未来任何 max()/比较/int() 变换(如 #134 连板回补)对 NaN 列 `int(NaN)` 抛 ValueError 打断采集链。属预防性修复。

### 改法 diff
`_zt_df` 增 `has_lianban: bool = True` 参数:无连板语义池连板列显式填 0;有连板语义池内层 `fillna(0)` 防御个别 item 缺值。
调用侧 `fetch_zt_fallback` L141(改后)按池区分:
```
    # #146 按池区分连板语义:limit-up-pool item 有 continue_day_cnt(连板数),
    # limit-down-pool/limit-break-pool 无该字段(契约文档 L201/L202),整列 NaN
    # 潜伏 int(NaN)/max(NaN) ValueError 打断采集链——无连板语义池填 0
    df = _zt_df(items, has_lianban=(r == "limit-up-pool"))
```

### 不变性证明(§23.7,实测对照)
方式:新版=真实模块 `_zt_df`,旧版对照=git HEAD 旧 `_zt_df` 逐字转录,构造 3 组样例逐位比对(脚本 `/tmp/prove146.py`):
- 样例 A(涨停池,有 continue_day_cnt):新 `has_lianban=True` vs 旧版 → **`df.equals()` = True**,连板列 `[7,1,3]` int64 逐位一致
- 样例 B(跌停/炸板池,无字段):旧版连板列 `[None,None]` 整列 isna;**新版 `[0,0]`**,`int()` 变换安全(潜伏 ValueError 解除)
- 样例 C(涨停池个别 item 缺值):旧版 `[5.0, nan]` 含 NaN;新版 fillna 后 `[5.0, 0.0]` 无 NaN

**结论:有该字段的池(涨停池)取值逐位不变;只有无字段的池由 NaN 变 0。**

## 三、同类错误面清单(§23.3/§23.2)

| # | 同类点 | 判定 | 处置 |
|---|---|---|---|
| 1 | 同文件 `fetch_lhb_fallback` L175-178:龙虎榜契约 date=YYYY-MM-DD,已单独做 ms→日期转换,与涨停池 date_ms 完全隔离 | ✅ 无混用 | 不受影响 |
| 2 | 同文件 `_lhb_df` L88 `it.get("org_net_value")`:item 缺该字段时列存在但值 None,L166 只查「列存在性」不查「值」,sum 得 0 失真 | ⚠️ 同类观察(字段缺失未兜底) | 非 #145/#146 范围,§23.7 冻结不擅改,登记待后续 |
| 3 | 同文件 `_zt_df`「最新价/涨跌幅」列:跌停/炸板池 item 也无 last_price/price_change_ratio_pct(契约 L201)→ 列全 None | ⚠️ 同类观察 | 当前 count_rows/ratio_count 只消费 len,无消费者;登记待后续 |
| 4 | 同数据源 FAPI 其他消费:`width_history.py L112 load_daily_fapi_fallback`(dump daily-k)契约 date_ms,非三池类 | ✅ 无混用 | 不受影响 |
| 5 | 全仓分页截断病灶:#140 reviewer 已独立 grep,唯一同款 = fapi_fallback(已修,#140 merge main);direct.py:276/696-730、etf_national_team.py:784-820、multisource.py:288、fetch_news.py:177-204 均非同款 | ✅ | 无同类未修点 |
| 6 | 调用链 fetchers.py L606-626:跌停/炸板池只走 count_rows/ratio_count(均 len),不读连板/最新价/涨跌幅列;连板 max 只对涨停池 | ✅ 修复后行为正确 | 本次修复正好闭环 |
| 7 | 龙虎榜兜底链 fetch_lhb_fallback 未触碰 | ✅ | 不受影响 |

## 四、自测结果
- `python -m py_compile app/collector/fapi_fallback.py` PASS(两轮)
- pre-commit lint_scripts.sh 全过(#146 commit `71a6dacbd` + #145 commit `d2135800e` 均触发并 PASS)
- 不变性证明两脚本(PROVE145 / PROVE146)PASS

## 复现段
```bash
# 环境:worktree /Users/linhuichen/code/trade/.claude/worktrees/agent-a1593f5b599a18d5a
# 用真实模块 + monkeypatch 验证 #145(mock _api 捕获 params):
/Users/linhuichen/code/trade/.venv/bin/python /tmp/prove145.py
#   → 5 场景断言全过:涨停池 date_ms 逐位不变 / 跌停·炸板池 date=YYYYMMDD / 翻页参数继承

# 用真实模块 + 旧版逐字对照验证 #146(3 组样例逐位比对):
/Users/linhuichen/code/trade/.venv/bin/python /tmp/prove146.py
#   → A df.equals=True(逐位不变)/ B NaN→[0,0] / C 缺值item fillna

# git 对照:
git show HEAD:app/collector/fapi_fallback.py   # 旧版 _zt_df(L62-76)与 fetch_zt_fallback params 构造
git show d2135800e --stat                      # #145 commit
git show 71a6dacbd --stat                      # #146 commit
```

## 关联登记
- `docs/pending-features-index.md` L236(#145 登记,原「待派单」→ 本报告修复)
- #140 reviewer 独立取证原始出处:`docs/pending-features-index.md` L231(含 #145/#146 两条 pre-existing 记录)
