# #145 + #146 fapi_fallback.py 修复 独立审查报告(2026-10-01)

> reviewer 独立审查(非实施 agent,不复用其实验脚本,独立构造前后两版逐位比对)。
> 分支 `worktree-agent-a1593f5b599a18d5a`,HEAD `4c796b176`;base `0b025c7db`(线上现状)。
> **结论:PASS-with-caveat**(3 条 caveat,均低风险,见第七节)。

## 审查方法

- 前后两版对照:旧版=`git show 0b025c7db:app/collector/fapi_fallback.py`(线上现状),新版=worktree HEAD。独立构造 `/tmp/rev_diff_test.py`(SourceFileLoader 双模块 + mock `_api`),16 断言全 PASS,不复用实施者 prove145/146.py。
- 全只读,主仓无改动;不改分支不 commit。

## 一、#145 分流判据独立核(头号问题)

**分流变量** = `r = ZT_ENDPOINTS.get(func_name)`,映射表 `{stock_zt_pool_em→limit-up-pool, stock_zt_pool_dtgc_em→limit-down-pool, stock_zt_pool_zbgc_em→limit-break-pool}`(fapi_fallback.py L29-33)。

**真实调用链唯一性**:全仓 `try_fallback` 调用方仅 `app/collector/fetchers.py` L616/L623(独立 grep 证实,intraday_snapshot/backfill/width_history 均不经三池);func_name 来自 `config/indicators.yaml` L22-25 三个 metric,恰好对应三池,无第四池落入。`func_name` 不在映射表 → `r=None` 提前 return(L116-117),不会落入 else 默认分支。

**独立测试**:涨停池 params 仍 `date_ms=1728316800000` 且无 date(与旧版逐位相同);跌停/炸板池 `date=20241008` 且无 date_ms;翻页 3 页参数继承正确、请求次数一致。→ **分流无错池、无默认分支误吞**。

**mock 是否自证同义反复**:「涨停池逐位不变」在代码未动分支下确属自证,但真正风险点(新 else 分支不污染涨停池 / 翻页参数继承 / date 值正确)已被 mock 断言覆盖,且外部契约另有 #140 独立 reviewer 实测链(见二)。自证不构成缺陷。

## 二、真实外部契约证据链

- 契约文档 `docs/fapi/fapi-integration-plan-20260901.md` L200-202:**仅 `limit-up-pool` item 有 `continue_day_cnt`;limit-down-pool 字段=total/first/last_limit_time/turnover_ratio_pct;limit-break-pool 字段=total/items** → #146 判断成立。
- **date_ms vs date 证据** = #140 独立 reviewer 真实调用取证(台账 `pending-features-index.md` L231 原文:「独立真实调用,跌停/炸板池老日期(20241008/20240930/20240417)date_ms 报 code=1002,改 date=YYYYMMDD 则成功」),非本次实施者闭门实验,满足 §5.1 实测优先。
- 龙虎榜端点 `date=yyyy-MM-dd` 契约文档 L150 明示(隔离确认)。
- WebSearch 已尝试:FAPI=自建代理 `fuyao.aicubes.cn`,非公开东财 push2 接口,社区无公开参数文档可佐证 → 以 #140 实测 + 契约文档为据,证据链成立。

## 三、#146 has_lianban 参数全覆盖

- `_zt_df` 外部无任何调用者(独立 grep);唯一调用=fetch_zt_fallback L162,显式传 `has_lianban=(r=="limit-up-pool")` → **无漏网调用方**。默认值 True 只影响未来新增调用,若新增方对跌停/炸板池不传参数会回退旧 NaN 行为,但当前不存在该调用方。
- `fillna(0)` 在 `_zt_df` 内部,对将来任何 `int()/max()` 变换均兜底。
- indicators.yaml 证实跌停/炸板池仅 count_rows/ratio_count(消费 len),无 max/mean 消费者;涨停池 max(连板数)只对涨停池生效。

## 四、§23.7 不变性:独立构造样例逐位比对(16/16 PASS)

