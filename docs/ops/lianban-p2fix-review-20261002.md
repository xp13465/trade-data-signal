# 独立审查:lianban P2 残留收尾修复(commit d1b3e9382)

> 审查者:reviewer(独立 fresh context,不读实施自测结果,逐条独立复现)
> 被审:分支 `feat/lianban-p2fix-20261002`,commit `d1b3e9382`(6 条修复 P2-1/2/3/4/5/7)
> 环境:隔离 worktree `/tmp/revlianbanp2-wt`(main@937c5ef34);mock 包 `/tmp/p2mock`
> 结论摘要:**6 条全 PASS + 1 条 P1 caveat(P2-3 空池判据)建议补强后再合 main**

## 审查范围

- `app/backfill_lianban.py`(+144,含 `_fmt/_to_float/_source_map/_upsert/_target_is_prod/main` 改动)
- `docs/scripts/verify_lianban_fillgaps_zerotouch.py`(P2-5 复用 `_upsert` + `_vals_equal`)
- `docs/scripts/sent_impact_lianban.py`(P2-5 复用 `_upsert`)
- `docs/ops/lianban-prod-write-checklist.md`(写库命令补 `--confirm-prod`)
- `docs/ops/lianban-backfill-p2fix-20261002.md`(新报告)
- ⚠️ 差异面 `docs/fapi/*` 3 文件删除 = 分支基于旧 main(559373420)落后现 main 所致,非本次改动,未审。

**背景钉死**:生产写库已完成(2026-10-02,1231 行 = akshare 25 / fapi 1154 / intraday 52,gap=0)。本批 P2 修复在写库之后,当前生产库未被本次代码改动触碰;**P2 修复的实际生效场景 = 未来重跑补新缺口**。

---

## 逐条结论

### P2-1 verbose 安全格式化 → PASS
- `_fmt`/`_to_float` 对 `''`/`'abc'`/`None`/`nan`/`inf` 均不崩(实测输出见复现段)。
- **无静默错误数值**:`_fmt` 只影响显示;`_to_float` 只用于对账比较,非数值→None→判"不等"而非误判相等。`_to_float('0')=0.0` 正确转数值。
- 对比段原 `abs(new_v - o[0])` 遇字符串脏值会 TypeError,新 `_to_float` 双端宽容,是纯改进。

### P2-2 manual+NULL 计数对齐 → PASS
- `_source_map` 独立查询含 value IS NULL 行,manual 判定改 `src_map.get(d)=='manual'`。
- 独立复现(4 日库:已有值/manual+NULL/manual+值/空缺口):`planned_write=1 | skipped_manual=2 | skipped_existing=1`,与修后报告完全一致;manual+NULL 缺口行不再混进 planned_write。
- 同 date 多条映射:`daily_metric` PK=(date,metric_id)+WHERE metric_id=? → 同 date 至多 1 行,无歧义。

### P2-3 空池写 0.0 → **P1 caveat,建议补强后合**
**行为本身正确**(真 0 写 0 合理),但**判据不落代码**:写 0 前从不检查 msg,存在两条"非真 0 的空 df"也会被永久写 0。

独立核实 `fetch_zt_fallback`(app/collector/fapi_fallback.py L104-168)返回契约,空 df 有 **3 条可达路径**:

| 路径 | 构造 | 返回 | backfill 行为 |
|---|---|---|---|
| B 真 0 | `pagination.total=0` | 空 df + `msg="fapi ... empty(真0)"` | 写 0(合理) |
| **A 契约异常(schema 变更)** | `pagination.total=700` 但 item 字段缺失/改名 | **空 df** + `msg="... 0 rows; TRUNCATED total=700 got=0"` | **写 0(错,丢 700 行)** |
| **C pagination 缺失/改名** | data 有 item 但无 pagination | **空 df** + `msg="... empty(真0)"`(误报真 0) | **写 0(错,实际有涨停)** |

- A 由 `fetch_zt_fallback` 的 `items=list(data.get("item") or data.get("items") or [])` 起,翻页后 `len(df)!=total` 走 msg 链路带 `TRUNCATED` 但**仍返回空 df**。
- C 由 `total = int(pag.get("total") or 0)` 起,pagination 字段缺失 → total=0 → 误走 empty 分支。
- 报告声称"判据=msg 显式声明 empty(真0)",**但代码 `len(df)==0` 分支从不读 msg**——判据只存在于 docstring/注释,不在执行逻辑。

**实害评估**:
- 当前无实害:真实写库 1154 天全 fapi 成功值、gap=0,**历史上没有任何一天触发空池**(A 股交易日涨停池为空的真 0 日极罕见,更可能是 FAPI 服务端无该日数据)。
- 未来重跑补新缺口时,FAPI 契约变化(外部系统最高频故障,§5.1/L47)会**永久写 0**——写后 fill-gaps-only 跳过、不再重试,下游 `a_sentiment` 缺/错 lianban 分项,修正只能靠人工 `--overwrite` 或 SQL。
- **建议一行修**:写 0 前验证 `msg` 含 `"empty"` 且不含 `"TRUNCATED"` 才写,否则记 gap;或把"数据缺失当 0 写"语义上报用户拍板(§23.7)。**建议实施补修 + reviewer 复验后再合 main**。

