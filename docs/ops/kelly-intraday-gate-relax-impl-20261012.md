# #254 凯利盘中「数据就绪闸」放宽(方案 A)实施台账(2026-10-12)

## 0. 四件套(§23.5)

| 件 | 位置 |
|---|---|
| 本体(设计/口径总账) | 本文件 |
| 生成脚本(实现) | `scripts/kelly_intraday_gate_decider.py`(判定器/状态/豁免)、`scripts/kelly_intraday_gate_ack.py`(确认 CLI)、`scripts/signal_kelly_backtest.py`(P0 分类 + 出档写 `unpriced_codes`)、`scripts/kelly_intraday_rerun.sh`(接线)、`scripts/nextday_gap_check.py`(签名同步) |
| 复现段 | §7(命令 + 真实样本来源 + 期望输出) |
| 配套 commit | `git log --oneline -1 -- scripts/kelly_intraday_gate_decider.py`(自包含, 不写死哈希防漂移) |

施工图(上游, 逐字): `docs/ops/kelly-intraday-gate-relax-design-20261012.md`、`docs/ops/kelly-intraday-rerun-exit5-20261012.md`。
语料底座: `docs/kelly/analysis/kelly-intraday-gate-zero-volume-series-20261012.json`(113 运行日)。
保留的 fail-closed 出处: `docs/ops/246-faultb-fallback-impl-20261010.md:155`。

## 1. 改了什么(一句话)

