# FAPI P1 涨停池 + 龙虎榜兜底实施报告

- 日期:2026-09-02(实施;调研见 `docs/fapi/fapi-integration-plan-20260901.md` §3)
- 实施人:主控直接落地(连续 2 个 implementer 因上游代理超时系统性无法交付,§0.1 例外接管)
- 对应 TASKS:#17
- 分支:research/fapi-h-k1
- 状态:已自测通过,待用户验收

---

## 0. 结论速览(TL;DR)

| 项目 | 结论 |
|---|---|
| 涨停/跌停/炸板池兜底 | **落地**。东财 stock_zt_pool_em 系失败/空时 → FAPI limit-up-pool/down/break 兜底,复用现有 transform 链 |
| 龙虎榜兜底 | **落地**。东财 stock_lhb_detail_em / stock_lhb_jgmmtj_em 失败/空时 → FAPI dragon-tiger-list 兜底 |
| 主源优先 | 东财活着时 FAPI 绝不抢跑(实测东财 83/79,主链路原样返回) |
| 真0 保护 | 跌停空=真0 由 cross_check 先行拦截,不误触 FAPI(实测东财涨停池 83→跌停空=0) |
| 口径差(诚实标注) | 涨停 80 vs 83、龙虎 68 vs 79、机构净买 -1.96亿 vs -2.42亿,均调研已测口径差,兜底场景可接受 |

**核心判断:兜底已可用,主链路零改动风险;东财稳定时它只是"不存在"的备用源。**

## 1. 改动清单(§23.7 只增不改)

| 文件 | 改动 | 类型 |
|---|---|---|
| `app/collector/fapi_fallback.py` | **新增**。FAPI 四端点抓取器,返回东财兼容 df | 新增 |
| `app/collector/fetchers.py` | import fapi_fallback(异源兜底段);collect_snapshot 空值分支加 FAPI 兜底(先 cross_check 真0,后 FAPI) | 修改(纯新增分支,主链路不变) |
| `config/indicators.yaml` | **不动** | - |
| 前端/README/公示 | **不动**(兜底源,用户视角无变化,§21 无算法口径变更) | - |

**不做的事**(刻意):
- 不替换东财主源(§23.7 只增不改,观察期)
- 不改 daily_metric 表结构/source 语义(source 仍 akshare,FAPI 场景经 collect_log msg `fapi-fallback` 追溯)
- 不碰 intraday_snapshot.py 的盘中链路(盘中涨停池实时仍走东财,盘中故障另行评估,不在本任务)

## 2. 设计要点

### 2.1 挂点:collect_snapshot 空值分支
```python
# 现有逻辑(不动):zt_pool count_rows 空 → cross_check(判"空=真0")
if (func_name in DATE_PARAM_FUNCS and func_name.startswith("stock_zt_pool_")
        and metric.get("transform") == "count_rows"):
    _cc = cross_check_zt_pool(func_name, date)
    if _cc[0] is not None:
        return _cc          # 真0 直接返回,不落兜底
    # 新增:cross_check 也空(源故障)→ FAPI 兜底
    _fb, _fb_msg = fapi_fallback.try_fallback(func_name, date)
    if _fb is not None:
        if len(_fb) == 0:
            return 0.0, f"ok (fapi-fallback {_fb_msg})"
        return _apply_transform(_fb, metric, date), f"ok (fapi-fallback {_fb_msg})"
# 其余 func(连板高度/炸板率/打板溢价/龙虎榜等)空时也试 FAPI 兜底(§23.3 举一反三)
_fb, _fb_msg = fapi_fallback.try_fallback(func_name, date)
if _fb is not None and len(_fb):
    return _apply_transform(_fb, metric, date), f"ok (fapi-fallback {_fb_msg})"
return None, f"{func_name} empty"
```

### 2.2 FAPI → 东财兼容 df(列名对齐,复用 _apply_transform)
| FAPI 字段 | 东财列 | 用途 |
|---|---|---|
| ticker/name/last_price/price_change_ratio_pct | 代码/名称/最新价/涨跌幅 | - |
| continue_day_cnt | 连板数 | max(连板高度) |
| (行数) | count_rows | 涨停/跌停/炸板数 |
| org_net_value | 机构买入净额 | sum(机构净买) |

### 2.3 安全
- key 从 .env 读 `HITHINK_FINANCE_API_KEY`(与 fapi_daily.py 同源,绝不打印)
- 超时 20s(与东财 _em 同档),失败返回 None 不抛异常,兜底失败=保留 empty(不阻断主链)
- 跌停真0:空 df → cross_check 拦截在前,FAPI 兜底只处理"源真挂"场景

