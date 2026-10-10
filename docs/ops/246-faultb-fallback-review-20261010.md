# #246 独立审查报告:B4-1 兜底链修复 + B4-2 重试策略(feat/246-faultb-fallback)

> 残留后台任务:**无**。全程短命令 + 自管 nohup 已回收;未出现 `moved to the background (ID:`。
> 审查者:reviewer agent(independent, fresh context);纪律:只读——未 Edit 业务文件、未 commit/push、未改 worktree 分支/HEAD;**探针一律 static-only**(§18 L50);**自测零外发**(§18 L48,全请求打桩 + 先证沙箱生效)。
> 对象:分支 `feat/246-faultb-fallback`(远端 tip `eb75e5394`;实施 `6111c8304` + 报告补 `eb75e5394`;base `d9911b814`;worktree `agent-a173b32fb96985c3b`,工作区洁净)。
> 依据:设计文 `docs/ops/1009-real-faults-rootcause-design-20261009.md` §B④(L126-153)+ 实施报告 `docs/ops/246-faultb-fallback-impl-20261010.md`。
> **结论:PASS —— 无阻断项**;6 项低分非阻断 finding(§6);R1 超时权限问题需拍板,recommendation=降 `RETRY_BUDGET_S` ≤570(建议 450),云上 600 不动(§5)。

---

## 1. 改动正确性(逐 hunk 审 + 边界推演)

