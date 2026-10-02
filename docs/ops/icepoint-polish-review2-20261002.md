# 冰点第 4 条尾巴(弹窗档位二义)修复 Review2 报告(2026-10-02)

- reviewer:独立复验增量 `101b521ab..7958a09ee`(父=101b521ab 我的上一份报告)
- 审查对象:分支 `feat/icepoint-consensus-20261002` @ `7958a09ee`,worktree 独立
- 全 diff:仅 1 文件(app.js 10+/3-),**无夹带**
- 审查方法:逐行 diff + Playwright 实测(临时重建 min,验完已还原)+ 证伪 + 冒烟回归

## 总体结论:PASS

## 1. diff 逐行 — 无夹带
- `git diff 101b521ab..7958a09ee`:唯一改动文件 `static-site/app.js`,改动 = `openSentimentDayDetailModal` 内 `_lvlTxt` 档位分支(app.js:7346-7356),`_hh` 声明位置上移复用。
- 命中判定(has_signal/sh_level/consensus)一行未动:diff 只含 `_lvlTxt` 三元分支 + `_hh` 位置,`_shHit`/`_consTxt`/`_hitTxt`/`_fxs` 均不在 diff。

## 2. 弹窗↔tooltip 文案逐字一致 — PASS(实测+证伪)
- **判据语义等价**:tooltip `_shMissTxt` 用 `_shTotal != null && _shTotal < 4`(null 兜底);弹窗用 `typeof _hh.total === "number" && _hh.total < 4`(number 兜底)。两者对 undefined/缺字段都走「评估过未命中」else,判据等价。
- **文案逐字一致**(Playwright 临时脚本实测,min 临时重建已还原):
  - total=3:tooltip 首段 = 弹窗档位 = `上海炒家口径当日数据不足不可判定(四因子仅可得 3 个, 老算法冰点)` → same=true
  - total=4 未命中:两处 = `上海炒家口径当日评估过未命中(仅老算法冰点)` → same=true
  - 命中(sh_level=main):tooltip=`上海炒家冰点(四因子共振…)`/ 弹窗档位=`主冰点(楼层+地量+涨停或跌停)` — 语义各自正确(命中时 tooltip 不走 _shMissTxt,两处本就不逐字,断言按语义验,非 bug)
  - **兜底(总字段 undefined)**:两处均回退 `评估过未命中`,逐字一致,`无 undefined/NaN 泄漏文案`。
- **证伪(断言非摆设)**:
  - total=3(判据命中)→ 两处都显示「数据不足不可判定」,逐字一致 ✓
  - total=5(判据永不匹配模拟,>4 必失配)→ 两处都回退「评估过未命中」,逐字一致 ✓
  - **断言灵敏度**:断言「数据不足文案 === 未命中文案」→ false(断言能区分两种文案,若代码把两情形渲染成同一文案,断言会 FAIL)→ 证明断言不是摆设 ✓

## 3. 兜底 — PASS
- sh_hits 缺失/undefined 构造实测:两处均回退「评估过未命中」,无诡异文案,与 tooltip 已验证写法行为一致。

## 4. 命中判定逻辑一行未动 — PASS
- diff 核实:`_shHit`(app.js:7234)、`_consTxt`(7239)、`_srcTxt`(7240)、`_hitTxt`(7358)、`_fxs`(7360)、hard/main 判定均不在 diff。仅 `_lvlTxt` 的 `sh_level===""` else 分支从硬编码「未命中」拆成两段。

## 5. 回归 — PASS
- 原冒烟 `verify_icepoint_front.mjs` 全 PASS(A1/A1b/A1c/A1d/A2/A3/B1/C1-C7b/D)。
- C7b「档位=未命中」:样本 24 天 total 全=4,`sh_level===""` 日显示「评估过未命中」,含「未命中」子串,断言兼容未破坏。
- 图例、老算法格子、点 sh 格开当天下钻弹窗(ac520e72b):冒烟 D 段 PASS,不受影响。

## 6. §21 公示 — PASS(判断成立)
- purpose-notes.js 本次 diff 未改(仅 app.js 1 文件)。
- 独立核实:sentiment.icepoint 公示全文**不含**「未命中/数据不足/不可判定/评估过」措辞,只含硬冰点/主冰点/重叠/仅上海炒家/仅老算法/认可度 x/y=命中/可得。弹窗档位新文案是对公示「可得」语义的展示层细化,**无冲突面**,无需公示补充。实施判断成立。

## 7. §23.2 同类错误面 — PASS(实施结论站得住)
- 独立 grep:`sh_hits/sh_level/sh_freeze/sh_factors` 全仓消费点 **仅 2 处**,都在 app.js:
  1. `_renderSentimentCalendar` tooltip 生成(7233-7241)
  2. `openSentimentDayDetailModal` 弹窗明细(7340-7360)
  - 无其他 JS/HTML 文件消费;图例(legend)只引用公示字符串,不消费 sh_* 数据字段。
- 其他「未命中」文案(AI降亏过滤=未命中8键删线、信号冻结、过拟合)语义均为**过滤/冻结判定**,与「数据可得性」二义无关,实施结论成立。
- **无它漏掉的展示位**:弹窗内 `四因子共振 n/total`(7358)在 total<4 时显示「0/3(0 个因子共振命中 / 3 个因子当日可得)」与档位「数据不足(可得3个)」一致;日历格 title 即 tooltip(已修);图例/公示不涉数据不足措辞。

## 验证遗留清单
- 临时重建 `static-site/app.min.js` 已 `git checkout` 还原;临时脚本已删;8379 server 已停;工作区干净。
