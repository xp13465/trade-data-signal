# assertion4 LOF 泄漏修复 · 独立复审(2026-09-25 reviewer agent)

复审对象: feat 分支 `worktree-agent-aec4d27d16e687b98` commit `b891a29c5`(base `0985e428a`, 仅改 `scripts/build_board_etf_map.py` 4 处 + 落档)
审查方式: 只读; 关键验证在**云上隔离目录**用生产 DB 只读跑(未动任何云上生产文件、未跑 deploy.sh)。

## 结论

**PASS — 可以 merge。** 修复有效性在云上真实 DB + 新浪兜底 FAIL 场景下端到端证明:
- 修前代码 assertion4 FAIL(sw_801200×1 + sw_801950×1, 与 18:55 生产 FAIL 日志逐字一致)
- 修后代码 assertion4 PASS(assertion1/2/3/4 全 PASS, EXIT=0)
- 非 empty_array 指数逐指数零差异、场内 LOF 零误伤(见 §4)

## 1. 根因机制 — 成立

| 证据点 | 核实结果 |
|---|---|
| 东财主源不含 LOF | akshare 1.18.64 `fund_etf_spot_em()` 源码(venv site-packages/fund/fund_etf_em.py L62)fs=`b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0827`, 页面=ETF 行情页; LOF 是**独立函数** `fund_lof_spot_em()`(fund_lof_em.py, fs=MK0404-07, 页面=LOF 页)。报告写「fs=b:MK0021-24+MK0827」是简写, 语义成立 |
| 新浪兜底带 360 只 LOF | `_etf_spot_fallback.py` L47 `_SINA_NODES=("etf_hq_fund","lof_hq_fund")` 确认; 实测兜底成功 2045 只 |
| kw 层漏网点 | 修前产物实测 kw 层把 163415 兴全商业模式LOF 塞进 sw_801200、168204 煤炭LOF 塞进 sw_801950, 且 fund_type=etf(证实「新浪 LOF 无 fund_type 被 setdefault('etf')」机制, track_index 层旧守卫失效) |
| 时间线 18:13 PASS / 18:55 FAIL | 云上 data/logs/deploy_20260924_1813.log(assertion4 PASS, R2 上传+purge 完成) / deploy_20260924_1855.log 起(1930/2141 同) FAIL「终止部署」, 与报告一致 |
| ⚠ 报告数字出入 | 报告称「修前 FAIL 4 处 13 只(sw_801950×4/sw_801970×2/thsc_306380×6), 含真 ETF 515220/512580/159566」。**18:55 生产 FAIL 日志实际是 2 处 2 只**(sw_801200×1/sw_801950×1, 即 163415/168204), reviewer 复现也精确是 2 只。报告验证数字有夸大/时刻差异(「含真 ETF 515220 等」无生产日志支撑), 但不影响修复有效性(整体清空对任何规模泄漏都兜得住), 已提示实施方自报验证精度问题 |

## 2. 判据复用既有口径 — 一致

- 新判据 `_is_lof_code` = `re.match(r'^(16|15|501|502)', code)`(build L693)
- `config/universe_rules.yaml` `lof_inclusion.on_exchange_prefixes=["16","15","501","502"]`(L133)——**逐字一致**
- 项目既有代码 `_load_lof_track_index` L621 同用 `^(16|15|501|502)`—— 非自造判据 ✓
- 已知边界: 15 前缀含 159 深市 ETF, 该判据在 empty_array 上下文多滤无害(empty_array 语义=必须空), 非 empty_array 指数不受影响(实测零差异, §4)

## 3. 4 处改动逐处审 — 通过

1. `_is_lof_code` 新增函数(带完整背景 docstring)✓
2. track_index 层守卫(fund_type→_is_lof_code): 位于 `if iid in empty_array_ids:` 分支内, 只作用于 empty_array ✓
3. kw 层守卫:`if iid in empty_array_ids and _is_lof_code(code): continue`, 作用于 append 前 ✓(实测漏网点精确堵住)
4. 写盘前整体兜底清空: 位于排序后、`_apply_hysteresis` 前(L1727-1735)—— 位置正确: 空数组直接 continue 不产生 `_hysteresis` 记录;实测修前 hysteresis 残留 sw_801200/sw_801950 两条, 修后 0 条 ✓
- 其他叠加层(宽基 base/overlap/holdings/global)无逐层守卫, 但写盘前单点兜底覆盖;实测 33 个 empty_array 全空 ✓
- 兜底循环只遍历 empty_array_ids, 不碰其他指数 ✓

## 4. 误伤独立复验(最关键)— 零误伤

