# 冰点三条遗留低分项修复 Review 报告(2026-10-02)

- reviewer:独立复验,未参与实施
- 审查对象:分支 `feat/icepoint-consensus-20261002` @ `668993e86`(父=main `8723a64a2`,merge-base 即父,全分支=1 commit)
- 全 diff:仅 2 文件(脚本 +10-2 / app.js +19-5),**无夹带**
- 审查方法:逐行 diff + Playwright 实测(临时重建 min,验完已还原)+ 证伪测试(close 改 no-op,验完已还原)+ 后端生成链路核对

## 总体结论:PASS(三条均通过)

---

## ① 冒烟脚本 D 段「复位已生效」断言 — PASS

**证据**:
- diff 确认断言在:`scripts/playwright-accept/verify_icepoint_front.mjs:166-170`(m0/resetClosed/resetFailed return),FAIL 文案 `:183`
- **证伪测试(close 改 no-op)**:跑脚本 → `FAIL D 点击前复位弹窗未关闭(close 失效), 阻断点击避免残留态假阳性` + node exit=1 + FAILURES=1。验完已还原。
- **阻断点击成立**:resetFailed 时直接 return,后续 `sh.click()` 不执行(证伪输出无 PASS 点击,只有 FAIL 复位,证实确实阻断)
- **正常路径**:重建 min 后跑全脚本 `ALL PASS`(A1/A1b/A1c/A1d/A2/A3/B1/C1-C7b/D 全 PASS)
- 断言顺序正确:close 调用(no-op 时)→ 断言弹窗 `hidden` → 未关闭即 FAIL,不留残留态假阳性窗口
- close 实现核对:`app.js closeSentimentDayDetailModal()` 确实 `classList.add("hidden")`,断言判据与实现一致

## ② tooltip 区分「数据不足不可判定」vs「评估过未命中」— PASS

**证据**:
- diff:`static-site/app.js:7241-7252`(`_shHits/_shTotal/_shMissTxt` + `_tipParts` else 分支)
- **判据可靠性(重点核对)**:后端 `app/queries.py:1596-1606` 中 `sh_freeze` 与 `sh_hits` 在**同一 `if _d in _ice_df.index` 块内写入**,sh_hits.total=`int(n_avail)` 必有。实测 24/24 天带 sh_freeze 且全带 sh_hits.total。
- **undefined 兜底**:前端 `_shTotal = (_shHits && typeof _shHits.total==="number") ? ... : null` → null 时走「评估过未命中」分支,不会崩、无第四种文案。此情形后端同块写不会出现,兜底合理。
- **判据与后端口径逐字一致**:icepoint.py `main = f1_hit & (f2_hit|f3_hit) & f4_hit`,每因子 hit 带 `.notna()` 门控 → **n_avail<4 时 has_signal 必 false**(缺因子则该因子 hit=false),不存在「数据不足却命中」的第三态;total=4 才可能评估出命中/未命中。判据全划分:total<4=不可判定 / total=4=评估过。
- **命中判定一行未动**:`_shHit = _hasSh && day.sh_freeze===true`、`_consTxt`、`_srcTxt`、sh 格渲染均不在 diff 内(仅 `_tipParts` 第一项 else 分支改)。
- **Playwright 实测三情形**(临时脚本 + 临时 min,已还原):
  - total=3 → `上海炒家口径当日数据不足不可判定(四因子仅可得 3 个, 老算法冰点)`
  - total=4 未命中 → `上海炒家口径当日评估过未命中(仅老算法冰点)`
  - 命中 → `上海炒家冰点(四因子共振 楼层+涨停或跌停+地量)`
- **数据现状注意**:当前样本 24/24 天 total=4,**无 <4 样例**,「数据不足」分支当前数据下不可触发(判据正确,历史缺楼层数据段才可能出现)。

## ③ 图例 4 条样式对齐 — PASS