### P2-4 exit code 分级 → PASS
- 全仓 grep `backfill_lianban`:调用方 = 脚本自身 + docs,**无 scheduler/cron/timer/import 挂载**,rc=1(有 gap)不会误报给任何自动化监控(当前无消费者,属"未来挂链可用")。
- dry-run 正常路径 rc=0 不破坏现有手动用法;参数错 rc=2、护栏拦 rc=3 分级正确。
- 小 caveat(滤项):护栏检查在 `--end` 格式校验之前,`--write --end abc`(无 confirm)返回 rc=3 而非 rc=2,无实质危害。

### P2-5 两脚本复用 `_upsert` → PASS(含 2 caveat)
- **逐字段一致性实测**:verify 脚本重放 vs 手抄版 SQL(executemany 同款 `ON CONFLICT ... WHERE source != 'manual'`)对 manual+NULL / manual+值 / 缺口三型行为**逐位一致**(manual 未覆盖、缺口写入 fapi、现有行零触碰)。
- verify 在新版接口下(increment_dates 不含 manual 行)重放 → `added=1/removed=0/changed=0` + `PASS`,守恒断言 `len(rows)==planned_write` 成立。
- caveat ①(滤项,60 分):verify 从此复用主脚本 `_upsert`,不再独立于主脚本验证该函数本身——但 `added/removed/changed` 判定逻辑(`planned_rows/key_map/_vals_equal`)仍独立,"零触碰证明"的验证价值保留。
- caveat ②(滤项,50 分):`from app.backfill_lianban import _upsert` 会连带 import `app.collector.fapi_fallback`(需 pandas/requests)。项目 venv 已装(实测 pandas 3.0.3/requests 2.34.2),且 sent_impact 本来就要 import app.db/compute,不构成新依赖负担。

### P2-7 生产护栏 → PASS(含 2 caveat)
- 四判独立实测全对:`None→True` / 云上主库 `/home/ubuntu/code/trade-data/data/sentiment.db →True` / 本机 `data/sentiment.db→True` / 沙箱→False。
- **正常写库流程走得通**:checklist 第五节已补 `--confirm-prod`,云上执行路径 realpath 匹配 `_CLOUD_PROD_DB` → 放行;dry-run 复核命令不拦。未修出"谁也跑不了"。
- caveat ①(75 分,极低概率):**硬链接可绕过护栏**——`os.path.realpath` 不解析硬链接,`ln 主库 /tmp/link.db` 后 `--db /tmp/link.db --write`(无 confirm)→ `_target_is_prod` 判 False 放行,写入硬链接=写入主库。需人为建硬链接,非"误写"场景,知情即可。
- caveat ②(知情):旧镜像 `/home/ubuntu/code/trade-data-signal/data/sentiment.db` 未登记 `_CLOUD_PROD_DB` → 误传会放行写旧镜像库(非主库,危害小;checklist 已明确警告勿写该路径)。

### 冻结契约(§23.7)核查 → PASS
- 默认 `fill-gaps-only` 不变、`source='manual'` 双层保护(Python 判定 + SQL WHERE)不变、`only_if_null` 竞态加固不变——重跑不会覆盖已有生产历史值。
- P2-3 写 0 只针对"原本 gap 的空池日"(未来重跑时),不覆盖已有值;唯一新风险即 P2-3 判据 caveat 本身。

---

## 复现段(独立 mock,未复用实施者脚本)

```bash
# 环境:mock 包 /tmp/p2mock(假 app/calendar/db + 真实 fapi_fallback.py)+ 被审 commit 的 backfill_lianban.py
mkdir -p /tmp/p2mock && git -C /Users/linhuichen/code/trade archive d1b3e9382 app/backfill_lianban.py | tar -x -C /tmp/p2mock  # 视包结构调整
# 见 /tmp/p2mock/test_p23.py / test_p23_real.py / test_p27.py / test_p21_p22.py / test_p25*.py

# P2-3 三路径(fetch_zt_fallback 真实代码 + patch _api):
#   A schema变更(pagination.total=700 无 item)  → df is not None=True, len=0, msg="... TRUNCATED total=700 got=0" → backfill 写 0.0
#   B 真0(total=0)                              → df is not None=True, len=0, msg="... empty(真0)"        → backfill 写 0.0
#   C pagination 缺失(data 有 item 无 pagination) → df is not None=True, len=0, msg="... empty(真0)"(误报) → backfill 写 0.0
#   backfill 主循环 len(df)==0 分支对 A/B/C 行为相同(均写 0),不检查 msg —— 判定实锤

# P2-1:_fmt('')='' / _fmt('abc')='abc' / _fmt(None)='None' / _fmt(nan)='nan' / _to_float('')=None
# P2-2:manual+NULL 计 skipped_manual,planned_write/skipped_existing/skipped_manual 逐位对
# P2-5:verify 脚本(新版接口)重放 → PASS,manual 保护生效,与手抄版逐位一致
# P2-7:四判全对;硬链接路径 _target_is_prod=False(绕过),相对路径 realpath 匹配
```

## 低分项滤除(§10.2,<80 未进正式 finding)
共 5 项:P2-4 护栏在 --end 校验前(40)、verify 独立性下降(60)、import pandas 依赖(50)、sent_impact 无 sys.path 处理(50)、verify `_upsert` only_if_null 默认 False vs 主脚本 True 的边角差异(40)。

## 未覆盖项
- 云上真实环境(122.51.111.173)未连接,`_target_is_prod` 在云上 symlink 链下的 realpath 行为未实测(本机 + 构造路径已验证逻辑)。
- 真实 FAPI 请求未打(契约路径用 patch `_api` 构造;FAPI 历史数据稳定且 #140 已独立真实调用复现)。
- 本次 P2 修复代码仍在 feat 分支未上线,不影响已完成的 1231 行生产写库。