exit5 原本 = 「取不到今日真实开盘价」一刀切 fail-closed(#246 B4-1 刻意设计语义)。本轮把它**按码分类**:
**可证实「09:40 前零成交」** 归 `zero_volume`(可出档, 不阻断);**真取不到**归 `unfetchable`,只有在
「未豁免取不到 / target > R=15%」时才 abort(exit 5)。**单日比例 > R 仍然 fail-closed** —— 放宽的是
「零成交也算缺口」这一类误伤,放宽的**不是**阈值语义。

## 2. 三段闸(冻结结构, §一)

| 优先级 | 闸 | 判据 | 出口 |
|---|---|---|---|
| P0 | 逐码分类(绝对前置) | 两源之一 `[30]==今日` 且 今开<=0 → `zero_volume`;否则 `unfetchable`(不可证实一律保守归此类) | 决定 ratio 分子 |
| P1 | 豁免查表(overlay) | 4 元组匹配 = 子集命中(`F.codes ⊆ E.codes`)+ 类别一致 + 源上下文一致 + `r_band ≤ band_cap` + 未过期 | 命中 → 移出分子 |
| P2 | 单日比例闸 | `ratio = 未豁免 unfetchable / target` > R(15%) | abort → exit 5(整轮跳过) |
| P3 | 累计运行日闸 | 容忍带 `0 < ratio ≤ R` 连续 ≥ D(5) 运行日 | 仅 WARN(不阻断) |

分类 > 豁免 > 单日 > 累计。空轮 `target==0` → verdict `pass`, exit 0, 静默(§五.6 版本断层已消)。

## 3. 冻结参数与冻结接口(§23.7, 改动须用户确认)

- R=15% / D=5 / 零成交类 TTL=60 自然日 / 取不到类 TTL=14 自然日(永不静默)/ band 地板: k≥3 或 r≥50% 无条件 WARN
- 豁免命中不自动续期;`band_cap = max(R, 确认时 r_band)`
- 新产物 `data/kelly_intraday_gate_report.json`,字段: `run_date / target_count / missing_count / ratio /
  main_source_ok / fallback_used / codes[{code,class,evidence,ts}] / exempted[] / verdict(pass|tolerate|abort) /
  unpriced_codes[] / unpriced_zero_volume_codes[]`
- **未定价双字段(接口补丁, 冻结)**:`unpriced_codes: [string]` = 本期**全部未定价**、未计入买价基准的代码
  (零成交类 + 取不到类含容忍带内放行的);`unpriced_zero_volume_codes: [string]` = 其中「09:40 前零成交」
  (class=`zero_volume`)的**子集**。不变式 `unpriced_zero_volume_codes ⊆ unpriced_codes`;
  子集缺失/为空时前端退回中性措辞 ⇒ 后端必须保证零成交类**不漏**归子集。
  两字段**同批出现在**盘中档 JSON 与 `data/kelly_intraday_gate_report.json`。
- **字段真实层级(以实际产物为准, 已实测)**:线上 `signal_kelly_trades_intraday.json` 的 `top_keys` 含
  **root 级 `intraday`**、**无 `meta`** ⇒ 路径 = **`intraday.unpriced_codes`** / `intraday.unpriced_zero_volume_codes`,
  **不是** `meta.intraday.*`(派单原措辞不精确, 见 §7 复现段实测命令)。`signal_kelly_backtest_intraday.json`
  同为 root 级 `intraday`(代码 `output["intraday"] = dict(trades_output["intraday"])`)。
- 退出码:`5` = 就绪闸 abort(整轮跳过, 保留);`0` = 出档(可能是 tolerate, 带 `unpriced_codes`)

## 4. 豁免状态机(§三)

状态文件 `data/alerts/kelly_intraday_gate_state.json`(flock + tmp/rename 原子写),追加式 ledger
`data/alerts/kelly_intraday_gate_ledger.jsonl`。**五维自动失效**:

| 维 | 触发 | 处置 |
|---|---|---|
| 集合新增成员 | 曾命中的面出现新码(`F.codes ⊄ E.codes` 且有交集) | 不命中 + 当日**强制 WARN**(附扩面命令),旧记录保持 active |
| 类别变化 | 覆盖码 `class` 与确认时不一致 | `invalidated:class` |
| 源上下文变化 | `{main_source_ok, fallback_used}` 与确认时不一致 | `invalidated:source` |
| 量级超带 | `r_band > band_cap` 连续 2 次 | `invalidated:band`(第 1 次先记 strike) |
| TTL 到期 | 超 60/14 自然日 | `invalidated:ttl` |

- 零成交类命中 → **完全静默**(仅 ledger/info 留痕);取不到类命中 → **降级 WARN**(7d 去重, 永不静默)
- fail-safe:状态读失败 → 当「无豁免」判定(偏告警)+ 独立 WARN(dedup 24h)
- 语义锚点(§23.13):问题面 = **观测形态**,不区分停牌/清盘/零成交/封禁成因;
  「09:40 前零成交」≠「当日零成交」——确认范围只覆盖 09:40 这一刻两源无当日成交的形态(确认卡与文案同口径)

## 5. 首任务(§六 待验证断言)实证结论

设计稿称「`target=0` 空轮时 HEAD 两支 `:828-829` / `:917-920` 都会 raise ⇒ 会新增 exit5」。
**独立实证: 该断言成立(TRUE)** —— `_fetch_intraday_open_via_http([])` 抛 `RuntimeError(target=0)`;
`_fetch_intraday_open_prices([])` 在主源异常路径抛、在主源健康路径于 `:828-829` 抛(两条分支实测均抛)。
故本轮定义空轮语义 = 正常空档(exit 0, 静默),并已落地(§2 末行)。

## 6. 与既有降噪的关系(未被破坏)

2026-10-12 刚上线的降噪(#254 同日)逐字保留:abort 告警 = `--tier warning --from-prefix "[告警]"
--dedup-key kelly_intraday_rerun_fail --dedup-window 1800`;unit `SuccessExitStatus=5` 语义不变。
新增回退保险(§23.11 不静默):decider 自身异常时,abort 分支沿用旧内联 WARN 并保持 exit 5;
tolerate/pass 分支补 WARN(`kelly_intraday_gate_decider_crash`)后照常发布。
对账 FAIL(3)/超时(142)/其他脚本错误 → SEVERE 直达链**逐字不变**。

> 注:**同源豁免改写了 :917-920 的 raise**(原为「passed-in set 全灭 ⇒ raise」,现为返回分类结果)。
> 该 raise 的原始 fail-closed 出处 `docs/ops/246-faultb-fallback-impl-20261010.md:155` 仍保留可追溯;
> 语义迁移到 P2 单日比例闸(未豁免 unfetchable / target > R)。回测历史档(无 `expect_date`)不做日期锚:
> 有 >0 价判 priced,否则 unknown → 归 unfetchable,行为与旧码一致。

## 7. 复现段

```bash
# 全量回归(CI 同口径, CI 只跑 scripts/tests/)
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/          # 781 passed, 2 skipped
# 本任务套(#254 27 项)
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_254_intraday_gate_relax_20261012.py
# #246 回归(签名扩容同步后)
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q scripts/tests/test_246_faultb_fallback_20261010.py
# 未定价字段层级实测(真实产物, 2026-10-12 实跑; 结论 = root 级 intraday, 无 meta):
#   curl -s --max-time 40 -A "Mozilla/5.0" -o /tmp/k254_intra.json \
#     "https://ss.fx8.store/data/signal_kelly_trades_intraday.json"
#   python -c "import json;d=json.load(open('/tmp/k254_intra.json'));print(list(d.keys()))"
#   → ['generated_at','buy_amount','period_cutoffs','fields','quadrants','intraday'](含 intraday, 无 meta)
# 上线后线上自检(人工, 交易日 9:40 后):
#   python scripts/kelly_intraday_gate_decider.py --report data/kelly_intraday_gate_report.json --print verdict
#   python scripts/kelly_intraday_gate_ack.py --list
```

真实生产样本来源(§18 L49, 全套零人工构造样本):
- 语料底座 113 运行日: `docs/kelly/analysis/kelly-intraday-gate-zero-volume-series-20261012.json`
- 逐字锚 10-12: `target=24`, `codes=['159513','164508']`, 8.3%(与云上日志 L748 一致)
- n=1 100% 日(整源挂/不可细分): 03-31 `513400`、09-23 `561120`
- 容忍带样本: 10-08 `target=15`, `codes=['160638','164508']`(13.3%)、09-30 `target=23`(8.7%)
- 字段位/时间戳语义: 设计稿 §六 V2/V3(腾讯 `[5]`=今开 / `[30]`=时间戳;新浪 `[1]`=今开 / `[30]`=日期)
- 出站全量打桩(requests.get 替换)、decider `--dry-run`,**零外发**(§18 L48: 已用 subprocess 哨兵证明沙箱生效)

## 8. 机检挂载(按既有口径, 未擅改挂载点)

既有口径 = 「机检挂载定案=CI-only」:`.github/workflows/ci.yml` 跑 `python3 -m pytest -q scripts/tests/`,
新增测试文件放 `scripts/tests/` 即被自动收集,**无需改 workflow**。本轮按此挂载(未动任何挂载点)。

## 9. 云上 unit(§14)

云上 `trade-kelly-intraday-rerun.service` 实查与 `docs/deploy/systemd-units-cloud-snapshot.txt` 一致:
`ExecStart=/bin/bash /home/ubuntu/code/trade-data/scripts/kelly_intraday_rerun.sh`、`TimeoutStartSec=600`、
**`SuccessExitStatus=5` 在位**(2026-10-12 降噪时已加)。本轮 decider 由 rerun.sh 内部调用,**unit 文件零改动**
⇒ 无需 `daemon-reload`,生成源 `docs/deploy/systemd-units-20260912.md` 与快照文本均**无需更新**(机检断言其含 `SuccessExitStatus=5`)。
云上 `scripts` 是符号链接(`trade-data/scripts → trade-data-signal/scripts`),实测 Python `__file__` **不做符号链接解析**
⇒ 判定器 `REPO` 解析为 `/home/ubuntu/code/trade-data`,状态/报告落 `trade-data/data/...`(与 rerun.sh 的 `$REPO` 一致)。

## 10. 同类错误面清单(§23.2)

| 面 | 是否受影响 | 处置 |
|---|---|---|
| `_fetch_intraday_open_via_http` 返回值扩容 | 是 | 全部调用点(2 处内部 + `nextday_gap_check.py`)同步解包 |
| `_fetch_intraday_open_prices` 返回值扩容(3 元组) | 是 | 同上 + #246 测试全部调用点同步 |
| `nextday_gap_check` 的 fail-closed 语义 | 是(输入变了) | **刻意保留**:`if not out: raise`(§23.7 冻结,不在本任务放宽范围) |
| `target=0` 空轮 | 是 | 新增早返回语义(实测坐实旧码会 raise) |
| 对账 FAIL(3)/超时(142)告警链 | 否 | 逐字未动 |
| unit `SuccessExitStatus=5` | 否 | 未动(机检在位) |
| 回测历史档(无 `expect_date`)取价行为 | 否 | 保持旧行为(有价判 priced) |

## 11. 举一反三清单(§23.3)

| 同模式/同数据源/同组件 | 还被谁用 | 覆盖结果 |
|---|---|---|
| 两源(腾讯/新浪)取今开 | 仅 `_fetch_intraday_open_via_http`(回测盘中档 + nextday_gap_check) | 已覆盖,无第三方 |
| 4 元组豁免面 | 仅 `signal_kelly_backtest.compute_intraday` + decider/ack | 单一事实源(同一 `evaluate`),零漂移 |
| 告警分级/去重 | notify.py 既有通道 | 复用,未新造通道 |
| alert 状态落盘模式(flock+tmp/rename) | `alert_ack.py` / `alert_denoise_rules.py` 模板 | 同模式复用 |
| `data/alerts/` 目录 | 既有 alert 状态同目录 | 复用(云上目录已存在且属 ubuntu) |

## 12. §21 前端公示同步点(本 agent 不改前端, 移交前端 agent)

以下为**必须由前端同步公示/展示**的点(口径与文案):
1. 盘中档视图:`intraday.unpriced_codes`(**root 级 `intraday`, 无 `meta` 包裹**)→ 「N 只未定价」提示;
   文案须写明「未定价 = 09:40 前两源无当日成交 **或** 已豁免取不到」,不得表述为「失败/缺数据」。
   同批新增 `intraday.unpriced_zero_volume_codes`(其中「09:40 前零成交」子集):只有该子集才可宣称
   「已知正常形态、非数据故障」;子集缺失/为空 → 退回中性措辞。
2. 就绪闸放宽公示:口径由「取不到开盘价即整轮跳过」改为「**未豁免**取不到比例 >15% 才整轮跳过」;
   零成交类不再视为缺口;单日 >R 仍 fail-closed。
3. 豁免命中分级公示:取不到类豁免命中 = **降级 WARN(永不静默)**;零成交类豁免命中 = **完全静默**。
4. 累计闸公示:容忍带(0<ratio≤15%)连续 ≥5 运行日 → 只通知不阻断。
5. 口径锚点公示(§23.13):问题面 = **观测形态**,不区分停牌/清盘/零成交/封禁成因;「09:40 前零成交」≠「当日零成交」。
6. 退出码语义公示:`exit 5` = 本轮跳过(17:50 全量兜底),**非故障**。