改动 = 7 文件:`signal_kelly_backtest.py` / `nextday_gap_check.py` / `nextday_gap_check.sh` / `schedule_monitor.sh` / `docs/deploy/systemd-units-20260912.md` / 新 `scripts/tests/test_246_*.py` / `docs/pending-features-index.md`(#246 补号)。与设计文 §B④ 逐项对照:一致,无偏离。

- **B4-1(i) 主源新鲜度守卫**:`_fetch_intraday_open_prices` 先判 `main_cols_ok`(L793-796)+ `date_stale`(L797-807),主源循环仅在两守卫均过时执行(L808-815);空/缺列/日期陈旧统一落入 missing 收口 → 兜底优先(不再"整批拒用")。`_verify_spot_data_date` F4 fail-closed 语义保留(校验器未动,仅调用方策略变"陈旧→走兜底")。
- **B4-1(ii) 兜底泛化全 missing**:`missing=[c for c in target if c not in out]` + `if missing: out.update(_fetch_intraday_open_via_http(missing, expect_date=expect_date))`(L821-823)——旧码仅 16 前缀 LOF 兜底,现对所有 missing 标的兜底。
- **兜底内部腾讯→新浪降级**:`_date_matches(field, expect)`(L857-867)以腾讯 [30] 时间戳前 8 位 YYYYMMDD 为当日性锚;时间戳缺失/不匹配 → 降级新浪(新浪 [30]=YYYY-MM-DD 同锚,L893-910);**逐标的独立**(单标的双源皆败仅记 missing,不 raise);**仅 out 为空才 raise**(L913-916,fail-closed 终检)。
- **调用方 fail-closed 保留**:L2054 `real_opens = _fetch_intraday_open_prices(needed_etfs, expect_date=next_date)` + L2055-2061 `missing_keys` 显式 raise,未被本改动弱化。
- **B4-2 重试策略**:`RETRY_BACKOFF_BASE_S=60` / `RETRY_JITTER_FRAC=0.25` / `RETRY_BUDGET_S=900` / `DEFAULT_RETRY_ROUNDS=3`;净纯函数 `_retry_backoff_schedule`(L76-95,`w=base*(1+jitter*(2rng()-1))`,预算截断 `w=max(budget-total,0)`,`total>=budget break`);删旧 `DEFAULT_RETRY_WAIT=300`;CLI `--retry-wait` 语义改退避基数(默认 60)+ 新增 `--retry-rounds`(默认 3)。重试循环 L211-234:attempts=1+len(backoffs);日志串 `✓ 重试成功(第N次失败后重试)` / `⚠ 第 N 次拉开盘价失败` / `等 Xs 退避重试(第N/M轮, 预算≤900s)`。

**边界推演(5 项,逐项给判)**:
| 边界 | 行为 | 判 |
|---|---|---|
| empty target | 主源循环空转 → `out` 空 → 兜底 codes 空 → raise RuntimeError | 安全;生产两调用点 target 非空,不可达 |
| `expect_date=""` | `_date_matches` 恒 False(头 8 位≠"")→ 腾讯/新浪全灭 → raise | fail-closed,与旧一致 |
| 双源都败(主源也败) | 逐标的 missing → out 空 → raise → gate FAIL(全部行「待人工」+severe) | 设计预期 |
| `out.update(...)` 部分缺失语义 | 兜底返回子集 → 按 code 补齐;兜底返回空 → 兜底内部 raise | 见 finding ④(窄边界保守方向) |
| schedule 预算截断 | `rounds=0/负` → 1 attempt(无退避);budget 触顶截断至余量;`--retry-wait` 负值 → sleep 负值 ValueError | 与旧码同(pre-existing,非本次引入) |

## 2. 正常路径零变化(独立复核,非只信自测)

- **兜底零调用**:读码推演——主源新鲜且整批命中 ⇒ `missing` 空 ⇒ 不调 `_fetch_intraday_open_via_http`;test #9 断言 `stub.calls==[]`(requests.get 零调用)。
- **gap 阈值未动**:`PSEUDO_GAP_EXCLUDE=0.20`(L86)与判定式 `abs(gap)>PSEUDO_GAP_EXCLUDE`(L263-274)逐字未改。
- **日志串逐字保留**(monitor/gen_schedule_stats 集成不破):以 ast 提取两脚本内嵌 Python 的**真实 regex**(`GAP_RETRY_SUCCESS_RE` / `TRANSIENT_WARN_LINE_RE` / `ANOMALY_RE`)对旧串与新串逐条 re 匹配——「⚠ 第 N 次拉开盘价失败」命中 TRANSIENT、「✓ 重试成功(第N次失败后重试)」命中 GAP_SUCCESS;新增退避行不产生假命中、不触发 ANOMALY。`DUR_THRESHOLDS["nextday_gap_check"]=900` 数值未动(仅注释)。
- **告警 dedup key 未动**:`_severe_alert` 的 `nextday_gap_check_gen_fail`(L104,归 #245 批2 目标)与 sh 侧 `--dedup-key nextday_gap_check_fail`(L69)均未动;sh 本次仅 L66 文案改。

## 3. 测试质量(红先验 + §18 L48/L49 + CI 兼容)

- **红先验独立复现**:独立 worktree `/tmp/246-verify`(checkout base `d9911b814`)拷入新测试文件实跑 = **10 failed, 4 passed in 0.61s**,与报告总数一致(10 红=缺口 1/2/3+独立+优先级+B4-2 各项)。
- **报告红绿名单不符实**(finding ②):报告称 4 绿=#4/#5/#6/#9;实跑精确名单=#4/#5/**#9/#14**(#6 实为红、#14 实为绿)。
- **test #14 空洞**(finding ①):body 仅 `src=read_text(); ast.parse(src); assert tree is not None`,与 docstring/覆盖矩阵声称的"ast 静态检查:tencent 在 sina 之前(防顺序漂移)"不符——顺序意识多源降级保护实际**无测试锚**。
- **silent-skip 检查**:模块级 try/except → `pytest.skip(allow_module_level=True)` 仅在依赖不可用时降级,属显式 skip 非静默;实测环境下 14/14 全跑。
- **§18 L48 零外发**:`_severe_alert`(内部 subprocess 调 notify.py 会真发邮件/飞书)与 `_sync_r2_and_notify` 均 monkeypatch 为 no-op(L259-260);requests.get 全量打桩且未预期 URL → `AssertionError`(沙箱"先证生效"判据);红先验 + 全量两次实跑期间零外发。
- **§18 L49 样本真实性**:假表 `_spot_df` 按 fund_etf_spot_em 真实形态(代码/开盘价/数据日期列);腾讯报文按真实 GBK 波浪号 split 并以 [30] 喂时间戳;新浪按真实字段布局。红先验在旧码跑出预期 10 红 ⇒ 样本**能区分新旧行为**(非"看起来合理"的空样本)。
- **CI 兼容独立实测**(§8 本机绿≠CI 绿;feat 无远端 CI run,ci.yml 触发仅 main):用 venv python 预注入 `akshare`/`requests` 空 ModuleType(与 `_ci_stubs.py` 注入形态逐字同构)实跑 test_246 = **14 passed, rc=0**。fixture(L99-104)自述即为 CI 空 stub 补 `requests.RequestException`,防御到位。CI 风险排除。

## 4. 全量复跑(CI 同款命令)

- feat 树:`.venv/bin/python -m pytest -q scripts/tests/` = **684 passed, 2 skipped in 91.72s**。
- base 树(独立 worktree 实跑,非推算):**670 passed, 2 skipped in 91.86s**;差值恰 +14(新测试),两 skip 在 base 树同 reason 出现(存量属实)。报告"684−14=670 推算"被实跑坐实。

## 5. R1 独立意见:RETRY_BUDGET_S=900 > 云上墙 600

**云上只读实测硬事实**(ssh 122.51.111.173):`TimeoutStartUSec=10min`(=600s)、unit 文件 `TimeoutStartSec=600`、`KillMode=control-group`、`ExecStart=/bin/bash .../nextday_gap_check.sh`(**无参数**)、上次真跑 2026-10-09 09:26:00→09:31:43 = 343s exit=2。云上 unit 手工管理,git pull 不更新。
**余量**:默认 60×3 jitter 后总退避 ≤225s;600−225=375s 余量给拉数/落盘/R2/通知。900 仅在操作员显式传大 `--retry-wait/--retry-rounds` 时才触。

| 选项 | 利 | 弊 |
|---|---|---|
| A 保持 900 | 零改动;默认行为不受影响 | 预算声明(900)与墙(600)矛盾=死代码+假安全感;显式大参数时未触预算先被 systemd 硬杀 |
| B **降 ≤570(建议 450)** | 预算落墙内、声明可信;不裁剪默认(≤225);450 保 150s+ 墙内梯度 | 若未来确需长窗口需再抬(重评) |
| C 云上抬墙 ≥1050 | 保留长窗口 | 云上 unit 手工管理(git pull 不更新)=部署面漂移隐性依赖;两处必须同批改,漂移即回 A 弊端 |

**推荐 B(降 `RETRY_BUDGET_S=450`)**:与 `nextday_gap_check.py` L392-396 **既有 #223 注释**同构("不能单独抬到 900——本链外层 systemd TimeoutStartSec=600,抬过 600 会先被 systemd SIGKILL")——本次把预算上限设到 900 恰是对该既有判据的表面违反(默认用不到,但语义矛盾);且 `KillMode=control-group` ⇒ 超墙=整 cgroup 硬杀,bash 包装层的 `RC!=0` 告警路径**根本走不到**(静默硬杀,最坏结局)。若拍板需长窗口,则必须同批抬云上墙 ≥1050 留梯度(C 的完整做法),不容内外不匹配。

## 6. 非阻断 finding(6 项,按严重度降序)

1. **[中低] test #14 空洞测试 + 覆盖矩阵描述不实**:`test_246_via_http_source_of_truth_static` 实际不验证"tencent 在 sina 之前",顺序漂移无测试锚。建议:补真 ast 顺序断言(或删误导性 docstring/矩阵行)。
2. **[低] 实施报告红绿名单不符实**:4 绿名单应以实跑 `-v` 为准(#4/#5/#9/#14)。总数 10/4 无误。
3. **[低] `_verify_spot_data_date` docstring 过时**(L713-715):仍写"主源陈旧时整批拒用、不落到 LOF 兜底 / 仍陈旧则跳过本轮",与新"陈旧→兜底优先"矛盾。doc 漂移,建议随手同步。
4. **[低] 窄边界保守方向不一致**:主源部分成功 + 兜底子集全灭 ⇒ 兜底内部 raise ⇒ **整批** gate FAIL(全部行待人工),而非"逐标的 missing"。与设计"单标的失败不拖累其他"精神不一致,但方向保守(实时源全挂时整批待人工,安全侧),不阻断。
5. **[低] 注释/报告数字小误**:退避实际区间 135~225s(3×45=135 下界),注释"≈180~225s"不精确。
6. **[待拍板] R1**(§5):推荐降 `RETRY_BUDGET_S=450`;若采纳,属本 feat 内 1 行常量,建议在 #246 内落定后合并,避免二轮。

## 7. 共享面 #245 批2 + merge 建议

- **ngc 冲突面**:#245 批2 计划动 L104(`_severe_alert` dedup-key 统一 `nextday_gap_check_fail`);本次动 L58-95/164-171/208-234/241 → **不同 hunk,零文本冲突**(任意 merge 顺序均可)。
- **sh 侧**:`--dedup-key nextday_gap_check_fail` 已存在且未动(批2 前置条件满足)。
- **schedule_monitor.sh**:本次仅 L216-217/L679 注释;#245 批2 落 r7 模板区(~L730-760)→ 无冲突。

## 8. 报告↔实物一致性 + §23.11

- `git diff --stat d9911b814..eb75e5394` 7 文件与报告 §七产物清单(5 改 + 2 新)逐项对,无多报/漏报。
- §23.11:worktree 洁净;两 commit 内容与声明一致;origin/main 新 3 个 docs commit 与 feat 7 文件**零重叠**(无静默覆盖/倒退)。
- 任务书点 8(schedule_monitor.sh 顶格 `#` 注释行):内嵌 Python heredoc(L65-3018)经 `ast.parse` 验证语法合法(顶格 `#` 是合法注释),**纯风格差异,非问题**。

## 9. 附:关键复现命令

```bash
# 红先验(独立 worktree,已回收)
git worktree add /tmp/246-verify d9911b814 && cp scripts/tests/test_246_*.py /tmp/246-verify/scripts/tests/ \
  && cd /tmp/246-verify && .venv/bin/python -m pytest -q scripts/tests/test_246_*.py -v   # → 10F/4P
# 全量(feat 树) → 684P/2S;base 树 → 670P/2S
# CI 模拟(缺库 stub 形态) → 14P rc=0
/Users/linhuichen/code/trade/.venv/bin/python -c "import sys,types; sys.modules['akshare']=types.ModuleType('akshare'); sys.modules['requests']=types.ModuleType('requests'); import pytest; pytest.main(['-q','scripts/tests/test_246_faultb_fallback_20261010.py'])"
# R1 云上核
ssh -i /Users/linhuichen/tdsignal.pem -4 ubuntu@122.51.111.173 'systemctl show trade-nextday-gap-check.service -p TimeoutStartUSec -p KillMode'
```