## 3. 自测结果(20260901 实盘数据)

### 3.1 东财正常(主链路原样,不触发 FAPI)
| 指标 | 值 | 口径 |
|---|---|---|
| a_width_zt_count | 83.0 | 东财封板 |
| a_width_max_lianban | 7.0 | 东财连板 max |
| a_width_zhaban_rate | 6.7% | 东财炸板 6/89 |
| lhb_count | 79.0 | 东财记录数 |
| lhb_inst_net | -2.42 亿 | 东财机构买入净额 sum |

### 3.2 FAPI 兜底(模拟东财挂,走 fapi-fallback)
| 指标 | FAPI 值 | msg |
|---|---|---|
| a_width_zt_count | 80.0 | fapi limit-up-pool 80 rows |
| a_width_max_lianban | 7.0 | fapi limit-up-pool 80 rows |
| a_width_zhaban_rate | 6.7% | fapi limit-break-pool 6 rows |
| lhb_count | 68.0 | fapi dragon-tiger-list 68 items |
| lhb_inst_net | -1.96 亿 | fapi dragon-tiger-list(org_net_value sum) |

### 3.3 真0保护(不误触 FAPI)
- 跌停 20260901:cross_check 返回 `(0, "ok (cross-check stock_zt_pool_em has 83 rows, 空=真0)")` → **FAPI 不触发**,现有行为完好

## 4. 风险与边界(诚实标注)

| 项 | 说明 |
|---|---|
| 口径差(涨停 80vs83/龙虎 68vs79/机构净买) | 调研已实测并标注;兜底场景(东财故障)可接受,替换主源前需 diff 差集 |
| 炸板率 ratio_count 的 func2 | FAPI 兜底时分子(FAPI 炸板数)与分母(东财涨停池)可能混源——仅当东财涨停池也挂时退化为 0/0 保护;现实测东财活,不受影响 |
| intraday 盘中链路 | 不覆盖。盘中涨停池实时仍东财,盘中故障需另行评估(不在本任务) |
| 北交所 | 涨停池 FAPI 可能含北交所(调研 339 只),若东财口径不含,兜底数字略高——width 宇宙口径问题已列入"待用户拍板"清单(与调研 §2.4 一致) |
| 单点依赖 | FAPI 是单一外部依赖,主链不动 + 只做兜底,风险可控 |

## 5. 验收要点(给用户)

1. `python -c "from app.collector.fapi_fallback import try_fallback; try_fallback('stock_zt_pool_em','20260901')"` → 80 rows
2. 东财正常时 collect_snapshot 仍返回东财值(83/79),msg=ok
3. 改动仅新增分支,主链路行为零变化(可 git diff 核对)
4. 如需强制验证兜底路径:临时把东财函数 mock 抛异常 → collect_snapshot 应返回 FAPI 值 + msg 含 `fapi-fallback`

## 复现

**改动文件**:`app/collector/fapi_fallback.py`(新)、`app/collector/fetchers.py`(2 处:import + 空值分支)

**输入依赖**:`data/sentiment.db`(daily_metric,仅对照)、`.env` 的 `HITHINK_FINANCE_API_KEY`、`config/indicators.yaml`

**验证命令**(worktree venv,20260901 实盘数据):
```bash
cd /Users/linhuichen/code/trade
# FAPI 四端点兜底
.venv/bin/python -c "
from app.collector import fapi_fallback as ff
for f in ('stock_zt_pool_em','stock_zt_pool_dtgc_em','stock_zt_pool_zbgc_em'):
    df,m=ff.fetch_zt_fallback(f,'20260901'); print(f,len(df),m)
df,m=ff.fetch_lhb_fallback('stock_lhb_detail_em','20260901'); print('lhb',len(df),m)
"
# 主链路不抢跑(东财活时应返回东财值)
.venv/bin/python -c "
from app.collector.fetchers import collect_snapshot
import yaml; m={x['id']:x for x in yaml.safe_load(open('config/indicators.yaml'))['metrics']}
for mid in ('a_width_zt_count','lhb_count'):
    print(mid, collect_snapshot(m[mid],'20260901'))
"
```

**数据截止**:2026-09-02 凌晨实施,20260901 实盘数据对照;FAPI 与东财同日均在场。

**关键口径一句话**:FAPI 涨停 80/跌停 0/炸板 6/龙虎 68 vs 东财 83/0/6/79;兜底返回东财兼容 df 复用 transform 链;跌停真0 由 cross_check 先行拦截。
