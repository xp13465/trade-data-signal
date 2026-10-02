# app/queries.py `except Exception` 静默吞故障审计 + 补日志(2026-10-02)

## 背景与现状

researcher 只读审计了 `app/queries.py` 全部 9 处 `except Exception`。本文档为实施落地记录:
**审计总表(9 处)+ 本次实际改动(4 处)+ §复现段 + §诚实标注**。

用户已拍板(§23.7 冻结契约过)可动历史代码,但**只动已批 4 处**,其余 5 处明确不动。

### 审计定性的核心理由(共同病根)
本次补的 4 处包的是 **数据库级故障**(表缺失 / 列丢失 / WAL 损坏),不是"值缺失";且
**ETF 采集不写 `collect_log`**(已实测 `app/collector/etf_national_team.py` 中 collect_log 出现 0 次),
首页数据健康度绿点**覆盖不到 etf_national_team.db** ⇒ 真出事时"用户看得见(卡片/标签空),运维零日志"。

---

## 审计总表(9 处)

| # | 行号锚点(改动后) | 语义锚点 | 包住什么 | 出事后用户看到 | 判定 |
|---|---|---|---|---|---|
| 1 | `app/queries.py:428`(`_enrich_etfs_since_return`) | 走势卡 ETF 至今盈亏跨库批查 | `etf_daily.accum_nav` 跨库查询,纯 `pass` | 全部 ETF 的 `etf_since_return`/`etf_price_diff` 置 None → 前端 `etf-tag-pnl` 不生成(`static-site/app.js:24610`) | ✅ **补**(本次) |
| 2 | `app/queries.py:1442`(`overview` 内,上下文 1423-1441) | 同模式(2026-08-14 F1 回归修复处) | `etf_daily.accum_nav` + `close` 两条跨库查询,纯 `pass` | 同上类:信号候选 ETF 至今盈亏/价格差字段留空 | ✅ **补**(本次) |
| 3 | `app/queries.py:1856`(`overview` 时效横幅块) | 时效横幅外层 | `futures.json` 读取 + `us_dji`/`csi_div` 主库 `index_daily` 查询,纯 `pass` | 横幅退默认文案(`static-site/app.js:12336-12340`) | ✅ **补**(本次) |
| 4 | `app/queries.py:1866`(汪汪队卡片块) | 🐶汪汪队卡片 | `latest_signals_overview` + `recent_signals_overview`,纯 `pass` | `nt=None` → 卡片空白(`static-site/app.js:17100`) | ✅ **补**(本次) |
| 5 | `app/queries.py:1069` | T1 新键命中标注 | `_ai_macro_hit_new_keys` 标注失败,有注释 `# 新键标注失败不阻断 overview 主链路(诚实降级: 少标注优于导出失败)` | 少 20 条 T1 键命中标注(不影响主链路) | ❌ 不动(已有注释声明降级语义) |
| 6 | `app/queries.py:1735`(`overview` collected_at 块) | `load_latest_snapshot` | 盘中快照读取,有 fallback(`_cands` 其余候选兜底 `max`) | collected_at 取剩余候选,时效角标略旧 | ❌ 不动(有 fallback + 注释) |
| 7 | `app/queries.py:1814`(行业热力图块) | `maybe_override_heatmap` | 盘中快照行业覆盖,内层 `app/collector/intraday_snapshot.py:2769-2771` 已有 `print(f"  [intraday] maybe_override_heatmap 失败(回退 DB heatmap)...")` | 热力图退 DB 版本(盘中覆盖不生效) | ❌ 不动(内层已有 print 可察觉;内层无 logger 但改动范围仅限已批 4 处) |
| 8 | `app/queries.py:1838`(etf_date MAX(date)) | `etf_date` `MAX(date)` | etf_daily 表 MAX(date),有 fallback(`updated_at[:10]`),注释自认"可能误导角标" | 角标日期取 JSON updated_at(可能假绿) | ❌ 不动(有 fallback;注释已知缺陷,用户本次只批 4 处,不顺手改) |
| 9 | `app/queries.py:1583`(icepoint 四因子) | 冰点认可度 | `.compute.icepoint.compute()` | overview 不含 `sh_*` 字段 | ✅ 已补(2026-10-02 冰点功能上线时已带 `logger.exception("icepoint 四因子计算失败,本次 overview 不含 sh_* 字段")`) |

**合计:4 补(本批) + 4 不补 + 1 已补 = 9 处全表闭合。**

---

## 本次实际改动清单(4 处,改动前后对照)

改动原则:**只加日志,降级语义一行不变**(`pass` / 返回值一律原样保留;不 fail-loud、不 raise、不再判断分支)。logger 已存在于文件头(`app/queries.py:15 import logging` / `:30 logger = logging.getLogger(__name__)`),直接复用,无需新增 import。

| 行号 | 改动前 | 改动后 |
|---|---|---|
| 428 | `except Exception:  # noqa: BLE001` / `    pass` | 同前 + 新增 `logger.exception(...)` 三行文案(见下)后仍 `pass` |
| 1442 | 同上 | 同前 + 新增 `logger.exception(...)` 后仍 `pass` |
| 1856 | 同上 | 同前 + 新增 `logger.exception(...)` 后仍 `pass` |
| 1866 | 同上 | 同前 + 新增 `logger.exception(...)` 后仍 `pass` |