独立脚本 `/tmp/rev_diff_test.py`(命令 + 输出见复现段):
- S1 涨停池无缺值:新旧 df.equals=True,连板列 `[2,5,1]` 逐位一致,date_ms 原样。
- S2 涨停池个别缺值:旧 `[5.0,nan,3.0]` vs 新 `[5.0,0.0,3.0]`(如实差异,方向安全,max 语义等价)。
- S3/S4 跌停/炸板池:旧参 date_ms(契约错)→ 新 `date=YYYYMMDD`;连板列旧 `[None,None]` → 新 `[0,0]`。
- S5 翻页:涨/跌各 3 页取满 600,参数逐页继承正确,请求次数新旧一致。
- S6 **最新价/涨跌幅/代码/名称列零 diff,列名集合一致** → 未被顺手改动。
- S7 `_date_ms("20241008")==1728316800000` 手算核对正确。

## 五、同类错误面清单(报告 7 项)独立核真伪

| 项 | 报告判定 | 独立核 |
|---|---|---|
| 1 fetch_lhb_fallback date=YYYY-MM-DD 隔离 | ✅ | 属实(L175-179 独立 ms→date 转换) |
| 2 _lhb_df org_net_value 值 None 失真 | ⚠️ 登记 | 属实(L166 只查列存在),pre-existing,登记合理 |
| 3 跌停/炸板池最新价/涨跌幅列全 None | ⚠️ 登记 | 属实(契约 L201-202 无该字段),当前无消费者(仅 count_rows/ratio_count),登记合理 |
| 4 width_history.py L112 dump daily-k | ✅ | 属实,独立函数不经三池 |
| 5 全仓分页唯一同款=fapi_fallback | ✅ | 属实(#140 已独立 grep) |
| 6 调用链只消费 len | ✅ | 属实(indicators.yaml 实证) |
| 7 龙虎榜兜底链未触碰 | ✅ | 属实 |

**无漏掉的同类点**:`_zt_df`/`_lhb_df` 内 `it.get()` 无默认值的字段(continue_day_cnt/last_price/price_change_ratio_pct/org_net_value)已全部被覆盖或登记。

## 六、台账一致性 + 报告四件套

- 台账 `pending-features-index.md` L236(#145)/L237(#146):状态「✅ 已修复」,编号未变,commit 串与实际链一致 → §23.12-1 一致。
- 报告含「复现段」(命令+脚本路径),prove145.py/prove146.py 实测存在且与报告描述一致 → §23.5 四件套满足。
- §21:采集兜底参数口径,不涉前端公示算法文案,不触发(#140 同判)。
- worktree 状态干净;新版 `python -m py_compile` PASS。

## 七、Caveat(均低风险,PASS-with-caveat)

1. **跌停/炸板池「当日实时」参数口径也切换**(date_ms→date,不只老日期):当日数据等价性基于「同一服务端同一天池」合理假设,未在真实服务端 A/B 逐位对账。风险低(#140 已实测 date 参数可用),上线后首个交易日兜底触发时顺带核对即可。
2. **涨停池个别缺值 item 由 NaN→0**:方向安全且 max 语义等价,但严格说非「逐位不变」,报告样例 C 已如实标注。
3. **FAPI 特殊端点参数格式无公开文档**(自建代理),date_ms/date 证据链靠 #140 独立实测,无社区二次佐证(WebSearch 已试无果)。

## 八、低分项(<80)已滤说明

- 跌停/炸板池兜底 df 的「最新价/涨跌幅」列在真实契约下整列 None(我构造样例带上了价格字段,真实场景无):报告同类面 #3 已登记,当前无消费者,非本次改动引入 → 滤除。

## 复现段

```bash
# 独立前后两版逐位比对(16 断言):
/Users/linhuichen/code/trade/.venv/bin/python /tmp/rev_diff_test.py
#   → 16/16 PASS(涨停池 df.equals / date_ms 原样 / 跌停·炸板 date=YYYYMMDD+连板0 /
#     翻页参数继承 / 最新价涨跌幅零diff / _date_ms 手算核对)

# 实施者复现脚本(已核存在且与报告一致):
/Users/linhuichen/code/trade/.venv/bin/python /tmp/prove145.py
/Users/linhuichen/code/trade/.venv/bin/python /tmp/prove146.py

# 证据来源:
git show 0b025c7db:app/collector/fapi_fallback.py          # 旧版(线上现状)
grep -rn "try_fallback" --include="*.py" app/              # 唯一调用方 fetchers.py L616/623
sed -n '200,202p' docs/fapi/fapi-integration-plan-20260901.md  # 契约字段表
sed -n '231p' docs/pending-features-index.md               # #140 reviewer 实测取证
```
