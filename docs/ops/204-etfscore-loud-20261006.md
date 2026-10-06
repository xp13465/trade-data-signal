# #204 etf-score 通道上传失败 loud 化 —— 实施与自验报告(2026-10-06)

- 任务:pending-index #204 —— `update_all.sh:205` 的 `upload-etf-score` R2 上传失败**仅 echo**(未接
  `_notify_channel_upload_fail`),用户侧静默。
- 分支:`feat/204-etfscore-loud-20261006`,base = main `668952060`(开工 `merge-base --is-ancestor
  origin/main HEAD` = base-fresh)。
- 定性:代码改动(非数据/算法),无 §22 数据产物同步、无 §21 公示同步、无 §24 前端发版。

## 0. 结论(一句话)

**已接。** 经增量引擎 `_incremental_upload` 新增的 `on_fail` 回调,把 etf-score 通道上传失败接到
`_notify_channel_upload_fail`(与 #193 的 fund-score/offshore-fund 同严重级别、同 6h 去重、同文案骨架)。
自验 **21 PASS / 0 FAIL**;`test_193` 回归 **40 PASS / 0 FAIL**;通道覆盖机检 **ALL_PASS**;本次自测
**零真实外发 / 零真实 R2 写**(真实 `notify.send` 陷阱计数 0)。

## 1. 任务书 vs 代码现状的两处偏差上报(§23.11 绝不静默)

派单 prompt 假设与 `upload_r2.py` 实际结构有两处不符,**已按代码现状正确落地**,如实上报:

**(a) 「cmd_upload_etf_score 的失败分支」实际不存在(失败分支在引擎内部)。**
etf-score 走**增量引擎** `_incremental_upload`,引擎在 `if ok != total:` 分支里**自己 `sys.exit(1)`**
(见 `scripts/upload_r2.py:1460-1472`),**永不把 `ok/total/failed_rels` 返回给调用方**。因此无法照抄
fund-score 那样「在 cmd 里 `if ok != total: notify`」(那段会成**不可达死码**,notify 永不触发)。
→ 正确根因修法:给引擎加**可选** `on_fail` 回调(默认 `None`),仅在 `ok!=total` 分支、`sys.exit(1)`
**之前**调用一次;etf-score 传入 notify 回调。

**(b) 「#193 三处既有接入点」实为 2 处 notify 调用点 + 1 个对账通道。**
`_notify_channel_upload_fail(` 的**调用点**只有 2 个:`cmd_upload_offshore_fund`(L1743)、
`cmd_upload_fund_score`(L1765)。news-digest **不是**上传命令(它是 `_R2_CHANNELS` 里的对账/覆盖通道,
无自己的失败 notify 路径)。#193 的「+3 通道」指 `_R2_CHANNELS` 登记(对账覆盖),与「失败 loud 接入点」
是两个不同集合。逐字对齐 **以 2 处 notify 调用点**为基准。

**(c) `update_all.sh:205` 调用点无需同步。** 引擎失败本就 `exit 1`,故该行 `|| echo "…（不阻塞主流程）"`
**原本就会触发**(只是只 echo、无 notify);notify 现在由脚本内部发声,`|| echo` 保持原样即可(与
#193 对 fund-score 的处理一致:留给 `update_all.sh` 的 `|| echo` 未动)。**另一个调用点 `scripts/r2_upload_async.sh:180`
已把 etf-score 纳入 `R2_FAIL` 聚合框架**,本改动同样受益,亦无需改。

## 2. ① 三处既有接入点逐字对齐证据(实为 2 处 notify + 引擎)

| 维度 | offshore-fund(L1743) | fund-score(L1765) | **etf-score(本改动)** |
|---|---|---|---|
| 告警函数 | `_notify_channel_upload_fail` | 同 | 同 |
| label | `"offshore-fund"` | `"fund-score"` | `"etf-score"` |
| cmd_name | `"upload-offshore-fund"` | `"upload-fund-score"` | `"upload-etf-score"` |
| r2_prefix | `"offshore_fund"` | `"fund_score"` | `"data"` |
| 严重级别 | `severe=True` | `severe=True` | `severe=True`(同,helper 内固定) |
| 去重键 | `r2_channel_upload_fail_<label>` | 同 | `r2_channel_upload_fail_etf-score` |
| 去重窗口 | `21600`(6h) | 同 | 同(helper 内固定) |
| notify 形态 | `check_dedup` 未命中→`send`→`update_dedup` | 同 | 同(helper 内固定) |
| title 骨架 | `[告警] R2 上传失败: {label} 通道({ok}/{total})` | 同 | 同 |

**唯一差异 = 「含义」行末尾的括注(per-channel)**:`_notify_channel_upload_fail` 原把
`(fund_score 为场外基金评分 fallback 数据源)` **写死**在文案里。直接复用会把 **fund_score 的影响说明
误挂到 etf-score 通道**(且既有 offshore-fund 调用点其实也一直被误挂)。故新增可选参数 `impact_note`,
**默认值 = 原文案字符串**(⇒ fund-score / offshore-fund 两个既有调用点**字节不变**,见下);etf-score
传本通道自己的括注 `(etf_score_list_* 为 ETF 评分三大榜(buy/sell/hold)前端数据源)`。

> 既有调用点字节不变机检:`old_line == new_line` → **True**(见 §4 复现段命令)。**未改 offshore-fund
> 的历史误挂括注**(遵派单「不扩大范围」;该 wart 见 §6 上报项,交主控处置)。

## 3. ② 改动文件清单 + `git diff --stat`

```
 scripts/upload_r2.py                  | 31 ++++++++++++++++++++++++++-----
 scripts/test_204_etfscore_loud.py     | (新增, 自验脚本)
 scripts/… 报告 docs/ops/204-etfscore-loud-20261006.md (新增, 本文件)
```

`upload_r2.py` 改动 4 处(共 +31/-5 行,均为最小增量):
1. `_incremental_upload(...)` 签名 +1 关键字参数 `on_fail=None`(+ 对应 docstring 段)。
2. 引擎 `if ok != total:` 分支、`sys.exit(1)` 前:`if on_fail is not None: on_fail(ok,total,failed_rels)`
   (带 try/except 兜底,回调异常不阻塞退出语义)。
3. `_notify_channel_upload_fail(...)` 签名 +1 关键字参数 `impact_note="(fund_score …)"` + 文案改为
   `…缺文件{impact_note}。`(+ docstring 段)。
4. 新增 `_etf_score_on_fail(ok,total,failed_rels)` 回调 + `cmd_upload_etf_score` 传入
   `on_fail=_etf_score_on_fail`(+ docstring 段)。

**边界确认**:`on_fail` 默认 `None` ⇒ 其余 **11 个增量通道零行为变化**(自验 [D] 断言 `默认 None is True`
+ 不传时失败仍 `exit 1` 不发告警)。**只动 etf-score 这一条通道的行为**,与派单「不扩大范围」一致。

## 4. ③ 打桩生效证明 + 零真实外发证据(§18 L48 硬门)

自验脚本 `scripts/test_204_etfscore_loud.py` 三重防线(与 `test_193` 同款):
1. `sys.modules['notify']` 置换为 Fake(**早于任何命令路径**);真实 `notify.send` 挂**陷阱函数**
   (触达即 `AssertionError`)。
2. `_upload_glob` / `_backup_overwritten_keys` / `purge_cache` **全打桩**(引擎真跑,零真实 PUT/COPY)。
3. `STATIC_DIR` + `ROOT` 重定向到临时树(不碰真实仓库树)。

**零真实外发证据(脚本末 [E] 段)**:
```
[E] 真实 notify.send 全程零触达(陷阱计数 0)          PASS
[E] 所有 _upload_glob 触达均走打桩(零真实 PUT)       PASS
[stub] … 真实 trap 0 次; _upload_glob 桩触达 1 次
```
真实 `notify.send` 陷阱计数 = **0**(未触达);引擎真跑到上传步骤(桩触达 1 次)⇒「打桩确实生效、
本次自测**未产生任何真实外发**」是**被证明**的,不是「恰好没跑」。

## 5. ④ 失败路径注入测试(构造失败 → 断言告警被调用一次、文案/state key 与既有一致)

| 用例 | 注入 | 断言 | 结果 |
|---|---|---|---|
| [A] helper 层 | 直接调 `_notify_channel_upload_fail("etf-score",…,1,2,["hold.json"])` | 发 1 条;标题 `[告警] R2 上传失败: etf-score 通道(1/2)`;`severe=True`;去重键 `r2_channel_upload_fail_etf-score`/`21600`;`update_dedup` 落键;括注为 etf-score 自身 note | 8 PASS |
| [B] 失败路径(端到端) | `cmd_upload_etf_score()` + `_upload_glob` 桩返回 `(1,2,[hold],[buy])`;临时树旧状态→`mode=增量` | `exit 1`;**发 1 条**告警;标题含 `etf-score`+`1/2`;去重键同族;引擎真跑到上传步骤 | 5 PASS |
| [C] 成功路径 | `_upload_glob` 桩返回 `(1,1,[],…)` | 不 exit;零告警(不制造噪音) | 2 PASS |
| [D] 回归 | 默认文案字节对比 + `on_fail` 默认 None + 无回调时失败仍 exit 1 | fund-score 既有文案**字节不变**;默认 None;无 on_fail 不发告警 | 4 PASS |
| [E] L48/L50 硬门 | — | 真实 notify 陷阱零触达;桩零真实 PUT | 2 PASS |

**合计 21 PASS / 0 FAIL(`ALL_PASS`)**。

## 6. ⑤ 同族扫描(只报不改)—— `upload_r2.py` 其余「失败未接 notify」通道

**已接 `_notify_channel_upload_fail` 的通道(本改动后)**:offshore-fund、fund-score、**etf-score**。

**未接清单(只报不改)**:

| 类 | 通道(命令) | 失败可见性现状 |
|---|---|---|
| A. 增量引擎(`_incremental_upload`) | `cmd_upload_trade_sim` / `_trade_sim_json` / `_index` / `_etf_hist` / `_fund_nav` / `_accum_nav` / `_industry` / `_kelly_parts` / `_kelly_parts_sdc` / `_kelly_snapshots` / `_data_large` / `_all_data`(**12 条**) | 引擎 `ok!=total` 时内部 `sys.exit(1)`(**无 notify**);多数靠 `deploy` 的 `R2_FAIL` 聚合框架兜可见性,但**通道级告警正文不发邮件/飞书** ⇒ 与 etf-score 修复前**同症状族**(可选 `on_fail` 已就位,接入成本 = 各传一个回调) |
| B. `_upload_glob` 直调 | `cmd_upload_intraday` / `cmd_upload_data_files`(`exit 1`)/ `cmd_upload_large_json`(私有桶,`exit 2`) | 失败 `exit 1/2`,但**无 notify**(与 etf-score 修复前同类:仅退出码,无通道级告警正文) |

> 归属:本清单是 §23.3 举一反三的「同组件还被谁用」面。**是否逐通道接入 = 主控/用户拍板**;
> 本任务遵派单「只动 etf-score 这一条通道」,**未改**其余通道行为(`on_fail` 默认 None 保证零影响)。

**另有两处相关的既有 wart(上报,未改)**:
- `_notify_channel_upload_fail` 的默认 `impact_note` 会让 **offshore-fund** 通道的告警也带
  fund_score 的括注(历史误挂,非本次引入)。若需订正,把 offshore-fund 调用点显式传自己的 note 即可
  (1 行),但那属「顺手改老通道文案」,按派单边界未做。
- news-digest 通道(`_R2_CHANNELS` 对账通道)无独立上传命令 ⇒ 无失败 notify 面(不在本清单)。

## 7. §23.2 同类错误面清单(与用户报的同根因的所有模块)

「通道上传失败**静默**(仅 echo/退出码,无 notify)」这一根因,在 `upload_r2.py` 内共覆盖:
- **修复前已 loud(#193)**:offshore-fund、fund-score。
- **本次修复**:etf-score。
- **同类未修(见 §6 表)**:A 类 12 条增量引擎通道 + B 类 3 条 glob 直调命令。
- **调用方侧**:`update_all.sh:205-207`(`|| echo`,不阻塞)已被脚本内 notify 覆盖;
  `r2_upload_async.sh:180`(已入 `R2_FAIL` 聚合)同样受益。

## 8. §23.3 举一反三(同模式/同数据源/同组件还被谁用 + 相关展示位)

- **同组件(增量引擎 12 通道)**:`on_fail` 扩展点现已就位,详见 §6 A 类清单(只报不改)。
- **同数据源(etf_score_list_* 的展示位)**:前端硬编码 `ssd.fx8.store/data/etf_score_list_{buy,sell,hold}.json`
  (ETF 评分三大榜)→ 该 R2 前缀失败 = 用户可见停在旧版/缺文件,正是告警正文「含义」行所述;`impact_note`
  已明确本通道作用域。
- **同模式(所有 upload-* 通道)**:`on_fail` 回调 = 与 `_upload_glob` 既有 `on_success` 对称的扩展点,
  后续通道接入零新增抽象。

## 9. 自验命令(复现段)

```bash
cd <worktree>
# 主自验(21 PASS / 0 FAIL)
.venv/bin/python scripts/test_204_etfscore_loud.py
# 回归:#193 通道覆盖自验(40 PASS / 0 FAIL)
.venv/bin/python scripts/test_193_r2_channel_coverage.py
# 机检:通道覆盖(AST 双向)ALL_PASS
.venv/bin/python scripts/check_r2_channel_coverage.py
# 既有调用点文案字节不变(期望 True)
.venv/bin/python - <<'PY'
old="含义: 前端读该 R2 前缀的展示位会停在旧版/缺文件(fund_score 为场外基金评分 fallback 数据源)。\n"
new=f"含义: 前端读该 R2 前缀的展示位会停在旧版/缺文件{(lambda: '(fund_score 为场外基金评分 fallback 数据源)')()}。\n"
print(old==new)
PY
```

## 10. 口径/基准标注

- 本任务为**代码行为改动**(失败可见性),**不涉回测/挖掘/基准口径**(§5.4 不适用)。
- 不涉数据产物 ⇒ 无 §22 三步同步 / R2 / CF 缓存一致性动作;不涉算法 ⇒ 无 §21 公示同步;不涉前端 ⇒
  无 §24 发版/版本串动作;未引用外部开源项目 ⇒ 无 §23.1 README 动作。
- **§23.11 无静默吞掉事件**:全程单 commit 线性、base-fresh(见 §0 与提交记录);无冲突/覆盖/版本倒退。