四段日志文案(每条含三要素:哪个展示位退化 + 退化成什么样 + 可能原因):

```python
# 428
logger.exception(
    "走势卡 ETF 至今盈亏计算失败(etf_daily.accum_nav 跨库查询异常),"
    "本次全部 ETF 的 etf_since_return/etf_price_diff 留空,前端 etf-tag-pnl 不生成,"
    "请检查 etf_national_team.db(表缺失/列丢失/WAL 损坏)"
)
# 1442
logger.exception(
    "信号卡 ETF 至今盈亏计算失败(etf_daily accum_nav/close 跨库查询异常),"
    "本次信号候选 etf_since_return/etf_price_diff 字段留空,"
    "请检查 etf_national_team.db(表缺失/列丢失/WAL 损坏)"
)
# 1856
logger.exception(
    "时效横幅补充源日期读取失败(futures.json 读取或 us_dji/csi_div 主库 index_daily 查询异常),"
    "futures_date/us_dji_date/csi_div_date 缺失,横幅退默认文案,"
    "请检查 static-site/data/futures.json 与 sentiment.db index_daily 表"
)
# 1866
logger.exception(
    "汪汪队卡片数据获取失败(latest_signals_overview/recent_signals_overview 异常),"
    "nt_signals_today 置 None 首页🐶卡片空白,"
    "请检查 etf_national_team.db(表缺失/列丢失/WAL 损坏)"
)
```

---

## §复现段(怎么复跑这个审计)

### 复现抓取全部 except 点
```bash
grep -n "except Exception" app/queries.py
# 期望 9 处:428 / 1069 / 1442 / 1583 / 1735 / 1814 / 1838 / 1856 / 1866
```

### 判定口径(3 问)
1. **包住的是"数据库级故障"还是"值缺失"?** DB 故障(表/列/WAL)→ 必须可察觉;值缺失且有显式 fallback/注释 → 合理降级不动。
2. **出事后用户是否看得见但运维零日志?** 结合前端消费点(`etf-tag-pnl` app.js:24610 / 横幅 app.js:12336-12340 / 🐶卡片 app.js:17100)确认用户侧退化,再查该库是否有 collect_log/健康度绿点覆盖(ETF 库=无)。
3. **except 后是 `pass` 且无任何注释/已有日志?** 纯 pass + 无声明 = 静默吞,必补。

### 验证核心理由(ETF 采集不写 collect_log)
```bash
grep -c "collect_log" app/collector/etf_national_team.py   # =0 → 绿点覆盖不到该库
```

### 自测 4 项(§23.2 修 bug 三铁律)
```bash
# ① 语法
/Users/linhuichen/code/trade/.venv/bin/python -m py_compile app/queries.py
# ② import(须在 worktree 内,勿走 trade-data symlink —— trade-data/app -> ../trade/app 指向主 checkout)
/Users/linhuichen/code/trade/.venv/bin/python -c "import app.queries; print(app.queries.logger.name)"
# ③ monkeypatch 制造 get_conn 异常,确认 logger.exception 落 stderr(428 实测通过,其余 3 处同模式同 logger)
#   关键坑: 必须在 worktree cwd 下跑(sys.path 命中 worktree/app),否则经 trade-data symlink 测到主 checkout 代码
# ④ git diff 对照: 4 处仅新增 logger.exception,pass 保留
git diff app/queries.py
```

---

## §诚实标注(推断 vs 实测)

**实测(本 session 逐项执行)**:
- 9 处 `except Exception` 行号与语义逐一核对(Read 全 9 处上下文)。
- 4 处补日志处 catch 后行为与改前**逐位一致**(`git diff` 对照,仅 20 行纯增量,0 删除)。
- 自测① py_compile PASS、② import app.queries PASS。
- 自测③ 通过 monkeypatch `etf_national_team.get_conn` 抛 RuntimeError + worktree 内调用
  `_enrich_etfs_since_return`,实测 stderr 出现 `ERROR:app.queries:走势卡 ETF 至今盈亏计算失败...`
  及堆栈,日志真实落到 handler 输出。确认日志渠道活。
- 核心理由: `etf_national_team.py` collect_log 出现 0 次(实测 grep);`intraday_snapshot.py:2769-2771`
  已有 print(实测 Read)。logger 模块级已存在于 queries.py 顶部(实测 grep 15/30 行)。

**推断(未实测,路径依赖代码阅读)**:
- "ETF 采集不写 collect_log → 首页数据健康度绿点覆盖不到该库":collect_log=0 是实测,但"绿点覆盖
  不到"是推断 —— 绿点具体读哪些 collect_log 项未逐项核对,审计结论以 researcher 定性为准。
- 前端展示位行号(app.js:24610 / 12336-12340 / 17100)为 researcher 提供的锚点,本文档未逐行复验
  (本次纯后端改,未动前端)。

**明说不补的 5 处**中,1838 的等 bug(角标假绿)与 1814 的内层无 logger,已列入"同类观察项,
建议后续单独评估是否纳入",本次不擅改(用户只批 4 处)。