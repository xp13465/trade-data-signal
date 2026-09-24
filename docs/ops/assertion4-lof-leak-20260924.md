# assertion4 LOF 泄漏 P0 根治(2026-09-24)

## 1. 根因(一句话)
deploy.sh 的 §23.6 入样宇宙对称校验 assertion4 今天起 FAIL:东财主源 fund_etf_spot_em() 被封装后启用**新浪+腾讯兜底源**,新浪兜底拉 `etf_hq_fund` + **`lof_hq_fund`** 两个节点把 360 只场内 LOF 带进 df,kw 名称匹配层(无 empty_array 守卫)把 LOF 塞进「无场内专属 ETF」指数(sw_801200 商贸零售/ sw_801950 煤炭)→ empty_array 规则被破坏。

## 2. 为什么"今天之前 PASS、今天 FAIL"(机制性解释)
- **东财主源不含 LOF**:`fund_etf_spot_em()` 用 `fs=b:MK0021-24+MK0827`(纯 ETF 板块,不含场内 LOF)。9-19 东财主源产物实测真 LOF=0 只。kw 层名称匹配时 df 里根本没有 163415/168204 这些 LOF,匹配不到,empty_array 指数保持空数组 → PASS。
- **新浪兜底含 LOF**:兜底源 `_sina_etf_spot_df()` 同时拉 etf_hq_fund(1685 只)+ lof_hq_fund(360 只)两节点,把场内 LOF 带进 df。新浪 lof 节点代码分布:501×98、502×9、506×7、16x×246(=360,含 163415 兴全商业模式LOF、168204 煤炭LOF)。
- **kw 层无 empty_array 守卫**:track_index 层(L1494-1499)有守卫但按 `fund_type != "lof"` 判——新浪 LOF 无 fund_type 字段(写入时无此字段,enrich 时 `setdefault("fund_type","etf")`),判据失效;**kw 层(L1540+)完全没有守卫**,是实际漏网点。
- **时间线吻合**:18:13 deploy 时 build 失败用旧版兜底(旧版 map 无 LOF)→ PASS;18:55 新浪兜底首次成功生成含 LOF 的新 map → FAIL。

## 3. 修复方案与理由
修改文件: `scripts/build_board_etf_map.py`,4 处:

### 3.1 新增 `_is_lof_code()` 函数
代码前缀判据 `^(16|15|501|502)`,与 `universe_rules.yaml` `lof_inclusion.on_exchange_prefixes` 同口径(2026-09-14 用户拍板),复用项目现成判据(`_load_lof_track_index` L621),不另造。

### 3.2 track_index 层守卫改可靠判据
原 `e.get("fund_type") != "lof"` → 改 `not _is_lof_code(e.get("code",""))`。因为 fund_type 字段随数据源漂移(新浪 LOF 无 fund_type → 标成 etf),代码前缀是稳定判据。

### 3.3 kw 层加 empty_array 守卫(实际漏网点)
append 前判断 `if iid in empty_array_ids and _is_lof_code(code): continue`。

### 3.4 写盘前整体兜底清空(单点最终防线)
排序后、`_apply_hysteresis` 前,对全部 empty_array_ids 强制 `out[iid] = []`。理由:
- 覆盖所有叠加层(track_index/kw/overlap/holdings/global/未来新增层)的潜在漏网,不逐 caller 打补丁(§6.5 单点守卫)。
- 修前实测泄漏 13 只,其中含**真 ETF**(515220 中证煤炭ETF、512580 中证环保ETF、159566 等)——empty_array 语义=无场内专属 ETF,任何 ETF 都不许,只有整体清空能兜住。
- 放 hysteresis 之前:空数组直接 continue,不为 empty_array 指数产生 `_hysteresis` 记录(修前旧版在 4 个 empty_array 指数上留了 4 条 hyst 状态,修后 0 条)。

### 为什么不选"从源头不让 LOF 被标成 etf"
2026-09-14 用户拍板「场内 LOF 进 board_etf_map 候选池」(yaml `lof_inclusion`),新浪兜底带 LOF 进 df 是**故意的**(覆盖东财等价集)。若从源头删掉 LOF,会改变用户可见入样宇宙(场内 LOF 不再能进其他指数的候选池,如 501302/160924/161831 等 496 只),违反用户拍板。故只修 empty_array 过滤处。