**证据**:
- diff:`static-site/app.js:7278-7281` 四条新增色块 + 去「·」前缀
- **DOM 实测**(临时脚本):重叠=`[#2563eb,#7c3aed]` 双色块 / 仅上海炒家=`[#7c3aed]` / 仅老算法=`[#7c3aed;opacity:.68]` / 认可度=`[#a58bd6]`
- **老条目逐条未变**:冰点维度(蓝#2563eb)、上海炒家冰点(紫#7c3aed)、红紫绿(文字色块)、📋(纯文字)全保留
- **色块与格子视觉一致**(读 CSS 比对):老算法格 `.freeze-val color:#2563eb`(style.css:937) / sh 格 `.sig-sh-ice color:#7c3aed`(:939) / 仅老算法 `.sig-sh-miss opacity:.68`(:942) / 认可度 miss `.sig-sh-cons color:#a58bd6`(:943)
- **style.css 无需改**:`.sig-cal-legend-swatch` inline-block 10x10,双色块由 flex gap 并排承载(style.css:908-910)

---

## 必查项

### 1. 全 diff 无夹带 — PASS(但实施自述 1 处失实)
- 全分支=1 commit(merge-base=父 `8723a64a2`),diff 仅脚本 2 行删除 + app.js 4 行删除,全是三条修复本身。
- **自述失实**:实施声称「全分支唯一删除行 = `const cells = freezeCells + sigCells;` → `freezeCells + _shCells + sigCells`」。核实:`freezeCells + _shCells + sigCells` 早在冰点首版 commit `cffe2b7a9`(已在 main 链)就存在,本次 `668993e86` diff 中**没有**这一删除行。属实施表述把「整个冰点开发史」误当「本次 commit」,不影响代码正确性,仅提示主控:实施自述的 diff 口径不可全信。

### 2. 老功能回归 — PASS
- 非命中日无 sh 格:A2 断言 PASS(无 sh 字段不渲染)
- 老算法格子(freezeCells):diff 未动其生成(7212-7216),A1 重叠/仅老算法格正常
- 情绪日历其他图例条目:DOM 实测全在未变
- 点 sh 格开当天下钻弹窗(`ac520e72b` 刚修):D 段 PASS(点击开含本次日期弹窗)

### 3. §21 公示 — PASS
- purpose-notes.js 本次 diff **未改**(仅 2 文件)。判断正确:公示已含「认可度 x/y=命中口径数/可得口径数」「数据齐全可判(y)」,新增「数据不足不可判定」是对 y 语义的展示层展开,不冲突,无需公示补充。

### 4. §23.2 同类错误面抽查
- ① 图例纯文字/色块混用:**无其他遗留**。全站信号图例(signal-legend-item)全带 `<i style=background>` 色块;情绪日历图例中红紫绿/📋 为老条目既有风格(§23.7 冻结不动),不属本次混用修复范围。
- ② tooltip「数据不足」二义:**弹窗明细档位有轻微同类残留(低分项见下)**;全站其他「未命中」文案(AI降亏/信号冻结等)语境明确,无二义。
- ③ 测试脚本「复位未断言」:其他 playwright 脚本无 open→close→click 序列,无此模式;verify_icepoint 已补。抽查结论成立。

### 5. §24 前端四查
- 版本串:`668993e86` 未 bump(符合机制 C,worktree agent 不自行 bump,merge 时 main-merge.sh 统一 bump+build_min);本次 commit 只改源码不带 min/bump ✓(审查用临时 min 已 `git checkout` 还原)
- 部署后哈希==引用、备站核心数据:未上线,属主控 §0 上线验证范畴。

---

## 低分项(<80 已滤,按 §10.2)

1. **(50 分)** 弹窗明细档位 `sh_level==="" → "未命中"`(app.js:7348)仍未区分「数据不足」——但弹窗内同时显示 `四因子共振 n/total` + 四因子明细(缺值显示"—"),用户可自辨;当前数据 total 全=4,该情形不触发。建议(非阻断):后续如需统一口径可同判据区分。

---

## 验证遗留清单
- 临时重建的 `static-site/app.min.js` 已 `git checkout` 还原;临时脚本(/tmp 及 worktree 内 .tmp_*.mjs)已删;本地 8379 http server 已停;`verify_icepoint_front.mjs` 证伪改动已还原为 commit 原状。
- 工作区干净(`git status --porcelain` 无输出)。
