# 长线模式「默认/主推/总建议」G→H 全站整改(2026-09-02)

> 定案依据:`docs/kelly/analysis/trade-method-final-recommendation-20260901.md` 长线主推 H(满仓不买@5万, 无强平完全确定 230.31%/230.83% 兜底态、操作最简、全周期第一);G(P≤3d@10万)降为可选档。用户已点名确认(§23.7)。
> 语义:只改「长线主推/默认/总建议」指向 G→H,不删 G 模式本身(G 仍是可切换卖出模式选项,保留展示),不动任何数字。

## 改动点

### static-site/lab.js
1. **按年窗口增长表默认档 G→H**(§23.3 用户点名主改点):
   - `_selMode = state.labSigKellyYearlyMode || "G"` → `|| "H"`(L10910)
   - `_selModeFinal = state.labSigKellyYearlyMode || "G"` → `|| "H"`(L10916)
   - 空数据兜底选项 `: ["G"]` → `: ["H"]`(极端无数据兜底)
   - 相关注释「默认 G(当前推荐卖出法)」/「保证默认 G 存在」→ H 版本
   - ⚠ 用户已存 `labSigKellyYearlyMode=G` 的 localStorage 不受默认值影响(预期,默认只影响未切过的人)
2. **「总建议口径」文案 G→H**:「完全遵守交易页面展示的交易方法(卖出信号 G 模式)」→ H 模式;「G 模式=当前推荐卖出法,与『总建议=遵守G模式卖出』语义对齐」→ H 模式(满仓不买@5万)(L10945)
3. **按年窗口增长聚合逻辑 G→H**(legacy `allYearly` 总建议口径,vestigial 字段但为注释/逻辑一致性同步改):
   - 注释「仅累加 G 模式」/「allYearly 仍取 G 模式(总建议语义)」→ H(L8652/L8655)
   - `for (_ymk0 in sellModes) if (_ymk0 === "G")` → `"H"`(L8703)+ 注释与「记录口径(H模式)」
4. **全信号操作建议指南「总建议」段 G→H**:
   - summary「总建议(全信号+G卖出模式)」→ H(L10665)
   - 「三玩法并列」G 描述去掉「也是总建议主选」,长线主推指向「总建议」行=H(满仓不买@5万)(L10757)
   - 「总建议」行「(卖出信号 G 模式)」→ H 模式(L10762)
   - 「总建议配套」段「G 模式最贴近交易页面信号驱动跟单」→「长线主推 H 模式(卖出+追止损触发离场=满仓不买@5万)」,G 为可选档(L10765)
   - A/F/J/G 实时表 G 行 desc 去掉「总建议主选」,改「可选档(长线主推 H 见『总建议』行)」(L10791)
   - 「投资习惯」note「G 为总建议主选」→「长线总建议主选 H,G 为可选档」(L10877)
   - 按年窗口来源提示 fallback `modeKey || "G"` → `|| "H"`(L10886)
5. **ai长线开关 G 档位展示框删除(缩短开关描述)**:删 `lab-sigkelly-gih-tier-wrap` 内「G档 10万 ✓」span(单档定案后无切换意义)(L10015-10018)
6. **G 档位死代码清理**:
   - 删除 `.lab-sigkelly-gih-tier-btn` 点击 handler(L10483 区,原 L10489-10514,档位框删后恒空 querySelectorAll 死代码)
   - 删除 `_kellySetGihGTier`(localStorage setter,仅被死 handler 引用)
   - **保留**:`_kellyGihGTier()`(仍被 `_gihTipG`/`_gihRefRows`/缓存键/三玩法/水印用)、`_gihGTierB`(被 `_gihTipG`/对比表用)、`_kellyGihGStratKey`/`_kellyGihStrategyKey`(G 档映射机制本体)
   - **保留**:L10801「G 定案档位」教学段/L10797「G 玩法完整交易方法」/L10799-10800 结论段——均为 G 模式机制本身的说明(且已含「主推 H」),非「长线主推=G」

### static-site/style.css
- 删除死 CSS `lab-sigkelly-gih-tier-wrap/lab/btn/active`(L231-236 区);`sim-gih-tier-*` 为首页模拟弹窗 G/H/I 模式标签,不同组件保留

### static-site/app.js
- 两处注释(L2948/L5243)「G=卖出信号中长线(…总建议主选)」→ G 为可选档 + 「长线主推 H(满仓不买@5万, 2026-09-02 总建议口径 G→H)」
- 首页弹窗用户可见文案(L2958/L2964/L5288/L5290)已为「主推 H」,未动

## 判断清单(改了=长线主推/默认/总建议语义;不改=G 模式本身说明)
- **改**:凡「总建议主选 / 当前推荐卖出法 / 总建议=遵守G卖出 / 默认 G」指向长线主推的 → 全部指 H
- **不改(保留清单)**:
  - purpose-notes.js `lab.sigkelly` 「怎么解读」10 种卖出模式描述(G/H/I 信号驱动卖出机制)、「✿全场主推 H」段——已与 H 主推一致,零改动
  - 「G 玩法完整交易方法 P≤3d@10万」教学段(机制/档位说明)
  - L10959「白话解释 回撤 vs 收益率」真实例子标「G 模式·K=1」——概念教学例子非「长线主推」声明,换 H 需重算数字(数字口径校准是另一任务),保留
  - 首页模拟弹窗 `.sim-gih-tier-*` G/H/I 三模式标签(模式信息展示,非默认/主推声明)
  - `_gihTipG`/对比表/`_KELLY_G_TIER_REF` G 档真实权威数(机制数据,非主推声明)

## 自验结果
- `node --check static-site/lab.js` / `app.js` / `purpose-notes.js` 全 PASS;style.css 花括号配平 0
- grep 验证:①按年窗口默认无 `|| "G"` 残留(L10910/L10916 均 `|| "H"`) ②ai长线开关已无「G档 10万 ✓」span(`gih-tier-wrap` 全站零残留) ③全站无「长线总建议=G 卖出」语义残留(见上文「判断清单」+「保留清单」)
- 排查同类(§23.2 三铁律):同「总建议/默认/主推=G」模式还出现在 lab.js 按年聚合/建议指南/投资习惯/来源提示 + app.js 两注释,逐处核改为 H;同「单档 G 档位展示」还出现在 lab.js tier span + handler + setter + style.css 死 CSS,四件一并清理
- 举一反三(§23.3):ai长线开关的 G 档位框消费点=开关标签(删)、对比表/G 教学段(保留,非展示框);「总建议=G」消费点=全信号表 desc/建议指南总建议行/投资习惯/按年聚合/allYearly、app.js 帮助弹窗注释,已全站覆盖
- 版本串:未自行 bump(机制 C,由 main-merge.sh 统一 build_min+bump)

## 复现
- 本报告为前端展示语义整改,非回测报告。复现口径:
  - 默认档:凯利区「全信号表 · 按年窗口增长」下拉初始选中 H(未切过 localStorage 时)
  - ai长线开关:凯利区开关行仅剩「ai长线模式(G/H/I)仓位管理 ⓘ」+「G/H/I 对比表」按钮,无「G档 10万 ✓」静态标签
  - 总建议:「全信号都看 + 完全遵守交易页面展示的交易方法(卖出信号 H 模式)」
- 验证命令:`node --check static-site/lab.js`;线上验证(合并后):curl 主站 lab.min.js 含「卖出信号 H 模式」字符串
- 改动 commit:`kelly-gh-default-h-fix-20260902`(见 git log,与本文档同 commit)