## 4. 验证(修前/修后对照,同一新浪兜底源)
| 项 | 修前(旧代码) | 修后(本修复) |
|---|---|---|
| assertion1 | FAIL(环境) | FAIL(环境,同因) |
| assertion2 | PASS | PASS |
| assertion3 | PASS | PASS |
| **assertion4** | **FAIL: 4 处泄漏** | **PASS** |
| empty_array 泄漏 | sw_801200×1、sw_801950×4、sw_801970×2、thsc_306380×6(共 13 只) | 全部空数组 |

- assertion1 FAIL 是**环境限制**:worktree 隔离环境无 `sentiment.db`/`etf_national_team.db`(git 不追踪 DB),相似度/跟踪评分全 None(track_score=None)→ recompute=False。对照实验证明:同一环境旧代码 assertion1 同样 FAIL,与修复无关。云上(有 DB)不受影响。
- 修后 assertion4 明细:排除类别全部正确(absent 18 项 + empty_array 33 项全空)。

## 5. 误伤检查
- **empty_array 指数**:33 个全部空数组 ✓(守卫/兜底只作用于 `empty_array_ids`)
- **非 empty_array 指数零差异**:修前 1027 只 vs 修后 1027 只(排除 `_hysteresis` 元数据后逐指数 code 集合完全一致)✓
- **合法场内 LOF 保留**:非 empty_array 指数保留 496 只 LOF,分布 58 个指数(sz/hs300/csi500/div_lowvol/hsi/hstech/hscei/sw_801030 等,含 163109/502048/501302/160924/161831/168203/502023)✓

## 6. R2 影响面(18:55 首个 FAIL 起 deploy.sh L334 终止,L612 R2 上传段停摆)
- **受影响最重 = `data/board_etf_map.json`**:R2 版停在 9-22 21:04(Last-Modified),是本次修复要恢复的产物;修复 merge + 下次成功 deploy 后自动重传。
- **未受影响(有独立于 deploy.sh 的通道活着)**:`data/overview.json`(collected_at=21:31)、`data/signal_kelly_trades.json`(21:17)、`signal_kelly_trades_sdc.json`(21:18)、`data/summary.json`(21:10)、`data/a-stock-3m.json`(21:10)——update_all/backfill_evening 自带 R2 上传调用,不经过 deploy.sh L334 闸门。
- **注意**:R2 `overview.json` 21:31 版**缺 `index_tiers` 字段**(多指数四档聚合卡数据)。index_tiers 生成逻辑在 `app/queries.py _ai_macro_build_index_tiers`,与 deploy 阻断的直接关联需主控另行判断(非本次 assertion4 修复范围)。
- deploy.sh 主链 14 个 R2 通道(upload-lab/trade-sim/trade-sim-json/index/etf-hist/accum-nav/industry/public-fund/etf-score/data-large/kelly-parts/kelly-parts-sdc/all-data/kelly-snapshots)自 18:55 起每轮在 L334 终止,该批通道的增量上传停摆约 5 小时。

## 7. 复现段
```bash
# 环境: 主树 venv(worktree 无 .venv)
PY=/Users/linhuichen/code/trade/.venv/bin/python
W=/Users/linhuichen/code/trade/.claude/worktrees/agent-aec4d27d16e687b98
cd $W
$PY scripts/build_board_etf_map.py   # 本地东财主源被封,自动走新浪兜底(2045只含LOF)= FAIL 场景
$PY scripts/check_universe_alignment.py \
  --repo $W \
  --overview /Users/linhuichen/code/trade/static-site/data/overview.json \
  --board-map $W/data/board_etf_map.json \
  --trades /Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json \
  --deploy-mode
# 期望: assertion4 PASS(修前 FAIL)
```
对照(修前 FAIL 证据): `git stash` 改后旧代码重跑同上命令,assertion4 FAIL(4 处泄漏),stash pop 恢复。

## 8. 修改文件与配套 commit
- `scripts/build_board_etf_map.py`(4 处,见 §3)
- 落档本体: `docs/ops/assertion4-lof-leak-20260924.md`
- 配套 commit: 见 git log(§23.5 四件套)