云上隔离目录(`/home/ubuntu/code/assertion4-review-cloud` 修后 / `-old` 修前), 生产 DB 只读, 新浪+腾讯兜底(2045 只, FAIL 场景), 同一时刻同一数据源:
- 非 empty_array 指数(exclude 元数据/_hysteresis)逐指数 code 集合**零差异**(修前 1419 条目 = 修后 1419 条目; 去重 LOF 578=578, 新增 0 删除 0)
- 33 个 empty_array 指数: 修后全空(非空泄漏 0、缺失 key 0)
- 4 个修前泄漏指数对比: sw_801200 OLD=[163415 兴全商业模式LOF kw etf]→NEW=[]; sw_801950 OLD=[168204 煤炭LOF kw etf]→NEW=[]; sw_801970/thsc_306380 全空
- 报告「1027=1027 / 496 只 LOF / 58 指数」为 18:55 时刻数据(reviewer 当前时刻 1419/578/99), 时刻差异正常, 关键=old=new 零差异成立

## 5. 云上端到端验证(补实施方缺口)— 完成

- 环境: 云上 `/home/ubuntu/code/assertion4-review-cloud{,-old}`(与生产 trade-data 平级, DB 路径 `base.parent/trade-data/data/*` 自动只读命中生产主库; data/ 下 etf_index_map/etf_track_index/lof_track_index 软链只读; app 软链; 写盘只在隔离目录)
- check_universe_alignment.py --deploy-mode(deploy.sh L335 同命令):
  - 修前: **[FAIL] assertion4**(应 empty_array 却有 1 个ETF: sw_801200 / sw_801950), EXIT=1 —— 与 18:55 生产日志逐字一致
  - 修后: **[PASS] assertion1/2/3/4 全 PASS**, EXIT=0
- **assertion1 在云上真实 DB 下 PASS**: 实施方「本地 worktree 无 DB 致 assertion1 FAIL 属环境, 云上有 DB 不受影响」说法成立
- 未改任何云上生产文件、未跑 deploy.sh

## 6. §23.6 五条 + §23.7 冻结契约 — 无需公示/联动

- ①显式声明: empty_array 规则在 universe_rules.yaml 已声明(2026-09-14 用户拍板), 本次是让产物**回归符合既有声明**, 不是改声明
- ②强制公示: 前端 empty_array 指数「无ETF」展示为既有行为, 语义没变, purpose-notes.js/app.js/lab.js 无需改
- ③首页 1:1 遵从: 空数组 → 首页 AI 建议不选 empty_array 指数 LOF(queries.py _bt_in_universe 空即不入样), 符合规则
- ④对称校验: assertion4 修后 PASS ✓
- ⑤变更联动: yaml 未改, 无需新增联动
- §23.7 判断: **实施方「empty_array 指数本来就该空, 本次恢复原状、不改用户可见入样宇宙」成立**(线上用户实际看到 9-22 前正常版, 18:55 起 FAIL 未上线, 修复只恢复 deploy 通行, 不改变任何用户可见行为); 无需新拍板、无需公示
- §21 公示查证: 未改算法/评分/权重/匹配规则口径, 只改数据过滤守卫, 公示无需同步

## 7. deploy 阻断解除 — 确认

- 修后 assertion4 PASS(与 deploy.sh L335 同命令同参数) → L339 不触发 → **下轮 deploy 会过 L334 阻断点**
- merge 后主控需: 云上跑一次完整 deploy 验证(assertion4 过 + 后续 1.2.1-1.2.3 既有 check 过 + §0③ 前端展示层)

## 8. 问题清单(严重度排序)

1. **[低] 报告验证数字夸大**: 报告 §3.4/§4 称「修前 FAIL 4 处 13 只, 含真 ETF 515220/512580/159566」, 但 18:55 生产日志与 reviewer 复现均为 2 处 2 只(163415/168204 两只 LOF)。不影响修复有效性与 merge。建议实施方后续自查报告数字与生产日志对齐。
2. **[低·pre-existing 备注] 非 empty_array 指数中的新浪 LOF fund_type 仍可能标 etf**(如 sz 163109 申万深成LOF, track_index 层 `info.get("fund_type","etf")` 若 LOF 不在 lof_track_map 则落 etf)。不在本次 diff 引入, 不影响 empty_array 过滤(判据已改代码前缀); 若前端/下游按 fund_type 区分展示, 属既有行为, 已按 §10.3① 不上报为 finding, 备用登记。

## 9. 复现段

```bash
# 云上(生产 DB 只读隔离):
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173
# /home/ubuntu/code/assertion4-review-cloud{,-old} 已含修前/修后代码(与 trade-data 平级)
cd /home/ubuntu/code/assertion4-review-cloud
/home/ubuntu/code/trade-data/.venv/bin/python scripts/build_board_etf_map.py   # 东财被封自动走新浪兜底(2045只)
/home/ubuntu/code/trade-data/.venv/bin/python scripts/check_universe_alignment.py \
  --repo /home/ubuntu/code/assertion4-review-cloud \
  --overview /home/ubuntu/code/trade-data/static-site/data/overview.json \
  --board-map /home/ubuntu/code/assertion4-review-cloud/data/board_etf_map.json \
  --trades /home/ubuntu/code/trade-data/static-site/data/signal_kelly_trades.json --deploy-mode
# 期望: 4 断言全 PASS(修前同命令 assertion4 FAIL)
```

## 10. 修改文件
- 本审查未改任何代码。落档: `docs/ops/assertion4-lof-leak-review-20260924.md`
